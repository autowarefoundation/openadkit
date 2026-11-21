#!/usr/bin/env python3
"""Backported Autoware fixes: list, check and apply a release line's patches.

A release line builds on one Autoware release tag. A fix that is upstream but
not yet in a release can be carried on the line as a patch, created in the
upstream repository with `git format-patch -1 <commit>`:

    .github/autoware-patches/<repository>/<NNNN>-<subject>.patch

<repository> is the path vcs imports it to under autoware/src (a key of the
Autoware lock, such as universe/autoware_universe). The commit message must
name the fix upstream in a line `Upstream: <https URL>` (the merged commit or
the open pull request), so every patch is a fix upstream already has.

    autoware_patches.py list [ROOT]          JSON list of the patches
    autoware_patches.py apply SRC [ROOT]     apply them to the imported sources
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

PATCH_DIR = Path(".github/autoware-patches")
UPSTREAM_RE = re.compile(r"^Upstream:\s*(https://\S+)\s*$", re.MULTILINE)
SUBJECT_RE = re.compile(r"^Subject:\s*(?:\[PATCH[^\]]*\]\s*)?(.+)$", re.MULTILINE)


def fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def list_patches(root: Path) -> list[dict[str, Any]]:
    """The patches under root's patch directory, in the order they apply."""
    directory = root / PATCH_DIR
    patches = []
    for path in sorted(directory.rglob("*.patch")) if directory.is_dir() else []:
        relative = path.relative_to(directory)
        if len(relative.parts) < 2:
            fail(f"{path}: put the patch under the repository it applies to")
        text = path.read_text(encoding="utf-8")
        upstream = UPSTREAM_RE.search(text)
        if upstream is None:
            fail(f"{path}: name the fix upstream in a line 'Upstream: <https URL>'")
        subject = SUBJECT_RE.search(text)
        patches.append({
            "repository": relative.parent.as_posix(),
            "patch": relative.as_posix(),
            "subject": subject.group(1).strip() if subject else relative.stem,
            "upstream": upstream.group(1),
        })
    return patches


def apply_patches(source: Path, root: Path) -> None:
    for item in list_patches(root):
        repository = source / item["repository"]
        patch = (root / PATCH_DIR / item["patch"]).resolve()
        if not (repository / ".git").exists():
            fail(f"{item['patch']}: {item['repository']} is not in the Autoware sources")
        for check in (["--check"], []):
            result = subprocess.run(
                ["git", "-C", str(repository), "apply", *check, str(patch)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                fail(f"{item['patch']} does not apply to {item['repository']}:\n{result.stderr.strip()}")
        print(f"applied {item['patch']} ({item['upstream']})")


def main(arguments: list[str]) -> int:
    if arguments[:1] == ["list"] and len(arguments) <= 2:
        print(json.dumps(list_patches(Path(arguments[1] if len(arguments) > 1 else "."))))
        return 0
    if arguments[:1] == ["apply"] and 2 <= len(arguments) <= 3:
        apply_patches(Path(arguments[1]), Path(arguments[2] if len(arguments) > 2 else "."))
        return 0
    print(__doc__.split("\n\n")[-1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
