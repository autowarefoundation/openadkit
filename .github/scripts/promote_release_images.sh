#!/usr/bin/env bash
# Promote validated build image digests to release tags and stable aliases.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=.github/scripts/registry_lookup.sh
source "${script_dir}/registry_lookup.sh"
# shellcheck source=.github/scripts/stable_alias_policy.sh
source "${script_dir}/stable_alias_policy.sh"

plan_file=${RELEASE_PLAN_FILE:-release-plan.json}
jq -e '
  .schemaVersion == 1 and
  (.release.version | type == "string") and
  (.release.defaultRosDistro | IN("humble", "jazzy")) and
  (.release.stable | type == "boolean") and
  (.release.publishLatestAliases | type == "boolean") and
  (.images | type == "array" and length > 0)
' "${plan_file}" >/dev/null
VERSION=$(jq -r '.release.version' "${plan_file}")
DEFAULT_ROS_DISTRO=$(jq -r '.release.defaultRosDistro' "${plan_file}")
PUBLISH_LATEST_ALIASES=$(jq -r '.release.publishLatestAliases' "${plan_file}")
STABLE_RELEASE=$(jq -r '.release.stable' "${plan_file}")

stable_release="${STABLE_RELEASE}"

# Record converged refs for the summary. Immutable version tags abort immediately.
# Alias updates continue after a single failure so a rerun can finish leftovers.
PROMOTED_REFS=()

available_distros=$(jq -r '.images | unique_by(.rosDistro) | map(.rosDistro) | join(" ")' "${plan_file}")
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

preflight_images() {
  local conflicts=0 source_ref release_ref digest source_digest existing_digest lookup_status
  while IFS=$'\t' read -r source_ref release_ref digest; do
    lookup_status=0
    source_digest=$(registry_manifest_digest "${source_ref}") || lookup_status=$?
    if [ "${lookup_status}" -eq 1 ]; then
      echo "Source image not found: ${source_ref}" >&2
      conflicts=1
    elif [ "${lookup_status}" -ne 0 ]; then
      return "${lookup_status}"
    elif [ "${source_digest}" != "${digest}" ]; then
      echo "Source digest mismatch for ${source_ref}: ${source_digest} != ${digest}" >&2
      conflicts=1
    fi

    lookup_status=0
    existing_digest=$(registry_manifest_digest "${release_ref}") || lookup_status=$?
    if [ "${lookup_status}" -eq 0 ] && [ "${existing_digest}" != "${digest}" ]; then
      echo "Release tag conflict: ${release_ref} points to ${existing_digest}, expected ${digest}" >&2
      conflicts=1
    elif [ "${lookup_status}" -ne 0 ] && [ "${lookup_status}" -ne 1 ]; then
      return "${lookup_status}"
    fi
  done < <(jq -r '.images[] | [.sourceRef, .releaseRef, .digest] | @tsv' "${plan_file}")
  [ "${conflicts}" -eq 0 ]
}

check_alias_policy() {
  local current_policy
  [ "${stable_release}" = true ] || return 0
  current_policy=$(current_latest_alias_policy)
  if [ "${current_policy}" != "${PUBLISH_LATEST_ALIASES}" ]; then
    echo "Latest alias policy changed during release: expected ${PUBLISH_LATEST_ALIASES}, now ${current_policy}; rerun the release workflow" >&2
    return 1
  fi
}

preflight_aliases() {
  local alias lookup_status existing_digest
  while IFS= read -r alias; do
    [ -n "${alias}" ] || continue
    lookup_status=0
    existing_digest=$(registry_manifest_digest "${alias}") || lookup_status=$?
    if [ "${lookup_status}" -ne 0 ] && [ "${lookup_status}" -ne 1 ]; then
      return "${lookup_status}"
    fi
  done < <(jq -r '.images[].aliases[]?' "${plan_file}")
}

check_alias_policy
preflight_images
preflight_aliases

while IFS=$'\t' read -r release_ref repo digest; do
  promote_tag "${release_ref}" "${repo}" "${digest}" immutable
done < <(jq -r '.images[] | [.releaseRef, .repo, .digest] | @tsv' "${plan_file}")

check_alias_policy

failed_aliases=()
if [ "${stable_release}" = true ] && [ "${PUBLISH_LATEST_ALIASES}" = true ]; then
  while IFS=$'\t' read -r alias repo digest; do
    [ -n "${alias}" ] || continue
    if ! promote_tag "${alias}" "${repo}" "${digest}" alias; then
      failed_aliases+=("${alias}")
    fi
  done < <(jq -r '.images[] | .repo as $repo | .digest as $digest | .aliases[] | [., $repo, $digest] | @tsv' "${plan_file}")
fi

echo "Alias promotion summary: ${#PROMOTED_REFS[@]} converged."
if [ "${#failed_aliases[@]}" -ne 0 ]; then
  echo "Alias promotion incomplete. Converged refs: ${PROMOTED_REFS[*]:-<none>}" >&2
  echo "Unconverged aliases: ${failed_aliases[*]}" >&2
  echo "Rerun the release workflow to finish remaining aliases." >&2
  exit 1
fi
