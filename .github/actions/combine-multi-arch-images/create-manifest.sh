#!/usr/bin/env bash
# Create one image's multi-arch (or single-arch) manifest from per-arch tags.
# Fails (and creates nothing) if any required architecture is missing, so a
# degraded manifest is never published.
#
# Per-arch bake tags are OCI indexes: the linux/<arch> image plus BuildKit
# provenance attestations (platform unknown/unknown). Combining those tags
# verbatim copies attestations into the public tag and GHCR lists them as a
# third OS/Arch. This script selects only the linux/<arch> image digest.
#
# Required env: IMAGE TARGET ROS_DISTRO ARCHES BUILD_TAG
set -euo pipefail

: "${IMAGE:?IMAGE is required}"
: "${TARGET:?TARGET is required}"
: "${ROS_DISTRO:?ROS_DISTRO is required}"
: "${ARCHES:?ARCHES is required}"
: "${BUILD_TAG:?BUILD_TAG is required}"

command -v jq >/dev/null 2>&1 || {
  echo "::error::jq is required to select linux image digests" >&2
  exit 1
}

target_ref="${IMAGE}:${TARGET}-${ROS_DISTRO}-${BUILD_TAG}"

# Prints the linux/<arch> image digest for ref.
# Exit 0 on success, 2 if the tag is absent, 1 if present but has no linux image.
linux_image_digest() {
  local ref="$1" arch="$2" json digest
  if ! json=$(docker buildx imagetools inspect "${ref}" --format '{{json .}}'); then
    return 2
  fi
  digest=$(
    jq -er --arg arch "${arch}" '
      [
        .manifest.manifests[]?
        | select(.platform.os == "linux" and .platform.architecture == $arch)
        | .digest
      ]
      | unique
      | if length == 1 and (.[0] | test("^sha256:[0-9a-f]{64}$")) then .[0]
        else empty end
    ' <<<"${json}"
  ) && {
    printf '%s\n' "${digest}"
    return 0
  }
  # A raw image manifest has no index entries. Accept it only when its
  # config platform is linux/<arch>; the tag name is not evidence.
  digest=$(
    jq -er --arg arch "${arch}" '
      if ((.manifest.manifests // []) | length) == 0
         and (.manifest.digest | type == "string" and test("^sha256:[0-9a-f]{64}$"))
         and (
           (.image.os == "linux" and .image.architecture == $arch)
           or (
             .manifest.platform.os == "linux"
             and .manifest.platform.architecture == $arch
           )
         )
      then .manifest.digest
      else empty end
    ' <<<"${json}"
  ) && {
    printf '%s\n' "${digest}"
    return 0
  }
  return 1
}

read -ra arch_list <<< "${ARCHES}"
sources=()
missing=()
for arch in "${arch_list[@]}"; do
  ref="${IMAGE}:${TARGET}-${arch}-${ROS_DISTRO}-${BUILD_TAG}"
  status=0
  digest=$(linux_image_digest "${ref}" "${arch}") || status=$?
  if [ "${status}" -eq 2 ]; then
    missing+=("${arch}")
    continue
  fi
  if [ "${status}" -ne 0 ]; then
    echo "::error::Cannot create ${target_ref}: ${ref} has no linux/${arch} image manifest" >&2
    exit 1
  fi
  sources+=("${IMAGE}@${digest}")
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "::error::Cannot create ${target_ref}: missing architecture(s): ${missing[*]}"
  exit 1
fi

echo "Creating ${target_ref} from: ${sources[*]}"
docker buildx imagetools create -t "${target_ref}" "${sources[@]}"
echo "Created ${target_ref}"
