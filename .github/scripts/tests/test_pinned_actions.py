"""Every action a workflow uses is pinned by commit, with its version in a comment."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)(.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def test_actions_are_pinned_by_commit_with_their_version():
    # A tag can move to another commit; a commit cannot. The comment is what
    # Dependabot reads to raise the pin, and what a reader sees.
    files = [*(ROOT / ".github/workflows").glob("*.yaml"), *(ROOT / ".github/actions").glob("*/action.yaml")]
    assert files
    loose = []
    for path in sorted(files):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES.match(line)
            # A local action or workflow is this repository at this commit.
            if not match or match.group(1).startswith("./"):
                continue
            if not PINNED.fullmatch(match.group(1)) or not re.fullmatch(r"\s+# v?\d[\w.-]*", match.group(2)):
                loose.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not loose, "pin by commit, as `owner/action@<sha> # vX.Y.Z`:\n" + "\n".join(loose)
