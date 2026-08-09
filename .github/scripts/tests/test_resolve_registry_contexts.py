import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github/scripts/resolve_registry_contexts.sh"
AUTOWARE_REF = "5b27e88e84683deb4afaf0aa917f80082a608871"
DIGEST = f"sha256:{'a' * 64}"


def registry_metadata(openadkit_sha, *, matches=True):
    input_ref = "1.8.0" if matches else "main"
    ref_type = "tag" if matches else "branch"
    image_autoware_ref = AUTOWARE_REF if matches else "c" * 40
    return json.dumps(
        {
            "manifest": {"digest": DIGEST},
            "image": {
                "config": {
                    "Labels": {
                        "org.opencontainers.image.autoware-input-ref": input_ref,
                        "org.opencontainers.image.autoware-ref-type": ref_type,
                        "org.opencontainers.image.autoware-ref": image_autoware_ref,
                        "org.opencontainers.image.autoware-base-version": "1.8.0",
                        "org.opencontainers.image.openadkit-sha": openadkit_sha,
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
    tmp_path,
    targets,
    *,
    common_matches=True,
    simulator_matches=True,
    changed_source=None,
):
    docker_log = tmp_path / "docker.log"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$4" >> "${DOCKER_LOG}"
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
            openadkit_sha, matches=common_matches
        ),
        "SIMULATOR_METADATA": registry_metadata(
            openadkit_sha, matches=simulator_matches
        ),
        "GITHUB_OUTPUT": str(output),
        "TARGETS_JSON": json.dumps(targets),
        "IMAGE_PREFIX_COMMON": "registry.example/common",
        "IMAGE_PREFIX_COMPONENT": "registry.example/component",
        "AUTOWARE_INPUT_REF": "1.8.0",
        "AUTOWARE_REF_TYPE": "tag",
        "AUTOWARE_REF": AUTOWARE_REF,
        "AUTOWARE_BASE_VERSION": "1.8.0",
        "USE_LOCAL_COMMON": "false",
        "USE_LOCAL_SIMULATOR": "false",
        "ROS_DISTRO": "humble",
    }
    subprocess.run(["bash", str(SCRIPT)], cwd=repo, env=env, check=True)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    inspected = docker_log.read_text().splitlines() if docker_log.exists() else []
    return outputs, inspected


def test_empty_target_plan_does_not_inspect_registry(tmp_path):
    outputs, inspected = run_resolver(tmp_path, [])
    assert outputs == {
        "use_local_common": "false",
        "use_local_simulator": "false",
    }
    assert inspected == []


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


def test_carla_only_uses_simulator_without_common_contexts(tmp_path):
    outputs, inspected = run_resolver(tmp_path, ["carla-interface"])
    assert outputs["simulator_context"].endswith(f"@{DIGEST}")
    assert outputs["use_local_simulator"] == "false"
    assert not {"devel_context", "runtime_context"} & outputs.keys()
    assert len(inspected) == 1
    assert ":simulator-" in inspected[0]


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
