"""Focused guards for the runtime, documentation, and security fixes."""

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[3]
ZENOH = ROOT / "deployments" / "zenoh-bridge"


def test_install_macro_uses_exact_ref_and_checked_out_checksum(monkeypatch):
    ref = "1" * 40
    monkeypatch.setenv("OPENADKIT_INSTALL_REF", ref)
    spec = importlib.util.spec_from_file_location("docs_macros_test", ROOT / "docs/macros.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    checksum = hashlib.sha256((ROOT / "install.sh").read_bytes()).hexdigest()
    assert f"/{ref}/install.sh" in module.INSTALL_COMMAND
    assert checksum in module.INSTALL_COMMAND
    assert "/main/install.sh" not in module.INSTALL_COMMAND
    assert "sha256sum --check" in module.INSTALL_COMMAND
    assert module.INSTALL_COMMAND.endswith("install_openadkit")
    subprocess.run(
        ["bash", "-n"],
        input=module.INSTALL_COMMAND,
        check=True,
        text=True,
    )


def test_docs_action_pins_checked_out_installer_ref():
    action = (ROOT / ".github/actions/build-docs/action.yaml").read_text()
    assert "OPENADKIT_INSTALL_REF" in action
    assert "git rev-parse HEAD" in action


def test_dotenv_reader_does_not_execute_values_and_preserves_environment(tmp_path):
    marker = tmp_path / "executed"
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"MAP_PATH=$(touch {marker})\n")
    command = (
        f'source "{ZENOH / "common.sh"}"; '
        'unset MAP_PATH; '
        f'read_dotenv_value MAP_PATH "{dotenv}"'
    )
    result = subprocess.run(
        ["bash", "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip().startswith("$(touch ")
    assert not marker.exists()

    environment = os.environ.copy()
    environment["MAP_PATH"] = "/external/map"
    result = subprocess.run(
        ["bash", "-c", command.replace("unset MAP_PATH; ", "")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.stdout.strip() == "/external/map"
    assert not marker.exists()


def test_zenoh_uses_wall_time_and_defines_teleop_color():
    compose = (ZENOH / "docker-compose.yaml").read_text()
    bridge_config = (ZENOH / "config/zenoh-bridge-ros2dds.json5").read_text()
    common = (ZENOH / "common.sh").read_text()
    docs = (ROOT / "docs/deployment/zenoh-bridge/index.md").read_text()

    assert "use_sim_time:=false" in compose
    assert "USE_SIM_TIME=false" in compose
    assert '"/clock"' not in bridge_config
    assert "CYAN=" in common
    assert "/clock` is intentionally not routed" in docs


def test_runtime_commands_support_upstream_non_root_entrypoint():
    compose = (ROOT / "deployments/base/docker-compose.yaml").read_text()
    visualizer = (
        ROOT / "components/visualizer/etc/visualizer_entrypoint.sh"
    ).read_text()

    assert 'sudo -n sed -i "s/use_emergency_handling: true/' in compose
    assert 'set +u\nsource "/opt/ros/${ROS_DISTRO}/setup.bash"' in visualizer
    assert 'source "/opt/autoware/setup.bash"\nset -u' in visualizer


def test_runtime_images_use_lean_base_and_installed_package_manifests():
    bake = (ROOT / "components/docker-bake.hcl").read_text()
    common = (ROOT / "components/universe-common/Dockerfile").read_text()

    assert 'autoware-base       = upstream("base")' in bake
    assert 'autoware-core       = upstream("core")' not in bake
    assert "FROM ${BASE_IMAGE} AS universe-common" in common
    runtime = common.split("FROM ${BASE_IMAGE} AS universe-common", 1)[1]
    assert "autoware/src/**/package.xml" not in runtime
    assert '--skip-keys "${internal_packages}"' in runtime

    dockerfiles = [
        ROOT / "components/api/Dockerfile",
        ROOT / "components/localization-mapping/Dockerfile",
        ROOT / "components/planning-control/Dockerfile",
        ROOT / "components/sensing-perception/Dockerfile",
        ROOT / "components/sensing-perception/Dockerfile.cuda",
        ROOT / "components/simulator/Dockerfile",
        ROOT / "components/vehicle-system/Dockerfile",
        ROOT / "components/visualizer/Dockerfile",
    ]
    for dockerfile in dockerfiles:
        content = dockerfile.read_text()
        assert "rosdep install -y --from-paths /tmp /opt/autoware" not in content
        assert "rosdep install -y --from-paths /opt/autoware/*/share" in content
        assert '--skip-keys "${internal_packages}"' in content


def test_carla_bundle_build_fails_with_clear_message(tmp_path):
    launcher = (ROOT / "deployments/carla-simulation/start-carla-e2e-demo.sh").read_text()
    assert 'REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)' in launcher

    deployment = tmp_path / "deployments" / "carla-simulation"
    deployment.mkdir(parents=True)
    for name in ("start-carla-e2e-demo.sh", "carla-simulation.env"):
        shutil.copy2(ROOT / "deployments/carla-simulation" / name, deployment / name)

    result = subprocess.run(
        [str(deployment / "start-carla-e2e-demo.sh"), "--build", "--dry-run"],
        cwd=deployment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Cannot use --build" in result.stderr
    assert "release bundles" in result.stderr


def test_cloud_launcher_rejects_wildcard_zenoh_binding():
    environment = os.environ.copy()
    environment["ZENOH_ROUTER_BIND_IP"] = "0.0.0.0"
    result = subprocess.run(
        ["bash", "cloud.sh", "dry-run"],
        cwd=ZENOH,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode != 0
    assert "Refusing wildcard Zenoh binding" in result.stdout
    assert "no transport authentication or encryption" in result.stdout


def test_zenoh_example_env_and_scripts_do_not_source_dotenv():
    assert (ZENOH / ".env.example").is_file()
    assert "/deployments/zenoh-bridge/.env" in (ROOT / ".gitignore").read_text()
    for name in ("common.sh", "cloud.sh", "edge.sh"):
        script = (ZENOH / name).read_text()
        assert ". ./.env" not in script
        assert "source .env" not in script
