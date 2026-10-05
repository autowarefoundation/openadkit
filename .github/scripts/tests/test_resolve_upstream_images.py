import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github/scripts/resolve_upstream_images.sh"
DIGEST = f"sha256:{'a' * 64}"


def resolver_env(tmp_path, distro=None, image_names=None):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"ros_distros": ["humble", "jazzy"]}))
    output = tmp_path / "upstream-images.json"
    docker_log = tmp_path / "docker.log"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$4" >> "${DOCKER_LOG}"
printf '{"manifest":{"digest":"%s"}}\n' "${DIGEST}"
"""
    )
    fake_docker.chmod(0o755)
    env = os.environ | {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "AUTOWARE_BASE_VERSION": "1.8.0",
        "IMAGE_INVENTORY": str(inventory),
        "UPSTREAM_IMAGES_OUTPUT": str(output),
        "DOCKER_LOG": str(docker_log),
        "DIGEST": DIGEST,
    }
    if distro is not None:
        env["UPSTREAM_ROS_DISTRO"] = distro
    if image_names is not None:
        env["UPSTREAM_IMAGE_NAMES"] = image_names
    return env, output, docker_log


def run_resolver(tmp_path, distro=None, image_names=None):
    env, output, docker_log = resolver_env(tmp_path, distro, image_names)
    result = subprocess.run(
        ["bash", str(SCRIPT)], env=env, text=True, capture_output=True
    )
    inspected = docker_log.read_text().splitlines() if docker_log.exists() else []
    data = json.loads(output.read_text()) if output.exists() else None
    return result, data, inspected


@pytest.mark.parametrize(
    ("distro", "names", "distros", "count"),
    [
        (None, None, {"humble", "jazzy"}, 8),
        ("humble", None, {"humble"}, 4),
        ("humble", "core-devel base", {"humble"}, 2),
        ("humble", "", set(), 0),
    ],
)
def test_resolves_requested_distros_and_images(tmp_path, distro, names, distros, count):
    result, data, inspected = run_resolver(tmp_path, distro, names)
    assert result.returncode == 0, result.stderr
    assert len(data) == len(inspected) == count
    assert {item["ros_distro"] for item in data} == distros
    if names:
        assert {item["name"] for item in data} == set(names.split())
    if distro:
        assert all(f"-{distro}-1.8.0" in ref for ref in inspected)
    assert all(item["uri"] == f"docker-image://{item['ref']}@{DIGEST}" for item in data)


@pytest.mark.parametrize(
    ("distro", "names", "message"),
    [
        ("rolling", None, "Unsupported upstream ROS distro: rolling"),
        ("humble", "base unknown", "Unsupported upstream image name: unknown"),
    ],
)
def test_rejects_unknown_inputs_before_registry_lookup(tmp_path, distro, names, message):
    result, data, inspected = run_resolver(tmp_path, distro, names)
    assert result.returncode != 0
    assert data is None
    assert inspected == []
    assert message in result.stderr
