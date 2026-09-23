import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

import resolve_image_matrices as matrices


INVENTORY = json.loads((ROOT / ".github/image-inventory.json").read_text())
BAKE = (ROOT / "components/docker-bake.hcl").read_text()


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


def test_kit_component_images_match_inventory_component_targets():
    kit = json.loads((ROOT / "openadkit.json").read_text())
    catalog = set(kit["componentImages"].values())
    inventory = {
        image["target"]
        for image in INVENTORY["images"]
        if image["stage"] == "component"
    }
    assert catalog == inventory


def test_curated_compose_kit_image_envs_are_catalogued():
    kit = json.loads((ROOT / "openadkit.json").read_text())
    catalog_keys = set(kit["componentImages"])
    third_party = {
        "AUTOWARE_UNIVERSE_IMAGE",
        "CARLA_CONTAINER_IMAGE",
        "SCENARIO_SIMULATOR_IMAGE",
        "ZENOH_BRIDGE_IMAGE",
    }
    compose_keys: set[str] = set()
    for path in (ROOT / "deployments").rglob("*.yaml"):
        compose_keys.update(
            re.findall(r"\$\{([A-Z][A-Z0-9_]*_IMAGE)", path.read_text())
        )
    assert compose_keys - third_party <= catalog_keys


def test_matrix_preserves_platform_and_distro_constraints():
    index = manifest_index()
    assert index[("component", "planning-control", "humble")] == "amd64 arm64"
    assert index[("component", "sensing-perception-cuda", "jazzy")] == "amd64"
    assert index[("component", "carla-interface", "humble")] == "amd64"
    assert index[("component", "carla-interface", "jazzy")] == "amd64"


def test_carla_builds_after_simulator():
    resolved = matrices.build_matrices(INVENTORY)
    components = {entry["target"] for entry in resolved["component_matrix"]["include"]}
    carla = {entry["target"] for entry in resolved["carla_matrix"]["include"]}
    assert "simulator" in components
    assert "carla-interface" not in components
    assert carla == {"carla-interface"}


@pytest.mark.parametrize(
    ("changed", "expected", "flags"),
    [
        (
            "components/universe-common/Dockerfile",
            {image["target"] for image in INVENTORY["images"]},
            {"with_middleware": True, "use_local_common": True},
        ),
        ("components/sensing-perception/Dockerfile", {"sensing-perception"}, {}),
        (
            "components/sensing-perception/Dockerfile.cuda",
            {"sensing-perception-cuda"},
            {},
        ),
        (
            "components/sensing-perception/scripts/build.sh",
            {"sensing-perception", "sensing-perception-cuda"},
            {},
        ),
        ("components/api/Dockerfile", {"api"}, {}),
        (
            "components/simulator/Dockerfile",
            {"carla-interface"},
            {"use_local_simulator": True},
        ),
        (
            "components/carla-interface/Dockerfile",
            {"carla-interface"},
            {"setup_autoware": False},
        ),
    ],
)
def test_component_changes_select_required_targets(changed, expected, flags):
    plan = matrices.build_single_image_plan(INVENTORY, [changed])
    assert set(plan["targets_json"]) == expected
    assert all(plan[name] is value for name, value in flags.items())


def test_shared_build_inputs_select_all_targets():
    expected = {image["target"] for image in INVENTORY["images"]}
    for changed in (
        ".github/scripts/registry_lookup.sh",
        ".github/scripts/resolve_registry_contexts.sh",
        ".github/scripts/resolve_upstream_images.sh",
        ".github/actions/inject-ccache/action.yaml",
        ".trivyignore",
    ):
        plan = matrices.build_single_image_plan(INVENTORY, [changed])
        assert set(plan["targets_json"]) == expected


def test_docker_bake_change_uses_all_local_images():
    plan = matrices.build_single_image_plan(
        INVENTORY, ["components/docker-bake.hcl"]
    )
    assert plan["use_local_common"] is True
    assert plan["use_local_simulator"] is True
    assert "carla-interface" in plan["targets_json"]
    assert "simulator" not in plan["targets_json"]


def test_manual_targets_are_validated_sorted_and_deduplicated():
    plan = matrices.build_single_image_plan(
        INVENTORY, target_input="visualizer api visualizer"
    )
    assert plan["targets_json"] == ["api", "visualizer"]

    with pytest.raises(ValueError, match="Unknown Bake target: missing"):
        matrices.build_single_image_plan(INVENTORY, target_input="missing")


def test_distro_validation_applies_to_global_and_target_constraints():
    with pytest.raises(ValueError, match="Unsupported ROS distro: rolling"):
        matrices.build_single_image_plan(INVENTORY, distro="rolling")
    plan = matrices.build_single_image_plan(
        INVENTORY, target_input="carla-interface", distro="jazzy"
    )
    assert plan["targets_json"] == ["carla-interface"]


def test_irrelevant_and_readme_changes_produce_empty_plan():
    plan = matrices.build_single_image_plan(
        INVENTORY,
        ["docs/index.md", "components/README.md", "components/api/README.md"],
    )
    assert plan["targets_json"] == []


def test_unknown_component_input_fails_closed():
    with pytest.raises(ValueError, match="Unmapped component build input"):
        matrices.build_single_image_plan(
            INVENTORY, ["components/new-component/Dockerfile"]
        )


COMPOSE_AVAILABLE = shutil.which("docker") is not None


def _compose_config(files, directory, extra_env=None):
    env = dict(os.environ)
    env.pop("COMPOSE_FILE", None)
    env.update(extra_env or {})
    command = ["docker", "compose", "--env-file", str(directory / "config.env")]
    for path in files:
        command.extend(("--file", str(path)))
    command.extend(("config", "--format", "json"))
    result = subprocess.run(
        command,
        cwd=directory,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _role_compose_env(directory, role):
    shared = ROOT / "deployments/shared"
    return {
        "ROS_DISTRO": "humble",
        "OPENADKIT_ROLE": role,
        "ZENOH_BASE_DIR": str(shared),
        "ZENOH_CONFIG_PATH": str(directory / "config/zenoh.json5"),
        "ZENOH_LISTEN": "tcp/127.0.0.1:7447",
        "ZENOH_PEER": "tcp/127.0.0.1:7447",
        "REMOTE_PASSWORD": "ci-validate",
    }


@pytest.mark.skipif(not COMPOSE_AVAILABLE, reason="docker compose is required")
def test_real_compose_views_keep_default_and_role_graphs_isolated():
    scenario = ROOT / "deployments/scenario-simulation"
    default = _compose_config([scenario / "docker-compose.yaml"], scenario)
    assert "zenoh-bridge" not in default["services"]
    assert "scenario_simulator" in default["services"]
    assert "map" in default["services"]

    autoware = _compose_config(
        [
            scenario / "services.autoware.yaml",
            ROOT / "deployments/shared/compose.zenoh.yaml",
        ],
        scenario,
        _role_compose_env(scenario, "autoware"),
    )
    assert "zenoh-bridge" in autoware["services"]
    assert "scenario_simulator" not in autoware["services"]
    assert "map" in autoware["services"]

    scenario_role = _compose_config(
        [
            scenario / "services.scenario.yaml",
            ROOT / "deployments/shared/compose.zenoh.yaml",
        ],
        scenario,
        _role_compose_env(scenario, "scenario"),
    )
    assert set(scenario_role["services"]) == {"scenario_simulator", "zenoh-bridge"}
    assert "pid" not in scenario_role["services"]["scenario_simulator"]

    carla = ROOT / "deployments/carla-simulation"
    carla_default = _compose_config(
        [carla / "docker-compose.yaml"],
        carla,
        {"REMOTE_PASSWORD": "ci-validate"},
    )
    assert "zenoh-bridge" not in carla_default["services"]
    assert "carla" in carla_default["services"]
    assert "carla-interface" in carla_default["services"]
    assert "map" in carla_default["services"]

    carla_autoware = _compose_config(
        [
            carla / "services.autoware.yaml",
            ROOT / "deployments/shared/compose.zenoh.yaml",
        ],
        carla,
        _role_compose_env(carla, "autoware"),
    )
    assert "zenoh-bridge" in carla_autoware["services"]
    assert "carla" not in carla_autoware["services"]
    assert "carla-interface" not in carla_autoware["services"]
    vehicle_deps = carla_autoware["services"]["vehicle"].get("depends_on") or {}
    assert "carla-interface" not in vehicle_deps

    carla_role = _compose_config(
        [
            carla / "services.carla.yaml",
            ROOT / "deployments/shared/compose.zenoh.yaml",
        ],
        carla,
        _role_compose_env(carla, "carla"),
    )
    assert set(carla_role["services"]) == {
        "carla",
        "carla-interface",
        "carla-map-loader",
        "zenoh-bridge",
    }


def test_single_image_cli_writes_github_outputs(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(sys, "stdin", io.StringIO("components/api/Dockerfile\n"))
    assert matrices.main(["resolver", "single-image", "humble", ""]) == 0
    assert 'targets_json=["api"]' in capsys.readouterr().out
