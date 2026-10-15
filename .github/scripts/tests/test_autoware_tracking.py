import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
RESOLVER = ROOT / ".github/scripts/resolve_build_inputs.sh"
spec = importlib.util.spec_from_file_location(
    "export_autoware_lock", ROOT / ".github/scripts/export_autoware_lock.py"
)
lock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lock)


def resolve_inputs(
    tmp_path, *, pin="main", branch="main", base_branch="", override="", kind="branch",
    overlay=True,
):
    (tmp_path / "autoware.ref").write_text(pin + "\n")
    metadata = tmp_path / "autoware-metadata/repositories"
    metadata.mkdir(parents=True)
    if overlay:
        (metadata / "autoware-nightly.repos").write_text("repositories: {}\n")
    git = tmp_path / "git"
    git.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ['GIT_LOG'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if 'ls-remote' in args:
    if os.environ['REF_KIND'] == 'sha':
        sys.exit(2)
    prefix = 'refs/heads/' if os.environ['REF_KIND'] == 'branch' else 'refs/tags/'
    sys.exit(0 if args[-1] == prefix + os.environ['RESOLVED_INPUT'] else 2)
if 'rev-parse' in args:
    print('a' * 40)
if 'describe' in args:
    print('v1.9.0')
"""
    )
    git.chmod(0o755)
    output = tmp_path / "output"
    env = os.environ | {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "AUTOWARE_PIN_FILE": str(tmp_path / "autoware.ref"),
        "AUTOWARE_REF_INPUT": override,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_EVENT_NAME": "pull_request" if base_branch else "push",
        "GITHUB_REF_NAME": branch,
        "GITHUB_BASE_REF": base_branch,
        "REF_KIND": kind,
        "RESOLVED_INPUT": override or pin,
        "GIT_LOG": str(tmp_path / "git.log"),
    }
    result = subprocess.run(
        ["bash", str(RESOLVER)], cwd=tmp_path, env=env, text=True, capture_output=True
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    return result, outputs


def test_main_tracks_development_sources_without_repository_variable(tmp_path):
    result, outputs = resolve_inputs(tmp_path)
    assert result.returncode == 0, result.stderr
    assert outputs["autoware_input_ref"] == "main"
    assert outputs["autoware_development"] == "true"
    assert outputs["autoware_repos_overlay"].endswith("autoware-nightly.repos")
    assert outputs["autoware_base_version"] == "1.9.0"
    assert outputs["build_tag"] == "123-2"


def test_release_pr_reads_merged_pin_and_scopes_cache_to_target_branch(tmp_path):
    result, outputs = resolve_inputs(
        tmp_path, pin="1.9.0", branch="42/merge", base_branch="release/2.0", kind="tag"
    )
    assert result.returncode == 0, result.stderr
    assert outputs["autoware_input_ref"] == "1.9.0"
    assert outputs["autoware_development"] == "false"
    assert outputs["autoware_repos_overlay"] == ""
    assert outputs["cache_scope"] == hashlib.sha256(b"release/2.0").hexdigest()[:12]


def test_cache_scope_is_valid_for_long_or_special_git_branch_names(tmp_path):
    result, outputs = resolve_inputs(tmp_path, branch="feature/" + "long#name" * 30)
    assert result.returncode == 0, result.stderr
    assert len(outputs["cache_scope"]) == 12
    assert all(character in "0123456789abcdef" for character in outputs["cache_scope"])


@pytest.mark.parametrize(
    ("pin", "branch"),
    [
        ("main", "release/2.0"), ("1.9.0", "main"), ("latest", "main"),
        ("main\n1.9.0", "main"), ("bad\n1.9.0", "release/2.0"),
    ],
)
def test_invalid_tracking_policy_fails_before_network_access(tmp_path, pin, branch):
    result, _ = resolve_inputs(tmp_path, pin=pin, branch=branch)
    assert result.returncode != 0
    assert not (tmp_path / "git.log").exists()


def test_missing_development_manifest_never_falls_back_to_release_sources(tmp_path):
    result, _ = resolve_inputs(tmp_path, overlay=False)
    assert result.returncode != 0
    assert "Development manifest not found" in result.stderr


def test_diagnostic_sha_preserves_regular_manifest_semantics(tmp_path):
    result, outputs = resolve_inputs(tmp_path, override="b" * 40, kind="sha")
    assert result.returncode == 0, result.stderr
    assert outputs["autoware_ref_type"] == "sha"
    assert outputs["autoware_development"] == "false"
    assert outputs["autoware_repos_overlay"] == ""
    calls = [json.loads(line) for line in (tmp_path / "git.log").read_text().splitlines()]
    fetch = next(call for call in calls if "fetch" in call)
    assert fetch[-1] == "b" * 40


def repository(version, url="https://example.com/repository.git"):
    return {"type": "git", "url": url, "version": version}


def test_development_overlay_is_merged_before_resolving_each_dependency_once(tmp_path, monkeypatch):
    source = tmp_path / "base.repos"
    overlay = tmp_path / "development.repos"
    target = tmp_path / "lock.repos"
    source.write_text(yaml.safe_dump({"repositories": {
        "core": repository("1.9.0"), "external": repository("1.0.0"),
    }}))
    overlay.write_text(yaml.safe_dump({"repositories": {
        "core": repository("main"), "new": repository("main"),
    }}))
    calls = []

    def resolve(url, version):
        calls.append((url, version))
        return ("a" if version == "main" else "b") * 40

    monkeypatch.setattr(lock, "resolve", resolve)
    lock.export_lock(source, target, overlay)
    repos = yaml.safe_load(target.read_text())["repositories"]
    assert repos["core"]["version"] == "a" * 40
    assert repos["new"]["version"] == "a" * 40
    assert repos["external"]["version"] == "b" * 40
    assert len(calls) == 3
    assert all(version != "1.9.0" for _, version in calls)


def test_regular_release_manifest_does_not_apply_development_overrides(tmp_path, monkeypatch):
    source = tmp_path / "base.repos"
    target = tmp_path / "lock.repos"
    source.write_text(yaml.safe_dump({"repositories": {"core": repository("a" * 40)}}))
    monkeypatch.setattr(lock, "ls_remote", lambda *_: pytest.fail("SHA must not be resolved again"))
    assert lock.main(["export_autoware_lock.py", str(source), str(target), ""]) == 0
    assert yaml.safe_load(target.read_text())["repositories"]["core"]["version"] == "a" * 40


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Buildx is not installed")
@pytest.mark.parametrize("development", [False, True])
@pytest.mark.parametrize("distro", ["humble", "jazzy"])
def test_bake_uses_locked_source_core_only_for_development(development, distro):
    args = ["docker", "buildx", "bake", "-f", "components/docker-bake.hcl"]
    if development:
        args += ["-f", "components/development.hcl"]
    args += ["--print", "localization-mapping"]
    result = subprocess.run(
        args, cwd=ROOT, env=os.environ | {"ROS_DISTRO": distro},
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    targets = json.loads(result.stdout)["target"]
    context = targets["universe-common-devel"]["contexts"]["autoware-core-devel"]
    if development:
        assert context == "target:autoware-development-core-devel"
        assert targets["autoware-development-core-devel"]["context"] == "autoware"
    else:
        assert context.startswith("docker-image://")
        assert "autoware-development-core-devel" not in targets
