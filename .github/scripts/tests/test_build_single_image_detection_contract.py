import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/build-single-image.yaml"
INVENTORY_PATH = REPO_ROOT / ".github/image-inventory.json"
INSTALL_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/install-host.yaml"
BAKE_PATH = REPO_ROOT / "components/docker-bake.hcl"


def detection_script():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["prepare"]["steps"]
    return next(step["run"] for step in steps if step.get("id") == "detect")


def git(repo, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run_detection(tmp_path, changed_path, base_sha=None):
    inventory = INVENTORY_PATH.read_text()
    inventory_path = tmp_path / ".github/image-inventory.json"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text(inventory)

    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "ci@example.com")
    git(tmp_path, "config", "user.name", "CI")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    actual_base_sha = git(tmp_path, "rev-parse", "HEAD")

    path = tmp_path / changed_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path == inventory_path:
        path.write_text(inventory + "\n")
    else:
        path.write_text("changed\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "change")

    output_path = tmp_path / "github-output"
    env = os.environ.copy()
    env.update(
        {
            "BASE_SHA": base_sha or actual_base_sha,
            "EVENT_NAME": "pull_request",
            "GITHUB_OUTPUT": str(output_path),
            "TARGET_INPUT": "",
        }
    )
    result = subprocess.run(
        ["bash", "-c", detection_script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    outputs = {}
    if output_path.exists():
        for line in output_path.read_text().splitlines():
            key, value = line.split("=", 1)
            outputs[key] = value
    return result, outputs


@pytest.mark.parametrize(
    ("changed_path", "expected_targets", "local_common", "local_simulator"),
    [
        (
            "components/universe-common/Dockerfile",
            {"universe-common-devel", "universe-common"},
            "true",
            "false",
        ),
        (
            "components/simulator/Dockerfile",
            {"simulator", "carla-interface"},
            "false",
            "true",
        ),
        ("components/api/Dockerfile", {"api"}, "false", "false"),
    ],
)
def test_parent_and_leaf_detection(
    tmp_path, changed_path, expected_targets, local_common, local_simulator
):
    result, outputs = run_detection(tmp_path, changed_path)

    assert result.returncode == 0, result.stderr
    assert set(json.loads(outputs["targets_json"])) == expected_targets
    assert outputs["use_local_common"] == local_common
    assert outputs["use_local_simulator"] == local_simulator


@pytest.mark.parametrize(
    ("changed_path", "local_common", "local_simulator"),
    [
        ("components/docker-bake.hcl", "true", "true"),
        (".github/actions/setup-build-env/action.yaml", "false", "false"),
        (".github/scripts/resolve_build_inputs.sh", "false", "false"),
        (".github/image-inventory.json", "false", "false"),
    ],
)
def test_shared_graph_changes_build_the_full_inventory(
    tmp_path, changed_path, local_common, local_simulator
):
    result, outputs = run_detection(tmp_path, changed_path)
    inventory_targets = {
        image["target"] for image in json.loads(INVENTORY_PATH.read_text())["images"]
    }

    assert result.returncode == 0, result.stderr
    assert set(json.loads(outputs["targets_json"])) == inventory_targets
    assert outputs["use_local_common"] == local_common
    assert outputs["use_local_simulator"] == local_simulator


def test_unmapped_component_input_fails_instead_of_building_nothing(tmp_path):
    result, _ = run_detection(tmp_path, "components/new-component/Dockerfile")

    assert result.returncode != 0
    assert "Unmapped component build input" in result.stderr


def test_invalid_pr_base_sha_is_not_suppressed(tmp_path):
    result, _ = run_detection(tmp_path, "components/api/Dockerfile", base_sha="bad-sha")

    assert result.returncode != 0


def test_local_context_and_pr_scan_contracts():
    workflow = WORKFLOW_PATH.read_text()
    bake = BAKE_PATH.read_text()
    install_workflow = INSTALL_WORKFLOW_PATH.read_text()

    assert 'simulator = ctx("simulator")' in bake
    assert 'SIMULATOR_IMAGE = "simulator"' in bake
    assert "github.event.pull_request.base.sha" in workflow
    assert "origin/main...HEAD" not in workflow
    assert "load: ${{ github.event_name == 'pull_request'" in workflow
    assert "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25" in workflow
    assert "OPENADKIT_CI_FORCE_DOCKER_INSTALL=true" in install_workflow
    assert "./install.sh --no-nvidia --verify" in install_workflow
