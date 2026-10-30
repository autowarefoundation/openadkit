"""The release-version checks must accept exactly the same tags.

The bash bootstrap cannot import Python, so the pattern exists in four places:
the launcher's regex, cli/manifest.py (kit extends and upgrade comparison),
release_plan.py and validate_release.sh. Each is run against the same vectors
here.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))
sys.path.insert(0, str(ROOT / "cli"))

import installation  # noqa: E402
import manifest  # noqa: E402
import release_plan  # noqa: E402

VALID = [
    "v0.0.0",
    "v1.2.3",
    "v2.0.0-rc.1",
    "v2.0.0-rc.1.2",
    "v1.0.0-alpha-1",
    "v1.0.0-0.3.7",
    "v1.0.0-x.7.z.92",
    "v1.0.0--",
]
INVALID = [
    "1.2.3",
    "v1.2",
    "v01.2.3",
    "v1.02.3",
    "v1.2.3-",
    "v1.2.3-rc..1",
    "v1.2.3-01",
    "v1.2.3-rc.01",
    "v1.2.3+build.1",
    "v1.2.3-rc_1",
    "v1.2.3 ",
]


def bash_pattern(path: Path, name: str) -> str:
    line = next(
        line
        for line in path.read_text().splitlines()
        if re.match(rf"^(readonly )?{name}=", line)
    )
    return line.split("=", 1)[1].strip("'")


def bash_accepts(pattern: str, version: str) -> bool:
    script = 're=$1; [[ $2 =~ $re ]]'
    return subprocess.run(["bash", "-c", script, "_", pattern, version]).returncode == 0


def upgrade_compare_accepts(version: str) -> bool:
    try:
        return installation.compare_versions(version, version) == "same"
    except ValueError:
        return False


CHECKS = {
    "launcher": lambda v: bash_accepts(
        bash_pattern(ROOT / "openadkit", "OPENADKIT_VERSION_RE"), v
    ),
    "upgrade-compare": upgrade_compare_accepts,
    "release_plan": lambda v: release_plan.SEMVER_RE.fullmatch(v) is not None,
    "kit-extends": lambda v: manifest.VERSION_RE.fullmatch(v) is not None,
    "validate_release": lambda v: bash_accepts(
        bash_pattern(ROOT / ".github/scripts/validate_release.sh", "openadkit_semver_re"), v
    ),
}


@pytest.mark.parametrize("check", sorted(CHECKS))
def test_release_version_checks_agree(check):
    accepts = CHECKS[check]
    assert [v for v in VALID if not accepts(v)] == []
    assert [v for v in INVALID if accepts(v)] == []
