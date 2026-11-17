#!/usr/bin/env bash
# Resolve immutable registry contexts, falling back to local dependency builds.
set -euo pipefail

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
: "${TARGETS_JSON:?TARGETS_JSON is required}"
: "${IMAGE_REPO:?IMAGE_REPO is required}"
: "${AUTOWARE_INPUT_REF:?AUTOWARE_INPUT_REF is required}"
: "${AUTOWARE_REF_TYPE:?AUTOWARE_REF_TYPE is required}"
: "${AUTOWARE_REF:?AUTOWARE_REF is required}"
: "${AUTOWARE_VERSION:?AUTOWARE_VERSION is required}"
: "${AUTOWARE_LOCK_SHA256:?AUTOWARE_LOCK_SHA256 is required}"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=.github/scripts/registry_lookup.sh
# shellcheck disable=SC1091
source "${script_dir}/registry_lookup.sh"

resolve_registry_context() {
  local ref="$1"
  shift
  local metadata labels image_autoware_ref base_version lock_sha256
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
  image_autoware_ref=$(jq -r '.["org.autoware.openadkit.autoware-ref"] // empty' <<<"${labels}")
  base_version=$(jq -r '.["org.autoware.openadkit.autoware-version"] // empty' <<<"${labels}")
  lock_sha256=$(jq -r '.["org.autoware.openadkit.autoware-lock-sha256"] // empty' <<<"${labels}")
  openadkit_sha=$(jq -r '.["org.opencontainers.image.revision"] // empty' <<<"${labels}")
  if [ "${image_autoware_ref}" != "${AUTOWARE_REF}" ] \
    || [ "${base_version}" != "${AUTOWARE_VERSION}" ]; then
    echo "Registry context ${ref} was built from Autoware ${base_version} (${image_autoware_ref}); expected ${AUTOWARE_VERSION} (${AUTOWARE_REF})" >&2
    return 1
  fi
  if ! [[ "${lock_sha256}" =~ ^[0-9a-f]{64}$ ]] \
    || [ "${lock_sha256}" != "${AUTOWARE_LOCK_SHA256}" ]; then
    echo "Registry context ${ref} has Autoware lock ${lock_sha256:-missing}; expected ${AUTOWARE_LOCK_SHA256}" >&2
    return 1
  fi
  if ! [[ "${openadkit_sha}" =~ ^[0-9a-f]{40}$ ]] \
    || ! git cat-file -e "${openadkit_sha}^{commit}"; then
    echo "Registry context ${ref} has no reachable Open AD Kit source commit" >&2
    return 1
  fi
  if ! git diff --quiet "${openadkit_sha}" HEAD -- "$@"; then
    echo "Registry context ${ref} does not match the current Open AD Kit build inputs: $*" >&2
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
# What a cached base was built from: its build files, plus the Autoware
# checkout. export_autoware_lock.py resolves the dependency SHAs that vcs
# import bakes into the base, and setup-build-env imports the sources and
# applies the line's Autoware patches; a change to any of them must
# invalidate cached registry contexts.
base_inputs=(
  .dockerignore components/docker-bake.hcl components/shared components/universe-common
  .github/scripts/export_autoware_lock.py .github/actions/setup-build-env
  .github/scripts/autoware_patches.py .github/autoware-patches
)
use_local_common="${USE_LOCAL_COMMON:-false}"

if jq -e 'length > 0' <<<"${TARGETS_JSON}" >/dev/null && [ "${use_local_common}" != true ]; then
  devel_ref="${IMAGE_REPO}:universe-common-devel-amd64-${distro}"
  runtime_ref="${IMAGE_REPO}:universe-common-amd64-${distro}"
  if devel_context=$(resolve_registry_context "${devel_ref}" "${base_inputs[@]}") \
    && runtime_context=$(resolve_registry_context "${runtime_ref}" "${base_inputs[@]}"); then
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
