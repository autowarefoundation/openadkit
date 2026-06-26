#!/usr/bin/env bash
# Capture release provenance for images produced by build-all-images.
set -euo pipefail

: "${BUILD_TAG:?BUILD_TAG is required}"
: "${OPENADKIT_SHA:?OPENADKIT_SHA is required}"
: "${AUTOWARE_INPUT_REF:?AUTOWARE_INPUT_REF is required}"
: "${AUTOWARE_REF_TYPE:?AUTOWARE_REF_TYPE is required}"
: "${AUTOWARE_REF:?AUTOWARE_REF is required}"
: "${AUTOWARE_BASE_VERSION:?AUTOWARE_BASE_VERSION is required}"
: "${PREPARED_LOCK_SHA256:?PREPARED_LOCK_SHA256 is required}"
: "${SCAN_REQUESTED:?SCAN_REQUESTED is required}"
: "${COMMON:?COMMON is required}"
: "${COMPONENT:?COMPONENT is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required}"

mkdir -p build-metadata
autoware_lock_sha256=$(sha256sum build-metadata/autoware-lock.repos | cut -d ' ' -f1)
[ "${autoware_lock_sha256}" = "${PREPARED_LOCK_SHA256}" ] || {
  echo "Autoware lock SHA ${autoware_lock_sha256} does not match prepare output ${PREPARED_LOCK_SHA256}" >&2
  exit 1
}
image_inventory_sha256=$(sha256sum build-metadata/image-inventory.json | cut -d ' ' -f1)
images_file="build-metadata/images.json"
jq -n '[]' > "${images_file}"

add_image() {
  local repo="$1"
  local target="$2"
  local distro="$3"
  local ref="${repo}:${target}-${distro}-${BUILD_TAG}"
  local inspect_json digest platforms tmp

  inspect_json=$(docker buildx imagetools inspect "${ref}" --format '{{json .}}')
  digest=$(printf '%s' "${inspect_json}" | jq -r '.manifest.digest')
  platforms=$(
    printf '%s' "${inspect_json}" \
      | jq -c '[.manifest.manifests[] | select(.platform.os != "unknown") | "\(.platform.os)/\(.platform.architecture)"] | unique'
  )

  tmp=$(mktemp)
  jq \
    --arg repo "${repo}" \
    --arg target "${target}" \
    --arg distro "${distro}" \
    --arg ref "${ref}" \
    --arg digest "${digest}" \
    --argjson platforms "${platforms}" \
    '. + [{repo: $repo, target: $target, ros_distro: $distro, ref: $ref, digest: $digest, platforms: $platforms}]' \
    "${images_file}" > "${tmp}"
  mv "${tmp}" "${images_file}"
}

while IFS=$'\t' read -r repo_kind target distro; do
  if [ "${repo_kind}" = "common" ]; then
    repo="${COMMON}"
  elif [ "${repo_kind}" = "component" ]; then
    repo="${COMPONENT}"
  else
    echo "Unsupported image inventory repo kind: ${repo_kind}" >&2
    exit 1
  fi
  add_image "${repo}" "${target}" "${distro}"
done < <(jq -r '
  .ros_distros as $global |
  .images[] |
  ((.ros_distros // $global)[]) as $distro |
  [.repo, .target, $distro] |
  @tsv
' build-metadata/image-inventory.json)

jq -n \
  --arg build_tag "${BUILD_TAG}" \
  --arg run_id "${GITHUB_RUN_ID}" \
  --arg run_attempt "${GITHUB_RUN_ATTEMPT}" \
  --arg openadkit_sha "${OPENADKIT_SHA}" \
  --arg autoware_input_ref "${AUTOWARE_INPUT_REF}" \
  --arg autoware_ref_type "${AUTOWARE_REF_TYPE}" \
  --arg autoware_ref "${AUTOWARE_REF}" \
  --arg autoware_base_version "${AUTOWARE_BASE_VERSION}" \
  --arg autoware_lock_sha256 "${autoware_lock_sha256}" \
  --arg image_inventory_sha256 "${image_inventory_sha256}" \
  --argjson scan_requested "${SCAN_REQUESTED}" \
  --slurpfile images "${images_file}" \
  '{
    build_tag: $build_tag,
    run_id: $run_id,
    run_attempt: $run_attempt,
    openadkit_sha: $openadkit_sha,
    autoware_input_ref: $autoware_input_ref,
    autoware_ref_type: $autoware_ref_type,
    autoware_ref: $autoware_ref,
    autoware_base_version: $autoware_base_version,
    autoware_lock_sha256: $autoware_lock_sha256,
    image_inventory_sha256: $image_inventory_sha256,
    scan_requested: $scan_requested,
    images: $images[0]
  }' > build-metadata/build-metadata.json
