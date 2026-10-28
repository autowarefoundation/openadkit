#!/usr/bin/env python3
"""Build the immutable release plan and runtime context."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

import autoware_patches
import validation_matrix
from evidence.release_gate import validate_report
from images import build_images, image_ref

_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
# Strict SemVer release tag; must agree with the launcher (test_release_versions.py).
SEMVER_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    rf"(?:-{_IDENTIFIER}(?:\.{_IDENTIFIER})*)?$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ROS_SNAPSHOT_RE = re.compile(r'variable "ROS_SNAPSHOT_([A-Z]+)" \{\s*default = "(\d{4}-\d{2}-\d{2})"\s*\}')


def fail(message: str) -> NoReturn:
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
    return validation_matrix.load_runtime(source_root)


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{name} must be a nonempty string")
    return value


def load_product(runtime: ModuleType, source_root: Path) -> dict[str, Any]:
    kit = runtime.load_kit(source_root)
    validation = validation_matrix.validation_cells(runtime, source_root, kit)
    inventory = validation_matrix.kit_inventory(runtime, source_root, kit)
    if not inventory["shared"]:
        fail("release deployments do not declare shared assets")
    return {
        "kit": kit,
        **inventory,
        "distros": sorted({row["rosDistro"] for row in validation}),
        "validation": validation,
        "evidenceExempt": validation_matrix.evidence_exemptions(runtime, source_root, kit),
    }


def stage_bundle(
    source_root: Path, plan: dict[str, Any], bundle_root: Path, *, include_example_kits: bool
) -> None:
    """Copy the planned kit into bundle_root, verify it and pin its release context.

    Release packaging and evidence staging both stage through here, so the
    evidence cells run the tree the release ships; evidence adds only the
    example kits, without their host colcon products.
    """
    if bundle_root.exists():
        fail(f"bundle root already exists: {bundle_root}")
    items = [
        *plan["bundle"]["runtime"],
        *(meta["path"] for meta in plan["releaseContext"]["deployments"].values()),
        *(f"deployments/{name}" for name in plan["bundle"]["shared"]),
    ]
    scrubbed = ["config.local.env", "__pycache__", "*.pyc"]
    examples: list[str] = []
    if include_example_kits:
        runtime = load_runtime(source_root)
        examples = [
            root.relative_to(source_root).as_posix()
            for root in validation_matrix.example_kit_roots(runtime, source_root)
        ]
    for item in [*items, *examples]:
        source, target = source_root / item, bundle_root / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir() and not source.is_symlink():
            patterns = scrubbed + (list(validation_matrix.COLCON_PRODUCTS) if item in examples else [])
            shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns(*patterns))
        else:
            shutil.copy2(source, target, follow_symlinks=False)
    for directory, names, files in os.walk(bundle_root):
        for name in [*names, *files]:
            if os.path.islink(os.path.join(directory, name)):
                fail(f"Release bundle must not contain symlinks: {os.path.join(directory, name)}")

    verify_staged_bundle(bundle_root, plan)
    write_json(bundle_root / "openadkit.json", plan["releaseContext"])
    verify_release_integrity(bundle_root, plan)


def verify_staged_bundle(bundle_root: Path, plan: dict[str, Any]) -> None:
    context = plan.get("releaseContext")
    bundle = plan.get("bundle")
    if not isinstance(context, dict) or not isinstance(bundle, dict):
        fail("release plan is missing bundle or releaseContext")

    expected_deployments = bundle.get("deployments")
    expected_shared = bundle.get("shared")
    if not isinstance(expected_deployments, list) or not expected_deployments:
        fail("release plan bundle.deployments must be a nonempty array")
    if not isinstance(expected_shared, list) or not expected_shared:
        fail("release plan bundle.shared must be a nonempty array")
    if sorted(expected_deployments) != sorted(context.get("deployments", {})):
        fail("release plan deployments do not match releaseContext")
    if sorted(expected_shared) != sorted(context.get("shared", {})):
        fail("release plan shared assets do not match releaseContext")

    staged = validation_matrix.kit_inventory(load_runtime(bundle_root), bundle_root)
    for name in expected_deployments:
        meta = context["deployments"].get(name)
        if not isinstance(meta, dict):
            fail(f"release plan is missing deployment context: {name}")
        require_string(meta.get("path"), f"releaseContext.deployments.{name}.path")
        require_string(meta.get("checksum"), f"releaseContext.deployments.{name}.checksum")
        if staged["deployments"].get(name) != meta:
            fail(f"deployment checksum mismatch: {name}")
    for name in expected_shared:
        expected = require_string(context["shared"].get(name), f"releaseContext.shared.{name}")
        if staged["shared"].get(name) != expected:
            fail(f"shared checksum mismatch: {name}")


def verify_release_integrity(bundle_root: Path, plan: dict[str, Any]) -> None:
    runtime = load_runtime(bundle_root)
    kit = runtime.load_kit(bundle_root)
    expected = plan["bundle"]["deployments"]
    if sorted(kit.deployments) != sorted(expected):
        fail("staged bundle deployments do not match the release plan")
    for name in expected:
        deployment = runtime.get_deployment(bundle_root, kit, name)
        state = runtime.deployment_integrity(bundle_root, deployment, kit)
        if state != "intact":
            fail(f"packaged deployment is not intact: {name} ({state})")


def ros_snapshots(source_root: Path, distros: list[str]) -> dict[str, str]:
    """The ROS apt snapshot each distro's images were built from."""
    bake = (source_root / "components/docker-bake.hcl").read_text(encoding="utf-8")
    snapshots = {name.lower(): date for name, date in ROS_SNAPSHOT_RE.findall(bake)}
    missing = sorted(set(distros) - snapshots.keys())
    if missing:
        fail(f"components/docker-bake.hcl declares no ROS snapshot for: {', '.join(missing)}")
    return {distro: snapshots[distro] for distro in sorted(distros)}


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    source_root = args.source_root.resolve()
    metadata = load_json(args.build_metadata)
    runtime = load_runtime(source_root)
    product = load_product(runtime, source_root)

    if not SEMVER_RE.fullmatch(args.version):
        fail(f"invalid release version: {args.version}")
    if not SHA_RE.fullmatch(args.release_sha):
        fail("release SHA must be 40 lowercase hexadecimal characters")
    if not SHA_RE.fullmatch(args.packager_sha):
        fail("packager SHA must be 40 lowercase hexadecimal characters")
    if args.default_ros_distro not in product["distros"]:
        fail(f"unsupported default ROS distro: {args.default_ros_distro}")
    if args.publish_latest_aliases and not args.stable_release:
        fail("prereleases cannot publish stable aliases")
    if metadata.get("openadkit_sha") != args.release_sha:
        fail("build metadata Open AD Kit SHA does not match the release SHA")

    build_tag = require_string(metadata.get("build_tag"), "build_tag")
    image_rows: list[dict[str, Any]] = []
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in build_images(metadata):
        repo, target, distro = raw["repo"], raw["target"], raw["ros_distro"]
        digest = raw["digest"]
        release_ref = image_ref(raw, args.version)
        aliases: list[str] = []
        if args.stable_release and args.publish_latest_aliases:
            aliases.extend((f"{repo}:{target}-{distro}", f"{repo}:{target}-{distro}-latest"))
            if distro == args.default_ros_distro:
                aliases.extend((f"{repo}:{target}", f"{repo}:{target}-latest"))
        row: dict[str, Any] = {
            "aliases": aliases,
            "digest": digest,
            "platforms": sorted(raw["platforms"]),
            "releaseExactRef": f"{release_ref}@{digest}",
            "releaseRef": release_ref,
            "repo": repo,
            "rosDistro": distro,
            "sourceRef": raw["ref"],
            "target": target,
        }
        image_rows.append(row)
        runtime_key = (target, distro)
        if runtime_key in indexed:
            fail(f"duplicate target/distro image across repositories: {target}-{distro}")
        indexed[runtime_key] = row

    kit = product["kit"]
    component_images = dict(kit.component_images)
    # The devel image ships pinned too, so integrators build overlays in it.
    runtime_targets = sorted(set(component_images.values()) | {runtime.DEVEL_IMAGE_TARGET})
    context_images: dict[str, dict[str, str]] = {}
    for distro in product["distros"]:
        distro_images: dict[str, str] = {}
        for target in runtime_targets:
            image = indexed.get((target, distro))
            if image is None:
                fail(f"missing runtime image: {target}-{distro}")
            distro_images[target] = image["releaseExactRef"]
        context_images[distro] = distro_images

    root_name = f"openadkit-{args.version}"
    asset_name = f"{root_name}.tar.gz"
    autoware: dict[str, Any] = {
        "version": require_string(metadata.get("autoware_base_version"), "autoware_base_version"),
        "ref": require_string(metadata.get("autoware_ref"), "autoware_ref"),
        "lockSha256": require_string(metadata.get("autoware_lock_sha256"), "autoware_lock_sha256"),
    }
    # The fixes the build applied on top of the tag; the release commit is the
    # build commit, so its patch directory is what the images carry.
    backports = autoware_patches.list_patches(source_root)
    if backports:
        autoware["backports"] = [
            {key: item[key] for key in ("repository", "subject", "upstream")} for item in backports
        ]
    release_context = {
        "artifacts": kit.artifacts,
        "autoware": autoware,
        "componentImages": component_images,
        "defaultRosDistro": args.default_ros_distro,
        "deployments": product["deployments"],
        "images": context_images,
        "kind": "release",
        "schemaVersion": runtime.SCHEMA_VERSION,
        "shared": product["shared"],
        "version": args.version,
    }
    evidence = {"exempt": product["evidenceExempt"]}
    if args.evidence_report is not None:
        evidence = load_json(args.evidence_report)
        validate_report(evidence, metadata, source_root, args.default_ros_distro)
    return {
        "bundle": {
            "asset": asset_name,
            "deployments": sorted(product["deployments"]),
            "root": root_name,
            "runtime": ["openadkit", "openadkit.json", "cli"],
            "shared": sorted(product["shared"]),
            "validation": product["validation"],
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
            {"name": "openadkit", "path": "dist/openadkit"},
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
        "rosSnapshots": ros_snapshots(source_root, product["distros"]),
        # Deployments that ship without CI evidence, with the reason.
        "evidence": evidence,
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--stage",
        type=Path,
        metavar="BUNDLE_ROOT",
        help="stage and verify the kit of the existing plan at --output",
    )
    parser.add_argument("--include-example-kits", action="store_true")
    parser.add_argument("--build-metadata", type=Path)
    parser.add_argument("--evidence-report", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--release-sha")
    parser.add_argument("--packager-sha")
    parser.add_argument("--default-ros-distro")
    parser.add_argument("--stable-release", type=parse_bool)
    parser.add_argument("--publish-latest-aliases", type=parse_bool)
    args = parser.parse_args()
    try:
        source_root = args.source_root.resolve()
        if args.stage:
            stage_bundle(
                source_root,
                load_json(args.output),
                args.stage.resolve(),
                include_example_kits=args.include_example_kits,
            )
            return 0

        required = {
            "--build-metadata": args.build_metadata,
            "--version": args.version,
            "--release-sha": args.release_sha,
            "--packager-sha": args.packager_sha,
            "--default-ros-distro": args.default_ros_distro,
            "--stable-release": args.stable_release,
            "--publish-latest-aliases": args.publish_latest_aliases,
        }
        missing = [flag for flag, value in required.items() if value is None]
        if missing:
            parser.error("the following arguments are required: " + ", ".join(missing))

        write_json(args.output, build_plan(args))
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
