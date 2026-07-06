#!/usr/bin/env python3
"""Generate docs/releases/index.md from GitHub Releases."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_REPO = os.environ.get("GITHUB_REPOSITORY", "autowarefoundation/openadkit")
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "releases" / "index.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate docs/releases/index.md from GitHub Releases.",
        epilog="If GITHUB_TOKEN is set in the environment, it is used for API requests."
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help="GitHub repository in 'owner/name' format (default: %(default)s)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output file path (default: %(default)s)"
    )
    return parser.parse_args()


def fetch_releases(repo: str, token: Optional[str]) -> list[dict]:
    releases: list[dict] = []
    page = 1

    while True:
        query = urllib.parse.urlencode({'per_page': 100, 'page': page})
        url = f"https://api.github.com/repos/{repo}/releases?{query}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "openadkit-docs-release-notes-generator",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                try:
                    batch = json.load(response)
                except (json.JSONDecodeError, ValueError) as exc:
                    print(f"GitHub API returned invalid JSON: {exc}", file=sys.stderr)
                    raise SystemExit(1) from exc
        except urllib.error.HTTPError as exc:
            print(f"GitHub API request failed: {exc.code} {exc.reason}", file=sys.stderr)
            raise SystemExit(1) from exc
        except urllib.error.URLError as exc:
            print(f"GitHub API request failed: {exc.reason}", file=sys.stderr)
            raise SystemExit(1) from exc

        if not batch:
            break

        releases.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    return releases


def format_date(iso_timestamp: str) -> str:
    parsed = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d")


def release_badge(release: dict) -> str:
    return "Pre-release" if release.get("prerelease") else "Stable"


def render_empty_state(repo: str) -> str:
    image_name = repo.split("/")[-1]
    return "\n".join(
        [
            "# Releases",
            "",
            "Published Open AD Kit releases are listed here, synchronized from",
            f"[GitHub Releases](https://github.com/{repo}/releases).",
            "",
            "!!! info \"No releases yet\"",
            "    There are no published releases yet. While waiting for the first stable release, you can:",
            "",
            f"    - Pull images from [GitHub Container Registry](https://github.com/{repo}/pkgs/container/{image_name})",
            "    - Use CI build tags as described in [Container Images & Versioning](../getting-started/container-images.md)",
            "    - Read how maintainers promote builds in the [Release Process](../development/build-from-source.md#release-process)",
            f"    - [Watch releases on GitHub](https://github.com/{repo}/releases) for notifications",
            "",
        ]
    )


def render_release_section(release: dict, repo: str) -> str:
    tag = release.get("tag_name", "unknown")
    title = release.get("name") or f"Open AD Kit {tag}"
    published_at = release.get("published_at") or release.get("created_at") or ""
    published_date = format_date(published_at) if published_at else "unknown date"
    html_url = release.get("html_url", f"https://github.com/{repo}/releases/tag/{tag}")
    body = (release.get("body") or "").strip()

    lines = [
        f"## {title}",
        "",
        f"**Published:** {published_date} · **Type:** {release_badge(release)} ·",
        f"[View on GitHub]({html_url})",
        "",
    ]

    if body:
        lines.append(body)
        lines.append("")

    return "\n".join(lines)


def render_release_notes(releases: list[dict], repo: str) -> str:
    published = [release for release in releases if not release.get("draft")]

    if not published:
        return render_empty_state(repo)

    lines = [
        "# Releases",
        "",
        "Published Open AD Kit releases are listed here, synchronized from",
        f"[GitHub Releases](https://github.com/{repo}/releases).",
        "",
    ]

    for release in published:
        lines.append(render_release_section(release, repo))

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    args = parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    releases = fetch_releases(args.repo, token)
    content = render_release_notes(releases, args.repo)

    header = "<!-- AUTOGENERATED by generate_release_notes.py; DO NOT EDIT MANUALLY -->\n\n"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(header + content, encoding="utf-8")
    print(f"Wrote {args.output} ({len(releases)} release(s) fetched)")


if __name__ == "__main__":
    main()
