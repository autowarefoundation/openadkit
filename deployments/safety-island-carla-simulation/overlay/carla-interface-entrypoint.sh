#!/usr/bin/env bash
set -euo pipefail
python3 /autoware_config/patch_sensors_only.py
exec ros2 launch autoware_carla_interface autoware_carla_interface.launch.xml "$@"
