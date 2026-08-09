import io
import json
from pathlib import Path
import re
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

import resolve_image_matrices as matrices


INVENTORY = json.loads((ROOT / ".github/image-inventory.json").read_text())
BAKE = (ROOT / "components/docker-bake.hcl").read_text()
ALL_IMAGES_WORKFLOW = (ROOT / ".github/workflows/build-all-images.yaml").read_text()
SINGLE_IMAGE_WORKFLOW = (ROOT / ".github/workflows/build-single-image.yaml").read_text()
REGISTRY_CONTEXT_RESOLVER = (
    ROOT / ".github/scripts/resolve_registry_contexts.sh"
).read_text()
ZENOH_COMPOSE = (ROOT / "deployments/zenoh-bridge/docker-compose.yaml").read_text()


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
            {"simulator", "carla-interface"},
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
    with pytest.raises(
        ValueError,
        match="Target 'carla-interface' does not support ROS distro 'jazzy'",
    ):
        matrices.build_single_image_plan(
            INVENTORY, target_input="carla-interface", distro="jazzy"
        )


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


def test_long_pr_build_leaves_time_for_vulnerability_scan():
    assert re.search(
        r"(?m)^\s+timeout-minutes:\s+(1[5-9][0-9]|[2-9][0-9]{2,})$",
        SINGLE_IMAGE_WORKFLOW,
    )


def test_carla_registry_simulator_provenance_is_validated():
    assert 'resolve_registry_context "${simulator_ref}"' in REGISTRY_CONTEXT_RESOLVER


def test_registry_provenance_mismatch_falls_back_before_source_setup():
    assert SINGLE_IMAGE_WORKFLOW.index("Resolve registry contexts") < (
        SINGLE_IMAGE_WORKFLOW.index("Set up build environment")
    )
    assert (
        "use_local_common: ${{ steps.contexts.outputs.use_local_common }}"
        in SINGLE_IMAGE_WORKFLOW
    )
    assert (
        "setup-autoware: ${{ needs.prepare.outputs.setup_autoware == 'true' || "
        "needs.prepare.outputs.use_local_common == 'true' || "
        "needs.prepare.outputs.use_local_simulator == 'true' }}"
        in SINGLE_IMAGE_WORKFLOW
    )
    assert (
        "with-middleware: ${{ needs.prepare.outputs.with_middleware == 'true' || "
        "needs.prepare.outputs.use_local_common == 'true' }}"
        in SINGLE_IMAGE_WORKFLOW
    )
    assert "needs.prepare.outputs.devel_context != ''" in SINGLE_IMAGE_WORKFLOW
    assert "needs.prepare.outputs.runtime_context != ''" in SINGLE_IMAGE_WORKFLOW


def test_carla_registry_simulator_overrides_named_context():
    for workflow in (ALL_IMAGES_WORKFLOW, SINGLE_IMAGE_WORKFLOW):
        assert "carla-interface.contexts.simulator=" in workflow
        assert "carla-interface.args.SIMULATOR_IMAGE=" not in workflow

    assert 'echo "simulator_context=${simulator_context}"' in REGISTRY_CONTEXT_RESOLVER
    assert "printf 'docker-image://%s@%s\\n'" in REGISTRY_CONTEXT_RESOLVER
    assert 'SIMULATOR_IMAGE = "simulator"' in BAKE


def test_zenoh_cloud_bridge_is_internal_only():
    cloud_bridge = ZENOH_COMPOSE.split("\n  cloud_zenoh_bridge:", 1)[1].split(
        "\n  cloud_zenoh_ready:", 1
    )[0]
    assert "ports:" not in cloud_bridge
    assert "-l tcp/0.0.0.0:7448" in cloud_bridge
    assert re.search(
        r"cloud_zenoh_ready:.*?depends_on:\s+cloud_zenoh_bridge:\s+"
        r"condition: service_started",
        ZENOH_COMPOSE,
        flags=re.DOTALL,
    )


def test_single_image_cli_writes_github_outputs(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(sys, "stdin", io.StringIO("components/api/Dockerfile\n"))
    assert matrices.main(["resolver", "single-image", "humble", ""]) == 0
    assert 'targets_json=["api"]' in capsys.readouterr().out
