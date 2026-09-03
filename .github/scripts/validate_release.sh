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

openadkit_semver_re='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*)|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z]*)(\.((0|[1-9][0-9]*)|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z]*))*)?$'
openadkit_stable_re='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
autoware_stable_re='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'

publish_latest_aliases=false
is_stable_release=false
release_sha=""
run_id=""
run_attempt=""
readonly BUILD_AGE_MAX_DAYS=90

fail() {
  echo "$*" >&2
  exit 1
}

validate_inputs() {
  printf '%s\n' "${VERSION}" | grep -Eq "${openadkit_semver_re}" \
    || fail "Invalid version format '${VERSION}': must be strict SemVer vX.Y.Z or vX.Y.Z-prerelease"
  printf '%s\n' "${BUILD_TAG}" | grep -Eq '^[0-9]+-[0-9]+$' \
    || fail "Invalid build_tag format '${BUILD_TAG}': must be RUN_ID-RUN_ATTEMPT"
  [ "${GITHUB_REF}" = "refs/heads/main" ] \
    || fail "Release must be triggered from main branch (got ${GITHUB_REF})"
  case "${DEFAULT_ROS_DISTRO:-humble}" in
    humble|jazzy) ;;
    *) fail "Invalid default_ros_distro '${DEFAULT_ROS_DISTRO}': must be one of humble, jazzy" ;;
  esac
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
  local run_json workflow_name workflow_path head_branch status conclusion created_at
  local created_epoch now_epoch max_age_seconds

  run_id="${BUILD_TAG%%-*}"
  run_attempt="${BUILD_TAG##*-}"
  run_json=$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}/attempts/${run_attempt}")

  workflow_name=$(printf '%s' "${run_json}" | jq -r '.name')
  workflow_path=$(printf '%s' "${run_json}" | jq -r '.path')
  head_branch=$(printf '%s' "${run_json}" | jq -r '.head_branch')
  status=$(printf '%s' "${run_json}" | jq -r '.status')
  conclusion=$(printf '%s' "${run_json}" | jq -r '.conclusion')
  release_sha=$(printf '%s' "${run_json}" | jq -r '.head_sha')
  created_at=$(printf '%s' "${run_json}" | jq -r '.created_at')

  [ "${workflow_name}" = "build-all-images" ] || fail "Expected build-all-images run, got '${workflow_name}'"
  [ "${workflow_path}" = ".github/workflows/build-all-images.yaml" ] || fail "Unexpected workflow path '${workflow_path}'"
  [ "${head_branch}" = "main" ] || fail "Source build must come from main branch (got '${head_branch}')"
  [ "${status}" = "completed" ] || fail "Source build must be completed (got '${status}')"
  [ "${conclusion}" = "success" ] || fail "Source build must succeed (got '${conclusion}')"

  created_epoch=$(date -u -d "${created_at}" +%s)
  now_epoch=$(date -u +%s)
  max_age_seconds=$((BUILD_AGE_MAX_DAYS * 24 * 60 * 60))
  if [ $((now_epoch - created_epoch)) -gt "${max_age_seconds}" ]; then
    fail "Build ${BUILD_TAG} is older than ${BUILD_AGE_MAX_DAYS} days and is no longer promotable"
  fi
}

download_build_metadata() {
  mkdir -p release-input/build release-input/scan
  gh run download "${run_id}" \
    --repo "${GITHUB_REPOSITORY}" \
    --name "build-metadata-${BUILD_TAG}" \
    --dir release-input/build
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

    if ! jq -e --arg build_tag "${BUILD_TAG}" '
      .build_tag == $build_tag and
      (.policy_sha | test("^[0-9a-f]{40}$")) and
      .scan_scope == "all" and
      (.scan_status == "passed" or .scan_status == "failed") and
      (.run_id | test("^[0-9]+$")) and
      (.run_attempt | test("^[0-9]+$")) and
      (.scanned_images | type == "array" and length > 0) and
      all(.scanned_images[];
        (.repo | type == "string" and length > 0) and
        (.target | type == "string" and length > 0) and
        (.ros_distro | type == "string" and length > 0) and
        (.digest | test("^sha256:[0-9a-f]{64}$")) and
        (.platform | test("^linux/(amd64|arm64)$")) and
        (.image_ref == (.repo + "@" + .digest))
      )
    ' release-input/scan/scan-metadata.json >/dev/null 2>&1; then
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
      [ "${scan_head_branch}" != "main" ] || \
      [ "${scan_status}" != "completed" ]; then
      echo "Ignoring scan artifact ${scan_artifact_id}: scan run ${scan_run_id}-${scan_run_attempt} is not a completed scan-images run on main" >&2
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

validate_build_metadata_schema() {
  if ! jq -e \
    --arg build_tag "${BUILD_TAG}" \
    --arg run_id "${run_id}" \
    --arg run_attempt "${run_attempt}" '
    .build_tag == $build_tag and
    .run_id == $run_id and
    .run_attempt == $run_attempt and
    (.openadkit_sha | test("^[0-9a-f]{40}$")) and
    (.autoware_input_ref | type == "string" and length > 0) and
    (.autoware_ref_type as $type | ["branch", "tag", "sha", "ref"] | index($type) != null) and
    (.autoware_ref | test("^[0-9a-f]{40}$")) and
    (.autoware_base_version | test("^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")) and
    (.autoware_lock_sha256 | test("^[0-9a-f]{64}$")) and
    (.image_inventory_sha256 | test("^[0-9a-f]{64}$")) and
    (.upstream_images_sha256 | test("^[0-9a-f]{64}$")) and
    (.scan_requested | type == "boolean") and
    (.images | type == "array" and length > 0) and
    all(.images[];
      (.repo | type == "string" and length > 0) and
      (.target | type == "string" and length > 0) and
      (.ros_distro | type == "string" and length > 0) and
      (.digest | test("^sha256:[0-9a-f]{64}$")) and
      (.ref == (.repo + ":" + .target + "-" + .ros_distro + "-" + $build_tag)) and
      (.platforms | type == "array" and length > 0) and
      all(.platforms[]; test("^linux/(amd64|arm64)$"))
    ) and
    (.upstream_images | type == "array" and length > 0) and
    all(.upstream_images[];
      (.name | IN("core-devel", "base", "base-cuda-runtime", "base-cuda-devel")) and
      (.ros_distro | type == "string" and length > 0) and
      (.ref | type == "string" and length > 0) and
      (.digest | test("^sha256:[0-9a-f]{64}$")) and
      .uri == ("docker-image://" + .ref + "@" + .digest)
    )
  ' release-input/build/build-metadata.json >/dev/null; then
    fail "Build metadata failed schema validation"
  fi
}

validate_metadata_files() {
  local metadata_lock_sha actual_lock_sha metadata_inventory_sha actual_inventory_sha
  local metadata_upstream_sha actual_upstream_sha

  [ -f release-input/build/autoware-lock.repos ] || fail "Build metadata is missing autoware-lock.repos"
  metadata_lock_sha=$(jq -r '.autoware_lock_sha256' release-input/build/build-metadata.json)
  actual_lock_sha=$(sha256sum release-input/build/autoware-lock.repos | cut -d ' ' -f1)
  [ "${actual_lock_sha}" = "${metadata_lock_sha}" ] \
    || fail "Autoware lock SHA ${actual_lock_sha} does not match metadata SHA ${metadata_lock_sha}"

  [ -f release-input/build/image-inventory.json ] || fail "Build metadata is missing image-inventory.json"
  metadata_inventory_sha=$(jq -r '.image_inventory_sha256' release-input/build/build-metadata.json)
  actual_inventory_sha=$(sha256sum release-input/build/image-inventory.json | cut -d ' ' -f1)
  [ "${actual_inventory_sha}" = "${metadata_inventory_sha}" ] \
    || fail "Image inventory SHA ${actual_inventory_sha} does not match metadata SHA ${metadata_inventory_sha}"

  [ -f release-input/build/upstream-images.json ] || fail "Build metadata is missing upstream-images.json"
  metadata_upstream_sha=$(jq -r '.upstream_images_sha256' release-input/build/build-metadata.json)
  actual_upstream_sha=$(sha256sum release-input/build/upstream-images.json | cut -d ' ' -f1)
  [ "${actual_upstream_sha}" = "${metadata_upstream_sha}" ] \
    || fail "Upstream image metadata SHA ${actual_upstream_sha} does not match metadata SHA ${metadata_upstream_sha}"
  cmp <(jq -S . release-input/build/upstream-images.json) \
    <(jq -S '.upstream_images' release-input/build/build-metadata.json) \
    || fail "Embedded upstream image metadata does not match upstream-images.json"
}

validate_inventory_coverage() {
  local expected_inventory actual_inventory expected_count actual_count actual_unique_count
  local missing_inventory extra_inventory

  expected_inventory=$(mktemp)
  actual_inventory=$(mktemp)
  jq -r \
    --arg common_repo "${IMAGE_PREFIX_COMMON}" \
    --arg component_repo "${IMAGE_PREFIX_COMPONENT}" '
    def repo_for($kind): if $kind == "common" then $common_repo elif $kind == "component" then $component_repo else error("unsupported repo kind") end;
    def image_distros($global): .ros_distros // $global;
    .ros_distros as $global |
    .images[] |
    image_distros($global)[] as $distro |
    [repo_for(.repo), .target, $distro, (.platforms | sort | join(","))] |
    @tsv
  ' release-input/build/image-inventory.json | sort -u > "${expected_inventory}"
  jq -r '
    .images[] |
    [.repo, .target, .ros_distro, (.platforms | sort | join(","))] |
    @tsv
  ' release-input/build/build-metadata.json | sort -u > "${actual_inventory}"

  expected_count=$(wc -l < "${expected_inventory}" | tr -d ' ')
  actual_count=$(jq -r '.images | length' release-input/build/build-metadata.json)
  actual_unique_count=$(wc -l < "${actual_inventory}" | tr -d ' ')
  missing_inventory=$(comm -23 "${expected_inventory}" "${actual_inventory}" || true)
  extra_inventory=$(comm -13 "${expected_inventory}" "${actual_inventory}" || true)
  rm -f "${expected_inventory}" "${actual_inventory}"

  [ "${actual_count}" = "${actual_unique_count}" ] || fail "Build metadata contains duplicate image entries"
  [ "${actual_count}" = "${expected_count}" ] \
    || fail "Build metadata image count ${actual_count} does not match inventory count ${expected_count}"
  if [ -n "${missing_inventory}" ]; then
    echo "Build metadata is missing inventory entries:" >&2
    printf '%s\n' "${missing_inventory}" >&2
    exit 1
  fi
  if [ -n "${extra_inventory}" ]; then
    echo "Build metadata contains entries outside inventory:" >&2
    printf '%s\n' "${extra_inventory}" >&2
    exit 1
  fi
}

validate_upstream_coverage() {
  local expected actual base_version expected_count actual_count
  expected=$(mktemp)
  actual=$(mktemp)
  base_version=$(jq -r '.autoware_base_version' release-input/build/build-metadata.json)

  jq -r --arg version "${base_version}" '
    .ros_distros[] as $distro |
    ["core-devel", "base", "base-cuda-runtime", "base-cuda-devel"][] as $name |
    [$name, $distro, ("ghcr.io/autowarefoundation/autoware:" + $name + "-" + $distro + "-" + $version)] |
    @tsv
  ' release-input/build/image-inventory.json | sort -u >"${expected}"
  jq -r '.upstream_images[] | [.name, .ros_distro, .ref] | @tsv' \
    release-input/build/build-metadata.json | sort -u >"${actual}"

  expected_count=$(wc -l <"${expected}" | tr -d ' ')
  actual_count=$(jq '.upstream_images | length' release-input/build/build-metadata.json)
  if [ "${actual_count}" != "${expected_count}" ] || ! cmp "${expected}" "${actual}"; then
    diff -u "${expected}" "${actual}" >&2 || true
    rm -f "${expected}" "${actual}"
    fail "Upstream image metadata does not cover every required Autoware base"
  fi
  rm -f "${expected}" "${actual}"
}

validate_scan_coverage() {
  local build_coverage scan_coverage missing_coverage extra_coverage build_sha policy_sha

  build_sha=$(jq -r '.openadkit_sha' release-input/build/build-metadata.json)
  policy_sha=$(jq -r '.policy_sha' release-input/scan/scan-metadata.json)
  [ "${policy_sha}" = "${build_sha}" ] \
    || fail "Scan policy SHA ${policy_sha} does not match build SHA ${build_sha}"

  build_coverage=$(mktemp)
  scan_coverage=$(mktemp)
  jq -r '
    .images[] as $image |
    $image.platforms[] |
    [$image.repo, $image.target, $image.ros_distro, $image.digest, .] |
    @tsv
  ' release-input/build/build-metadata.json | sort -u > "${build_coverage}"
  jq -r '
    .scanned_images[] |
    [.repo, .target, .ros_distro, .digest, .platform] |
    @tsv
  ' release-input/scan/scan-metadata.json | sort -u > "${scan_coverage}"

  missing_coverage=$(comm -23 "${build_coverage}" "${scan_coverage}" || true)
  extra_coverage=$(comm -13 "${build_coverage}" "${scan_coverage}" || true)
  rm -f "${build_coverage}" "${scan_coverage}"
  if [ -n "${missing_coverage}" ]; then
    echo "Scan metadata is missing build digest/platform coverage:" >&2
    printf '%s\n' "${missing_coverage}" >&2
    exit 1
  fi
  if [ -n "${extra_coverage}" ]; then
    echo "Scan metadata contains digest/platform entries outside build metadata:" >&2
    printf '%s\n' "${extra_coverage}" >&2
    exit 1
  fi
}

validate_release_rules() {
  local metadata_sha autoware_input_ref autoware_ref_type autoware_base_version

  metadata_sha=$(jq -r '.openadkit_sha' release-input/build/build-metadata.json)
  [ "${metadata_sha}" = "${release_sha}" ] \
    || fail "Build metadata SHA ${metadata_sha} does not match workflow SHA ${release_sha}"

  autoware_input_ref=$(jq -r '.autoware_input_ref' release-input/build/build-metadata.json)
  autoware_ref_type=$(jq -r '.autoware_ref_type' release-input/build/build-metadata.json)
  autoware_base_version=$(jq -r '.autoware_base_version' release-input/build/build-metadata.json)
  if [ "${autoware_ref_type}" = "tag" ]; then
    printf '%s\n' "${autoware_input_ref}" | grep -Eq "${autoware_stable_re}" \
      || fail "Autoware release tags must use X.Y.Z format (got ${autoware_input_ref})"
    [ "${autoware_base_version}" = "${autoware_input_ref}" ] \
      || fail "Autoware base version ${autoware_base_version} does not match release tag ${autoware_input_ref}"
  elif ! printf '%s\n' "${VERSION}" | grep -Eq "${openadkit_stable_re}" \
    && [ "${autoware_ref_type}" = "sha" ] \
    && printf '%s\n' "${autoware_input_ref}" | grep -Eq '^[0-9a-fA-F]{40}$'; then
    :
  elif printf '%s\n' "${VERSION}" | grep -Eq "${openadkit_stable_re}"; then
    fail "Stable releases must be built from an Autoware release tag (got ${autoware_ref_type}:${autoware_input_ref})"
  else
    fail "Pre-releases must be built from an Autoware release tag or full SHA (got ${autoware_ref_type}:${autoware_input_ref})"
  fi
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
  local conflicts repo target distro ref digest source_digest release_ref existing_digest lookup_status

  conflicts=0
  while IFS=$'\t' read -r repo target distro ref digest; do
    lookup_status=0
    source_digest=$(registry_manifest_digest "${ref}") || lookup_status=$?
    if [ "${lookup_status}" -eq 1 ]; then
      echo "Source image not found: ${ref}" >&2
      return 1
    elif [ "${lookup_status}" -ne 0 ]; then
      return "${lookup_status}"
    fi
    if [ "${source_digest}" != "${digest}" ]; then
      echo "Source digest mismatch for ${ref}: ${source_digest} != ${digest}" >&2
      conflicts=1
    fi

    release_ref="${repo}:${target}-${distro}-${VERSION}"
    lookup_status=0
    existing_digest=$(registry_manifest_digest "${release_ref}") || lookup_status=$?
    if [ "${lookup_status}" -eq 0 ]; then
      if [ "${existing_digest}" != "${digest}" ]; then
        echo "Release tag conflict: ${release_ref} points to ${existing_digest}, expected ${digest}" >&2
        conflicts=1
      fi
    elif [ "${lookup_status}" -ne 1 ]; then
      return "${lookup_status}"
    fi
  done < <(jq -r '.images[] | [.repo, .target, .ros_distro, .ref, .digest] | @tsv' release-input/build/build-metadata.json)

  [ "${conflicts}" -eq 0 ] || exit 1
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
  download_build_metadata
  select_scan_metadata
  validate_build_metadata_schema
  validate_metadata_files
  validate_inventory_coverage
  validate_upstream_coverage
  validate_scan_coverage
  validate_release_rules
  validate_git_tag
  validate_registry_conflicts
  write_outputs
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main
fi
