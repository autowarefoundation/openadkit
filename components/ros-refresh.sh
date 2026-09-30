#!/usr/bin/env bash
set -euo pipefail

# Keep the ROS packages our compiled tree links against in step between the
# devel and runtime stages of a build.
#
# `upgrade` runs in a devel stage after the first colcon pass: it upgrades
# every package in the link lock to the current apt candidate. The caller
# regenerates the lock and rebuilds when anything moved.
#
# `install` runs in the matching runtime stage: it installs the exact versions
# recorded in the lock, so the runtime cannot drift from the compile
# environment (07-testler.md: diagnostic_updater 4.2.6 vs 4.2.7).
#
# Usage: ros-refresh.sh upgrade|install --lock <file>

action="${1:?usage: ros-refresh.sh upgrade|install --lock <file>}"
shift

lock=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --lock)
            lock="${2:?--lock needs a file}"
            shift 2
            ;;
        *)
            echo "unknown argument: $1" >&2
            exit 2
            ;;
    esac
done
[ -n "${lock}" ] || { echo "--lock is required" >&2; exit 2; }
[ -f "${lock}" ] || { echo "lock file not found: ${lock}" >&2; exit 1; }

entries=()
while IFS= read -r line; do
    line="${line%%#*}"
    line="$(printf '%s' "${line}" | xargs)"
    [ -n "${line}" ] || continue
    entries+=("${line}")
done < "${lock}"
[ "${#entries[@]}" -gt 0 ] || exit 0

apt-get update
case "${action}" in
    upgrade)
        packages=()
        for entry in "${entries[@]}"; do
            packages+=("${entry%%=*}")
        done
        echo "ros refresh: upgrading ${#packages[@]} linked packages"
        DEBIAN_FRONTEND=noninteractive \
            apt-get install -y --no-install-recommends "${packages[@]}"
        ;;
    install)
        echo "ros refresh: installing ${#entries[@]} locked packages"
        DEBIAN_FRONTEND=noninteractive \
            apt-get install -y --no-install-recommends --allow-downgrades "${entries[@]}"
        ;;
    *)
        echo "unknown action '${action}'" >&2
        exit 2
        ;;
esac