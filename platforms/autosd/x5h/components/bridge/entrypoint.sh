#!/usr/bin/env bash
# Entrypoint for the domain_bridge container built by the Dockerfile beside
# this file: source the ROS 2 and Autoware overlays, then run the bridge over
# /autoware/bridge-config.yaml -- the conventional shape for a domain_bridge
# container, and reconstructible from the domain_bridge package's own
# documentation plus the topic map in bridge-config.yaml beside this file.
#
# One deliberate departure from that conventional shape: the
# command-override check sits AHEAD of the bridge invocation, not after it.
# `ros2 run domain_bridge` blocks in the foreground for the life of the
# bridge, so a check placed after it could only ever run once the bridge had
# already died. Putting it first means a command passed by the unit (e.g.
# `bash -lc 'ros2 topic list'` for debugging) replaces the bridge, which is
# what an override is for.
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
