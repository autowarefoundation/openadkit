import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github/scripts/resolve_registry_contexts.sh"
AUTOWARE_REF = "5b27e88e84683deb4afaf0aa917f80082a608871"
DIGEST = f"sha256:{'a' * 64}"
LOCK_SHA256 = "b" * 64


def registry_metadata(
    openadkit_sha, *, matches=True, plain_labels=False, lock_sha256=LOCK_SHA256
):
    if matches == "same-commit-branch":
        input_ref = "main"
        ref_type = "branch"
        image_autoware_ref = AUTOWARE_REF
    elif matches:
        input_ref = "1.8.0"
        ref_type = "tag"
        image_autoware_ref = AUTOWARE_REF
    else:
        input_ref = "main"
        ref_type = "branch"
        image_autoware_ref = "c" * 40

    def label(name):
        # `imagetools inspect --format '{{json .}}'` renders label keys with
        # embedded quotes, which is what the resolver's quoted-key jq fallback
        # reads. plain_labels=False emits that live shape by default.
        return name if plain_labels else f'"{name}"'

    return json.dumps(
        {
            "manifest": {"digest": DIGEST},
            "image": {
                "config": {
                    "Labels": {
                        label("org.opencontainers.image.autoware-input-ref"): input_ref,
                        label("org.opencontainers.image.autoware-ref-type"): ref_type,
                        label("org.opencontainers.image.autoware-ref"): image_autoware_ref,
                        label("org.opencontainers.image.autoware-base-version"): "1.8.0",
                        label("org.opencontainers.image.autoware-lock-sha256"): lock_sha256,
                        label("org.opencontainers.image.openadkit-sha"): openadkit_sha,
                    }
                }
            },
        }
    )


def git(repo, *args, capture_output=False):
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=OpenADKit Tests",
            "-c",
            "user.email=tests@example.com",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=capture_output,
        text=True,
    )


def source_repository(tmp_path, changed_source=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    for source_path in (
        "components/docker-bake.hcl",
        "components/runtime-cleanup.sh",
        "components/universe-common/input",
        "components/simulator/input",
    ):
        path = repo / source_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("image source\n")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "image source")
    image_sha = git(repo, "rev-parse", "HEAD", capture_output=True).stdout.strip()

    changed = repo / (changed_source or "README.md")
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("current source\n")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "current source")
    return repo, image_sha


def resolver_env(
    tmp_path,
    targets,
    *,
    common_matches=True,
    simulator_matches=True,
    changed_source=None,
    plain_labels=False,
    common_lock_sha256=LOCK_SHA256,
    simulator_lock_sha256=LOCK_SHA256,
    docker_fail_ref=None,
    docker_fail_mode="notfound",
):
    docker_log = tmp_path / "docker.log"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$4" >> "${DOCKER_LOG}"
if [ -n "${DOCKER_FAIL_REF:-}" ] && [[ "$4" == *"${DOCKER_FAIL_REF}"* ]]; then
  if [ "${DOCKER_FAIL_MODE:-notfound}" = "notfound" ]; then
    printf 'ERROR: %s: not found\\n' "$4" >&2
    exit 1
  fi
  printf 'connection reset\\n' >&2
  exit 1
fi
if [[ "$4" == *":simulator-"* ]]; then
  printf '%s\\n' "${SIMULATOR_METADATA}"
else
  printf '%s\\n' "${COMMON_METADATA}"
fi
"""
    )
    fake_docker.chmod(0o755)
    repo, openadkit_sha = source_repository(tmp_path, changed_source)
    output = tmp_path / "github-output"
    env = os.environ | {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "COMMON_METADATA": registry_metadata(
            openadkit_sha,
            matches=common_matches,
            plain_labels=plain_labels,
            lock_sha256=common_lock_sha256,
        ),
        "SIMULATOR_METADATA": registry_metadata(
            openadkit_sha,
            matches=simulator_matches,
            plain_labels=plain_labels,
            lock_sha256=simulator_lock_sha256,
        ),
        "GITHUB_OUTPUT": str(output),
        "TARGETS_JSON": json.dumps(targets),
        "IMAGE_PREFIX_COMMON": "registry.example/common",
        "IMAGE_PREFIX_COMPONENT": "registry.example/component",
        "AUTOWARE_INPUT_REF": "1.8.0",
        "AUTOWARE_REF_TYPE": "tag",
        "AUTOWARE_REF": AUTOWARE_REF,
        "AUTOWARE_BASE_VERSION": "1.8.0",
        "AUTOWARE_LOCK_SHA256": LOCK_SHA256,
        "USE_LOCAL_COMMON": "false",
        "USE_LOCAL_SIMULATOR": "false",
        "ROS_DISTRO": "humble",
    }
    if docker_fail_ref is not None:
        env["DOCKER_FAIL_REF"] = docker_fail_ref
        env["DOCKER_FAIL_MODE"] = docker_fail_mode
    return repo, env, output, docker_log


def run_resolver(
    tmp_path,
    targets,
    *,
    common_matches=True,
    simulator_matches=True,
    changed_source=None,
    plain_labels=False,
    common_lock_sha256=LOCK_SHA256,
    simulator_lock_sha256=LOCK_SHA256,
):
    repo, env, output, docker_log = resolver_env(
        tmp_path,
        targets,
        common_matches=common_matches,
        simulator_matches=simulator_matches,
        changed_source=changed_source,
        plain_labels=plain_labels,
        common_lock_sha256=common_lock_sha256,
        simulator_lock_sha256=simulator_lock_sha256,
    )
    subprocess.run(["bash", str(SCRIPT)], cwd=repo, env=env, check=True)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    inspected = docker_log.read_text().splitlines() if docker_log.exists() else []
    return outputs, inspected


def run_resolver_failure(
    tmp_path,
    targets,
    *,
    docker_fail_ref,
    docker_fail_mode="notfound",
    common_matches=True,
):
    repo, env, output, docker_log = resolver_env(
        tmp_path,
        targets,
        common_matches=common_matches,
        docker_fail_ref=docker_fail_ref,
        docker_fail_mode=docker_fail_mode,
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env=env, text=True, capture_output=True
    )
    inspected = docker_log.read_text().splitlines() if docker_log.exists() else []
    return result.returncode, inspected, result.stderr


def test_empty_target_plan_does_not_inspect_registry(tmp_path):
    outputs, inspected = run_resolver(tmp_path, [])
    assert outputs == {
        "use_local_common": "false",
        "use_local_simulator": "false",
    }
    assert inspected == []


def test_same_autoware_commit_reuses_branch_labeled_common_contexts(tmp_path):
    outputs, inspected = run_resolver(
        tmp_path, ["api"], common_matches="same-commit-branch"
    )
    assert outputs["devel_context"].endswith(f"@{DIGEST}")
    assert outputs["runtime_context"].endswith(f"@{DIGEST}")
    assert outputs["use_local_common"] == "false"
    assert len(inspected) == 2


def test_non_carla_target_uses_digest_pinned_common_contexts(tmp_path):
    outputs, inspected = run_resolver(tmp_path, ["api"])
    assert outputs["devel_context"].endswith(f"@{DIGEST}")
    assert outputs["runtime_context"].endswith(f"@{DIGEST}")
    assert outputs["use_local_common"] == "false"
    assert all(":universe-common" in ref for ref in inspected)


def test_common_mismatch_selects_local_common_build(tmp_path):
    outputs, inspected = run_resolver(tmp_path, ["api"], common_matches=False)
    assert outputs == {
        "use_local_common": "true",
        "use_local_simulator": "false",
    }
    assert len(inspected) == 1


@pytest.mark.parametrize("lock_sha256", ["", "c" * 64])
def test_common_lock_mismatch_selects_local_common_build(tmp_path, lock_sha256):
    outputs, inspected = run_resolver(
        tmp_path, ["api"], common_lock_sha256=lock_sha256
    )
    assert outputs == {
        "use_local_common": "true",
        "use_local_simulator": "false",
    }
    assert len(inspected) == 1


def test_carla_only_uses_simulator_without_common_contexts(tmp_path):
    outputs, inspected = run_resolver(tmp_path, ["carla-interface"])
    assert outputs["simulator_context"].endswith(f"@{DIGEST}")
    assert outputs["use_local_simulator"] == "false"
    assert not {"devel_context", "runtime_context"} & outputs.keys()
    assert len(inspected) == 1
    assert ":simulator-" in inspected[0]


def test_simulator_lock_mismatch_falls_back_to_local_simulator(tmp_path):
    outputs, inspected = run_resolver(
        tmp_path, ["carla-interface"], simulator_lock_sha256="c" * 64
    )
    assert outputs["use_local_simulator"] == "true"
    assert outputs["use_local_common"] == "false"
    assert outputs["devel_context"].endswith(f"@{DIGEST}")
    assert outputs["runtime_context"].endswith(f"@{DIGEST}")
    assert len(inspected) == 3


def test_simulator_mismatch_falls_back_then_resolves_common(tmp_path):
    outputs, inspected = run_resolver(
        tmp_path, ["carla-interface"], simulator_matches=False
    )
    assert outputs["use_local_simulator"] == "true"
    assert outputs["use_local_common"] == "false"
    assert outputs["devel_context"].endswith(f"@{DIGEST}")
    assert outputs["runtime_context"].endswith(f"@{DIGEST}")
    assert len(inspected) == 3


def test_common_source_mismatch_selects_local_common_build(tmp_path):
    outputs, _ = run_resolver(
        tmp_path, ["api"], changed_source="components/universe-common/input"
    )
    assert outputs == {
        "use_local_common": "true",
        "use_local_simulator": "false",
    }


def test_simulator_source_mismatch_reuses_matching_common_contexts(tmp_path):
    outputs, inspected = run_resolver(
        tmp_path,
        ["carla-interface"],
        changed_source="components/simulator/input",
    )
    assert outputs["use_local_simulator"] == "true"
    assert outputs["use_local_common"] == "false"
    assert outputs["devel_context"].endswith(f"@{DIGEST}")
    assert outputs["runtime_context"].endswith(f"@{DIGEST}")
    assert len(inspected) == 3


@pytest.mark.parametrize(
    "changed_source",
    [
        "components/docker-bake.hcl",
        "components/runtime-cleanup.sh",
        "components/universe-common/input",
    ],
)
def test_carla_shared_source_mismatch_selects_all_local_dependencies(
    tmp_path, changed_source
):
    outputs, inspected = run_resolver(
        tmp_path, ["carla-interface"], changed_source=changed_source
    )
    assert outputs == {
        "use_local_common": "true",
        "use_local_simulator": "true",
    }
    assert len(inspected) == 2


def test_plain_key_labels_still_resolve(tmp_path):
    outputs, inspected = run_resolver(
        tmp_path, ["api"], plain_labels=True
    )
    assert outputs["devel_context"].endswith(f"@{DIGEST}")
    assert outputs["runtime_context"].endswith(f"@{DIGEST}")
    assert outputs["use_local_common"] == "false"
    assert len(inspected) == 2


def test_not_found_context_falls_back_with_diagnostic(tmp_path):
    returncode, inspected, stderr = run_resolver_failure(
        tmp_path, ["api"], docker_fail_ref=":universe-common-devel-"
    )
    assert returncode == 0
    assert len(inspected) == 1
    assert "not found" in stderr


def test_persistent_context_error_aborts_after_retries(tmp_path):
    returncode, inspected, stderr = run_resolver_failure(
        tmp_path,
        ["api"],
        docker_fail_ref=":universe-common-devel-",
        docker_fail_mode="transient",
    )
    assert returncode != 0
    assert len(inspected) == 3
    assert "unavailable after retries" in stderr
