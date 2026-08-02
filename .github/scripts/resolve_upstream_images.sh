#!/usr/bin/env bash
# Resolve every upstream Autoware build context once and persist immutable refs.
set -euo pipefail

: "${AUTOWARE_BASE_VERSION:?AUTOWARE_BASE_VERSION is required}"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=.github/scripts/registry_lookup.sh
# shellcheck disable=SC1091
source "${script_dir}/registry_lookup.sh"

inventory="${IMAGE_INVENTORY:-.github/image-inventory.json}"
output="${UPSTREAM_IMAGES_OUTPUT:-upstream-images/upstream-images.json}"
repo="${UPSTREAM_REPO:-ghcr.io/autowarefoundation/autoware}"
tmp=$(mktemp)
trap 'rm -f "${tmp}"' EXIT

mkdir -p "$(dirname -- "${output}")"
: >"${tmp}"

for distro in $(jq -r '.ros_distros[]' "${inventory}"); do
  for name in core-devel base base-cuda-runtime base-cuda-devel; do
    ref="${repo}:${name}-${distro}-${AUTOWARE_BASE_VERSION}"
    digest=$(registry_manifest_digest "${ref}")
    jq -n \
      --arg name "${name}" \
      --arg distro "${distro}" \
      --arg ref "${ref}" \
      --arg digest "${digest}" \
      '{name: $name, ros_distro: $distro, ref: $ref, digest: $digest, uri: ("docker-image://" + $ref + "@" + $digest)}' \
      >>"${tmp}"
  done
done

jq -s 'sort_by(.ros_distro, .name)' "${tmp}" >"${output}"
