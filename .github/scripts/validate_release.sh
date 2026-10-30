#!/usr/bin/env bash
# Validate that a build-all-images run can be promoted to an OpenADKit release.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=.github/scripts/release_tag.sh
source "${script_dir}/release_tag.sh"
# shellcheck source=.github/scripts/registry_lookup.sh
source "${script_dir}/registry_lookup.sh"
# shellcheck source=.github/scripts/stable_alias_policy.sh
source "${script_dir}/stable_alias_policy.sh"

: "${BUILD_TAG:?BUILD_TAG is required}"
: "${VERSION:?VERSION is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REF:?GITHUB_REF is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
: "${IMAGE_PREFIX_COMMON:?IMAGE_PREFIX_COMMON is required}"
: "${IMAGE_PREFIX_COMPONENT:?IMAGE_PREFIX_COMPONENT is required}"

openadkit_semver_re='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*)|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(\.((0|[1-9][0-9]*)|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?$'
openadkit_stable_re='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
autoware_stable_re='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'

publish_latest_aliases=false
is_stable_release=false
release_sha=""
source_branch=""
run_id=""
readonly BUILD_AGE_MAX_DAYS=90

fail() {
  echo "$*" >&2
  exit 1
}

# The X.Y release line of VERSION.
release_line() {
  printf '%s\n' "${VERSION#v}" | cut -d. -f1-2
}

validate_inputs() {
  printf '%s\n' "${VERSION}" | grep -Eq "${openadkit_semver_re}" \
    || fail "Invalid version format '${VERSION}': must be strict SemVer vX.Y.Z or vX.Y.Z-prerelease"
  printf '%s\n' "${BUILD_TAG}" | grep -Eq '^[0-9]+-[0-9]+$' \
    || fail "Invalid build_tag format '${BUILD_TAG}': must be RUN_ID-RUN_ATTEMPT"
  # A release line releases from its own branch, with its own scripts.
  [ "${GITHUB_REF}" = "refs/heads/release/$(release_line)" ] \
    || fail "Release ${VERSION} must be triggered from release/$(release_line) (got ${GITHUB_REF})"
  case "${DEFAULT_ROS_DISTRO:-humble}" in
    humble|jazzy) ;;
    *) fail "Invalid default_ros_distro '${DEFAULT_ROS_DISTRO}': must be one of humble, jazzy" ;;
  esac
}

# Docs and the CLI are generated from openadkit.json, so the release must agree
# with it. A mismatched default would publish bare tag aliases the docs call
# the wrong distro, and a mismatched prefix would push images the manifest
# does not name.
validate_manifest_consistency() {
  local manifest manifest_distro manifest_registry

  manifest="${RELEASE_SOURCE_ROOT:-${script_dir}/../..}/openadkit.json"
  [ -f "${manifest}" ] || fail "Product manifest not found at ${manifest}"
  manifest_distro=$(jq -r '.defaultRosDistro // empty' "${manifest}")
  [ -n "${manifest_distro}" ] \
    || fail "Product manifest ${manifest} does not declare defaultRosDistro"
  [ "${DEFAULT_ROS_DISTRO:-humble}" = "${manifest_distro}" ] \
    || fail "default_ros_distro '${DEFAULT_ROS_DISTRO:-humble}' must match openadkit.json defaultRosDistro '${manifest_distro}'; update the manifest before releasing"
  manifest_registry=$(jq -r '.imagePrefixComponent // empty' "${manifest}")
  [ -n "${manifest_registry}" ] \
    || fail "Product manifest ${manifest} does not declare imagePrefixComponent"
  [ "${IMAGE_PREFIX_COMPONENT}" = "${manifest_registry}" ] \
    || fail "IMAGE_PREFIX_COMPONENT '${IMAGE_PREFIX_COMPONENT}' must match openadkit.json imagePrefixComponent '${manifest_registry}'"
}

resolve_latest_alias_policy() {
  local current_policy

  if printf '%s\n' "${VERSION}" | grep -Eq "${openadkit_stable_re}"; then
    is_stable_release=true
    current_policy=$(current_latest_alias_policy)
    if [ "${current_policy}" = true ]; then
      publish_latest_aliases=true
    else
      echo "Stable aliases will not be updated because a newer stable release exists"
    fi
  fi
}

validate_build_run() {
  local run_json latest_tag workflow_name workflow_path status conclusion created_at
  local created_epoch now_epoch max_age_seconds

  run_id="${BUILD_TAG%%-*}"
  # The run's latest attempt decides: "Re-run failed jobs" finishes a build
  # under its first tag, while "Re-run all jobs" supersedes that tag.
  run_json=$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}")
  latest_tag=$(gh api --paginate "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}/artifacts?per_page=100" \
    --jq '.artifacts[] | select(.expired | not) | .name | select(startswith("build-metadata-")) | ltrimstr("build-metadata-")' \
    | sort -V | tail -n 1)
  [ "${latest_tag}" = "${BUILD_TAG}" ] || fail "Build ${BUILD_TAG} is not the latest build of run ${run_id} (latest: '${latest_tag}')"

  workflow_name=$(printf '%s' "${run_json}" | jq -r '.name')
  workflow_path=$(printf '%s' "${run_json}" | jq -r '.path')
  source_branch=$(printf '%s' "${run_json}" | jq -r '.head_branch')
  status=$(printf '%s' "${run_json}" | jq -r '.status')
  conclusion=$(printf '%s' "${run_json}" | jq -r '.conclusion')
  release_sha=$(printf '%s' "${run_json}" | jq -r '.head_sha')
  created_at=$(printf '%s' "${run_json}" | jq -r '.created_at')

  [ "${workflow_name}" = "build-all-images" ] || fail "Expected build-all-images run, got '${workflow_name}'"
  [ "${workflow_path}" = ".github/workflows/build-all-images.yaml" ] || fail "Unexpected workflow path '${workflow_path}'"
  [ "${status}" = "completed" ] || fail "Source build must be completed (got '${status}')"
  [ "${conclusion}" = "success" ] || fail "Source build must succeed (got '${conclusion}')"

  created_epoch=$(date -u -d "${created_at}" +%s)
  now_epoch=$(date -u +%s)
  max_age_seconds=$((BUILD_AGE_MAX_DAYS * 24 * 60 * 60))
  if [ $((now_epoch - created_epoch)) -gt "${max_age_seconds}" ]; then
    fail "Build ${BUILD_TAG} is older than ${BUILD_AGE_MAX_DAYS} days and is no longer promotable"
  fi
}

warn_unreleased_kit_changes() {
  # The bundle ships cli/ and deployments/ from the build SHA, and pushes that
  # only touch them start no build. Name what the branch would add; do not fail.
  local changed
  changed=$(gh api "repos/${GITHUB_REPOSITORY}/compare/${release_sha}...${source_branch}" --jq '.files[].filename' 2>/dev/null \
    | grep -E '^(cli/|deployments/|openadkit$|openadkit\.json$)') || return 0
  echo "::warning title=Unreleased kit changes::${source_branch} changes the CLI or deployments after ${release_sha}; dispatch build-all-images on ${source_branch} to release them"
  printf '%s\n' "${changed}" | sed 's/^/  /' >&2
}

download_build_metadata() {
  mkdir -p release-input/build release-input/scan
  gh run download "${run_id}" \
    --repo "${GITHUB_REPOSITORY}" \
    --name "build-metadata-${BUILD_TAG}" \
    --dir release-input/build
}

checkout_release_source() {
  # Keep dispatch-time policy/scripts separate from the exact promoted source.
  # Sparse checkout must not cause missing CLI/example checksums to be ignored.
  RELEASE_SOURCE_ROOT="${PWD}/release-source"
  export RELEASE_SOURCE_ROOT
  [ ! -e "${RELEASE_SOURCE_ROOT}" ] || fail "Release source directory already exists"
  git fetch --quiet --depth 1 origin "${release_sha}"
  mkdir -p "${RELEASE_SOURCE_ROOT}"
  git archive "${release_sha}" | tar -x -C "${RELEASE_SOURCE_ROOT}"
}

select_scan_metadata() {
  local scan_artifact_ids scan_artifact_id artifact_json artifact_run_id scan_run_id scan_run_attempt
  local scan_run_json scan_workflow_name scan_workflow_path scan_head_branch scan_status scan_conclusion
  local selected_scan_artifact_id selected_scan_run_id selected_scan_run_attempt selected_scan_status selected_scan_conclusion
  local lookup_status scan_lookup_http_status

  scan_artifact_ids=$(
    gh api --paginate "repos/${GITHUB_REPOSITORY}/actions/artifacts?name=scan-metadata-${BUILD_TAG}" \
      --jq '.artifacts[] | select(.expired == false) | [.id, .created_at] | @tsv' \
      | sort -k2,2r \
      | cut -f1
  )
  [ -n "${scan_artifact_ids}" ] || fail "No non-expired full scan metadata found for ${BUILD_TAG}"

  selected_scan_artifact_id=""
  selected_scan_run_id=""
  selected_scan_run_attempt=""
  selected_scan_status=""
  selected_scan_conclusion=""
  while IFS= read -r scan_artifact_id; do
    [ -n "${scan_artifact_id}" ] || continue

    rm -rf release-input/scan
    mkdir -p release-input/scan
    rm -f scan-metadata.zip

    artifact_json=$(gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${scan_artifact_id}")
    artifact_run_id=$(printf '%s' "${artifact_json}" | jq -r '.workflow_run.id // empty')
    gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${scan_artifact_id}/zip" > scan-metadata.zip
    unzip -q scan-metadata.zip -d release-input/scan

    if ! python3 "${script_dir}/images.py" check-scan release-input/scan/scan-metadata.json >/dev/null 2>&1; then
      echo "Ignoring scan artifact ${scan_artifact_id}: metadata is not full scan metadata for ${BUILD_TAG}" >&2
      continue
    fi

    scan_run_id=$(jq -r '.run_id' release-input/scan/scan-metadata.json)
    scan_run_attempt=$(jq -r '.run_attempt' release-input/scan/scan-metadata.json)
    if [ "${artifact_run_id}" != "${scan_run_id}" ]; then
      echo "Ignoring scan artifact ${scan_artifact_id}: artifact run ${artifact_run_id} does not match metadata run ${scan_run_id}" >&2
      continue
    fi

    lookup_status=0
    scan_run_json=$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${scan_run_id}/attempts/${scan_run_attempt}" 2>/dev/null) || lookup_status=$?
    if [ "${lookup_status}" -ne 0 ]; then
      scan_lookup_http_status=$(jq -r '(.status // empty) | tostring' <<< "${scan_run_json}" 2>/dev/null || true)
      if [ "${scan_lookup_http_status}" = "404" ]; then
        echo "Ignoring scan artifact ${scan_artifact_id}: scan run ${scan_run_id}-${scan_run_attempt} was not found" >&2
        continue
      fi
      fail "Could not read scan run ${scan_run_id}-${scan_run_attempt} for artifact ${scan_artifact_id}"
    fi

    scan_workflow_name=$(printf '%s' "${scan_run_json}" | jq -r '.name')
    scan_workflow_path=$(printf '%s' "${scan_run_json}" | jq -r '.path')
    scan_head_branch=$(printf '%s' "${scan_run_json}" | jq -r '.head_branch')
    scan_status=$(printf '%s' "${scan_run_json}" | jq -r '.status')
    scan_conclusion=$(printf '%s' "${scan_run_json}" | jq -r '.conclusion')

    if [ "${scan_workflow_name}" != "scan-images" ] || \
      [ "${scan_workflow_path}" != ".github/workflows/scan.yaml" ] || \
      [ "${scan_head_branch}" != "${source_branch}" ] || \
      [ "${scan_status}" != "completed" ]; then
      echo "Ignoring scan artifact ${scan_artifact_id}: scan run ${scan_run_id}-${scan_run_attempt} is not a completed scan-images run on ${source_branch}" >&2
      continue
    fi

    selected_scan_artifact_id="${scan_artifact_id}"
    selected_scan_run_id="${scan_run_id}"
    selected_scan_run_attempt="${scan_run_attempt}"
    selected_scan_status=$(jq -r '.scan_status' release-input/scan/scan-metadata.json)
    selected_scan_conclusion="${scan_conclusion}"
    break
  done <<< "${scan_artifact_ids}"

  [ -n "${selected_scan_artifact_id}" ] || fail "No validated full scan metadata found for ${BUILD_TAG}"
  if [ "${selected_scan_status}" != "passed" ] || [ "${selected_scan_conclusion}" != "success" ]; then
    fail "Latest full scan for ${BUILD_TAG} did not pass: scan run ${selected_scan_run_id}-${selected_scan_run_attempt} has metadata status '${selected_scan_status}' and conclusion '${selected_scan_conclusion}'"
  fi
}

validate_metadata() {
  # The same model is parsed again at packaging; this is not a bypass token.
  python3 "${script_dir}/images.py" validate release-input/build release-input/scan/scan-metadata.json
}

# Releases come from release/X.Y branches, whose .github/autoware.ref pins the
# Autoware release their builds use; main builds for upstream development.
validate_release_rules() {
  local metadata_sha autoware_input_ref autoware_ref_type autoware_base_version

  metadata_sha=$(jq -r '.openadkit_sha' release-input/build/build-metadata.json)
  [ "${metadata_sha}" = "${release_sha}" ] \
    || fail "Build metadata SHA ${metadata_sha} does not match workflow SHA ${release_sha}"

  [ "${source_branch}" = "release/$(release_line)" ] \
    || fail "${VERSION} must be built from release/$(release_line) (got '${source_branch}')"

  autoware_input_ref=$(jq -r '.autoware_input_ref' release-input/build/build-metadata.json)
  autoware_ref_type=$(jq -r '.autoware_ref_type' release-input/build/build-metadata.json)
  autoware_base_version=$(jq -r '.autoware_base_version' release-input/build/build-metadata.json)
  if [ "${autoware_ref_type}" != "tag" ] || ! printf '%s\n' "${autoware_input_ref}" | grep -Eq "${autoware_stable_re}"; then
    fail "Releases must be built from an Autoware X.Y.Z release tag (got ${autoware_ref_type}:${autoware_input_ref})"
  fi
  [ "${autoware_base_version}" = "${autoware_input_ref}" ] \
    || fail "Autoware base version ${autoware_base_version} does not match release tag ${autoware_input_ref}"
}

# One Open AD Kit release line builds on one Autoware minor release: v2.0.x is
# Autoware 1.9.x. The line's first release sets it, from the release/X.Y pin;
# every later release must keep it, so the version alone tells the Autoware.
validate_autoware_line() {
  local autoware_base_version releases previous previous_autoware

  autoware_base_version=$(jq -r '.autoware_base_version' release-input/build/build-metadata.json)
  releases=$(gh api --paginate --slurp "repos/${GITHUB_REPOSITORY}/releases?per_page=100") \
    || fail "Could not list releases to check the Autoware of release line $(release_line)"
  previous=$(jq -r --arg line "v$(release_line)." --arg version "${VERSION}" '
    [.[][] | select(.draft | not) | select(.tag_name | startswith($line)) | select(.tag_name != $version)]
    | sort_by(.published_at) | last | .tag_name // empty' <<<"${releases}")
  [ -n "${previous}" ] || return 0
  previous_autoware=$(gh release download "${previous}" --repo "${GITHUB_REPOSITORY}" \
      --pattern release-metadata.json --output - | jq -r '.autoware_base_version') \
    || fail "Could not read the Autoware of ${previous}"
  [ "${previous_autoware%.*}" = "${autoware_base_version%.*}" ] \
    || fail "Release line $(release_line) builds on Autoware ${previous_autoware%.*}.x (${previous}); ${VERSION} would build on ${autoware_base_version}. Start a new release line for another Autoware minor release"
}

validate_git_tag() {
  local lookup_status tag_sha

  if tag_sha=$(release_tag_sha); then
    if [ "${tag_sha}" != "${release_sha}" ]; then
      fail "Tag ${VERSION} already exists at ${tag_sha}, expected ${release_sha}"
    fi
  else
    lookup_status=$?
    [ "${lookup_status}" -eq 1 ] || return "${lookup_status}"
  fi
}

validate_registry_conflicts() {
  jq -r --arg version "${VERSION}" \
    '.images[] | [.ref, "\(.repo):\(.target)-\(.ros_distro)-\($version)", .digest] | @tsv' \
    release-input/build/build-metadata.json \
    | registry_preflight_release_images
}

# The evidence gate: a successful evidence run on this release line that tested
# this build at its own commit and passed every cell. A passing rerun may
# supersede a failed run; a failed run never counts.
select_evidence_summary() {
  local artifact_ids artifact_id evidence_run_id run_json

  # Never leave an old summary usable after a failed selection.
  rm -rf release-input/evidence release-input/evidence-summary.json
  artifact_ids=$(
    gh api --paginate "repos/${GITHUB_REPOSITORY}/actions/artifacts?name=evidence-summary-${BUILD_TAG}" \
      --jq '.artifacts[] | select(.expired == false) | [.id, .created_at] | @tsv' \
      | sort -k2,2r \
      | cut -f1
  )
  [ -n "${artifact_ids}" ] || fail "evidence gate: no evidence summary found for ${BUILD_TAG}"

  while IFS= read -r artifact_id; do
    [ -n "${artifact_id}" ] || continue
    evidence_run_id=$(gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${artifact_id}" --jq '.workflow_run.id // empty')
    [ -n "${evidence_run_id}" ] || continue
    run_json=$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${evidence_run_id}") || continue
    if ! jq -e --arg branch "${source_branch}" '
        .path == ".github/workflows/evidence.yaml" and .head_branch == $branch and
        .status == "completed" and .conclusion == "success"' <<<"${run_json}" >/dev/null; then
      echo "Ignoring evidence run ${evidence_run_id}: not a successful evidence run on ${source_branch}" >&2
      continue
    fi

    rm -rf release-input/evidence
    mkdir -p release-input/evidence
    gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${artifact_id}/zip" >evidence-summary.zip
    unzip -q evidence-summary.zip -d release-input/evidence
    if jq -e --arg tag "${BUILD_TAG}" --arg sha "${release_sha}" '
        .result == "PASSED" and .release_evidence == true and
        .build_tag == $tag and .build_sha == $sha and .source_sha == $sha' \
        release-input/evidence/evidence-summary.json >/dev/null; then
      cp release-input/evidence/evidence-summary.json release-input/evidence-summary.json
      echo "evidence gate: PASSED (evidence run ${evidence_run_id})"
      return 0
    fi
    echo "Ignoring evidence run ${evidence_run_id}: its summary did not pass ${BUILD_TAG} at ${release_sha}" >&2
  done <<< "${artifact_ids}"

  fail "evidence gate: no successful evidence run on ${source_branch} passed build ${BUILD_TAG} at ${release_sha}"
}

write_outputs() {
  {
    echo "release_sha=${release_sha}"
    echo "publish_latest_aliases=${publish_latest_aliases}"
    echo "is_stable_release=${is_stable_release}"
  } >> "${GITHUB_OUTPUT}"
}

main() {
  validate_inputs
  resolve_latest_alias_policy
  validate_build_run
  warn_unreleased_kit_changes
  checkout_release_source
  validate_manifest_consistency
  download_build_metadata
  select_scan_metadata
  validate_metadata
  validate_release_rules
  validate_autoware_line
  select_evidence_summary
  validate_git_tag
  validate_registry_conflicts
  write_outputs
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main
fi
