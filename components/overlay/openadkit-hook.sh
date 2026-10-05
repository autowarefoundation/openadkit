#!/usr/bin/env bash
# Apply the integrator layer, then run the container command.
#
# Chained after the upstream /docker-entrypoint.sh, so ROS and Autoware are
# already sourced and this runs as the aw user. /tmp/openadkit is rebuilt on
# every start, so an override that was removed never lingers:
#   1. the integrator's overlay workspace, if mounted, is sourced on top of
#      Autoware;
#   2. overlay.py copies autoware_launch and every package with overrides into
#      /tmp/openadkit, merges the YAML overrides parameter by parameter and
#      links the selected vehicle description;
#   3. those copies go first on AMENT_PREFIX_PATH, so $(find-pkg-share) finds
#      the merged files. Launch arguments in our Compose files point at the
#      same stable paths.
# shellcheck disable=SC1090,SC1091
set -eo pipefail

# Images whose own entrypoint does not source ROS (the visualizer).
if [ -z "${AMENT_PREFIX_PATH:-}" ]; then
    source "/opt/ros/${ROS_DISTRO}/setup.bash"
    if [ -f /opt/autoware/setup.bash ]; then
        source /opt/autoware/setup.bash
    fi
fi

if [ -f /openadkit/overlay_ws/install/local_setup.bash ]; then
    source /openadkit/overlay_ws/install/local_setup.bash
fi

prefixes=$(python3 /opt/openadkit/overlay.py)
if [ -n "${prefixes}" ]; then
    export AMENT_PREFIX_PATH="${prefixes}:${AMENT_PREFIX_PATH}"
fi

exec "$@"
