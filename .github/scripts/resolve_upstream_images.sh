#!/usr/bin/env bash
# Resolve upstream Autoware build contexts once and persist immutable refs.
# Optional filters narrow PR checks; release builds leave them unset.
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

distros=()
if [ -n "${UPSTREAM_ROS_DISTRO:-}" ]; then
  if ! jq -e --arg distro "${UPSTREAM_ROS_DISTRO}" \
    '.ros_distros | index($distro) != null' "${inventory}" >/dev/null; then
    echo "Unsupported upstream ROS distro: ${UPSTREAM_ROS_DISTRO}" >&2
    exit 1
  fi
  distros=("${UPSTREAM_ROS_DISTRO}")
else
  mapfile -t distros < <(jq -r '.ros_distros[]' "${inventory}")
fi

default_names=(core-devel base base-cuda-runtime base-cuda-devel)
names=()
if [[ -v UPSTREAM_IMAGE_NAMES ]]; then
  read -r -a names <<<"${UPSTREAM_IMAGE_NAMES}"
else
  names=("${default_names[@]}")
fi
for name in "${names[@]}"; do
  case " ${default_names[*]} " in
    *" ${name} "*) ;;
    *)
      echo "Unsupported upstream image name: ${name}" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$(dirname -- "${output}")"
: >"${tmp}"

for distro in "${distros[@]}"; do
  for name in "${names[@]}"; do
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
