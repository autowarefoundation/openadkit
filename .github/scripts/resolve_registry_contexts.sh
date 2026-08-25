#!/usr/bin/env bash
# Resolve immutable registry contexts, falling back to local dependency builds.
set -euo pipefail

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
: "${TARGETS_JSON:?TARGETS_JSON is required}"
: "${IMAGE_PREFIX_COMMON:?IMAGE_PREFIX_COMMON is required}"
: "${IMAGE_PREFIX_COMPONENT:?IMAGE_PREFIX_COMPONENT is required}"
: "${AUTOWARE_INPUT_REF:?AUTOWARE_INPUT_REF is required}"
: "${AUTOWARE_REF_TYPE:?AUTOWARE_REF_TYPE is required}"
: "${AUTOWARE_REF:?AUTOWARE_REF is required}"
: "${AUTOWARE_BASE_VERSION:?AUTOWARE_BASE_VERSION is required}"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=.github/scripts/registry_lookup.sh
# shellcheck disable=SC1091
source "${script_dir}/registry_lookup.sh"

resolve_registry_context() {
  local ref="$1"
  shift
  local metadata labels input_ref ref_type image_autoware_ref base_version
  local openadkit_sha digest rc
  if metadata=$(registry_inspect_json "${ref}"); then
    :
  else
    rc=$?
    if [ "${rc}" -eq 1 ]; then
      echo "Registry context ${ref} not found" >&2
      return 1
    fi
    echo "::error::Registry context ${ref} unavailable after retries" >&2
    return 2
  fi
  labels=$(jq '.image.config.Labels' <<<"${metadata}")
  input_ref=$(jq -r '.["org.opencontainers.image.autoware-input-ref"] // .["\"org.opencontainers.image.autoware-input-ref\""] // empty' <<<"${labels}")
  ref_type=$(jq -r '.["org.opencontainers.image.autoware-ref-type"] // .["\"org.opencontainers.image.autoware-ref-type\""] // empty' <<<"${labels}")
  image_autoware_ref=$(jq -r '.["org.opencontainers.image.autoware-ref"] // .["\"org.opencontainers.image.autoware-ref\""] // empty' <<<"${labels}")
  base_version=$(jq -r '.["org.opencontainers.image.autoware-base-version"] // .["\"org.opencontainers.image.autoware-base-version\""] // empty' <<<"${labels}")
  openadkit_sha=$(jq -r '.["org.opencontainers.image.openadkit-sha"] // .["\"org.opencontainers.image.openadkit-sha\""] // empty' <<<"${labels}")
  if [ "${image_autoware_ref}" != "${AUTOWARE_REF}" ] \
    || [ "${base_version}" != "${AUTOWARE_BASE_VERSION}" ]; then
    echo "Registry context ${ref} was built from ${ref_type}:${input_ref}@${image_autoware_ref} with base ${base_version}; expected Autoware ${AUTOWARE_REF} with base ${AUTOWARE_BASE_VERSION}" >&2
    return 1
  fi
  if ! [[ "${openadkit_sha}" =~ ^[0-9a-f]{40}$ ]] \
    || ! git cat-file -e "${openadkit_sha}^{commit}"; then
    echo "Registry context ${ref} has no reachable OpenADKit source commit" >&2
    return 1
  fi
  if ! git diff --quiet "${openadkit_sha}" HEAD -- "$@"; then
    echo "Registry context ${ref} does not match the current OpenADKit build inputs: $*" >&2
    return 1
  fi
  digest=$(jq -r '.manifest.digest // empty' <<<"${metadata}")
  if ! [[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Registry context ${ref} has no valid manifest digest" >&2
    return 1
  fi
  printf 'docker-image://%s@%s\n' "${ref}" "${digest}"
}

distro="${ROS_DISTRO:-humble}"
use_local_common="${USE_LOCAL_COMMON:-false}"
use_local_simulator="${USE_LOCAL_SIMULATOR:-false}"

if jq -e 'index("carla-interface") != null' <<<"${TARGETS_JSON}" >/dev/null \
  && [ "${use_local_simulator}" != true ]; then
  simulator_ref="${IMAGE_PREFIX_COMPONENT}:simulator-amd64-${distro}"
  # export_autoware_lock.py resolves the dependency SHAs that vcs import bakes
  # into the base, so a change to it must invalidate cached registry contexts.
  if simulator_context=$(resolve_registry_context "${simulator_ref}" \
    components/docker-bake.hcl components/runtime-cleanup.sh \
    components/universe-common components/simulator \
    .github/scripts/export_autoware_lock.py); then
    echo "simulator_context=${simulator_context}" >> "${GITHUB_OUTPUT}"
  else
    rc=$?
    if [ "${rc}" -eq 2 ]; then
      echo "::error::Registry context ${simulator_ref} unavailable; aborting" >&2
      exit 1
    fi
    echo "Falling back to a local simulator build" >&2
    use_local_simulator=true
  fi
fi

common_required=false
if [ "${use_local_simulator}" = true ] \
  || jq -e 'map(select(. != "carla-interface")) | length > 0' <<<"${TARGETS_JSON}" >/dev/null; then
  common_required=true
fi
if [ "${common_required}" = true ] && [ "${use_local_common}" != true ]; then
  devel_ref="${IMAGE_PREFIX_COMMON}:universe-common-devel-amd64-${distro}"
  runtime_ref="${IMAGE_PREFIX_COMMON}:universe-common-amd64-${distro}"
  if devel_context=$(resolve_registry_context "${devel_ref}" \
    components/docker-bake.hcl components/runtime-cleanup.sh \
    components/universe-common \
    .github/scripts/export_autoware_lock.py) \
    && runtime_context=$(resolve_registry_context "${runtime_ref}" \
      components/docker-bake.hcl components/runtime-cleanup.sh \
      components/universe-common \
      .github/scripts/export_autoware_lock.py); then
    echo "devel_context=${devel_context}" >> "${GITHUB_OUTPUT}"
    echo "runtime_context=${runtime_context}" >> "${GITHUB_OUTPUT}"
  else
    rc=$?
    if [ "${rc}" -eq 2 ]; then
      echo "::error::Registry contexts ${devel_ref}/${runtime_ref} unavailable; aborting" >&2
      exit 1
    fi
    echo "Falling back to local universe-common builds" >&2
    use_local_common=true
  fi
fi

echo "use_local_common=${use_local_common}" >> "${GITHUB_OUTPUT}"
echo "use_local_simulator=${use_local_simulator}" >> "${GITHUB_OUTPUT}"
