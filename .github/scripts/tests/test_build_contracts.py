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
LINT_WORKFLOW = (ROOT / ".github/workflows/lint.yaml").read_text()
DOCS_WORKFLOW = (ROOT / ".github/workflows/deploy-docs.yaml").read_text()
REGISTRY_CONTEXT_RESOLVER = (
    ROOT / ".github/scripts/resolve_registry_contexts.sh"
).read_text()
CAPTURE_METADATA = (ROOT / ".github/scripts/capture_build_metadata.sh").read_text()
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


def test_long_pr_build_leaves_time_for_vulnerability_scan():
    assert re.search(
        r"(?m)^\s+timeout-minutes:\s+(1[5-9][0-9]|[2-9][0-9]{2,})$",
        SINGLE_IMAGE_WORKFLOW,
    )


def test_single_image_skips_ccache_extraction():
    assert SINGLE_IMAGE_WORKFLOW.count('skip-extraction: "true"') == 2
    assert "steps.cache-restore.outputs.cache-hit" not in SINGLE_IMAGE_WORKFLOW
    assert "lookup-only: true" not in SINGLE_IMAGE_WORKFLOW


def test_scheduled_main_builds_refresh_ccache_lineages():
    save_ccache = (
        "github.ref == 'refs/heads/main' && "
        "(github.event_name == 'push' || github.event_name == 'schedule')"
    )
    assert save_ccache in ALL_IMAGES_WORKFLOW
    common = ALL_IMAGES_WORKFLOW.split("  build-common:\n", 1)[1].split(
        "  build-components:\n", 1
    )[0]
    components = ALL_IMAGES_WORKFLOW.split("  build-components:\n", 1)[1].split(
        "\n  build-carla-interface:\n", 1
    )[0]
    for job in (common, components):
        assert save_ccache in job
        assert job.count("if: env.SAVE_CCACHE == 'true'") == 2
        assert "if: env.IS_MAIN_PUSH == 'true'" not in job
        assert "enable=${{ env.IS_MAIN_PUSH }}" in job


def test_local_common_build_is_shared_without_persistent_pr_cache():
    assert "github.event_name == 'workflow_dispatch' && github.run_id || github.ref" in (
        SINGLE_IMAGE_WORKFLOW
    )
    assert "cancel-in-progress: true" in SINGLE_IMAGE_WORKFLOW

    producer = SINGLE_IMAGE_WORKFLOW.split("  build-local-common:\n", 1)[1].split(
        "\n  build:\n", 1
    )[0]
    build = SINGLE_IMAGE_WORKFLOW.split("\n  build:\n", 1)[1].split(
        "\n  cleanup-pr-caches:\n", 1
    )[0]
    cleanup = SINGLE_IMAGE_WORKFLOW.split("\n  cleanup-pr-caches:\n", 1)[1]

    assert "github.event_name == 'pull_request'" in producer
    assert "head.repo.full_name == github.repository" in producer
    assert "actions: write" in producer
    assert "targets: universe-common" in producer
    assert "scope=pr-common-devel-${{ github.run_id }},mode=min" in producer
    assert "scope=pr-common-runtime-${{ github.run_id }},mode=min" in producer
    assert 'gh cache delete --all --ref "${PR_REF}"' in producer

    assert "needs: [prepare, build-local-common]" in build
    assert "always() &&\n      !cancelled()" in build
    assert "needs.build-local-common.result == 'skipped'" in build
    assert "*.cache-from+=type=gha,scope=pr-common-devel-" in build
    assert "*.cache-from+=type=gha,scope=pr-common-runtime-" in build

    assert "needs: [prepare, build-local-common, build]" in cleanup
    assert "always() &&" in cleanup
    assert "!cancelled()" in cleanup
    assert "actions: write" in cleanup
    assert 'gh cache delete --all --ref "${PR_REF}"' not in cleanup
    assert 'test("pr-common-(devel|runtime)-" + $run)' in cleanup
    assert "*.cache-from+=type=registry,ref=ghcr.io/{0}/openadkit-buildcache:universe-common" in build
    assert "*.cache-from+=type=registry,ref=ghcr.io/{0}/openadkit-buildcache:simulator" in build


def test_single_image_build_pins_all_upstream_autoware_contexts():
    assert "UPSTREAM_ROS_DISTRO: ${{ inputs.ros-distro || 'humble' }}" in (
        SINGLE_IMAGE_WORKFLOW
    )
    for output, context in (
        ("upstream_core_devel", "*.contexts.autoware-core-devel={0}"),
        ("upstream_base", "*.contexts.autoware-base={0}"),
        (
            "upstream_cuda_runtime",
            "sensing-perception-cuda.contexts.autoware-base-cuda-runtime={0}",
        ),
        (
            "upstream_cuda_devel",
            "sensing-perception-cuda.contexts.autoware-base-cuda-devel={0}",
        ),
    ):
        assert f"{output}: ${{{{ steps.upstream.outputs." in SINGLE_IMAGE_WORKFLOW
        assert context in SINGLE_IMAGE_WORKFLOW
        assert f"needs.prepare.outputs.{output}" in SINGLE_IMAGE_WORKFLOW
    assert 'export UPSTREAM_IMAGE_NAMES="${names[*]}"' in SINGLE_IMAGE_WORKFLOW
    assert "@sha256:" not in SINGLE_IMAGE_WORKFLOW


def test_carla_runs_after_unrelated_component_failure():
    carla = ALL_IMAGES_WORKFLOW.split("  build-carla-interface:\n", 1)[1].split(
        "\n  # =============================================================================\n"
        "  # Stage 3:",
        1,
    )[0]
    assert "needs: [prepare, build-common, build-components]" in carla
    assert "!cancelled()" in carla
    assert "needs.prepare.result == 'success'" in carla
    assert "needs.build-common.result == 'success'" in carla
    assert "needs.build-components.result == 'success'" not in carla


def test_common_matrix_failure_does_not_skip_component_cells():
    components = ALL_IMAGES_WORKFLOW.split("  build-components:\n", 1)[1].split(
        "\n  build-carla-interface:\n", 1
    )[0]
    assert "!cancelled() && needs.prepare.result == 'success'" in components
    assert "needs.build-common.result == 'success'" not in components


def test_manifest_jobs_require_prepare_success():
    manifests = ALL_IMAGES_WORKFLOW.split("  create-manifests:\n", 1)[1].split(
        "\n  manifest-report:\n", 1
    )[0]
    report = ALL_IMAGES_WORKFLOW.split("  manifest-report:\n", 1)[1].split(
        "\n  capture-metadata:\n", 1
    )[0]
    assert "!cancelled() && needs.prepare.result == 'success'" in manifests
    assert "!cancelled() && needs.prepare.result == 'success'" in report


def test_yaml_and_docs_navigation_inputs_trigger_validation():
    for path in (
        ".github/ISSUE_TEMPLATE/**",
        ".github/DISCUSSION_TEMPLATE/**",
        ".github/dependabot.yaml",
        ".github/stale.yml",
        ".github/sync-files.yaml",
        "deployments/**/*.yaml",
        "platforms/**/*.yml",
    ):
        assert path in LINT_WORKFLOW
    assert '"docs/.pages"' in DOCS_WORKFLOW
    assert '"docs/**/.pages"' in DOCS_WORKFLOW


def test_capture_metadata_uses_retrying_registry_lookup():
    assert "source \"${script_dir}/registry_lookup.sh\"" in CAPTURE_METADATA
    assert "registry_inspect_json" in CAPTURE_METADATA
    assert 'select(test("^sha256:[0-9a-f]{64}$"))' in CAPTURE_METADATA


def test_published_images_include_autoware_lock_provenance():
    label = 'labels."org.opencontainers.image.autoware-lock-sha256"'
    assert ALL_IMAGES_WORKFLOW.count(label) == 3
    assert "AUTOWARE_LOCK_SHA256: ${{ steps.lock.outputs.autoware_lock_sha256 }}" in (
        SINGLE_IMAGE_WORKFLOW
    )
    assert "AUTOWARE_LOCK_SHA256" in REGISTRY_CONTEXT_RESOLVER


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


def test_logging_universe_image_has_compose_default():
    logging = (ROOT / "deployments/logging-simulation/docker-compose.yaml").read_text()
    assert "${AUTOWARE_UNIVERSE_IMAGE:-ghcr.io/autowarefoundation/autoware:universe@" in logging


def test_carla_compose_uses_gpu_sensing_image():
    carla = (ROOT / "deployments/carla-simulation/docker-compose.yaml").read_text()
    env = (ROOT / "deployments/carla-simulation/config.env").read_text()
    assert "SENSING_PERCEPTION_GPU_IMAGE:-ghcr.io/autowarefoundation/openadkit:sensing-perception-cuda" in carla
    assert "SENSING_PERCEPTION_GPU_IMAGE=" in env
    assert "image: ${SENSING_PERCEPTION_IMAGE" not in carla


def test_lint_validates_standalone_zenoh_compose():
    assert "cd deployments/zenoh-bridge && docker compose --env-file config.env config -q" in (
        LINT_WORKFLOW
    )


def test_zenoh_stays_off_cli_inventory():
    inventory = (ROOT / "openadkit.json").read_text()
    assert '"zenoh-bridge"' not in inventory


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
