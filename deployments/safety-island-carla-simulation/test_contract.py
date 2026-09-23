#!/usr/bin/env python3
"""Privilege-free closed-loop deployment checks. No running CARLA required."""

from __future__ import annotations

import sys
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
OVERLAY = ROOT / "overlay"

sys.path.insert(0, str(OVERLAY))
from patch_sensors_only import (  # noqa: E402
    APPLY,
    DISABLED,
    DESTROY_BLOCK,
    SPAWN_ANCHOR,
    main as patch_main,
    patch_destroy_leftover_egos,
    patch_sensors_only,
)

EXPECTED_INPUTS = {
    "vehicle/status/steering_status": "autoware_vehicle_msgs/msg/SteeringReport",
    "planning/trajectory": "autoware_planning_msgs/msg/Trajectory",
    "system/operation_mode/state": "autoware_adapi_v1_msgs/msg/OperationModeState",
    "localization/kinematic_state": "nav_msgs/msg/Odometry",
    "localization/acceleration": "geometry_msgs/msg/AccelWithCovarianceStamped",
}


def test_overlay_skips_apply() -> None:
    sample = (
        "            try:\n"
        "                ego_action = self.sensor()\n"
        "            except SensorReceivedNoData as e:\n"
        "                raise RuntimeError(e)\n"
        "            self.ego_actor.apply_control(ego_action)\n"
        "        if self.running:\n"
        "            CarlaDataProvider.get_world().tick()\n"
    )
    patched = patch_sensors_only(sample)
    assert APPLY not in patched
    assert DISABLED in patched
    assert "CarlaDataProvider.get_world().tick()" in patched
    assert patch_sensors_only(patched) == patched


def test_overlay_refuses_unknown_upstream() -> None:
    for text in ("# self.ego_actor.apply_control(ego_action)\n", "self.ego_actor.apply_control(other)\n"):
        try:
            patch_sensors_only(text)
        except ValueError:
            pass
        else:
            raise AssertionError("unrecognized CARLA actuator was silently accepted")
    try:
        patch_destroy_leftover_egos("upstream spawn method changed\n")
    except ValueError:
        pass
    else:
        raise AssertionError("missing CARLA spawn anchor was silently accepted")

    with TemporaryDirectory() as directory:
        source = Path(directory) / "autoware_carla_interface" / "carla_autoware.py"
        source.parent.mkdir()
        source.write_text("self.ego_actor.apply_control(other)\n")
        with patch.object(sys, "argv", ["patch_sensors_only.py", directory]), redirect_stderr(StringIO()):
            assert patch_main() == 1
        assert source.read_text() == "self.ego_actor.apply_control(other)\n"


def test_overlay_destroys_leftover_egos() -> None:
    sample = (
        "        CarlaDataProvider.set_client(client)\n"
        "        spawn_point, randomize = self._parse_spawn_point()\n"
        "        self.ego_actor = CarlaDataProvider.request_new_actor(\n"
        "            self.vehicle_type, spawn_point, self.agent_role_name, random_location=randomize\n"
        "        )\n"
    )
    patched = patch_destroy_leftover_egos(sample)
    assert DESTROY_BLOCK in patched
    assert SPAWN_ANCHOR in patched
    assert patched.index("actor.destroy()") < patched.index("request_new_actor")
    assert patch_destroy_leftover_egos(patched) == patched


def test_bridge_config_inputs() -> None:
    text = (ROOT / "bridge-config.yaml").read_text()
    assert "control/trajectory_follower/control_cmd" not in text
    assert "remap: planning/scenario_planning/trajectory" in text
    for topic, msg_type in EXPECTED_INPUTS.items():
        assert f"{topic}:" in text
        assert msg_type in text
        idx = text.index(topic)
        chunk = text[idx : idx + 280]
        assert "from_domain: 1" in chunk
        assert "to_domain: 2" in chunk
    assert "durability: transient_local" in text


def test_topics_matrix() -> None:
    text = (ROOT / "topics.yaml").read_text()
    assert "outputs: []" in text
    assert "remap: /planning/scenario_planning/trajectory" in text
    for topic, msg_type in EXPECTED_INPUTS.items():
        assert f"/{topic}" in text
        assert msg_type in text


def test_images_pinned() -> None:
    config = dict(
        line.split("=", 1) for line in (ROOT / "config.env").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for name in (
        "CARLA_CONTAINER_IMAGE", "CARLA_INTERFACE_IMAGE", "SENSING_PERCEPTION_GPU_IMAGE",
        "LOCALIZATION_MAPPING_IMAGE", "PLANNING_CONTROL_IMAGE", "VEHICLE_SYSTEM_IMAGE",
        "API_IMAGE", "VISUALIZER_IMAGE",
    ):
        assert "@sha256:" in config[name], name


def test_deployment_files_exist() -> None:
    assert (OVERLAY / "patch_sensors_only.py").is_file()
    assert (OVERLAY / "carla-interface-entrypoint.sh").is_file()
    assert (ROOT / "control.launch.xml").is_file()
    assert (ROOT / "bridge" / "Dockerfile").is_file()
    compose = (ROOT / "docker-compose.yaml").read_text()
    assert "safety-island-bridge:" in compose
    assert "./control.launch.xml:" in compose
    assert "./overlay/patch_sensors_only.py:" in compose
    assert "carla_autoware.py:" not in compose


def main() -> int:
    test_overlay_skips_apply()
    test_overlay_refuses_unknown_upstream()
    test_overlay_destroys_leftover_egos()
    test_bridge_config_inputs()
    test_topics_matrix()
    test_images_pinned()
    test_deployment_files_exist()
    print("closed-loop contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
