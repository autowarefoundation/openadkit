"""The Autoware pin rules of resolve_build_inputs.sh."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SHA = "b" * 40

FAKE_GIT = r"""#!/usr/bin/env bash
# Answers resolve_build_inputs.sh's git calls for one Autoware ref.
args=("$@")
[ "${args[0]}" = -C ] && args=("${args[@]:2}")
case "${args[0]}" in
  init|remote|checkout) exit 0 ;;
  ls-remote)
    case "${args[*]}" in
      *refs/heads/"${FAKE_BRANCH:-}") [ -n "${FAKE_BRANCH:-}" ] && echo "${FAKE_SHA} x" && exit 0 ;;
      *refs/tags/"${FAKE_TAG:-}") [ -n "${FAKE_TAG:-}" ] && echo "${FAKE_SHA} x" && exit 0 ;;
    esac
    exit 2 ;;
  fetch) mkdir -p autoware-metadata/repositories && touch autoware-metadata/repositories/autoware-nightly.repos ;;
  rev-parse) echo "${FAKE_SHA}" ;;
  describe) echo 2.0.0 ;;
esac
"""


def resolve(tmp_path, pin, *, ref_name="main", **fake):
    work = tmp_path / "work"
    (work / ".github").mkdir(parents=True)
    (work / ".github/autoware.ref").write_text(pin + "\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(FAKE_GIT)
    (bin_dir / "git").chmod(0o755)
    output = tmp_path / "github-output"
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output), "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF_NAME": ref_name, "FAKE_SHA": SHA, **fake,
    }
    env.pop("GITHUB_BASE_REF", None)
    result = subprocess.run(
        ["bash", str(ROOT / ".github/scripts/resolve_build_inputs.sh")],
        cwd=work, env=env, capture_output=True, text=True,
    )
    values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    return result, values


def test_a_release_pin_uses_the_release_manifest_and_images(tmp_path):
    result, values = resolve(tmp_path, "2.0.0", FAKE_TAG="2.0.0")
    assert result.returncode == 0, result.stderr
    assert values["autoware_ref_type"] == "tag" and values["autoware_ref"] == SHA
    assert values["upstream_tag"] == "2.0.0" and values["autoware_overlay"] == ""


def test_a_branch_pin_resolves_the_development_manifest(tmp_path):
    result, values = resolve(tmp_path, "main", FAKE_BRANCH="main")
    assert result.returncode == 0, result.stderr
    assert values["autoware_ref_type"] == "branch" and values["upstream_tag"] == ""
    assert values["autoware_overlay"].endswith("autoware-nightly.repos")


def test_a_commit_pin_is_refused(tmp_path):
    result, _ = resolve(tmp_path, SHA)
    assert result.returncode != 0
    assert "as a branch or tag" in result.stderr


@pytest.mark.parametrize(("ref_name", "scope"), [("main", "main"), ("release/2.0", "release-2.0")])
def test_each_branch_keeps_its_own_caches(tmp_path, ref_name, scope):
    result, values = resolve(tmp_path, "2.0.0", ref_name=ref_name, FAKE_TAG="2.0.0")
    assert result.returncode == 0, result.stderr
    assert values["cache_scope"] == scope
