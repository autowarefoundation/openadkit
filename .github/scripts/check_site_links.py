#!/usr/bin/env python3
"""Check the documentation-site links in the repository's Markdown against a built site.

MkDocs checks the links between its pages in strict mode. It cannot check the
absolute links that READMEs and .github/*.md make to the published site, so a
page that moves leaves them broken. Run this after a docs build; lint.yaml does.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def site_url(root: Path) -> str:
    match = re.search(r"^site_url:\s*(\S+)", (root / "mkdocs.yaml").read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit("mkdocs.yaml has no site_url")
    return match.group(1).rstrip("/") + "/"


def broken_links(files: list[Path], site: Path, url: str) -> list[str]:
    """Links under url whose page, or whose #anchor on it, the built site does not have."""
    pattern = re.compile(re.escape(url) + r"[\w/#.-]*")
    broken = []
    for file in files:
        for link in sorted(set(pattern.findall(file.read_text(encoding="utf-8")))):
            # A sentence's full stop is not part of the link.
            path, _, anchor = link.rstrip(".")[len(url):].partition("#")
            page = site / path
            if page.is_dir() or not path:
                page = page / "index.html"
            if not page.is_file():
                broken.append(f"{file}: {link} has no page")
            elif anchor and f'id="{anchor}"' not in page.read_text(encoding="utf-8"):
                broken.append(f"{file}: {link} has no #{anchor}")
    return broken


def main() -> int:
    site = ROOT / "site"
    if not (site / "index.html").is_file():
        raise SystemExit("no built site; run: mkdocs build")
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.md"], capture_output=True, text=True, check=True
    ).stdout.split()
    broken = broken_links([ROOT / name for name in tracked], site, site_url(ROOT))
    for line in broken:
        print(line, file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
