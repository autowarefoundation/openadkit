#!/usr/bin/env bash
# Create the GitHub release as a draft, and publish it once its images are
# promoted. Publishing creates the tag and, with immutable releases on, freezes
# the release: a bad one is followed by the next version, never replaced.
set -euo pipefail

plan_file=${RELEASE_PLAN_FILE:-release-plan.json}
VERSION=$(jq -r '.release.version' "${plan_file}")
RELEASE_SHA=$(jq -r '.release.releaseSha' "${plan_file}")
STABLE_RELEASE=$(jq -r '.release.stable' "${plan_file}")
PUBLISH_LATEST_ALIASES=$(jq -r '.release.publishLatestAliases' "${plan_file}")

create_draft() {
  local -a assets
  case "$(gh release view "${VERSION}" --json isDraft --jq .isDraft 2>/dev/null || true)" in
    false)
      echo "Release ${VERSION} is already published; release the next version" >&2
      exit 1
      ;;
    true)
      echo "Replacing the draft of an earlier attempt."
      gh release delete "${VERSION}" --yes
      ;;
  esac
  mapfile -t assets < <(jq -r '.githubAssets[].path' "${plan_file}")
  gh release create "${VERSION}" \
    --target "${RELEASE_SHA}" \
    --title "${VERSION}" \
    --notes-file release-notes.md \
    --draft \
    "${assets[@]}"
}

publish() {
  local prerelease=true latest=false
  if [ "${STABLE_RELEASE}" = true ]; then
    prerelease=false
    [ "${PUBLISH_LATEST_ALIASES}" != true ] || latest=true
  fi
  gh release edit "${VERSION}" --draft=false --prerelease="${prerelease}" --latest="${latest}"
  # The repository setting is not readable with the workflow token; the
  # release itself says whether publishing froze it, once GitHub has marked it.
  local attempt
  for attempt in 1 2 3 4 5; do
    [ "$(gh api "repos/{owner}/{repo}/releases/tags/${VERSION}" --jq '.immutable')" != true ] || return 0
    [ "${attempt}" = 5 ] || sleep "${IMMUTABLE_RETRY_SECONDS:-3}"
  done
  echo "Release ${VERSION} is published but not immutable: turn on immutable releases in the repository settings" >&2
  exit 1
}

case "${1:-}" in
  draft) create_draft ;;
  publish) publish ;;
  *)
    echo "Usage: $0 draft|publish" >&2
    exit 2
    ;;
esac
