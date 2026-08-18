#!/usr/bin/env bash
# Mirrors autoware-safety-island's demo/bridge/entrypoint.sh. The trailing
# exec "$@" is deliberate: it lets a Quadlet unit override the command for
# debugging (e.g. `ros2 topic list`) without rebuilding the image.
set -euo pipefail

source "/opt/ros/${ROS_DISTRO}/setup.bash"
source "/opt/autoware/setup.bash"

ros2 run domain_bridge domain_bridge \
    --wait-for-publisher false /autoware/bridge-config.yaml

exec "$@"
