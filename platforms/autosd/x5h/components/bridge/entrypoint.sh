#!/usr/bin/env bash
# Adapted from autoware-safety-island's demo/bridge/entrypoint.sh, with the
# command-override check moved ahead of the bridge invocation: ros2 run
# domain_bridge blocks in the foreground for the life of the bridge, so a
# check placed after it (as in the original) would never run in practice.
# A command passed by the unit (e.g. `bash -lc 'ros2 topic list'` for
# debugging) therefore replaces the bridge entirely instead of running
# after it dies.
set -euo pipefail

# ROS 2's own setup.bash references unset variables (e.g.
# AMENT_TRACE_SETUP_FILES), so -u must be relaxed around sourcing it or
# every invocation of this entrypoint fails before the bridge even starts.
set +u
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source "/opt/autoware/setup.bash"
set -u

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

ros2 run domain_bridge domain_bridge \
    --wait-for-publisher false /autoware/bridge-config.yaml
