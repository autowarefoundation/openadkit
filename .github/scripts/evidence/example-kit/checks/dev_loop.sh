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
# New on every run: a retried cell starts from the kit the first attempt
# changed and built, so a fixed message would show without build and restart.
after="integrator overlay was rebuilt by run $(date +%s%N)"

sed -i -E "s/integrator overlay (is running|was rebuilt by run [0-9]+)/${after}/" "${source_file}"
grep -qF "\"${after}\"" "${source_file}"

"${cli}" build --ros-distro "${distro}"
# restart finds the running stack, and how it was started, from anywhere.
(cd / && "${cli}" restart)
# restart returns once the probe's healthcheck sees it publish again.
message=$("${cli}" shell api timeout 60 ros2 topic echo --once /acme/probe)
printf '%s\n' "${message}"
grep -qF "data: ${after}" <<<"${message}"
