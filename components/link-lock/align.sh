#!/usr/bin/env bash
set -euo pipefail

# Align the ROS packages the compiled tree links against with the current apt
# feed and rebuild when any of them moved.
#
# Runs at the end of a devel stage, after its last dependency install, so the
# lock reflects the final environment of the tree: record -> upgrade -> record
# -> rebuild only when something moved -> write the final lock. The rebuild
# reuses the base paths the first colcon pass recorded in
# /opt/openadkit/colcon-base-paths, so this step re-runs cheaply on every build
# and the expensive first compile stays cached until a linked package actually
# moves. See README.md.

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
lock=${LINK_LOCK:-/opt/openadkit/link-lock.txt}
base_paths=/opt/openadkit/colcon-base-paths
before=$(mktemp)
after=$(mktemp)
trap 'rm -f "${before}" "${after}"' EXIT

[ -f "${base_paths}" ] || {
    echo "missing ${base_paths}; the first colcon pass must record its base paths" >&2
    exit 1
}

bash "${script_dir}/lock.sh" record "${before}"
bash "${script_dir}/lock.sh" upgrade --lock "${before}"
bash "${script_dir}/lock.sh" record "${after}"

if cmp -s "${before}" "${after}"; then
    echo "ros align: linked packages already current"
else
    echo "ros align: linked packages moved; rebuilding"
    diff -u "${before}" "${after}" || true

    mapfile -t paths < "${base_paths}"
    # ROS setup scripts reference variables that may be unset, which `set -u`
    # rejects (e.g. AMENT_TRACE_SETUP_FILES); relax it while sourcing.
    set +u
    # shellcheck source=/dev/null
    . "/opt/ros/${ROS_DISTRO}/setup.sh"
    # shellcheck source=/dev/null
    . /opt/autoware/setup.sh
    set -u
    colcon build \
        --base-paths "${paths[@]}" \
        --install-base /opt/autoware \
        --cmake-args -DCMAKE_BUILD_TYPE=Release
    rm -rf build log
    # The rebuilt tree can link a different set; record it, not the pre-rebuild one.
    bash "${script_dir}/lock.sh" record "${after}"
fi

mkdir -p "$(dirname "${lock}")"
cp "${after}" "${lock}"