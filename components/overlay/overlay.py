#!/usr/bin/env python3
"""Build /tmp/openadkit: stable paths and the merged config overrides.

Overrides come in layers mounted under /openadkit/config, applied in order:
shared (all our deployments), base (the deployment a kit builds on) and
deployment (the one being run). Inside each layer, autoware/<package>/<path>
overrides <path> in that package's share directory. A YAML override holds only
the changed parameters and is merged into the file; any other file replaces
it. Keys and files with no counterpart in the package are reported, because
after an upgrade they usually mean a parameter was renamed.

Prints the new prefixes for AMENT_PREFIX_PATH; writes overlay-report.json.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/tmp/openadkit")
LAYERS = [Path("/openadkit/config") / name for name in ("shared", "base", "deployment")]
# Our Compose files pass paths inside it as launch arguments.
ALWAYS = "autoware_launch"


def find_prefix(package: str) -> Path | None:
    for entry in os.environ.get("AMENT_PREFIX_PATH", "").split(":"):
        if entry and (Path(entry) / "share" / package).is_dir():
            return Path(entry)
    return None


def materialize(package: str, prefix: Path) -> Path:
    """Copy the package's share directory; link everything else (lib, ...)."""
    target = ROOT / package
    shutil.copytree(prefix / "share" / package, target / "share" / package, symlinks=True)
    marker = target / "share/ament_index/resource_index/packages" / package
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    for entry in prefix.iterdir():
        if entry.name != "share":
            (target / entry.name).symlink_to(entry)
    return target


def merge(base: dict[str, Any], override: dict[str, Any], path: str, unknown: list[str]) -> None:
    for key, value in override.items():
        where = f"{path}.{key}" if path else str(key)
        if key not in base:
            unknown.append(where)
            base[key] = value
        elif isinstance(base[key], dict) and isinstance(value, dict):
            merge(base[key], value, where, unknown)
        else:
            base[key] = value


def apply(layer_package: Path, share: Path, report: dict[str, list[str]]) -> None:
    for source in sorted(path for path in layer_package.rglob("*") if path.is_file()):
        relative = source.relative_to(layer_package)
        destination = share / relative
        label = f"{layer_package.name}/{relative}"
        if not destination.exists():
            report["unknownFiles"].append(label)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            continue
        if source.suffix in (".yaml", ".yml"):
            base = yaml.safe_load(destination.read_text(encoding="utf-8"))
            override = yaml.safe_load(source.read_text(encoding="utf-8"))
            if isinstance(base, dict) and isinstance(override, dict):
                unknown: list[str] = []
                merge(base, override, "", unknown)
                report["unknownKeys"].extend(f"{label}: {key}" for key in unknown)
                destination.unlink()
                destination.write_text(
                    yaml.safe_dump(base, sort_keys=False, default_flow_style=None),
                    encoding="utf-8",
                )
                continue
        destination.unlink()
        shutil.copyfile(source, destination)


def main() -> int:
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    report: dict[str, list[str]] = {"unknownPackages": [], "unknownFiles": [], "unknownKeys": []}

    overridden: dict[str, list[Path]] = {}
    for layer in LAYERS:
        workload = layer / "autoware"
        if workload.is_dir():
            for package in sorted(path for path in workload.iterdir() if path.is_dir()):
                overridden.setdefault(package.name, []).append(package)

    prefixes = []
    for package in [ALWAYS, *sorted(set(overridden) - {ALWAYS})]:
        prefix = find_prefix(package)
        if prefix is None:
            if package in overridden:
                report["unknownPackages"].append(package)
            continue
        target = materialize(package, prefix)
        for layer_package in overridden.get(package, []):
            apply(layer_package, target / "share" / package, report)
        prefixes.append(str(target))

    model = os.environ.get("VEHICLE_MODEL")
    if model:
        description = f"{model}_description"
        prefix = find_prefix(description)
        if prefix is not None:
            (ROOT / "vehicle_description").symlink_to(prefix / "share" / description)

    (ROOT / "overlay-report.json").write_text(json.dumps(report, indent=2) + "\n")
    for kind, items in report.items():
        for item in items:
            print(f"[openadkit] override without a base ({kind}): {item}", file=sys.stderr)
    print(":".join(prefixes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
