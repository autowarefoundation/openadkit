#!/usr/bin/env python3
"""Image metadata from build capture through scan and release boundaries.

The persisted JSON format stays unchanged. Parsing is shared; trust decisions
(GitHub run, attestation signature, registry state) remain with their callers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

PLATFORMS = ("linux/amd64", "linux/arm64")
UPSTREAM_NAMES = ("core-devel", "base", "base-cuda-runtime", "base-cuda-devel")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
VERSION_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def string(value: Any, name: str) -> str:
    require(isinstance(value, str) and bool(value), f"{name} must be a nonempty string")
    return str(value)


def matches(pattern: re.Pattern[str], value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def image_ref(image: dict[str, Any], suffix: str) -> str:
    return f'{image["repo"]}:{image["target"]}-{image["ros_distro"]}-{suffix}'


def build_images(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    require(isinstance(metadata, dict), "build metadata must be an object")
    build_tag = string(metadata.get("build_tag"), "build_tag")
    rows = metadata.get("images")
    if not isinstance(rows, list) or not rows:
        raise ValueError("build metadata images must be a nonempty array")
    seen = set()
    for index, row in enumerate(rows):
        require(isinstance(row, dict), f"images[{index}] must be an object")
        key = tuple(string(row.get(field), f"images[{index}].{field}") for field in ("repo", "target", "ros_distro"))
        require(key not in seen, f"duplicate build image: {key}")
        seen.add(key)
        require(matches(DIGEST_RE, row.get("digest")), f"invalid image digest for {key}")
        require(row.get("ref") == image_ref(row, build_tag), f"invalid source image reference for {key}")
        platforms = row.get("platforms")
        require(isinstance(platforms, list) and bool(platforms) and all(platform in PLATFORMS for platform in platforms), f"invalid platforms for {key}")
    return rows


def inventory_images(inventory: dict[str, Any], common: str, component: str) -> list[dict[str, Any]]:
    prefixes = {"common": common, "component": component}
    rows = []
    for image in inventory["images"]:
        require(image["repo"] in prefixes, f'unsupported repo kind: {image["repo"]}')
        for distro in image.get("ros_distros", inventory["ros_distros"]):
            rows.append({"repo": prefixes[image["repo"]], "target": image["target"], "ros_distro": distro,
                         "platforms": image["platforms"]})
    return rows


def scan_rows(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**{key: image[key] for key in ("repo", "target", "ros_distro", "digest")},
             "image_ref": f'{image["repo"]}@{image["digest"]}', "platform": platform, "platform_label": platform.replace("/", "-")}
            for image in build_images(metadata) for platform in image["platforms"]]


def validate_scan(scan: dict[str, Any], build_tag: str) -> None:
    require(isinstance(scan, dict), "scan metadata must be an object")
    require(scan.get("build_tag") == build_tag and matches(SHA_RE, scan.get("policy_sha")), "invalid scan build/policy identity")
    require(scan.get("scan_scope") == "all" and scan.get("scan_status") in ("passed", "failed"), "not full scan metadata")
    for key in ("run_id", "run_attempt"):
        require(matches(re.compile(r"[0-9]+"), scan.get(key)), f"invalid scan {key}")
    rows = scan.get("scanned_images")
    if not isinstance(rows, list) or not rows:
        raise ValueError("scan images must be a nonempty array")
    for row in rows:
        require(isinstance(row, dict), "scan image must be an object")
        for key in ("repo", "target", "ros_distro"):
            string(row.get(key), f"scan image {key}")
        require(matches(DIGEST_RE, row.get("digest")) and row.get("platform") in PLATFORMS, "invalid scan digest/platform")
        require(row.get("image_ref") == f'{row["repo"]}@{row["digest"]}', "invalid scan image reference")


def validate_artifacts(directory: Path, scan: dict[str, Any], build_tag: str, common: str, component: str) -> None:
    metadata = load_json(directory / "build-metadata.json")
    require(isinstance(metadata, dict), "build metadata must be an object")
    run_id, run_attempt = build_tag.split("-")
    require(metadata.get("build_tag") == build_tag and metadata.get("run_id") == run_id and metadata.get("run_attempt") == run_attempt,
            "build metadata run identity mismatch")
    for key in ("openadkit_sha", "autoware_ref"):
        require(matches(SHA_RE, metadata.get(key)), f"invalid build {key}")
    string(metadata.get("autoware_input_ref"), "autoware_input_ref")
    require(metadata.get("autoware_ref_type") in ("branch", "tag"), "invalid Autoware ref type")
    require(matches(VERSION_RE, metadata.get("autoware_base_version")), "invalid Autoware base version")
    for file, key in (("autoware-lock.repos", "autoware_lock_sha256"), ("image-inventory.json", "image_inventory_sha256"), ("upstream-images.json", "upstream_images_sha256")):
        require(matches(HASH_RE, metadata.get(key)), f"invalid {key}")
        require(hashlib.sha256((directory / file).read_bytes()).hexdigest() == metadata[key], f"{file} SHA does not match metadata")
    inventory = load_json(directory / "image-inventory.json")
    upstream = load_json(directory / "upstream-images.json")
    require(json.dumps(upstream, sort_keys=True) == json.dumps(metadata.get("upstream_images"), sort_keys=True),
            "embedded upstream image metadata does not match upstream-images.json")
    images = build_images(metadata)
    def inventory_key(row):
        return (row["repo"], row["target"], row["ros_distro"], tuple(sorted(row["platforms"])))
    expected = {inventory_key(row) for row in inventory_images(inventory, common, component)}
    require(len(images) == len(expected) and {inventory_key(row) for row in images} == expected,
            "build metadata does not cover exactly the image inventory")
    require(isinstance(upstream, list) and bool(upstream), "upstream images must be a nonempty array")
    for row in upstream:
        require(isinstance(row, dict) and row.get("name") in UPSTREAM_NAMES, "invalid upstream image")
        string(row.get("ros_distro"), "upstream ros_distro")
        string(row.get("ref"), "upstream ref")
        require(matches(DIGEST_RE, row.get("digest")) and row.get("uri") == f'docker-image://{row["ref"]}@{row["digest"]}', "invalid upstream digest/URI")
    expected_upstream = {(name, distro, f'ghcr.io/autowarefoundation/autoware:{name}-{distro}-{metadata["autoware_base_version"]}')
                         for name in UPSTREAM_NAMES for distro in inventory["ros_distros"]}
    require(len(upstream) == len(expected_upstream) and {(row["name"], row["ros_distro"], row["ref"]) for row in upstream} == expected_upstream,
            "upstream image metadata does not cover every required Autoware base")
    validate_scan(scan, build_tag)
    require(scan["policy_sha"] == metadata["openadkit_sha"], "scan policy SHA does not match build SHA")
    fields = ("repo", "target", "ros_distro", "digest", "platform")
    # Compared as sets: an identical scan row listed twice is still one image.
    require({tuple(row[key] for key in fields) for row in scan_rows(metadata)} ==
            {tuple(row[key] for key in fields) for row in scan["scanned_images"]},
            "scan metadata does not cover exactly the build digest/platforms")


def capture(directory: Path, env: dict[str, str]) -> dict[str, Any]:
    hashes = {key: hashlib.sha256((directory / file).read_bytes()).hexdigest() for file, key in (
        ("autoware-lock.repos", "autoware_lock_sha256"), ("image-inventory.json", "image_inventory_sha256"), ("upstream-images.json", "upstream_images_sha256"))}
    require(hashes["autoware_lock_sha256"] == env["PREPARED_LOCK_SHA256"], "Autoware lock SHA does not match prepare output")
    rows = inventory_images(load_json(directory / "image-inventory.json"), env["COMMON"], env["COMPONENT"])
    registry = Path(__file__).with_name("registry_lookup.sh")
    for row in rows:
        ref = image_ref(row, env["BUILD_TAG"])
        observed = json.loads(subprocess.check_output(["bash", "-c", 'source "$1"; registry_inspect_json "$2"', "registry", str(registry), ref], text=True))
        manifest = observed["manifest"]
        row.update(ref=ref, digest=manifest["digest"], platforms=sorted({f'{item["platform"]["os"]}/{item["platform"]["architecture"]}'
                   for item in manifest["manifests"] if item["platform"]["os"] != "unknown"}))
    metadata: dict[str, Any] = {key.lower(): env[key] for key in ("BUILD_TAG", "OPENADKIT_SHA", "AUTOWARE_INPUT_REF", "AUTOWARE_REF_TYPE", "AUTOWARE_REF", "AUTOWARE_BASE_VERSION")}
    # A partial rerun keeps prepare's build tag; the tag, not this attempt, names the images.
    run_id, run_attempt = env["BUILD_TAG"].split("-")
    metadata.update(hashes, run_id=run_id, run_attempt=run_attempt,
                    images=rows, upstream_images=load_json(directory / "upstream-images.json"))
    build_images(metadata)
    return metadata


def summary(metadata: dict[str, Any]) -> str:
    """One table for the run page: what was built, on what, and each image's digest."""
    lines = [
        f'Build `{metadata["build_tag"]}` · Autoware {metadata["autoware_base_version"]} '
        f'(`{metadata["autoware_ref"][:7]}`) · Open AD Kit `{metadata["openadkit_sha"][:7]}`',
        "",
        "| Image | Distro | Platforms | Digest |",
        "|---|---|---|---|",
    ]
    for image in metadata["images"]:
        platforms = ", ".join(platform.removeprefix("linux/") for platform in image["platforms"])
        lines.append(f'| `{image["target"]}` | {image["ros_distro"]} | {platforms} | `{image["digest"][:19]}` |')
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("capture", "scan-matrix", "scan-report", "check-scan", "validate"))
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "capture":
            directory = Path("build-metadata")
            metadata = capture(directory, dict(os.environ))
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as page:
                page.write(summary(metadata))
            (directory / "build-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        elif args.operation == "scan-matrix":
            print(json.dumps({"include": scan_rows(load_json(args.paths[0]))}, separators=(",", ":")))
        elif args.operation == "scan-report":
            env = os.environ
            report = {"build_tag": env["BUILD_TAG"], "policy_sha": env["POLICY_SHA"], "scan_scope": "all",
                      "scan_status": "passed" if env["SCAN_RESULT"] == "success" else "failed", "scan_result": env["SCAN_RESULT"],
                      "run_id": env["GITHUB_RUN_ID"], "run_attempt": env["GITHUB_RUN_ATTEMPT"],
                      "scanned_images": [{key: value for key, value in row.items() if key != "platform_label"} for row in json.loads(env["SCAN_MATRIX"])["include"]]}
            validate_scan(report, env["BUILD_TAG"])
            Path("scan-metadata").mkdir(exist_ok=True)
            Path("scan-metadata/scan-metadata.json").write_text(json.dumps(report, indent=2) + "\n")
        elif args.operation == "check-scan":
            validate_scan(load_json(args.paths[0]), os.environ["BUILD_TAG"])
        else:
            validate_artifacts(args.paths[0], load_json(args.paths[1]), os.environ["BUILD_TAG"], os.environ["IMAGE_PREFIX_COMMON"], os.environ["IMAGE_PREFIX_COMPONENT"])
    except (ValueError, OSError, KeyError, IndexError, TypeError, subprocess.CalledProcessError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
