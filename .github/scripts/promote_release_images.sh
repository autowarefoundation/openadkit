#!/usr/bin/env bash
# Promote validated build image digests to release tags and stable aliases.
set -euo pipefail

: "${VERSION:?VERSION is required}"
: "${DEFAULT_ROS_DISTRO:?DEFAULT_ROS_DISTRO is required}"
: "${PUBLISH_LATEST_ALIASES:?PUBLISH_LATEST_ALIASES is required}"
: "${STABLE_RELEASE:?STABLE_RELEASE is required}"

stable_release="${STABLE_RELEASE:-false}"

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
  local existing_json existing_digest

  if existing_json=$(docker buildx imagetools inspect "${ref}" --format '{{json .}}' 2>/dev/null); then
    existing_digest=$(printf '%s' "${existing_json}" | jq -r '.manifest.digest')
    if [ "${existing_digest}" = "${digest}" ]; then
      echo "${ref} already points to ${digest}; skipping"
      return
    fi
    if [ "${mode}" = "immutable" ]; then
      echo "Release tag conflict: ${ref} points to ${existing_digest}, expected ${digest}" >&2
      exit 1
    fi
    echo "Updating ${ref}: ${existing_digest} -> ${digest}"
  else
    echo "Promoting ${repo}@${digest} -> ${ref}"
  fi

  docker buildx imagetools create -t "${ref}" "${repo}@${digest}"
}

while IFS=$'\t' read -r repo target distro digest; do
  release_ref="${repo}:${target}-${distro}-${VERSION}"
  promote_tag "${release_ref}" "${repo}" "${digest}" immutable

  if [ "${stable_release}" = "true" ] && [ "${PUBLISH_LATEST_ALIASES}" = "true" ]; then
    promote_tag "${repo}:${target}-${distro}" "${repo}" "${digest}" alias
    promote_tag "${repo}:${target}-${distro}-latest" "${repo}" "${digest}" alias

    if [ "${distro}" = "${DEFAULT_ROS_DISTRO}" ]; then
      promote_tag "${repo}:${target}" "${repo}" "${digest}" alias
      promote_tag "${repo}:${target}-latest" "${repo}" "${digest}" alias
    fi
  fi
done < <(jq -r '.images[] | [.repo, .target, .ros_distro, .digest] | @tsv' release-input/build/build-metadata.json)
