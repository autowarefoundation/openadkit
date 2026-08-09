#!/usr/bin/env python3
"""Build the immutable release plan and runtime context."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any


CURATED_DEPLOYMENTS = (
    "logging-simulation",
    "planning-simulation",
    "scenario-simulation",
)
ROS_DISTROS = ("humble", "jazzy")
SEMVER_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"could not read JSON from {path}: {error}")
    if not isinstance(value, dict):
        fail(f"JSON root must be an object: {path}")
    return value


def load_runtime(source_root: Path) -> ModuleType:
    module_path = source_root / "openadkit.d/manifest.py"
    spec = importlib.util.spec_from_file_location("openadkit_release_manifest", module_path)
    if spec is None or spec.loader is None:
        fail(f"could not load runtime manifest module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{name} must be a nonempty string")
    return value


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    source_root = args.source_root.resolve()
    metadata = load_json(args.build_metadata)
    runtime = load_runtime(source_root)

    if not SEMVER_RE.fullmatch(args.version):
        fail(f"invalid release version: {args.version}")
    if not SHA_RE.fullmatch(args.release_sha):
        fail("release SHA must be 40 lowercase hexadecimal characters")
    if not SHA_RE.fullmatch(args.packager_sha):
        fail("packager SHA must be 40 lowercase hexadecimal characters")
    if args.default_ros_distro not in ROS_DISTROS:
        fail(f"unsupported default ROS distro: {args.default_ros_distro}")
    if args.publish_latest_aliases and not args.stable_release:
        fail("prereleases cannot publish stable aliases")
    if metadata.get("openadkit_sha") != args.release_sha:
        fail("build metadata Open AD Kit SHA does not match the release SHA")

    build_tag = require_string(metadata.get("build_tag"), "build_tag")
    raw_images = metadata.get("images")
    if not isinstance(raw_images, list) or not raw_images:
        fail("build metadata images must be a nonempty array")

    image_rows: list[dict[str, Any]] = []
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_images):
        if not isinstance(raw, dict):
            fail(f"images[{index}] must be an object")
        repo = require_string(raw.get("repo"), f"images[{index}].repo")
        target = require_string(raw.get("target"), f"images[{index}].target")
        distro = require_string(raw.get("ros_distro"), f"images[{index}].ros_distro")
        source_ref = require_string(raw.get("ref"), f"images[{index}].ref")
        digest = require_string(raw.get("digest"), f"images[{index}].digest")
        platforms = raw.get("platforms")
        key = (repo, target, distro)
        if key in seen:
            fail(f"duplicate build image: {repo}:{target}-{distro}")
        seen.add(key)
        if not DIGEST_RE.fullmatch(digest):
            fail(f"invalid image digest for {target}-{distro}")
        if source_ref != f"{repo}:{target}-{distro}-{build_tag}":
            fail(f"invalid source image reference for {target}-{distro}")
        if not isinstance(platforms, list) or not platforms or any(
            platform not in ("linux/amd64", "linux/arm64") for platform in platforms
        ):
            fail(f"invalid platforms for {target}-{distro}")

        release_ref = f"{repo}:{target}-{distro}-{args.version}"
        aliases: list[str] = []
        if args.stable_release and args.publish_latest_aliases:
            aliases.extend((f"{repo}:{target}-{distro}", f"{repo}:{target}-{distro}-latest"))
            if distro == args.default_ros_distro:
                aliases.extend((f"{repo}:{target}", f"{repo}:{target}-latest"))
        row = {
            "aliases": aliases,
            "digest": digest,
            "platforms": sorted(platforms),
            "releaseExactRef": f"{release_ref}@{digest}",
            "releaseRef": release_ref,
            "repo": repo,
            "rosDistro": distro,
            "sourceRef": source_ref,
            "target": target,
        }
        image_rows.append(row)
        runtime_key = (target, distro)
        if runtime_key in indexed:
            fail(f"duplicate target/distro image across repositories: {target}-{distro}")
        indexed[runtime_key] = row

    runtime_targets = sorted(set(runtime.COMPONENT_IMAGE_TARGETS.values()))
    context_images: dict[str, dict[str, str]] = {}
    for distro in ROS_DISTROS:
        distro_images: dict[str, str] = {}
        for target in runtime_targets:
            row = indexed.get((target, distro))
            if row is None:
                fail(f"missing runtime image: {target}-{distro}")
            distro_images[target] = row["releaseExactRef"]
        context_images[distro] = distro_images

    discovered = runtime.discover(source_root)
    if set(discovered) != set(CURATED_DEPLOYMENTS):
        fail(
            "release source must contain exactly the curated deployments: "
            + ", ".join(CURATED_DEPLOYMENTS)
        )
    deployments: dict[str, str] = {}
    shared_names: set[str] = set()
    for name in CURATED_DEPLOYMENTS:
        deployment = runtime.validate_manifest(source_root, discovered[name])
        deployments[name] = runtime.deployment_checksum(deployment.directory)
        shared_names.update(deployment.shared)
    if shared_names != {"base"}:
        fail("curated deployments must use exactly the shared base assets")
    shared = {
        name: runtime.deployment_checksum(source_root / "deployments" / name)
        for name in sorted(shared_names)
    }

    root_name = f"openadkit-{args.version}"
    asset_name = f"{root_name}.tar.gz"
    release_context = {
        "defaultRosDistro": args.default_ros_distro,
        "deployments": deployments,
        "images": context_images,
        "kind": "release",
        "schemaVersion": 1,
        "shared": shared,
        "version": args.version,
    }
    return {
        "bundle": {
            "asset": asset_name,
            "deployments": list(CURATED_DEPLOYMENTS),
            "root": root_name,
            "runtime": ["openadkit", "openadkit.d"],
            "shared": sorted(shared_names),
        },
        "githubAssets": [
            {"name": "release-plan.json", "path": "release-plan.json"},
            {"name": "release-metadata.json", "path": "release-metadata.json"},
            {
                "name": "autoware-lock.repos",
                "path": "release-input/build/autoware-lock.repos",
            },
            {
                "name": "upstream-images.json",
                "path": "release-input/build/upstream-images.json",
            },
            {"name": asset_name, "path": f"dist/{asset_name}"},
        ],
        "images": sorted(
            image_rows,
            key=lambda row: (row["repo"], row["target"], row["rosDistro"]),
        ),
        "release": {
            "buildTag": build_tag,
            "defaultRosDistro": args.default_ros_distro,
            "packagerSha": args.packager_sha,
            "publishLatestAliases": args.publish_latest_aliases,
            "releaseSha": args.release_sha,
            "stable": args.stable_release,
            "version": args.version,
        },
        "releaseContext": release_context,
        "schemaVersion": 1,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )


def parse_bool(value: str) -> bool:
    if value not in ("true", "false"):
        raise argparse.ArgumentTypeError("expected true or false")
    return value == "true"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--build-metadata", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--packager-sha", required=True)
    parser.add_argument("--default-ros-distro", required=True)
    parser.add_argument("--stable-release", type=parse_bool, required=True)
    parser.add_argument("--publish-latest-aliases", type=parse_bool, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-output", type=Path)
    args = parser.parse_args()
    try:
        plan = build_plan(args)
        write_json(args.output, plan)
        if args.context_output:
            write_json(args.context_output, plan["releaseContext"])
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
