#!/usr/bin/env bash
# Regenerate ros2.repos: every ROS 2 Jazzy package that the Autoware tree in
# autoware/src depends on, with its dependencies, minus Autoware's own packages.
# The output does not depend on the host architecture, so run this natively.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
src="$(cd "${here}/../../autoware/src" && pwd)"

# The bash entrypoint keeps /opt/ros/jazzy unsourced. If it were sourced,
# "rosdep keys --ignore-src" would drop every ROS package the image installs.
docker run --rm --entrypoint bash -v "${src}:/src:ro" ros:jazzy-ros-base -c '
set -euo pipefail
apt-get update -qq >/dev/null
apt-get install -y -qq python3-rosinstall-generator >/dev/null 2>&1
rosdep update --rosdistro jazzy >/dev/null 2>&1
python3 - <<PY
import subprocess
from catkin_pkg.packages import find_packages
from rosdistro import get_cached_distribution, get_index, get_index_url

ws = sorted({p.name for p in find_packages("/src").values()})
keys = set(subprocess.run(
    ["rosdep", "keys", "--from-paths", "/src", "--ignore-src"],
    capture_output=True, text=True, check=True).stdout.split())
ros = set(get_cached_distribution(get_index(get_index_url()), "jazzy").release_packages)
# mimick_vendor: test-only, and Mimick has no riscv64 port.
# rmw_connextdds*: needs RTI Connext, which has no riscv64 build.
skip = ["mimick_vendor", "rmw_connextdds", "rmw_connextdds_common",
        "rti_connext_dds_cmake_module"]
subprocess.run(
    ["rosinstall_generator", "--rosdistro", "jazzy", "--deps", "--format", "repos",
     "--exclude", *ws, *skip, "--", "ros_base", "rmw_cyclonedds_cpp", *sorted(keys & ros)],
    check=True)
PY
' > "${here}/ros2.repos"

echo "$(grep -c '^  [^ ].*:$' "${here}/ros2.repos") packages in ${here}/ros2.repos"
