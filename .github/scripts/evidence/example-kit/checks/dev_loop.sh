#!/usr/bin/env bash
# The development loop CI runs on this kit once its verify step passed, from
# the kit's directory: change the overlay package, build it, restart from
# another directory, and see the running stack publish the change.
#
# Usage: checks/dev_loop.sh <openadkit> <ros-distro>
set -euo pipefail

cli=${1:?usage: dev_loop.sh <openadkit> <ros-distro>}
distro=${2:?usage: dev_loop.sh <openadkit> <ros-distro>}
source_file=overlay_ws/src/acme_probe/src/probe.cpp
before="integrator overlay is running"
after="integrator overlay was rebuilt"

# A retried cell finds the change already made.
sed -i "s/${before}/${after}/" "${source_file}"
grep -qF "\"${after}\"" "${source_file}"

"${cli}" build --ros-distro "${distro}"
# restart finds the running stack, and how it was started, from anywhere.
(cd / && "${cli}" restart)
# restart returns once the probe's healthcheck sees it publish again.
message=$("${cli}" shell api timeout 60 ros2 topic echo --once /acme/probe)
printf '%s\n' "${message}"
grep -qF "data: ${after}" <<<"${message}"
