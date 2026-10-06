"""Fetch an informational upgrade baseline, never an input to the release gate.

Prefer the previous stable release below the target version. If none exists,
use the most recent successful evidence run on main for a different build.
Missing historical evidence is reported, not replaced with fabricated metrics.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def previous_release(releases: list[dict[str, Any]], version: str) -> dict[str, Any] | None:
    target = tuple(int(part) for part in version.split("-", 1)[0].removeprefix("v").split("."))
    candidates = []
    for release in releases:
        tag = release.get("tag_name", "")
        if release.get("draft") or release.get("prerelease") or not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
            continue
        parts = tuple(int(part) for part in tag[1:].split("."))
        if parts < target:
            candidates.append((parts, release))
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


def usable_summary(summary: Any, build_tag: str) -> bool:
    if not isinstance(summary, dict) or summary.get("result") != "PASSED" or summary.get("build_tag") in (None, build_tag):
        return False
    cells = summary.get("cells")
    return isinstance(cells, list) and bool(cells) and all(isinstance(cell, dict) and cell.get("result") == "PASSED" for cell in cells)


def fetch(plan: dict[str, Any], repository: str, directory: Path) -> dict[str, Any] | None:
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100"))
    previous = previous_release([release for page in pages for release in page], plan["release"]["version"])
    build_tag = plan["release"]["buildTag"]
    if previous is not None:
        # Do not silently replace an unavailable previous release with a CI run.
        gh("release", "download", previous["tag_name"], "--repo", repository,
           "--pattern", "release-metadata.json", "--dir", str(directory))
        metadata = json.loads((directory / "release-metadata.json").read_text())
        summary = metadata.get("evidence")
        if usable_summary(summary, build_tag):
            return summary | {"baseline": {"kind": "release", "version": previous["tag_name"]}}
        return None

    runs = json.loads(gh("run", "list", "--repo", repository, "--workflow", "evidence.yaml",
                         "--branch", "main", "--status", "success", "--limit", "20", "--json", "databaseId"))
    for run in runs:
        run_dir = directory / str(run["databaseId"])
        try:
            gh("run", "download", str(run["databaseId"]), "--repo", repository,
               "--pattern", "evidence-attestation-*", "--dir", str(run_dir))
            paths = list(run_dir.rglob("evidence-summary.json"))
            if len(paths) != 1:
                continue
            summary = json.loads(paths[0].read_text())
            if usable_summary(summary, build_tag):
                return summary | {"baseline": {"kind": "main", "runId": run["databaseId"]}}
        except (subprocess.CalledProcessError, OSError, ValueError):
            continue  # Artifact retention can make historical runs unavailable.
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory() as temporary:
            summary = fetch(json.loads(args.plan.read_text()), args.repository, Path(temporary))
        if summary is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            return 0
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"::warning::Upgrade baseline unavailable: {error}")
    print("No previous release/main evidence available for comparison.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
