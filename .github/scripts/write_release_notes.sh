#!/usr/bin/env bash
# Write release metadata and notes from the immutable release plan.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

plan_file=${RELEASE_PLAN_FILE:-release-plan.json}
# release_plan.py validated this plan. It also plans evidence kits, which
# carry no evidence: release notes need the release's own PASSED summary.
jq -e '
  .schemaVersion == 1 and
  .evidence.result == "PASSED" and
  .evidence.build_tag == .release.buildTag and
  .evidence.source_sha == .release.releaseSha
' "${plan_file}" >/dev/null

VERSION=$(jq -r '.release.version' "${plan_file}")
RELEASE_SHA=$(jq -r '.release.releaseSha' "${plan_file}")
DEFAULT_ROS_DISTRO=$(jq -r '.release.defaultRosDistro' "${plan_file}")
PUBLISH_LATEST_ALIASES=$(jq -r '.release.publishLatestAliases' "${plan_file}")
bundle_name=$(jq -r '.bundle.asset' "${plan_file}")
bundle="dist/${bundle_name}"

bundle_sha256=$(sha256sum "${bundle}" | cut -d ' ' -f1)
jq \
  --arg version "${VERSION}" \
  --arg release_sha "${RELEASE_SHA}" \
  --arg default_ros_distro "${DEFAULT_ROS_DISTRO}" \
  --arg bundle_name "${bundle_name}" \
  --arg bundle_sha256 "${bundle_sha256}" \
  --argjson publish_latest_aliases "${PUBLISH_LATEST_ALIASES}" \
  --slurpfile scan release-input/scan/scan-metadata.json \
  --argjson evidence "$(jq -c '.evidence' "${plan_file}")" \
  --argjson bom "$(jq -c '(.releaseContext | {autoware, images, externalImages}) + {rosSnapshots}' "${plan_file}")" \
  '. + {
    version: $version,
    release_sha: $release_sha,
    default_ros_distro: $default_ros_distro,
    bundles: [{name: $bundle_name, sha256: $bundle_sha256}],
    latest_aliases_updated: $publish_latest_aliases,
    scan: $scan[0],
    evidence: $evidence,
    bom: $bom
  }' \
  release-input/build/build-metadata.json >release-metadata.json

python3 "${script_dir}/release_notes.py" --plan "${plan_file}" --highlights-dir "${script_dir}/../release-highlights"
