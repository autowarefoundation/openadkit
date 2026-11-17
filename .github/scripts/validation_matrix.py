#!/usr/bin/env python3
"""Manifest-derived views of a kit shared by lint, release planning and evidence.

A validation cell is one `./openadkit validate` invocation: a deployment, ROS
distro, GPU mode, and optional split-host role. An evidence cell is the complete
plan of one runtime evidence run, which run_cell.sh executes as given. The kit
inventory is what a release bundle ships. Lint, the release planner and the
evidence workflow all read these views, so a new deployment or role is walked
everywhere without editing a hardcoded list.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

# A cell runs on a hosted runner of its own architecture, for every
# architecture its deployment supports.
EVIDENCE_PLATFORMS = ("linux/amd64", "linux/arm64")
# Readiness (L1) is each deployment's healthchecks, which `openadkit run` waits
# for, and the end-to-end level (L2) its manifest's verify step. A cell passes
# only with L2, so every deployment that is not exempt declares one.
# Cells beyond Compose on Docker, for each distro: the backend run_cell.sh starts
# the stack with, on the runner it needs. quadlet runs platforms/autosd under
# Podman and systemd.
PLATFORM_CELLS: dict[str, dict[str, str]] = {
    "planning-simulation": {"backend": "quadlet", "runner": "ubuntu-24.04"},
}
# The same runner image for an arm64 cell.
ARM64_RUNNER_SUFFIX = "-arm"
# The example kits and their bases, exercised against the same build as the
# base: made by the staged kit's own `openadkit new` into kits/, with the CI
# fixture on top (an overlay C++ package, a parameter override, a healthcheck
# and a pinned external image).
EXAMPLE_KITS = {"example-kit": ("planning-simulation", "logging-simulation")}
EXAMPLE_KIT_DIRECTORY = "kits"
EXAMPLE_KIT_FIXTURE = Path(__file__).resolve().parent / "evidence/example-kit"
# Host build products of an overlay workspace; never kit content.
COLCON_PRODUCTS = ("build", "install", "log")


def fail(message: str) -> NoReturn:
    raise ValueError(message)


# The CLI modules the catalog needs; each source root loads its own copy.
RUNTIME_MODULES = ("manifest", "catalog")


def load_runtime(source_root: Path) -> ModuleType:
    """The catalog module of the CLI in source_root, without touching other loads."""
    directory = source_root / "cli"
    if not (directory / "catalog.py").is_file():
        fail(f"could not load the runtime catalog module: {directory / 'catalog.py'}")
    saved = {name: sys.modules.pop(name) for name in RUNTIME_MODULES if name in sys.modules}
    sys.path.insert(0, str(directory))
    try:
        return importlib.import_module("catalog")
    except (OSError, ImportError) as error:
        fail(f"could not load the runtime catalog module: {directory}: {error}")
    finally:
        sys.path.remove(str(directory))
        for name in RUNTIME_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def validation_cells(
    runtime: ModuleType,
    source_root: Path,
    catalog: Any | None = None,
) -> list[dict[str, Any]]:
    """Return sorted validation cells for every deployment and each of its roles."""
    catalog = catalog if catalog is not None else runtime.load_catalog(source_root)
    if not catalog.deployments:
        fail("release source has no deployments")

    rows: list[dict[str, Any]] = []
    distros: set[str] = set()
    for name in sorted(catalog.deployments):
        deployment = runtime.get_deployment(source_root, catalog, name)
        gpu = deployment.requirements["gpu"]
        roles = [""] + sorted(deployment.roles)
        for distro in deployment.requirements["rosDistros"]:
            distros.add(distro)
            for role in roles:
                if gpu in ("none", "optional"):
                    rows.append(
                        {
                            "deployment": name,
                            "gpu": False,
                            "rosDistro": distro,
                            "role": role,
                        }
                    )
                if gpu in ("required", "optional"):
                    rows.append(
                        {
                            "deployment": name,
                            "gpu": True,
                            "rosDistro": distro,
                            "role": role,
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
            row["role"],
        )
    )
    return rows


def evidence_cells(
    runtime: ModuleType,
    source_root: Path,
    catalog: Any | None = None,
    platforms: tuple[str, ...] = EVIDENCE_PLATFORMS,
) -> list[dict[str, str]]:
    """Cells the evidence workflow runs: every distro and architecture of every
    deployment that is not exempt, plus one cell running all roles where a
    deployment declares roles. Each cell carries its identity and everything
    run_cell.sh checks."""
    catalog = catalog if catalog is not None else runtime.load_catalog(source_root)
    cells: list[dict[str, str]] = []
    for name in sorted(catalog.deployments):
        deployment = runtime.get_deployment(source_root, catalog, name)
        if deployment.evidence_exemption:
            continue
        if deployment.verify is None:
            fail(f"{name} declares no verify step; add one to its deployment.json or declare evidence.exempt")
        supported = [platform for platform in platforms
                     if platform.split("/")[1] in deployment.requirements["architectures"]]
        for distro, platform in ((distro, platform) for distro in deployment.requirements["rosDistros"]
                                 for platform in supported):
            identities = [{"deployment": name, "distro": distro, "platform": platform}]
            if deployment.roles:
                identities.append({"deployment": name, "distro": distro, "platform": platform, "role": "split"})
            for identity in identities:
                cells.append(identity | {
                    "name": evidence_cell_name(identity),
                    # Started in manifest order and stopped in reverse.
                    "roles": " ".join(deployment.roles) if "role" in identity else "",
                    "verify": json.dumps(deployment.verify),
                })
        if name in PLATFORM_CELLS:
            for row in [row for row in cells if row["deployment"] == name and "role" not in row]:
                cell = row | PLATFORM_CELLS[name]
                if cell["platform"] == "linux/arm64":
                    cell["runner"] += ARM64_RUNNER_SUFFIX
                cells.append(cell | {"name": evidence_cell_name(cell)})
    # One plain cell per distro also checks the launch arguments of every
    # deployment, the exempt ones included (evidence/launch_arguments.py).
    for distro in sorted({cell["distro"] for cell in cells}):
        plain = next(cell for cell in cells if cell["distro"] == distro and not cell.keys() & {"role", "backend"})
        plain["launch_arguments"] = "all"
    return cells


def make_example_kits(launcher_root: Path, parent: Path) -> list[Path]:
    """Make the example kits in parent with launcher_root's `openadkit new`, the CI fixture on top."""
    parent.mkdir(parents=True, exist_ok=True)
    environment = {name: value for name, value in os.environ.items() if name not in ("OPENADKIT_KIT", "OPENADKIT_DELEGATED")}
    kits = []
    for name, (base, *more_bases) in EXAMPLE_KITS.items():
        result = subprocess.run(
            [str(launcher_root / "openadkit"), "new", name, "--base", base],
            cwd=parent, env=environment, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            fail(f"openadkit new {name} failed: {result.stderr.strip()}")
        kit = parent / name
        shutil.copytree(
            EXAMPLE_KIT_FIXTURE, kit, dirs_exist_ok=True,
            # The fixture's README describes the fixture; the kit keeps the one new wrote.
            ignore=shutil.ignore_patterns("external-images.json", "README.md", "__pycache__", *COLCON_PRODUCTS),
        )
        manifest = json.loads((kit / "openadkit.json").read_text(encoding="utf-8"))
        manifest["externalImages"] = json.loads((EXAMPLE_KIT_FIXTURE / "external-images.json").read_text(encoding="utf-8"))
        # The same kit on its other bases: one manifest entry each.
        manifest["deployments"] |= {f"{name}-{other}": {"base": other} for other in more_bases}
        (kit / "openadkit.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        kits.append(kit)
    return kits


def example_kit_cells(
    runtime: ModuleType, source_root: Path, platforms: tuple[str, ...] = EVIDENCE_PLATFORMS,
) -> list[dict[str, str]]:
    """Each example kit runs its first deployment in its base's single-host
    cells, from its directory in kits/; the cells validate its other deployments."""
    base_cells = evidence_cells(runtime, source_root, platforms=platforms)
    cells = []
    for name, (base, *_) in EXAMPLE_KITS.items():
        for cell in base_cells:
            if cell["deployment"] == base and not cell.get("role") and not cell.get("backend"):
                # The base's cell already checks the launch arguments.
                kit_cell = {key: value for key, value in cell.items() if key != "launch_arguments"}
                kit_cell |= {"deployment": f"{name}-{base}", "kit": f"{EXAMPLE_KIT_DIRECTORY}/{name}"}
                cells.append(kit_cell | {"name": evidence_cell_name(kit_cell)})
    return cells


def evidence_cell_name(cell: dict[str, Any]) -> str:
    """The evidence cell identity, shared by the workflow matrix and the summary."""
    variant = cell.get("role") or cell.get("backend") or ""
    suffix = f"-{variant}" if variant else ""
    platform = cell["platform"].replace("/", "-")
    return f"{cell['deployment']}-{cell['distro']}{suffix}-{platform}"


def catalog_inventory(
    runtime: ModuleType,
    source_root: Path,
    catalog: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """What a kit ships: deployment paths and checksums, and shared asset checksums.

    The release plan and bundle staging and verification read this one view,
    so packaging and the evidence kit cannot disagree about a kit's contents.
    """
    catalog = catalog if catalog is not None else runtime.load_catalog(source_root)
    deployments: dict[str, dict[str, str]] = {}
    shared: set[str] = set()
    for name in catalog.deployments:
        deployment = runtime.get_deployment(source_root, catalog, name)
        deployments[name] = {
            "path": catalog.deployments[name].path,
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
    catalog: Any | None = None,
) -> list[dict[str, str]]:
    catalog = catalog if catalog is not None else runtime.load_catalog(source_root)
    exempt = []
    for name in sorted(catalog.deployments):
        reason = runtime.get_deployment(source_root, catalog, name).evidence_exemption
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
    parser.add_argument(
        "--evidence-platforms", default=",".join(EVIDENCE_PLATFORMS), metavar="LIST",
        help="comma-separated platforms to list evidence cells for (default: all)",
    )
    parser.add_argument(
        "--make-example-kits", type=Path, metavar="DIRECTORY",
        help="make the example kits in DIRECTORY with this checkout's openadkit new instead",
    )
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    try:
        if args.make_example_kits:
            for kit in make_example_kits(source_root, args.make_example_kits.resolve()):
                print(kit)
            return 0
        runtime = load_runtime(source_root)
        if args.evidence_cells:
            platforms = tuple(args.evidence_platforms.split(","))
            unknown = sorted(set(platforms) - set(EVIDENCE_PLATFORMS))
            if unknown:
                parser.error(f"unknown evidence platform: {', '.join(unknown)}")
            cells = evidence_cells(runtime, source_root, platforms=platforms)
            if args.include_example_kits:
                cells.extend(example_kit_cells(runtime, source_root, platforms))
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
            cell["role"],
        )
        print("\t".join(fields))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
