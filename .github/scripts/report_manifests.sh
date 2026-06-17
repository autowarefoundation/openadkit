#!/usr/bin/env bash
# Emit a per-image created/missing multi-arch manifest table (Markdown) to
# stdout. Reads registry truth, so it is correct regardless of which manifest
# legs ran. Required env: MANIFEST_MATRIX IMAGE_PREFIX_COMMON
# IMAGE_PREFIX_COMPONENT BUILD_TAG
set -euo pipefail
: "${MANIFEST_MATRIX:?}"
: "${IMAGE_PREFIX_COMMON:?}"
: "${IMAGE_PREFIX_COMPONENT:?}"
: "${BUILD_TAG:?}"

echo "## Multi-arch manifest report"
echo ""
echo "| Image | ROS distro | Status |"
echo "|-------|------------|--------|"

jq -c '.include[]' <<< "${MANIFEST_MATRIX}" | while read -r entry; do
  repo=$(jq -r '.repo' <<< "${entry}")
  target=$(jq -r '.target' <<< "${entry}")
  distro=$(jq -r '."ros-distro"' <<< "${entry}")
  if [ "${repo}" = "common" ]; then
    prefix="${IMAGE_PREFIX_COMMON}"
  else
    prefix="${IMAGE_PREFIX_COMPONENT}"
  fi
  ref="${prefix}:${target}-${distro}-${BUILD_TAG}"
  if docker buildx imagetools inspect "${ref}" >/dev/null 2>&1; then
    echo "| \`${target}\` | ${distro} | ✅ created |"
  else
    echo "| \`${target}\` | ${distro} | ❌ missing |"
  fi
done
