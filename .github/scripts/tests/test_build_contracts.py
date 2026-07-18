import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

import resolve_image_matrices as matrices


INVENTORY = json.loads((ROOT / ".github/image-inventory.json").read_text())
BAKE = (ROOT / "components/docker-bake.hcl").read_text()
WORKFLOW = ROOT / ".github/workflows/build-single-image.yaml"


def manifest_index():
    return {
        (entry["repo"], entry["target"], entry["ros-distro"]): entry["arches"]
        for entry in matrices.build_matrices(INVENTORY)["manifest_matrix"]["include"]
    }


def test_inventory_matches_bake_targets_and_metadata_stubs():
    inventory = {image["target"] for image in INVENTORY["images"]}
    targets = set(
        re.findall(
            r'^target\s+"(?!_|docker-metadata-action-)([\w-]+)"',
            BAKE,
            flags=re.MULTILINE,
        )
    )
    metadata = set(re.findall(r'target\s+"docker-metadata-action-([\w-]+)"', BAKE))
    assert targets == inventory
    assert metadata == inventory


def test_matrix_preserves_platform_and_distro_constraints():
    index = manifest_index()
    assert index[("component", "planning-control", "humble")] == "amd64 arm64"
    assert index[("component", "sensing-perception-cuda", "jazzy")] == "amd64"
    assert index[("component", "carla-interface", "humble")] == "amd64"
    assert ("component", "carla-interface", "jazzy") not in index


def test_carla_builds_after_simulator():
    resolved = matrices.build_matrices(INVENTORY)
    components = {entry["target"] for entry in resolved["component_matrix"]["include"]}
    carla = {entry["target"] for entry in resolved["carla_matrix"]["include"]}
    assert "simulator" in components
    assert "carla-interface" not in components
    assert carla == {"carla-interface"}


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def run_detection(tmp_path, changed_path):
    inventory = ROOT / ".github/image-inventory.json"
    target_inventory = tmp_path / ".github/image-inventory.json"
    target_inventory.parent.mkdir(parents=True)
    target_inventory.write_bytes(inventory.read_bytes())
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "ci@example.com")
    git(tmp_path, "config", "user.name", "CI")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    changed = tmp_path / changed_path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("changed\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "change")
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["prepare"]["steps"]
    script = next(step["run"] for step in steps if step.get("id") == "detect")
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=os.environ
        | {
            "BASE_SHA": base,
            "EVENT_NAME": "pull_request",
            "GITHUB_OUTPUT": str(output),
            "ROS_DISTRO": "humble",
            "TARGET_INPUT": "",
        },
        text=True,
        capture_output=True,
    )
    values = {}
    if output.exists():
        values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return result, values


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        ("components/api/Dockerfile", {"api"}),
        ("components/simulator/Dockerfile", {"simulator", "carla-interface"}),
    ],
)
def test_component_changes_select_required_targets(tmp_path, changed, expected):
    result, outputs = run_detection(tmp_path, changed)
    assert result.returncode == 0, result.stderr
    assert set(json.loads(outputs["targets_json"])) == expected


def test_unknown_component_input_fails_closed(tmp_path):
    result, _ = run_detection(tmp_path, "components/new-component/Dockerfile")
    assert result.returncode != 0
    assert "Unmapped component build input" in result.stderr
