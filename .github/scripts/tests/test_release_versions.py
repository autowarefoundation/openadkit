"""The four release-version checks must accept exactly the same tags.

The bash bootstrap cannot import Python, so the pattern exists in four places:
the launcher's regex, the launcher's version comparison, release_plan.py and
validate_release.sh. Each is run against the same vectors here.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

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


def launcher_compare_accepts(version: str) -> bool:
    function = subprocess.run(
        ["sed", "-n", "/^compare_release_versions()/,/^}/p", str(ROOT / "openadkit")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    result = subprocess.run(
        ["bash", "-c", function + '\ncompare_release_versions "$1" "$1"', "_", version],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "same"


CHECKS = {
    "launcher": lambda v: bash_accepts(
        bash_pattern(ROOT / "openadkit", "OPENADKIT_VERSION_RE"), v
    ),
    "launcher-compare": launcher_compare_accepts,
    "release_plan": lambda v: release_plan.SEMVER_RE.fullmatch(v) is not None,
    "validate_release": lambda v: bash_accepts(
        bash_pattern(ROOT / ".github/scripts/validate_release.sh", "openadkit_semver_re"), v
    ),
}


@pytest.mark.parametrize("check", sorted(CHECKS))
def test_release_version_checks_agree(check):
    accepts = CHECKS[check]
    assert [v for v in VALID if not accepts(v)] == []
    assert [v for v in INVALID if accepts(v)] == []
