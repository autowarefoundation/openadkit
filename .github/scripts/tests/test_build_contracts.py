"""Build selection and real Compose topology boundaries, without running containers."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "cli"), str(ROOT / ".github/scripts")]

import build as matrices  # noqa: E402
import compose  # noqa: E402
import manifest  # noqa: E402

INVENTORY = json.loads((ROOT / ".github/image-inventory.json").read_text())


def test_inventory_bake_and_runtime_catalog_agree():
    bake = (ROOT / "components/docker-bake.hcl").read_text()
    targets = {image["target"] for image in INVENTORY["images"]}
    # universe-common-build is CI's unpublished compile base for components, and
    # development builds compile autoware-core-devel for it.
    assert set(re.findall(r'^target\s+"(?!_|docker-metadata-action-)([\w-]+)"', bake, re.M)) == targets | {"universe-common-build", "autoware-core-devel"}
    assert set(re.findall(r'target\s+"docker-metadata-action-([\w-]+)"', bake)) == targets
    kit = json.loads((ROOT / "openadkit.json").read_text())
    assert set(kit["componentImages"].values()) == {image["target"] for image in INVENTORY["images"] if image["stage"] == "component"}
    resolved = matrices.build_matrices(INVENTORY)
    index = {(row["target"], row["ros-distro"]): row["arches"] for row in resolved["manifest_matrix"]["include"]}
    assert index[("planning-control", "humble")] == "amd64 arm64"
    assert index[("sensing-perception-cuda", "jazzy")] == "amd64"
    assert {row["target"] for row in resolved["carla_matrix"]["include"]} == {"carla-interface"}
    assert "simulator" in {row["target"] for row in resolved["component_matrix"]["include"]}


@pytest.mark.parametrize(("path", "expected", "flags"), [
    ("components/universe-common/Dockerfile", {image["target"] for image in INVENTORY["images"]}, {"use_local_common": True}),
    # carla-interface builds the simulator locally, so it is not a separate target.
    (".dockerignore", {image["target"] for image in INVENTORY["images"]} - {"simulator"},
     {"use_local_common": True, "use_local_simulator": True}),
    (".github/autoware.ref", {image["target"] for image in INVENTORY["images"]} - {"simulator"},
     {"use_local_common": True, "use_local_simulator": True}),
    (".github/autoware-base-images.json", {image["target"] for image in INVENTORY["images"]} - {"simulator"},
     {"use_local_common": True, "use_local_simulator": True}),
    ("components/sensing-perception/Dockerfile.cuda", {"sensing-perception-cuda"}, {}),
    ("components/sensing-perception/scripts/build.sh", {"sensing-perception", "sensing-perception-cuda"}, {}),
    ("components/simulator/Dockerfile", {"carla-interface"}, {"use_local_simulator": True}),
    ("docs/index.md", set(), {}),
])
def test_changed_inputs_select_required_builds(path, expected, flags):
    plan = matrices.build_single_image_plan(INVENTORY, [path])
    assert set(plan["targets_json"]) == expected
    assert all(plan[name] is value for name, value in flags.items())


def test_invalid_build_inputs_fail_closed():
    for options, message in [
        ({"target_input": "missing"}, "Unknown Bake target"),
        ({"distro": "rolling"}, "Unsupported ROS distro"),
        ({"changed_files": ["components/new-component/Dockerfile"]}, "Unmapped component build input"),
    ]:
        with pytest.raises(ValueError, match=message):
            matrices.build_single_image_plan(INVENTORY, **options)


@pytest.mark.parametrize(("target", "publish", "local"), [
    ("universe-common", True, False), ("sensing-perception-cuda", True, False),
    ("carla-interface", True, False), ("api", False, False), ("carla-interface", False, True),
])
def test_shared_build_recipe_keeps_pins_provenance_and_local_graphs(target, publish, local):
    uri = "docker-image://example/base@sha256:" + "c" * 64
    prepared = {"build_tag": "123-1", "cache_scope": "main", "autoware_input_ref": "1.8.0", "autoware_ref_type": "tag",
                "autoware_ref": "a" * 40, "autoware_base_version": "1.8.0", "autoware_lock_sha256": "e" * 64,
                "upstream_images": json.dumps({"humble": {name: {"uri": uri} for name in ("core-devel", "base", "base-cuda-runtime", "base-cuda-devel")}}),
                "use_local_common": str(local).lower(), "use_local_simulator": str(local).lower(), "simulator_context": uri}
    if not local:
        prepared.update(devel_context=uri, runtime_context=uri)
    recipe, targets = matrices.bake_recipe(INVENTORY, prepared, target, "humble", "linux/amd64", publish=publish,
                                           shared_common=False, common_cached=local, owner="example", source_sha="b" * 40, run_id="123")
    row = recipe["target"][target]
    assert targets == (["universe-common-build", "universe-common-devel", "universe-common"]
                       if publish and target == "universe-common" else [target])
    common_build = "ghcr.io/example/openadkit-buildcache:universe-common-build-amd64-humble-123-1"
    if publish:
        assert row["labels"]['"org.opencontainers.image.autoware-lock-sha256"'] == "e" * 64
        assert row["labels"]['"org.opencontainers.image.openadkit-sha"'] == "b" * 40
        assert row["cache-to"][0].endswith(",mode=max")
        assert (row["contexts"].get("autoware-base-cuda-devel") == uri) is (target == "sensing-perception-cuda")
        if target == "universe-common":
            # Per-build labels or provenance would change the compile base's
            # digest on every build and invalidate every component compile.
            build = recipe["target"]["universe-common-build"]
            assert build["tags"] == [common_build] and not build["labels"]
            assert build["attest"] == ["type=provenance,disabled=true"]
            # Nor may the build time: the config records it.
            assert build["args"]["SOURCE_DATE_EPOCH"] == matrices.COMPILE_BASE_EPOCH
            assert "SOURCE_DATE_EPOCH" not in row["args"]
            # The build and runtime stages keep separate caches; neither
            # export may overwrite the other.
            cache = "type=registry,ref=ghcr.io/example/openadkit-buildcache:{}-amd64-humble-main"
            assert build["cache-to"] == [cache.format("universe-common-build") + ",mode=max"]
            assert row["cache-to"] == [cache.format("universe-common") + ",mode=max"]
            assert "cache-to" not in recipe["target"]["universe-common-devel"]
            assert row["cache-from"] == [cache.format(name) for name in ("autoware-core-devel", "universe-common-build", "universe-common")]
        else:
            assert row["contexts"]["universe-common-devel"] == "docker-image://" + common_build
    else:
        assert not row["labels"] and "cache-to" not in row
        assert ("universe-common" in row["contexts"]) is (not local)
        assert ("simulator" in row["contexts"]) is (target == "carla-interface" and not local)


def test_development_recipe_compiles_core_on_the_pinned_base():
    uri = "docker-image://example/base@sha256:" + "c" * 64
    prepared = {"build_tag": "123-1", "cache_scope": "release-2.0", "autoware_input_ref": "main", "autoware_ref_type": "branch",
                "autoware_ref": "a" * 40, "autoware_base_version": "1.9.0", "autoware_lock_sha256": "e" * 64,
                "upstream_images": json.dumps({"humble": {name: {"uri": uri} for name in ("base", "base-cuda-runtime", "base-cuda-devel")}})}
    recipe, _ = matrices.bake_recipe(INVENTORY, prepared, "universe-common", "humble", "linux/amd64", publish=True,
                                     shared_common=False, common_cached=False, owner="example", source_sha="b" * 40, run_id="123")
    core = recipe["target"]["autoware-core-devel"]
    # HCL compiles core; the recipe pins its base and keeps per-build labels
    # off it, since it is the compile base's FROM.
    assert "autoware-core-devel" not in recipe["target"]["universe-common"]["contexts"]
    assert core["contexts"]["autoware-base"] == uri and not core["labels"]
    assert core["cache-to"] == ["type=registry,ref=ghcr.io/example/openadkit-buildcache:autoware-core-devel-amd64-humble-release-2.0,mode=max"]


def test_development_core_is_pushed_and_pinned_by_digest():
    uri = "docker-image://example/base@sha256:" + "c" * 64
    prepared = {"build_tag": "123-1", "cache_scope": "main", "autoware_input_ref": "a" * 40, "autoware_ref_type": "sha",
                "autoware_ref": "a" * 40, "autoware_base_version": "1.9.0", "autoware_lock_sha256": "e" * 64,
                "upstream_images": json.dumps({"humble": {name: {"uri": uri} for name in ("base", "base-cuda-runtime", "base-cuda-devel")}})}
    recipe, image = matrices.core_recipe(prepared, "humble", "linux/amd64", owner="example")
    core = recipe["target"]["autoware-core-devel"]
    assert image == "ghcr.io/example/openadkit-buildcache:autoware-core-devel-amd64-humble-123-1"
    # Nothing per build may reach the image universe-common starts from.
    assert core["tags"] == [image] and not core["labels"]
    assert core["args"] == {"ROS_DISTRO": "humble", "SOURCE_DATE_EPOCH": matrices.COMPILE_BASE_EPOCH}
    assert core["attest"] == ["type=provenance,disabled=true"] and core["contexts"]["autoware-base"] == uri
    assert core["cache-to"] == ["type=registry,ref=ghcr.io/example/openadkit-buildcache:autoware-core-devel-amd64-humble-main,mode=max"]

    pinned = image + "@sha256:" + "d" * 64
    recipe, _ = matrices.bake_recipe(INVENTORY, prepared, "universe-common", "humble", "linux/amd64", publish=True,
                                     shared_common=False, common_cached=False, owner="example", source_sha="b" * 40, run_id="123",
                                     core_devel=pinned)
    for name in ("universe-common-build", "universe-common-devel", "universe-common"):
        assert recipe["target"][name]["contexts"]["autoware-core-devel"] == "docker-image://" + pinned

    # Release builds start from the upstream core image.
    prepared["upstream_images"] = json.dumps({"humble": {name: {"uri": uri} for name in ("core-devel", "base")}})
    assert matrices.core_recipe(prepared, "humble", "linux/amd64", owner="example") is None


def test_lock_overlay_moves_repositories_to_development_versions(tmp_path):
    import export_autoware_lock
    source, overlay, lock = tmp_path / "a.repos", tmp_path / "b.repos", tmp_path / "lock.repos"
    source.write_text(f"repositories:\n  core/a:\n    type: git\n    url: https://x/a.git\n    version: {'1' * 40}\n"
                      f"  core/b:\n    type: git\n    url: https://x/b.git\n    version: {'2' * 40}\n")
    overlay.write_text(f"repositories:\n  core/b:\n    type: git\n    url: https://x/b.git\n    version: {'3' * 40}\n")
    export_autoware_lock.export_lock(source, lock, overlay)
    assert [line.split()[-1] for line in lock.read_text().splitlines() if "version" in line] == ['"' + "1" * 40 + '"', '"' + "3" * 40 + '"']


@pytest.mark.parametrize("path", ["components/universe-common/Dockerfile", "components/sensing-perception/Dockerfile.cuda"])
def test_stages_pin_ros_snapshot_and_runtime_checks_linked_libraries(path):
    text = (ROOT / path).read_text()
    devel, runtime = text.rsplit("\nFROM ", 1)
    pin = 'bash /tmp/ros-snapshot/ros-snapshot.sh "${ROS_SNAPSHOT}" --check'
    assert devel.index(pin) < devel.index("colcon build")
    assert runtime.index(pin) < runtime.index("bash /tmp/security-refresh.sh") < runtime.index("bash /tmp/check-linked-libs.sh") < runtime.index("COPY components/shared/entrypoint/")
    assert 'ENTRYPOINT ["/docker-entrypoint.sh", "/opt/openadkit/openadkit-hook.sh"]' in runtime


@pytest.fixture
def compose_context(tmp_path, monkeypatch):
    if shutil.which("docker") is None:
        pytest.skip("docker compose is required")
    # Keep Docker's own config: CI installs Compose v5 into ~/.docker/cli-plugins,
    # and without it Docker falls back to the runner's older plugin.
    monkeypatch.setenv("DOCKER_CONFIG", os.environ.get("DOCKER_CONFIG") or str(Path.home() / ".docker"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENADKIT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENADKIT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ZENOH_LISTEN", "tcp/127.0.0.1:7447")
    monkeypatch.setenv("ZENOH_PEER", "tcp/127.0.0.1:7447")
    monkeypatch.setenv("REMOTE_PASSWORD", "ci-validate")
    monkeypatch.delenv("OPENADKIT_KIT", raising=False)
    monkeypatch.delenv("OPENADKIT_DELEGATED", raising=False)
    return manifest.load_kit(ROOT)


@pytest.mark.parametrize(("name", "node", "present", "absent"), [
    ("scenario-simulation", None, {"scenario_simulator", "map", "mrm-state-relay"}, {"zenoh-bridge"}),
    ("scenario-simulation", "autoware", {"map", "zenoh-bridge", "mrm-state-relay"}, {"scenario_simulator"}),
    ("scenario-simulation", "scenario", {"scenario_simulator", "zenoh-bridge"}, {"map", "vehicle", "mrm-state-relay"}),
    ("carla-simulation", None, {"carla", "carla-interface", "map"}, {"zenoh-bridge"}),
    ("carla-simulation", "autoware", {"map", "zenoh-bridge"}, {"carla", "carla-interface"}),
    ("carla-simulation", "carla", {"carla", "carla-interface", "carla-map-loader", "zenoh-bridge"}, {"map", "vehicle"}),
])
def test_real_compose_preserves_single_and_split_graphs(compose_context, name, node, present, absent):
    deployment = manifest.get_deployment(ROOT, compose_context, name)
    selection = deployment.select(compose_context, "humble", False, node=node)
    result = compose.compose_capture(deployment, selection, ["config", "--format", "json"])
    services = json.loads(result.stdout)["services"]
    assert present <= services.keys() and not absent & services.keys()
    if node:
        bridge = services["zenoh-bridge"]
        assert "container_name" not in bridge
        assert bridge["environment"]["ROS_DOMAIN_ID"] == str(deployment.nodes[node]["rosDomainId"])
        mounts = {item["target"]: item["source"] for item in bridge["volumes"]}
        assert mounts["/config/zenoh.json5"] == str(deployment.directory / "config/zenoh.json5")
        assert mounts["/etc/cyclonedds/cyclonedds.xml"] == str(ROOT / "deployments/shared/cyclonedds.xml")
    if node in ("scenario", "carla"):
        assert set(services) == present
    if node == "scenario":
        assert "pid" not in services["scenario_simulator"]
    if name == "carla-simulation" and node == "autoware":
        assert "carla-interface" not in services["vehicle"].get("depends_on", {})


@pytest.mark.parametrize(("override", "rule"), [
    ("", None), ('  control:\n    command: ["true"]\n', "command"),
    ('  control:\n    volumes:\n      - ./config:/opt/autoware/config:ro\n', "internal-mount"),
])
def test_real_integrator_contract_checks_compiled_models(tmp_path, compose_context, override, rule):
    kit = tmp_path / "custom-kit"
    shutil.copytree(ROOT / "deployments/custom-kit", kit, ignore=shutil.ignore_patterns("build", "install", "log"))
    path = kit / "openadkit.json"
    document = json.loads(path.read_text())
    document["extends"] = str(ROOT)
    path.write_text(json.dumps(document))
    directory = kit
    # Documented site settings, used by the shared services and runtime.env.
    (directory / "config.env").write_text(
        "VEHICLE_ID=custom\nCYCLONEDDS_NETWORK_INTERFACE=eth0\nWEBSOCKIFY_BIND=0.0.0.0\nRVIZ_GPU=off\n"
    )
    with (directory / "docker-compose.yaml").open("a") as output:
        output.write(override)
    result = subprocess.run([str(ROOT / "openadkit"), "validate", "custom-kit", "--json"],
                            cwd=kit, env=dict(os.environ), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["overlayConformant"] is (rule is None)
    assert {warning["rule"] for warning in report["overlayWarnings"]} == ({rule} if rule else set())
    assert all(warning.get("service") != "acme-probe" for warning in report["overlayWarnings"])


@pytest.mark.parametrize("change", [None, "command", "typo"])
def test_kit_on_one_service_layer_owns_its_services_and_settings(tmp_path, compose_context, change):
    # An integrator kit: carla-simulation's Autoware side, with its own CARLA.
    kit = tmp_path / "kit"
    directory = kit / "deployments/world"
    directory.mkdir(parents=True)
    (kit / "openadkit.json").write_text(json.dumps({
        "schemaVersion": 2, "kind": "kit", "extends": str(ROOT),
        "deployments": {"world": {"path": "deployments/world"}}, "artifacts": {},
    }))
    (directory / "deployment.json").write_text(json.dumps({
        "schemaVersion": 2, "name": "world", "description": "Own simulator",
        "base": "carla-simulation", "compose": {"files": ["docker-compose.yaml"]},
    }))
    (directory / "config.env").write_text("TOWN=Town01\n" + ("VEHICLE_MODLE=typo\n" if change == "typo" else ""))
    override = '  control:\n    command: ["true"]\n' if change == "command" else ""
    (directory / "docker-compose.yaml").write_text(
        "include:\n  - ${OPENADKIT_BASE_DEPLOYMENT}/services.autoware.yaml\n"
        "services:\n" + override +
        "  carla:\n    image: busybox:1.36.1\n    command: [\"sleep\", \"${TOWN}\"]\n"
    )
    result = subprocess.run([str(ROOT / "openadkit"), "validate", "world", "--gpu", "--json"],
                            cwd=kit, env=dict(os.environ), text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    rules = {warning["rule"] for warning in json.loads(result.stdout)["overlayWarnings"]}
    # Its own carla service replaces nothing, and TOWN is set and read by the kit;
    # changing an inherited service or setting a variable nothing reads still warns.
    assert rules == {None: set(), "command": {"command"}, "typo": {"variable"}}[change]


@pytest.mark.parametrize("change", [None, "plain-read", "set-only"])
def test_kit_files_shared_by_deployments_and_host_reads_are_the_kits(tmp_path, compose_context, change):
    # An integrator kit: a world file two deployments include, one of which
    # takes nothing from the base and reads the desktop's DISPLAY.
    kit = tmp_path / "kit"
    (kit / "deployments/shared").mkdir(parents=True)
    (kit / "openadkit.json").write_text(json.dumps({
        "schemaVersion": 2, "kind": "kit", "extends": str(ROOT),
        "deployments": {"manual": {"path": "deployments/manual"}}, "artifacts": {},
    }))
    world = '  carla:\n    image: busybox:1.36.1\n    command: ["sleep", "${TOWN}"]\n'
    if change == "plain-read":
        world += '    environment:\n      SPAWN: ${SPAWNN}\n'
    (kit / "deployments/shared/world.yaml").write_text("services:\n" + world)
    directory = kit / "deployments/manual"
    directory.mkdir()
    (directory / "deployment.json").write_text(json.dumps({
        "schemaVersion": 2, "name": "manual", "description": "Drive by hand",
        "base": "carla-simulation", "compose": {"files": ["docker-compose.yaml"]},
    }))
    (directory / "config.env").write_text("TOWN=Town01\n" + ("CARLA_CPU=3\n" if change == "set-only" else ""))
    (directory / "docker-compose.yaml").write_text(
        "include:\n  - ../shared/world.yaml\n"
        "services:\n  manual:\n    image: busybox:1.36.1\n"
        "    environment:\n      DISPLAY: ${DISPLAY:?run from a desktop session}\n"
    )
    environment = dict(os.environ, DISPLAY=":1")
    result = subprocess.run([str(ROOT / "openadkit"), "validate", "manual", "--gpu", "--json"],
                            cwd=kit, env=environment, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    warnings = json.loads(result.stdout)["overlayWarnings"]
    # Its carla is its own (it includes no base file), TOWN is set and read by
    # the kit across its files, and DISPLAY is read from the host on purpose.
    assert [warning.get("variable") for warning in warnings] == {
        None: [], "plain-read": ["SPAWNN"], "set-only": ["CARLA_CPU"]}[change]


def test_centerpoint_models_mount_where_the_cli_installs_them(compose_context, tmp_path):
    import data
    (tmp_path / "config").mkdir()
    (tmp_path / "config/logging-simulation.env").write_text("DATA_PATH=/srv/autoware_data\n")
    deployment = manifest.get_deployment(ROOT, compose_context, "logging-simulation")
    selection = compose.resolve_settings(
        deployment, deployment.select(compose_context, "humble", True, require_gpu=False))
    resource = next(item for item in deployment.data if item["destinationEnv"] == "CENTERPOINT_DATA_PATH")
    result = compose.compose_capture(deployment, selection, ["config", "--format", "json"])
    mounts = {item["target"]: item["source"] for item in json.loads(result.stdout)["services"]["perception"]["volumes"]}
    assert mounts["/autoware_data"] == "/srv/autoware_data"
    assert mounts["/autoware_data/lidar_centerpoint"] == str(data.resolve_destination(resource, selection))
