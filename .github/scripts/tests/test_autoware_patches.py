import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github/scripts/autoware_patches.py"


def git(repository, *args):
    return subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True, text=True).stdout


def upstream_fix(tmp_path, *, upstream=True):
    """A repository at the tag, and a fix on top of it as git format-patch writes it."""
    repository = tmp_path / "upstream"
    repository.mkdir()
    git(repository, "init", "-q")
    git(repository, "config", "user.email", "dev@example.com")
    git(repository, "config", "user.name", "Dev")
    (repository / "planner.py").write_text("LIMIT = 5.0\n")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "base")
    git(repository, "tag", "1.9.0")
    (repository / "planner.py").write_text("LIMIT = 3.9\n")
    message = "fix(planner): honor the vehicle's braking limit"
    if upstream:
        message += "\n\nUpstream: https://github.com/autowarefoundation/autoware_universe/pull/123"
    git(repository, "commit", "-qam", message)
    return repository, git(repository, "format-patch", "-1", "--stdout", "HEAD")


def sources(tmp_path, repository):
    """autoware/src as vcs import leaves it: the tag, under its lock key."""
    source = tmp_path / "src"
    target = source / "universe/autoware_universe"
    target.parent.mkdir(parents=True)
    git(tmp_path, "clone", "-q", "--branch", "1.9.0", str(repository), str(target))
    return source, target


def line(tmp_path, patch, name="0001-honor-braking-limit.patch"):
    root = tmp_path / "openadkit"
    path = root / ".github/autoware-patches/universe/autoware_universe" / name
    path.parent.mkdir(parents=True)
    path.write_text(patch)
    return root


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def test_a_backport_applies_on_the_tag_and_is_listed_with_its_upstream(tmp_path):
    repository, patch = upstream_fix(tmp_path)
    source, target = sources(tmp_path, repository)
    root = line(tmp_path, patch)
    assert json.loads(run("list", root).stdout) == [{
        "repository": "universe/autoware_universe",
        "patch": "universe/autoware_universe/0001-honor-braking-limit.patch",
        "subject": "fix(planner): honor the vehicle's braking limit",
        "upstream": "https://github.com/autowarefoundation/autoware_universe/pull/123",
    }]
    result = run("apply", source, root)
    assert result.returncode == 0, result.stderr
    assert (target / "planner.py").read_text() == "LIMIT = 3.9\n"
    # A line without patches applies nothing.
    assert run("apply", source, tmp_path / "empty").returncode == 0


@pytest.mark.parametrize("problem", ["upstream", "conflict", "repository"])
def test_a_backport_without_upstream_or_that_does_not_apply_fails_the_build(tmp_path, problem):
    repository, patch = upstream_fix(tmp_path, upstream=problem != "upstream")
    source, target = sources(tmp_path, repository)
    if problem == "conflict":
        (target / "planner.py").write_text("LIMIT = 4.5\n")
    if problem == "repository":
        target.rename(target.with_name("moved"))
    result = run("apply", source, line(tmp_path, patch))
    assert result.returncode != 0
    assert {"upstream": "Upstream: <https URL>", "conflict": "does not apply",
            "repository": "is not in the Autoware sources"}[problem] in result.stderr
