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


CARLA_INTERFACE_ENV = "CARLA_INTERFACE_IMAGE"
CARLA_INTERFACE_TARGET = "carla-interface"
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
    module_path = source_root / "cli/manifest.py"
    if not module_path.is_file():
        fail(f"could not load runtime manifest module: {module_path}")
    spec = importlib.util.spec_from_file_location("openadkit_release_manifest", module_path)
    if spec is None or spec.loader is None:
        fail(f"could not load runtime manifest module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError) as error:
        fail(f"could not load runtime manifest module: {module_path}: {error}")
    return module


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{name} must be a nonempty string")
    return value


def load_product(runtime: ModuleType, source_root: Path) -> dict[str, Any]:
    kit = runtime.load_kit(source_root)
    if not kit.deployments:
        fail("release source has no deployments")

    deployments: dict[str, dict[str, str]] = {}
    shared_names: set[str] = set()
    distros: set[str] = set()
    validation: list[dict[str, Any]] = []
    for name in sorted(kit.deployments):
        deployment = runtime.get_deployment(source_root, kit, name)
        deployments[name] = {
            "path": kit.deployments[name].path,
            "checksum": runtime.deployment_checksum(deployment.directory),
        }
        shared_names.update(deployment.shared)
        gpu = deployment.requirements["gpu"]
        for distro in deployment.requirements["rosDistros"]:
            distros.add(distro)
            if gpu in ("none", "optional"):
                validation.append(
                    {"deployment": name, "gpu": False, "rosDistro": distro}
                )
            if gpu in ("required", "optional"):
                validation.append(
                    {"deployment": name, "gpu": True, "rosDistro": distro}
                )

    if not distros:
        fail("release deployments do not declare any ROS distros")
    if not validation:
        fail("release deployments do not produce any validation cases")
    if not shared_names:
        fail("release deployments do not declare shared assets")
    for name in sorted(shared_names):
        shared_dir = source_root / "deployments" / name
        if not shared_dir.is_dir():
            fail(f"missing shared deployment assets: {name}")

    validation.sort(key=lambda row: (row["deployment"], row["rosDistro"], row["gpu"]))
    return {
        "kit": kit,
        "deployments": deployments,
        "distros": sorted(distros),
        "shared": {
            name: runtime.deployment_checksum(source_root / "deployments" / name)
            for name in sorted(shared_names)
        },
        "validation": validation,
    }


def verify_staged_bundle(source_root: Path, plan: dict[str, Any]) -> None:
    runtime = load_runtime(source_root)
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

    for name in expected_deployments:
        meta = context["deployments"].get(name)
        if not isinstance(meta, dict):
            fail(f"release plan is missing deployment context: {name}")
        path = require_string(meta.get("path"), f"releaseContext.deployments.{name}.path")
        expected = require_string(
            meta.get("checksum"), f"releaseContext.deployments.{name}.checksum"
        )
        actual = runtime.deployment_checksum(source_root / path)
        if actual != expected:
            fail(f"deployment checksum mismatch: {name}")

    for name in expected_shared:
        expected = require_string(
            context["shared"].get(name), f"releaseContext.shared.{name}"
        )
        actual = runtime.deployment_checksum(source_root / "deployments" / name)
        if actual != expected:
            fail(f"shared checksum mismatch: {name}")


def verify_release_integrity(source_root: Path, plan: dict[str, Any]) -> None:
    runtime = load_runtime(source_root)
    kit = runtime.load_kit(source_root)
    expected = plan["bundle"]["deployments"]
    if sorted(kit.deployments) != sorted(expected):
        fail("staged bundle deployments do not match the release plan")
    for name in expected:
        deployment = runtime.get_deployment(source_root, kit, name)
        state = runtime.deployment_integrity(source_root, deployment, kit)
        if state != "intact":
            fail(f"packaged deployment is not intact: {name} ({state})")


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

    kit = product["kit"]
    component_images = dict(kit.component_images)
    component_images[CARLA_INTERFACE_ENV] = CARLA_INTERFACE_TARGET
    runtime_targets = sorted(set(component_images.values()))
    context_images: dict[str, dict[str, str]] = {}
    for distro in product["distros"]:
        distro_images: dict[str, str] = {}
        for target in runtime_targets:
            row = indexed.get((target, distro))
            if row is None:
                fail(f"missing runtime image: {target}-{distro}")
            distro_images[target] = row["releaseExactRef"]
        context_images[distro] = distro_images

    root_name = f"openadkit-{args.version}"
    asset_name = f"{root_name}.tar.gz"
    release_context = {
        "componentImages": component_images,
        "defaultRosDistro": args.default_ros_distro,
        "deployments": product["deployments"],
        "images": context_images,
        "kind": "release",
        "schemaVersion": 1,
        "shared": product["shared"],
        "version": args.version,
    }
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
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--build-metadata", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--release-sha")
    parser.add_argument("--packager-sha")
    parser.add_argument("--default-ros-distro")
    parser.add_argument("--stable-release", type=parse_bool)
    parser.add_argument("--publish-latest-aliases", type=parse_bool)
    parser.add_argument("--context-output", type=Path)
    args = parser.parse_args()
    try:
        source_root = args.source_root.resolve()
        if args.verify:
            plan = load_json(args.output)
            verify_staged_bundle(source_root, plan)
            context_path = args.context_output or (source_root / "openadkit.json")
            write_json(context_path, plan["releaseContext"])
            verify_release_integrity(source_root, plan)
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

        plan = build_plan(args)
        write_json(args.output, plan)
        if args.context_output:
            write_json(args.context_output, plan["releaseContext"])
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
