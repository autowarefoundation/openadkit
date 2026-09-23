#!/usr/bin/env bash
set -euo pipefail

source "/opt/ros/$ROS_DISTRO/setup.bash"
source "/opt/autoware/setup.bash"

ros2 run domain_bridge domain_bridge --wait-for-publisher false /autoware/bridge-config.yaml
