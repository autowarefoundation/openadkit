#!/usr/bin/env bash
set -euo pipefail

# Install the system packages the runtime tree's packages run with: their exec
# dependencies, never another Autoware package, which only builds from source.
# RViz and its plugins are skipped unless --with-visualization is given: only
# the visualizer runs them (install-packages.sh).
#
# Usage: runtime-deps.sh [--with-visualization] <autoware-src>

with_visualization=false
if [ "${1:-}" = --with-visualization ]; then
    with_visualization=true
    shift
fi
src=${1:?usage: runtime-deps.sh [--with-visualization] <autoware-src>}
: "${ROS_DISTRO:?ROS_DISTRO is required}"

apt-get update
# ROS setup scripts reference unset variables.
set +u
# shellcheck source=/dev/null
. "/opt/ros/${ROS_DISTRO}/setup.sh"
set -u
skip="$(colcon list --base-paths "${src}" --names-only | tr '\n' ' ')"
if [ "${with_visualization}" = false ]; then
    # Such as autoware_launch's rviz2, which it starts only when asked to.
    skip+=" $(grep -ohE '<(exec_)?depend[^>]*>[^<]*rviz[^<]*<' /opt/autoware/*/share/*/package.xml \
        | sed -E 's/.*>([^<]*)<$/\1/' | sort -u | tr '\n' ' ')"
fi
rosdep install -y --from-paths /opt/autoware/*/share \
    --dependency-types=exec --ignore-src --rosdistro "${ROS_DISTRO}" \
    --skip-keys "${skip}"
