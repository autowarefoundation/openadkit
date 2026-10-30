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

# The newest <name> artifact from a completed <workflow> run on the release
# branch decides: its run must have succeeded and <passed> must accept it.
# <eligible> skips artifacts that are not about this release, such as an
# evidence run that tested another commit against this build's images.
# Usage: select_latest_artifact <name> <workflow> <file> <eligible> <passed> <dir>
select_latest_artifact() {
  local name=$1 workflow=$2 file=$3 eligible=$4 passed=$5 dir=$6
  local artifact_ids artifact_id run_id run_json archive

  artifact_ids=$(
    gh api --paginate "repos/${GITHUB_REPOSITORY}/actions/artifacts?name=${name}" \
      --jq '.artifacts[] | select(.expired == false) | [.id, .created_at] | @tsv' \
      | sort -k2,2r \
      | cut -f1
  )
  [ -n "${artifact_ids}" ] || fail "No ${name} artifact found"
  archive=$(mktemp)

  while IFS= read -r artifact_id; do
    [ -n "${artifact_id}" ] || continue
    run_id=$(gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${artifact_id}" --jq '.workflow_run.id // empty')
    [ -n "${run_id}" ] || continue
    run_json=$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}" 2>/dev/null) || continue
    jq -e --arg workflow "${workflow}" --arg branch "${source_branch}" '
      .path == $workflow and .head_branch == $branch and .status == "completed"' \
      <<<"${run_json}" >/dev/null || continue

    rm -rf "${dir}"
    mkdir -p "${dir}"
    gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${artifact_id}/zip" >"${archive}"
    unzip -q "${archive}" -d "${dir}"
    "${eligible}" "${dir}/${file}" || continue

    rm -f "${archive}"
    if [ "$(jq -r '.conclusion' <<<"${run_json}")" != success ] || ! "${passed}" "${dir}/${file}"; then
      rm -rf "${dir}"
      fail "The latest ${name} (run ${run_id}) did not pass"
    fi
    echo "${name}: passed (run ${run_id})"
    return 0
  done <<< "${artifact_ids}"

  rm -f "${archive}"
  rm -rf "${dir}"
  fail "No ${name} from a completed ${workflow} run on ${source_branch}"
}

scan_is_full() { python3 "${script_dir}/images.py" check-scan "$1" >/dev/null 2>&1; }
scan_passed() { [ "$(jq -r '.scan_status' "$1")" = passed ]; }

# An evidence run is about this release when it tested the build's own commit.
evidence_is_release() {
  jq -e --arg tag "${BUILD_TAG}" --arg sha "${release_sha}" '
    .release_evidence == true and .build_tag == $tag and
    .build_sha == $sha and .source_sha == $sha' "$1" >/dev/null
}
evidence_passed() { [ "$(jq -r '.result' "$1")" = PASSED ]; }

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
  select_latest_artifact "scan-metadata-${BUILD_TAG}" .github/workflows/scan.yaml \
    scan-metadata.json scan_is_full scan_passed release-input/scan
  validate_metadata
  validate_release_rules
  validate_autoware_line
  select_latest_artifact "evidence-summary-${BUILD_TAG}" .github/workflows/evidence.yaml \
    evidence-summary.json evidence_is_release evidence_passed release-input/evidence
  validate_git_tag
  validate_registry_conflicts
  write_outputs
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main
fi
