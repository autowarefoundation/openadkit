"""One versioned cell payload for runners, summaries and derived views."""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1
METRICS = ("ready_s", "arrival_s", "peak_mib")


def normalize_cell(cell: dict[str, Any]) -> dict[str, Any]:
    version = cell.get("schemaVersion")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError(f"unsupported evidence cell schemaVersion: {version!r}")
    if not isinstance(cell.get("metrics"), dict):
        raise ValueError(f"{cell.get('name')}: missing cell metrics")
    return {**cell, "node": cell.get("node") or None, "kit": cell.get("kit") or None}


def report_cells(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted((normalize_cell(cell) for cell in summary["cells"]), key=lambda cell: cell["name"])
