#!/usr/bin/env bash
# Safely prepare and publish workflow-owned GitHub releases.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=.github/scripts/release_tag.sh
source "${script_dir}/release_tag.sh"

readonly RELEASE_WORKFLOW_MARKER='<!-- openadkit-release-workflow:v1 -->'

project_release() {
  jq -c '{
    id,
    assets,
    body: (.body // ""),
    isDraft: .draft,
    isPrerelease: .prerelease,
    name,
    tagName: .tag_name,
    targetCommitish: .target_commitish
  }'
}

expected_prerelease() {
  if [ "${STABLE_RELEASE}" = true ]; then
    printf '%s\n' false
  else
    printf '%s\n' true
  fi
}

verify_release_tag_target() {
  local tag_sha lookup_status=0
  tag_sha=$(release_tag_sha) || lookup_status=$?
  if [ "${lookup_status}" -ne 0 ]; then
    echo "Release tag ${VERSION} could not be resolved" >&2
    return 1
  fi
  if [ "${tag_sha}" != "${RELEASE_SHA}" ]; then
    echo "Release tag ${VERSION} resolves to ${tag_sha}, expected ${RELEASE_SHA}" >&2
    return 1
  fi
}

verify_owned_draft() {
  local state="$1"
  jq -e \
    --arg marker "${RELEASE_WORKFLOW_MARKER}" \
    --arg version "${VERSION}" \
    --arg release_sha "${RELEASE_SHA}" '
      (.id | type == "number") and
      .isDraft == true and
      .tagName == $version and
      .name == $version and
      .targetCommitish == $release_sha and
      (.body | startswith($marker))
    ' <<<"${state}" >/dev/null
}

write_expected_asset_manifest() {
  {
    for asset in \
      release-metadata.json \
      release-input/build/autoware-lock.repos \
      release-input/build/upstream-images.json \
      dist/*.tar.gz; do
      [ -f "${asset}" ] || {
        echo "Expected release asset is missing: ${asset}" >&2
        return 1
      }
      printf '%s  %s\n' "$(sha256sum "${asset}" | cut -d ' ' -f1)" "$(basename "${asset}")"
    done
  } | sort -k2,2 > release-assets.sha256
}

verify_draft_assets() {
  local state="$1"
  local manifest="${RELEASE_ASSET_MANIFEST:-release-assets.sha256}"
  local expected_assets existing_assets download_dir manifest_path

  [ -f "${manifest}" ] || {
    echo "Expected release asset manifest is missing: ${manifest}" >&2
    return 1
  }
  if ! awk '
    NF != 2 || $1 !~ /^[0-9a-f]{64}$/ || $2 !~ /^[A-Za-z0-9._-]+$/ { invalid=1 }
    { count++ }
    END { exit(!invalid && count > 0 ? 0 : 1) }
  ' "${manifest}"; then
    echo "Release asset manifest is invalid" >&2
    return 1
  fi

  expected_assets=$(awk '{ print $2 }' "${manifest}" | sort)
  existing_assets=$(jq -r '.assets[].name' <<<"${state}" | sort)
  if ! diff -u <(printf '%s\n' "${expected_assets}") <(printf '%s\n' "${existing_assets}"); then
    echo "Draft release asset names changed before publication" >&2
    return 1
  fi

  download_dir=$(mktemp -d)
  manifest_path=$(realpath "${manifest}")
  if ! (
    cd "${download_dir}"
    while IFS=$'\t' read -r asset_id asset_name; do
      [[ "${asset_id}" =~ ^[0-9]+$ && "${asset_name}" =~ ^[A-Za-z0-9._-]+$ ]] || exit 1
      gh api \
        -H 'Accept: application/octet-stream' \
        "repos/${GITHUB_REPOSITORY}/releases/assets/${asset_id}" > "${asset_name}"
    done < <(jq -r '.assets[] | [.id, .name] | @tsv' <<<"${state}")
    sha256sum --check "${manifest_path}"
  ); then
    rm -rf "${download_dir}"
    echo "Draft release asset contents changed before publication" >&2
    return 1
  fi
  rm -rf "${download_dir}"
}

fetch_release_by_id() {
  local release_id="$1" response
  response=$(gh api "repos/${GITHUB_REPOSITORY}/releases/${release_id}") || return
  project_release <<<"${response}"
}

fetch_release_by_tag() {
  local response
  response=$(gh api --paginate --slurp "repos/${GITHUB_REPOSITORY}/releases?per_page=100") || return
  jq -c --arg version "${VERSION}" '
    [.[][] | select(.tag_name == $version)] |
    if length > 1 then error("duplicate releases for tag")
    elif length == 1 then
      .[0] | {
        id,
        assets,
        body: (.body // ""),
        isDraft: .draft,
        isPrerelease: .prerelease,
        name,
        tagName: .tag_name,
        targetCommitish: .target_commitish
      }
    else empty end
  ' <<<"${response}"
}

verify_published_release() {
  local state="$1"
  local prerelease expected_assets existing_assets existing_dir release_id refreshed
  prerelease=$(expected_prerelease)
  release_id=$(jq -r '.id' <<<"${state}")
  jq -e \
    --arg version "${VERSION}" \
    --arg release_sha "${RELEASE_SHA}" \
    --argjson prerelease "${prerelease}" \
    --rawfile expected_body release-notes.md '
      (.id | type == "number") and
      .tagName == $version and
      .targetCommitish == $release_sha and
      .name == $version and
      .isDraft == false and
      .isPrerelease == $prerelease and
      .body == $expected_body
    ' <<<"${state}" >/dev/null

  refreshed=$(fetch_release_by_id "${release_id}")
  cmp <(jq -S . <<<"${state}") <(jq -S . <<<"${refreshed}")

  expected_assets=$(
    {
      printf '%s\n' release-metadata.json autoware-lock.repos upstream-images.json
      for asset in dist/*.tar.gz; do
        basename "${asset}"
      done
    } | sort
  )
  existing_assets=$(jq -r '.assets[].name' <<<"${state}" | sort)
  diff -u <(printf '%s\n' "${expected_assets}") <(printf '%s\n' "${existing_assets}")

  existing_dir=$(mktemp -d)
  gh release download "${VERSION}" \
    --dir "${existing_dir}" \
    --pattern release-metadata.json \
    --pattern autoware-lock.repos \
    --pattern upstream-images.json \
    --pattern '*.tar.gz'
  cmp <(jq -S . "${existing_dir}/release-metadata.json") <(jq -S . release-metadata.json)
  for asset in release-input/build/autoware-lock.repos release-input/build/upstream-images.json dist/*.tar.gz; do
    cmp "${asset}" "${existing_dir}/$(basename "${asset}")"
  done
  rm -rf "${existing_dir}"
}

create_draft() {
  local state
  gh release create "${VERSION}" \
    --target "${RELEASE_SHA}" \
    --title "${VERSION}" \
    --notes-file release-notes.md \
    --draft \
    release-metadata.json \
    release-input/build/autoware-lock.repos \
    release-input/build/upstream-images.json \
    dist/*.tar.gz >/dev/null
  state=$(fetch_release_by_tag) || return
  if [ -z "${state}" ] || ! verify_owned_draft "${state}"; then
    echo "Created draft release ${VERSION} could not be verified" >&2
    return 1
  fi
  jq -er '.id' <<<"${state}"
}

prepare_release() {
  local release_state existing_is_draft release_id refreshed body_sha256 create_release=false

  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
  write_expected_asset_manifest
  verify_release_tag_target
  release_state=$(fetch_release_by_tag) || return

  if [ -n "${release_state}" ]; then
    existing_is_draft=$(jq -r '.isDraft' <<<"${release_state}")
    release_id=$(jq -r '.id' <<<"${release_state}")
    if [ "${existing_is_draft}" = true ]; then
      verify_owned_draft "${release_state}" || return
      refreshed=$(fetch_release_by_id "${release_id}") || return
      verify_owned_draft "${refreshed}" || return
      cmp <(jq -S . <<<"${release_state}") <(jq -S . <<<"${refreshed}")
      echo "Removing workflow-owned incomplete draft release ${VERSION}."
      gh api --method DELETE "repos/${GITHUB_REPOSITORY}/releases/${release_id}" >/dev/null
      create_release=true
    else
      verify_published_release "${release_state}"
      echo "Existing release ${VERSION} matches validated metadata, notes, and assets."
    fi
  else
    create_release=true
  fi

  if [ "${create_release}" = true ]; then
    release_id=$(create_draft) || return
  fi
  body_sha256=$(sha256sum release-notes.md | cut -d ' ' -f1)
  {
    echo "created=${create_release}"
    echo "release_id=${release_id}"
    echo "release_body_sha256=${body_sha256}"
  } >>"${GITHUB_OUTPUT}"
}

publish_release() {
  local state prerelease make_latest actual_body_sha256
  : "${RELEASE_ID:?RELEASE_ID is required}"
  : "${RELEASE_BODY_SHA256:?RELEASE_BODY_SHA256 is required}"
  verify_release_tag_target
  state=$(fetch_release_by_id "${RELEASE_ID}")
  verify_owned_draft "${state}"
  actual_body_sha256=$(jq -jr '.body' <<<"${state}" | sha256sum | cut -d ' ' -f1)
  if [ "${actual_body_sha256}" != "${RELEASE_BODY_SHA256}" ]; then
    echo "Draft release body changed before publication" >&2
    return 1
  fi
  verify_draft_assets "${state}"
  prerelease=$(expected_prerelease)
  make_latest=false
  if [ "${STABLE_RELEASE}" = true ] && [ "${PUBLISH_LATEST_ALIASES}" = true ]; then
    make_latest=true
  fi
  gh api --method PATCH "repos/${GITHUB_REPOSITORY}/releases/${RELEASE_ID}" \
    -F draft=false \
    -F prerelease="${prerelease}" \
    -f make_latest="${make_latest}" >/dev/null
}

: "${VERSION:?VERSION is required}"
: "${RELEASE_SHA:?RELEASE_SHA is required}"
: "${STABLE_RELEASE:?STABLE_RELEASE is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

case "${1:-}" in
  prepare) prepare_release ;;
  publish)
    : "${PUBLISH_LATEST_ALIASES:?PUBLISH_LATEST_ALIASES is required}"
    publish_release
    ;;
  *)
    echo "Usage: $0 prepare|publish" >&2
    exit 2
    ;;
esac
