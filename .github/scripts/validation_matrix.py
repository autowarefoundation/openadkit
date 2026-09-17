#!/usr/bin/env python3
"""Enumerate package validation cells shared by lint and release planning.

One cell is one `./openadkit validate` invocation: a deployment, ROS distro,
GPU mode, and optional split-host role. Both the lint workflow (via this
script) and `.github/scripts/release_plan.py` (which imports
`validation_cells`) read the same enumeration, so a new deployment or role is
walked everywhere without editing a hardcoded list.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def fail(message: str) -> None:
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
    """Return sorted validation cells for every deployment and role view."""
    kit = kit if kit is not None else runtime.load_kit(source_root)
    if not kit.deployments:
        fail("release source has no deployments")

    rows: list[dict[str, Any]] = []
    distros: set[str] = set()
    for name in sorted(kit.deployments):
        deployment = runtime.get_deployment(source_root, kit, name)
        gpu = deployment.requirements["gpu"]
        views = [""] + sorted(deployment.roles)
        for distro in deployment.requirements["rosDistros"]:
            distros.add(distro)
            for role in views:
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        cells = validation_cells(load_runtime(args.source_root.resolve()), args.source_root.resolve())
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
