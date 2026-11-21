#!/usr/bin/env bash
set -euo pipefail

# Install the named launch and config packages of autoware_launch's
# autoware_universe_launch tree into /opt/autoware, for the components this
# image runs. They install files and compile nothing, so they build in their
# own layer after the component's compile layer. colcon skips an unknown
# package silently, so fail when one was not installed.
#
# Usage: launch-packages.sh <package>...

: "${ROS_DISTRO:?ROS_DISTRO is required}"
# ROS setup scripts reference unset variables.
set +u
# shellcheck source=/dev/null
. "/opt/ros/${ROS_DISTRO}/setup.sh"
# shellcheck source=/dev/null
. /opt/autoware/setup.sh
set -u

colcon build \
    --base-paths /tmp/autoware/src/launcher/autoware_launch/autoware_universe_launch \
    --packages-select "$@" \
    --install-base /opt/autoware
rm -rf build log
for package in "$@"; do
    [ -d "/opt/autoware/${package}" ] || { echo "launch package not installed: ${package}" >&2; exit 1; }
done
