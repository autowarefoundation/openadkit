#!/usr/bin/env bash
# The entrypoint of every Open AD Kit image.
#
# Started as root, it gives the aw user the host user's ids (HOST_UID and
# HOST_GID, which the CLI sets), so what the services write to mounted host
# directories belongs to that user, and runs itself again as aw. As aw it
# applies the config overrides and the overlay workspace, then runs the
# container command.
# /tmp/openadkit is rebuilt on every start, so an override that was removed
# never lingers:
#   1. ROS, Autoware and the kit's overlay workspace, if mounted, are sourced;
#   2. overlay.py copies autoware_launch and every package with overrides into
#      /tmp/openadkit, merges the YAML overrides parameter by parameter and
#      links the selected vehicle description;
#   3. those copies go first on AMENT_PREFIX_PATH, so $(find-pkg-share) finds
#      the merged files. Launch arguments in our Compose files point at the
#      same stable paths.
# The command then runs with the launch option of health/ on PYTHONPATH, which
# records a node that dies for the service's healthcheck.
# shellcheck disable=SC1090,SC1091
set -eo pipefail

user="${USERNAME:-aw}"
if [ "$(id -u)" = 0 ]; then
    if [ -n "${HOST_UID:-}" ] && [ -n "${HOST_GID:-}" ]; then
        # -o: the host ids may already exist in the image, such as gid 100 (users).
        [ "$(id -g "${user}")" = "${HOST_GID}" ] || groupmod -o -g "${HOST_GID}" "${user}"
        [ "$(id -u "${user}")" = "${HOST_UID}" ] || usermod -o -u "${HOST_UID}" "${user}"
    fi
    exec gosu "${user}" "$0" "$@"
fi

source "/opt/ros/${ROS_DISTRO}/setup.bash"
if [ -f /opt/autoware/setup.bash ]; then
    source /opt/autoware/setup.bash
fi
if [ -f /openadkit/overlay_ws/install/local_setup.bash ]; then
    source /openadkit/overlay_ws/install/local_setup.bash
fi

prefixes=$(python3 /opt/openadkit/overlay.py)
if [ -n "${prefixes}" ]; then
    export AMENT_PREFIX_PATH="${prefixes}:${AMENT_PREFIX_PATH}"
fi

export PYTHONPATH="/opt/openadkit/health${PYTHONPATH:+:${PYTHONPATH}}"

exec "$@"
