#!/usr/bin/env bash
# Build the Open AD Kit images for linux/riscv64.
#
# Usage: platforms/riscv64/build.sh [bake target or group ...]   (default: planning)
#
# Prepare autoware/ first, as in docs/development/build-from-source.md. The host
# needs qemu-user-static with binfmt support when it is not riscv64 itself.
set -euo pipefail

cd "$(dirname "$0")/../.."
here=platforms/riscv64
platform=linux/riscv64
export ROS_DISTRO=jazzy

# 1. ROS 2 Jazzy from source, in place of ros:jazzy-ros-base.
docker buildx build --platform "${platform}" --load \
  -f "${here}/ros-base.Dockerfile" -t openadkit-riscv64/ros:jazzy-ros-base .

# 2. Let the upstream acados role build its code generator from source.
#    The reverse check skips the patch when it is already applied.
patch="$(pwd)/${here}/autoware-acados.patch"
git -C autoware apply --reverse --check "${patch}" 2>/dev/null ||
  git -C autoware apply "${patch}"

# 3. Upstream Autoware base and core-devel, tagged autoware:<target>-jazzy.
(cd autoware && docker buildx bake --load \
  -f docker/docker-bake.hcl -f "../${here}/autoware-bake.hcl" \
  --set "*.platform=${platform}" base core-devel)

# 4. Open AD Kit images on top of the local Autoware images.
UPSTREAM_REPO=autoware UPSTREAM_TAG="" docker buildx bake --load \
  -f components/docker-bake.hcl --set "*.platform=${platform}" "${@:-planning}"
