#!/usr/bin/env bash
# Create one image's multi-arch (or single-arch) manifest from per-arch tags.
# Fails (and creates nothing) if any required architecture is missing, so a
# degraded manifest is never published.
#
# Required env: IMAGE TARGET ROS_DISTRO ARCHES BUILD_TAG
set -euo pipefail

: "${IMAGE:?IMAGE is required}"
: "${TARGET:?TARGET is required}"
: "${ROS_DISTRO:?ROS_DISTRO is required}"
: "${ARCHES:?ARCHES is required}"
: "${BUILD_TAG:?BUILD_TAG is required}"

target_ref="${IMAGE}:${TARGET}-${ROS_DISTRO}-${BUILD_TAG}"

read -ra arch_list <<< "${ARCHES}"
sources=()
missing=()
for arch in "${arch_list[@]}"; do
  ref="${IMAGE}:${TARGET}-${arch}-${ROS_DISTRO}-${BUILD_TAG}"
  if docker buildx imagetools inspect "${ref}" >/dev/null 2>&1; then
    sources+=("${ref}")
  else
    missing+=("${arch}")
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "::error::Cannot create ${target_ref}: missing architecture(s): ${missing[*]}"
  exit 1
fi

echo "Creating ${target_ref} from: ${sources[*]}"
docker buildx imagetools create -t "${target_ref}" "${sources[@]}"
echo "Created ${target_ref}"
