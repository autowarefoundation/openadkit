"""Write a release's notes from its validated plan.

The notes are for people: the highlights, how to install, what changed and
what the evidence showed. Digests, provenance and the BOM stay in the release's
release-metadata.json, where tools read them.

What changed comes from GitHub's generated notes since the previous release,
grouped by the Conventional Commits type of each pull request title.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence.cells import report_cells  # noqa: E402
from evidence.report import render as render_evidence  # noqa: E402

# Ordering only: the release gates already validated the version format.
VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
TITLE = re.compile(r"^\* (?P<type>[a-z]+)(?:\([^)]*\))?(?P<breaking>!)?: ")
GROUPS = (("breaking", "⚠️ Breaking changes"), ("feat", "Features"), ("fix", "Fixes"), ("other", "Other changes"))
# Past this many pull requests the list stops being readable; the compare link stays.
MAX_LISTED = 40


def precedence(tag: str) -> tuple[Any, ...] | None:
    """A SemVer precedence key for a release tag, or None for other tags."""
    match = VERSION.match(tag)
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    if pre is None:
        return (int(major), int(minor), int(patch), 1, ())
    parts = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in pre.split("."))
    return (int(major), int(minor), int(patch), 0, parts)


def previous_release(version: str, published: list[str]) -> str | None:
    """The release the notes compare with: the closest earlier one, and for a
    stable release the closest earlier stable one, so it lists everything
    since the last stable release rather than since its last candidate."""
    current = precedence(version)
    assert current is not None, version
    stable = current[3] == 1
    earlier = [
        (key, tag) for tag in published
        if (key := precedence(tag)) is not None and key < current and (key[3] == 1 or not stable)
    ]
    return max(earlier)[1] if earlier else None


def group_changes(body: str) -> str:
    """GitHub's generated notes, grouped by pull request type."""
    changes: dict[str, list[str]] = {name: [] for name, _ in GROUPS}
    contributors: list[str] = []
    full_changelog = ""
    section = ""
    for line in body.splitlines():
        if line.startswith("## "):
            section = line
        elif line.startswith("**Full Changelog**"):
            full_changelog = line
        elif line.startswith("* ") and "New Contributors" in section:
            # Bots such as dependabot are not contributors to welcome.
            if "[bot]" not in line:
                contributors.append(line)
        elif line.startswith("* "):
            match = TITLE.match(line)
            if match is None:
                changes["other"].append(line)
            elif match["breaking"]:
                changes["breaking"].append(line)
            else:
                changes[match["type"] if match["type"] in changes else "other"].append(line)
    listed = sum(len(lines) for lines in changes.values())
    out = ["## What's Changed", ""]
    if listed > MAX_LISTED:
        out += [f"{listed} pull requests; see the full changelog.", ""]
    else:
        for name, title in GROUPS:
            if changes[name]:
                out += [f"### {title}", "", *changes[name], ""]
        if contributors:
            out += ["### New contributors", "", *contributors, ""]
    if full_changelog:
        out += [full_changelog, ""]
    return "\n".join(out) if listed or full_changelog else ""


def github_changes(repository: str, version: str, target: str) -> str:
    """What changed since the previous published release, or "" for the first."""
    tags = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{repository}/releases", "--jq", ".[] | select(.draft | not) | .tag_name"],
        text=True, capture_output=True, check=True,
    ).stdout.split()
    previous = previous_release(version, tags)
    if previous is None:
        return ""
    body = subprocess.run(
        ["gh", "api", f"repos/{repository}/releases/generate-notes", "--jq", ".body",
         "-f", f"tag_name={version}", "-f", f"target_commitish={target}", "-f", f"previous_tag_name={previous}"],
        text=True, capture_output=True, check=True,
    ).stdout
    return group_changes(body)


def details(summary: str, body: str) -> list[str]:
    return ["<details>", f"<summary>{summary}</summary>", "", body.rstrip("\n"), "", "</details>", ""]


def render(plan: dict[str, Any], repository: str, highlights: str, changes: str) -> str:
    release, evidence = plan["release"], plan["evidence"]
    version = release["version"]
    autoware = plan["releaseContext"]["autoware"]
    distros = ", ".join(distro.capitalize() for distro in sorted(plan["releaseContext"]["images"]))
    cells = report_cells(evidence)
    architectures = ", ".join(sorted({cell["platform"].rsplit("/", 1)[-1] for cell in cells if cell.get("platform")}))
    # The build accepts only an Autoware release, so its version is a tag with a release page.
    autoware_link = f"[{autoware['version']}](https://github.com/autowarefoundation/autoware/releases/tag/{autoware['version']})"
    # What the release runs, before anything else: its title is the version alone.
    out: list[str] = [
        "| Autoware | ROS 2 | Architectures |",
        "| --- | --- | --- |",
        f"| {autoware_link} | {distros} | {architectures} |",
        "",
    ]
    if highlights.strip():
        out += [highlights.strip(), ""]

    out += [
        "## Install", "",
        "```bash",
        f"curl -fsSL https://github.com/{repository}/releases/download/{version}/openadkit \\",
        f"  | bash -s -- install --version {version}",
        "```", "",
    ]
    aliases = [alias for image in plan["images"] for alias in image.get("aliases", [])]
    if release["publishLatestAliases"] and aliases:
        out += [f"Latest aliases such as `{aliases[0].rsplit(':', 1)[-1]}` now point to this release.", ""]
    elif release["stable"]:
        out += ["Latest aliases stay on a newer stable release.", ""]

    if changes:
        out += [changes.rstrip("\n"), ""]

    passed = sum(cell.get("result") == "PASSED" for cell in cells)
    out += [
        "## Verification", "",
        f"**{passed}/{len(cells)}** evidence cells passed · "
        "[How to verify this release](https://autowarefoundation.github.io/openadkit/releases/verification/)", "",
    ]
    exempt = [f"- `{item['deployment']}`: {item['reason']}" for item in evidence.get("exempt") or []]
    out += details("Evidence cells", "\n".join(
        [render_evidence(evidence, summary=False).rstrip("\n"),
         *(["", "Not verified in CI:", "", *exempt] if exempt else []),
         *(["", f"Run: {evidence['url']}"] if evidence.get("url") else [])]))
    out += details("Image digests", "\n".join(f"- `{image['releaseRef']}@{image['digest']}`" for image in plan["images"]))
    backports = autoware.get("backports") or []
    if backports:
        out += details(
            f"Fixes backported to Autoware {autoware['version']}",
            "\n".join(f"- {fix['subject']} (`{fix['repository']}`): {fix['upstream']}" for fix in backports),
        )
    while out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=Path("release-plan.json"))
    parser.add_argument("--highlights-dir", type=Path, default=Path(".github/release-highlights"))
    parser.add_argument("--output", type=Path, default=Path("release-notes.md"))
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    repository = os.environ["GITHUB_REPOSITORY"]
    version = plan["release"]["version"]
    # A release and its candidates share the highlights of the version they lead to.
    highlights_file = args.highlights_dir / f"{version.split('-', 1)[0]}.md"
    highlights = highlights_file.read_text(encoding="utf-8") if highlights_file.is_file() else ""
    changes = github_changes(repository, version, plan["release"]["releaseSha"])
    args.output.write_text(render(plan, repository, highlights, changes), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
