#!/usr/bin/env bash
# Build the overlay workspace (extension point 3) in the devel image of the
# Open AD Kit this kit extends, so it links against the same packages the
# runtime images ship. The CLI mounts overlay_ws/install into every Autoware
# service, and the entrypoint hook sources it on top of Autoware.
#
# Usage: overlay_ws/build.sh [ros-distro]   (DEVEL_IMAGE overrides the image)
set -euo pipefail

distro=${1:-humble}
case "$(uname -m)" in
    x86_64 | amd64) arch=amd64 ;;
    aarch64 | arm64) arch=arm64 ;;
    *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac
image=${DEVEL_IMAGE:-ghcr.io/autowarefoundation/openadkit-common:universe-common-devel-${arch}-${distro}}
workspace=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

docker run --rm \
    --user "$(id -u):$(id -g)" \
    --env HOME=/tmp \
    --volume "${workspace}:/overlay_ws" \
    --workdir /overlay_ws \
    --entrypoint bash \
    "${image}" -c '
        source "/opt/ros/${ROS_DISTRO}/setup.bash"
        source /opt/autoware/setup.bash
        colcon build --install-base install --cmake-args -DCMAKE_BUILD_TYPE=Release
    '
