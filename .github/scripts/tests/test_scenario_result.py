"""The verdict the scenario service exits with (deployments/shared/checks/scenario_result.py)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deployments/shared/checks/scenario_result.py"


def junit(path, *outcomes, mtime=None):
    cases = "".join(f'<testcase name="case{index}">{outcome}</testcase>' for index, outcome in enumerate(outcomes))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def verdict(directory, since=1000):
    return subprocess.run([sys.executable, str(SCRIPT), str(directory), str(since)],
                          capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize(("outcomes", "passed"), [
    (("",), True),
    (("", "<failure/>"), False),
    (("<error/>",), False),
    (("<skipped/>",), False),
])
def test_every_case_of_the_run_must_pass(tmp_path, outcomes, passed):
    junit(tmp_path / "scenario_test_runner/sample/result.junit.xml", *outcomes)
    assert (verdict(tmp_path).returncode == 0) is passed


def test_a_run_without_results_fails_and_an_earlier_run_does_not_count(tmp_path):
    assert verdict(tmp_path).returncode != 0
    # A failure left by an earlier run is not this run's; a pass from then is no result either.
    junit(tmp_path / "old/result.junit.xml", "<failure/>", mtime=500)
    result = verdict(tmp_path)
    assert result.returncode != 0 and "no result" in result.stderr
    junit(tmp_path / "new/result.junit.xml", "")
    assert verdict(tmp_path).returncode == 0
