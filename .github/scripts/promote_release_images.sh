#!/usr/bin/env bash
# Promote validated build image digests to release tags and stable aliases.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=.github/scripts/registry_lookup.sh
source "${script_dir}/registry_lookup.sh"
# shellcheck source=.github/scripts/stable_alias_policy.sh
source "${script_dir}/stable_alias_policy.sh"

: "${VERSION:?VERSION is required}"
: "${DEFAULT_ROS_DISTRO:?DEFAULT_ROS_DISTRO is required}"
: "${PUBLISH_LATEST_ALIASES:?PUBLISH_LATEST_ALIASES is required}"
: "${STABLE_RELEASE:?STABLE_RELEASE is required}"

stable_release="${STABLE_RELEASE}"

# Record converged refs for the summary. Any failed promotion aborts immediately
# so a later alias phase cannot expose a partially tagged release.
PROMOTED_REFS=()

available_distros=$(jq -r '.images | unique_by(.ros_distro) | map(.ros_distro) | join(" ")' release-input/build/build-metadata.json)
echo "Available ROS distros in build: ${available_distros}"

if ! echo "${available_distros}" | grep -qw "${DEFAULT_ROS_DISTRO}"; then
  echo "ERROR: default_ros_distro '${DEFAULT_ROS_DISTRO}' is not in the build metadata." >&2
  echo "Available distros: ${available_distros}" >&2
  echo "Update the 'default_ros_distro' input or trigger a new build for '${DEFAULT_ROS_DISTRO}'." >&2
  exit 1
fi

promote_tag() {
  local ref="$1"
  local repo="$2"
  local digest="$3"
  local mode="$4"
  local existing_digest lookup_status=0

  existing_digest=$(registry_manifest_digest "${ref}") || lookup_status=$?
  if [ "${lookup_status}" -eq 0 ]; then
    if [ "${existing_digest}" = "${digest}" ]; then
      echo "${ref} already points to ${digest}; skipping"
      PROMOTED_REFS+=("${ref}")
      return
    fi
    if [ "${mode}" = "immutable" ]; then
      echo "Release tag conflict: ${ref} points to ${existing_digest}, expected ${digest}" >&2
      exit 1
    fi
    echo "Updating ${ref}: ${existing_digest} -> ${digest}"
  elif [ "${lookup_status}" -eq 1 ]; then
    echo "Promoting ${repo}@${digest} -> ${ref}"
  else
    return "${lookup_status}"
  fi

  # Retry the mutating create, then confirm the alias actually resolves to the
  # intended digest before treating it as promoted. A timeout, rate limit, or
  # transient network failure on a single alias no longer leaves the release
  # split across old and new digests unnoticed.
  local attempt result_digest result_status
  for attempt in 1 2 3; do
    if docker buildx imagetools create -t "${ref}" "${repo}@${digest}"; then
      result_status=0
      result_digest=$(registry_manifest_digest "${ref}") || result_status=$?
      if [ "${result_status}" -eq 0 ] && [ "${result_digest}" = "${digest}" ]; then
        PROMOTED_REFS+=("${ref}")
        return 0
      fi
      echo "Post-promote verification for ${ref} did not match on attempt ${attempt}: got '${result_digest:-<none>}', want '${digest}'" >&2
    else
      echo "imagetools create for ${ref} failed on attempt ${attempt}" >&2
    fi
    if [ "${attempt}" -lt 3 ]; then
      sleep "$(( attempt * 5 ))"
    fi
  done

  echo "ERROR: ${ref} did not converge to ${digest} after retries" >&2
  return 1
}

while IFS=$'\t' read -r repo target distro digest; do
  release_ref="${repo}:${target}-${distro}-${VERSION}"
  promote_tag "${release_ref}" "${repo}" "${digest}" immutable
done < <(jq -r '.images[] | [.repo, .target, .ros_distro, .digest] | @tsv' release-input/build/build-metadata.json)

if [ "${stable_release}" = true ]; then
  current_policy=$(current_latest_alias_policy)
  if [ "${current_policy}" != "${PUBLISH_LATEST_ALIASES}" ]; then
    echo "Latest alias policy changed during release: expected ${PUBLISH_LATEST_ALIASES}, now ${current_policy}; rerun the release workflow" >&2
    exit 1
  fi
fi

if [ "${stable_release}" = true ] && [ "${PUBLISH_LATEST_ALIASES}" = true ]; then
  while IFS=$'\t' read -r repo target distro digest; do
    promote_tag "${repo}:${target}-${distro}" "${repo}" "${digest}" alias
    promote_tag "${repo}:${target}-${distro}-latest" "${repo}" "${digest}" alias

    if [ "${distro}" = "${DEFAULT_ROS_DISTRO}" ]; then
      promote_tag "${repo}:${target}" "${repo}" "${digest}" alias
      promote_tag "${repo}:${target}-latest" "${repo}" "${digest}" alias
    fi
  done < <(jq -r '.images[] | [.repo, .target, .ros_distro, .digest] | @tsv' release-input/build/build-metadata.json)
fi

echo "Alias promotion summary: ${#PROMOTED_REFS[@]} converged."
