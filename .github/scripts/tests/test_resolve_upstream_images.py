import json
import os
from pathlib import Path
import subprocess


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


def test_resolves_all_inventory_distros_by_default(tmp_path):
    result, data, inspected = run_resolver(tmp_path)
    assert result.returncode == 0
    assert len(data) == 8
    assert len(inspected) == 8
    assert {item["ros_distro"] for item in data} == {"humble", "jazzy"}


def test_resolves_only_requested_distro(tmp_path):
    result, data, inspected = run_resolver(tmp_path, "humble")
    assert result.returncode == 0
    assert len(data) == 4
    assert len(inspected) == 4
    assert {item["ros_distro"] for item in data} == {"humble"}
    assert all("-humble-1.8.0" in ref for ref in inspected)
    assert all(item["uri"] == f"docker-image://{item['ref']}@{DIGEST}" for item in data)


def test_resolves_only_requested_image_names(tmp_path):
    result, data, inspected = run_resolver(
        tmp_path, "humble", "core-devel base"
    )
    assert result.returncode == 0
    assert {item["name"] for item in data} == {"core-devel", "base"}
    assert len(inspected) == 2


def test_empty_image_name_list_skips_registry_lookup(tmp_path):
    result, data, inspected = run_resolver(tmp_path, "humble", "")
    assert result.returncode == 0
    assert data == []
    assert inspected == []


def test_rejects_unknown_distro_before_registry_lookup(tmp_path):
    result, data, inspected = run_resolver(tmp_path, "rolling")
    assert result.returncode != 0
    assert data is None
    assert inspected == []
    assert "Unsupported upstream ROS distro: rolling" in result.stderr


def test_rejects_unknown_image_before_registry_lookup(tmp_path):
    result, data, inspected = run_resolver(tmp_path, "humble", "base unknown")
    assert result.returncode != 0
    assert data is None
    assert inspected == []
    assert "Unsupported upstream image name: unknown" in result.stderr
