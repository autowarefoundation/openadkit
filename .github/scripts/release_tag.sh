#!/usr/bin/env bash
# Query and create release tags without treating arbitrary API failures as 404s.

release_tag_sha() {
  local object response sha status type
  local depth=0

  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  : "${VERSION:?VERSION is required}"

  if response=$(gh api "repos/${GITHUB_REPOSITORY}/git/refs/tags/${VERSION}" 2>/dev/null); then
    if ! object=$(jq -ec '.object' <<< "${response}"); then
      echo "Invalid tag response for ${VERSION}" >&2
      return 2
    fi
    while [ "${depth}" -lt 5 ]; do
      depth=$((depth + 1))
      if ! type=$(jq -er '.type | strings' <<< "${object}") || \
        ! sha=$(jq -er '.sha | strings | select(test("^[0-9a-fA-F]{40}$"))' <<< "${object}"); then
        echo "Invalid tag object for ${VERSION}" >&2
        return 2
      fi
      case "${type}" in
        commit)
          printf '%s\n' "${sha}"
          return 0
          ;;
        tag)
          if ! response=$(gh api "repos/${GITHUB_REPOSITORY}/git/tags/${sha}" 2>/dev/null) || \
            ! object=$(jq -ec '.object' <<< "${response}"); then
            echo "Failed to resolve annotated tag ${VERSION}" >&2
            return 2
          fi
          ;;
        *)
          echo "Unsupported tag object type '${type}' for ${VERSION}" >&2
          return 2
          ;;
      esac
    done
    echo "Annotated tag ${VERSION} exceeds the supported nesting depth" >&2
    return 2
  fi

  status=$(jq -r '(.status // empty) | tostring' <<< "${response}" 2>/dev/null || true)
  if [ "${status}" = "404" ]; then
    return 1
  fi

  if [ -n "${status}" ]; then
    echo "Failed to query tag ${VERSION}: GitHub API returned HTTP ${status}" >&2
  else
    echo "Failed to query tag ${VERSION}: GitHub API request failed" >&2
  fi
  return 2
}

ensure_release_tag() {
  local lookup_status tag_sha

  : "${RELEASE_SHA:?RELEASE_SHA is required}"

  if tag_sha=$(release_tag_sha); then
    if [ "${tag_sha}" != "${RELEASE_SHA}" ]; then
      echo "Tag ${VERSION} exists at ${tag_sha}, expected ${RELEASE_SHA}" >&2
      return 1
    fi
    echo "Tag ${VERSION} already exists at ${RELEASE_SHA}; continuing"
    return 0
  else
    lookup_status=$?
  fi

  [ "${lookup_status}" -eq 1 ] || return "${lookup_status}"
  gh api "repos/${GITHUB_REPOSITORY}/git/refs" \
    -f ref="refs/tags/${VERSION}" \
    -f sha="${RELEASE_SHA}" >/dev/null
  echo "Created tag ${VERSION} at ${RELEASE_SHA}"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  ensure_release_tag
fi
