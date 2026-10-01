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


def run_resolver(
    tmp_path, targets, *, common_matches=True, simulator_matches=True,
    changed_source=None, plain_labels=False, common_lock_sha256=LOCK_SHA256,
    simulator_lock_sha256=LOCK_SHA256, fail_ref="", fail_mode="notfound",
):
    """Run the resolver against a fake registry; return result, outputs, lookups."""
    docker_log = tmp_path / "docker.log"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$4" >> "${DOCKER_LOG}"
if [ -n "${DOCKER_FAIL_REF}" ] && [[ "$4" == *"${DOCKER_FAIL_REF}"* ]]; then
  if [ "${DOCKER_FAIL_MODE}" = "notfound" ]; then
    printf 'ERROR: %s: not found\\n' "$4" >&2
  else
    printf 'connection reset\\n' >&2
  fi
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
        "DOCKER_FAIL_REF": fail_ref,
        "DOCKER_FAIL_MODE": fail_mode,
        "COMMON_METADATA": registry_metadata(
            openadkit_sha, matches=common_matches, plain_labels=plain_labels,
            lock_sha256=common_lock_sha256,
        ),
        "SIMULATOR_METADATA": registry_metadata(
            openadkit_sha, matches=simulator_matches, plain_labels=plain_labels,
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
    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env=env, text=True, capture_output=True
    )
    outputs = (
        dict(line.split("=", 1) for line in output.read_text().splitlines())
        if output.exists() else {}
    )
    lookups = docker_log.read_text().splitlines() if docker_log.exists() else []
    return result, outputs, lookups


def test_empty_target_plan_does_not_inspect_registry(tmp_path):
    result, outputs, lookups = run_resolver(tmp_path, [])
    assert result.returncode == 0, result.stderr
    assert outputs == {"use_local_common": "false", "use_local_simulator": "false"}
    assert lookups == []


SHARED_SOURCES = (
    "components/docker-bake.hcl",
    "components/runtime-cleanup.sh",
    "components/universe-common/input",
)


@pytest.mark.parametrize(
    ("targets", "options", "common", "simulator", "lookups"),
    [
        # common/simulator: "registry" reuses the pinned image, "local" builds it.
        (["api"], {}, "registry", None, 2),
        (["api"], {"common_matches": "same-commit-branch"}, "registry", None, 2),
        (["api"], {"plain_labels": True}, "registry", None, 2),
        (["api"], {"common_matches": False}, "local", None, 1),
        (["api"], {"common_lock_sha256": ""}, "local", None, 1),
        (["api"], {"common_lock_sha256": "c" * 64}, "local", None, 1),
        (["api"], {"changed_source": "components/universe-common/input"}, "local", None, None),
        (["carla-interface"], {}, None, "registry", 1),
        (["carla-interface"], {"simulator_lock_sha256": "c" * 64}, "registry", "local", 3),
        (["carla-interface"], {"simulator_matches": False}, "registry", "local", 3),
        (["carla-interface"], {"changed_source": "components/simulator/input"}, "registry", "local", 3),
        *((["carla-interface"], {"changed_source": path}, "local", "local", 2) for path in SHARED_SOURCES),
    ],
)
def test_resolver_reuses_registry_images_only_when_they_match(
    tmp_path, targets, options, common, simulator, lookups
):
    result, outputs, inspected = run_resolver(tmp_path, targets, **options)
    assert result.returncode == 0, result.stderr
    if common == "registry":
        assert outputs["use_local_common"] == "false"
        assert outputs["devel_context"].endswith(f"@{DIGEST}")
        assert outputs["runtime_context"].endswith(f"@{DIGEST}")
    else:
        assert not {"devel_context", "runtime_context"} & outputs.keys()
        if common == "local":
            assert outputs["use_local_common"] == "true"
    if simulator == "registry":
        assert outputs["use_local_simulator"] == "false"
        assert outputs["simulator_context"].endswith(f"@{DIGEST}")
    else:
        assert "simulator_context" not in outputs
        assert outputs["use_local_simulator"] == ("true" if simulator == "local" else "false")
    if lookups is not None:
        assert len(inspected) == lookups
    if targets == ["api"]:
        assert all(":universe-common" in ref for ref in inspected)


def test_not_found_context_falls_back_with_diagnostic(tmp_path):
    result, _, inspected = run_resolver(tmp_path, ["api"], fail_ref=":universe-common-devel-")
    assert result.returncode == 0, result.stderr
    assert len(inspected) == 1
    assert "not found" in result.stderr


def test_persistent_context_error_aborts_after_retries(tmp_path):
    result, _, inspected = run_resolver(
        tmp_path, ["api"], fail_ref=":universe-common-devel-", fail_mode="transient"
    )
    assert result.returncode != 0
    assert len(inspected) == 3
    assert "unavailable after retries" in result.stderr
