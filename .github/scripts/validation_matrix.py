#!/usr/bin/env python3
"""Manifest-derived views of a kit shared by lint, release planning and evidence.

A validation cell is one `./openadkit validate` invocation: a deployment, ROS
distro, GPU mode, and optional split-host node. An evidence cell is the complete
plan of one runtime evidence run, which run_cell.sh executes as given. The kit
inventory is what a release bundle ships. Lint, the release planner and the
evidence workflow all read these views, so a new deployment or node is walked
everywhere without editing a hardcoded list.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

EVIDENCE_PLATFORM = "linux/amd64"
# Topics that flow without a route or an initial pose, in every deployment.
FRESH_TOPICS = ("/system/operation_mode/availability",)
# What each curated behaviour proves beyond readiness: extra fresh topics (L1)
# and the end-to-end check run_cell.sh runs (L2). A cell passes only with L2,
# so every deployment that is not exempt needs an entry. Scenario simulation
# runs on sim time; planning simulation runs on wall time and has no /clock.
BEHAVIOUR_CHECKS: dict[str, dict[str, Any]] = {
    "planning-simulation": {"fresh": (), "l2": "golden"},
    "scenario-simulation": {"fresh": ("/clock",), "l2": "scenario"},
}
# The example kit's acceptance: fresh publication proves its C++ overlay node
# survived the ABI boundary, and custom_kit.py checks its parameter overrides.
EXAMPLE_KIT_CHECKS: dict[str, Any] = {"fresh": ("/acme/probe",), "l1": "custom-kit"}
# Host build products of an overlay workspace; never kit content.
COLCON_PRODUCTS = ("build", "install", "log")


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def load_runtime(source_root: Path) -> ModuleType:
    module_path = source_root / "cli/manifest.py"
    if not module_path.is_file():
        fail(f"could not load runtime manifest module: {module_path}")
    spec = importlib.util.spec_from_file_location("openadkit_matrix_manifest", module_path)
    if spec is None or spec.loader is None:
        fail(f"could not load runtime manifest module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError) as error:
        fail(f"could not load runtime manifest module: {module_path}: {error}")
    return module


def validation_cells(
    runtime: ModuleType,
    source_root: Path,
    kit: Any | None = None,
) -> list[dict[str, Any]]:
    """Return sorted validation cells for every deployment and node view."""
    kit = kit if kit is not None else runtime.load_kit(source_root)
    if not kit.deployments:
        fail("release source has no deployments")

    rows: list[dict[str, Any]] = []
    distros: set[str] = set()
    for name in sorted(kit.deployments):
        deployment = runtime.get_deployment(source_root, kit, name)
        gpu = deployment.requirements["gpu"]
        views = [""] + sorted(deployment.nodes)
        for distro in deployment.requirements["rosDistros"]:
            distros.add(distro)
            for node in views:
                if gpu in ("none", "optional"):
                    rows.append(
                        {
                            "deployment": name,
                            "gpu": False,
                            "rosDistro": distro,
                            "node": node,
                        }
                    )
                if gpu in ("required", "optional"):
                    rows.append(
                        {
                            "deployment": name,
                            "gpu": True,
                            "rosDistro": distro,
                            "node": node,
                        }
                    )
    if not distros:
        fail("release deployments do not declare any ROS distros")
    if not rows:
        fail("release deployments do not produce any validation cases")
    rows.sort(
        key=lambda row: (
            row["deployment"],
            row["rosDistro"],
            row["gpu"],
            row["node"],
        )
    )
    return rows


def evidence_cells(
    runtime: ModuleType,
    source_root: Path,
    kit: Any | None = None,
) -> list[dict[str, str]]:
    """Cells the evidence workflow runs: every distro of every deployment that
    is not exempt, plus one cell running all nodes where a deployment declares
    nodes. Each cell carries its identity and everything run_cell.sh checks."""
    kit = kit if kit is not None else runtime.load_kit(source_root)
    cells: list[dict[str, str]] = []
    for name in sorted(kit.deployments):
        deployment = runtime.get_deployment(source_root, kit, name)
        if deployment.evidence_exemption:
            continue
        # A kit runs its base deployment's behaviour on top of its own layer.
        behaviour = deployment.base.name if deployment.base else name
        checks = BEHAVIOUR_CHECKS.get(behaviour)
        if checks is None:
            fail(
                f"{name} has no L2 evidence check for {behaviour}; "
                "add one to BEHAVIOUR_CHECKS or declare evidence.exempt"
            )
        for distro in deployment.requirements["rosDistros"]:
            identities = [{"deployment": name, "distro": distro}]
            if deployment.nodes:
                identities.append({"deployment": name, "distro": distro, "node": "split"})
            for identity in identities:
                cells.append(identity | {
                    "name": evidence_cell_name(identity),
                    "platform": EVIDENCE_PLATFORM,
                    # Started in manifest order and stopped in reverse.
                    "nodes": " ".join(deployment.nodes) if "node" in identity else "",
                    "fresh": " ".join((*FRESH_TOPICS, *checks["fresh"])),
                    "l1": "",
                    "l2": checks["l2"],
                })
    return cells


def example_kit_roots(runtime: ModuleType, source_root: Path) -> list[Path]:
    """The one integrator example, deployments/custom-kit."""
    relative = "deployments/custom-kit"
    root = source_root / relative
    if not (root / "openadkit.json").is_file():
        fail(f"custom-kit example is missing ({relative}); its cells are required evidence")
    if runtime.load_json(root / "openadkit.json").get("kind") != "kit":
        fail(f"custom-kit example must declare kind: kit ({relative})")
    return [root]


def example_kit_cells(runtime: ModuleType, source_root: Path) -> list[dict[str, str]]:
    """Exercise the custom-kit example against the same build as the base."""
    return [cell | {
        "kit": root.relative_to(source_root).as_posix(),
        "fresh": " ".join((cell["fresh"], *EXAMPLE_KIT_CHECKS["fresh"])),
        "l1": EXAMPLE_KIT_CHECKS["l1"],
    } for root in example_kit_roots(runtime, source_root) for cell in evidence_cells(runtime, root)]


def evidence_cell_name(cell: dict[str, Any]) -> str:
    """The hosted runtime cell identity, shared by the workflow matrix and the summary."""
    node = cell.get("node") or ""
    suffix = f"-{node}" if node else ""
    platform = EVIDENCE_PLATFORM.replace("/", "-")
    return f"{cell['deployment']}-{cell['distro']}{suffix}-{platform}"


def kit_inventory(
    runtime: ModuleType,
    source_root: Path,
    kit: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """What a kit ships: deployment paths and checksums, and shared asset checksums.

    The release plan and bundle staging and verification read this one view,
    so packaging and the evidence kit cannot disagree about a kit's contents.
    """
    kit = kit if kit is not None else runtime.load_kit(source_root)
    deployments: dict[str, dict[str, str]] = {}
    shared: set[str] = set()
    for name in sorted(kit.deployments):
        deployment = runtime.get_deployment(source_root, kit, name)
        deployments[name] = {
            "path": kit.deployments[name].path,
            "checksum": runtime.deployment_checksum(deployment.directory),
        }
        shared.update(deployment.shared)
    return {
        "deployments": deployments,
        "shared": {
            name: runtime.deployment_checksum(source_root / "deployments" / name)
            for name in sorted(shared)
        },
    }


def evidence_exemptions(
    runtime: ModuleType,
    source_root: Path,
    kit: Any | None = None,
) -> list[dict[str, str]]:
    kit = kit if kit is not None else runtime.load_kit(source_root)
    exempt = []
    for name in sorted(kit.deployments):
        reason = runtime.get_deployment(source_root, kit, name).evidence_exemption
        if reason:
            exempt.append({"deployment": name, "reason": reason})
    return exempt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--evidence-cells",
        action="store_true",
        help="print the evidence cells as a GitHub matrix instead",
    )
    parser.add_argument("--include-example-kits", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    try:
        runtime = load_runtime(source_root)
        if args.evidence_cells:
            cells = evidence_cells(runtime, source_root)
            if args.include_example_kits:
                cells.extend(example_kit_cells(runtime, source_root))
            print(json.dumps({"include": cells}))
            return 0
        cells = validation_cells(runtime, source_root)
    except ValueError as error:
        parser.error(str(error))
    for cell in cells:
        fields = (
            cell["deployment"],
            cell["rosDistro"],
            "true" if cell["gpu"] else "false",
            cell["node"],
        )
        print("\t".join(fields))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
