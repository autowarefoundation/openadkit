#!/usr/bin/env bash
# Write release metadata and notes from the immutable release plan.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

plan_file=${RELEASE_PLAN_FILE:-release-plan.json}
# release_plan.py validated this plan, and the workflow checks its digest
# before every use. It also plans evidence kits, which carry no evidence:
# release notes need the release's own PASSED summary.
jq -e '
  .schemaVersion == 1 and
  .evidence.result == "PASSED" and
  .evidence.build_tag == .release.buildTag and
  .evidence.source_sha == .release.releaseSha
' "${plan_file}" >/dev/null

VERSION=$(jq -r '.release.version' "${plan_file}")
RELEASE_SHA=$(jq -r '.release.releaseSha' "${plan_file}")
DEFAULT_ROS_DISTRO=$(jq -r '.release.defaultRosDistro' "${plan_file}")
PACKAGER_SHA=$(jq -r '.release.packagerSha' "${plan_file}")
PUBLISH_LATEST_ALIASES=$(jq -r '.release.publishLatestAliases' "${plan_file}")
bundle_name=$(jq -r '.bundle.asset' "${plan_file}")
bundle_root=$(jq -r '.bundle.root' "${plan_file}")
bundle="dist/${bundle_name}"
installer="dist/openadkit"

[ -f "${bundle}" ] || {
  echo "Expected release bundle is missing: ${bundle}" >&2
  exit 1
}
[ -f "${installer}" ] || {
  echo "Expected release installer is missing: ${installer}" >&2
  exit 1
}
mapfile -t archives < <(find dist -maxdepth 1 -type f -name '*.tar.gz' -printf '%f\n' | sort)
if [ "${#archives[@]}" -ne 1 ] || [ "${archives[0]}" != "${bundle_name}" ]; then
  echo "dist/ must contain exactly the planned release bundle" >&2
  exit 1
fi

temporary=$(mktemp -d)
trap 'rm -rf "${temporary}"' EXIT
tar -xOf "${bundle}" "${bundle_root}/openadkit.json" \
  | jq -S . >"${temporary}/bundle-context.json"
jq -S '.releaseContext' "${plan_file}" >"${temporary}/plan-context.json"
cmp "${temporary}/plan-context.json" "${temporary}/bundle-context.json"

bundle_sha256=$(sha256sum "${bundle}" | cut -d ' ' -f1)
installer_sha256=$(sha256sum "${installer}" | cut -d ' ' -f1)
plan_sha256=$(sha256sum "${plan_file}" | cut -d ' ' -f1)
jq \
  --arg version "${VERSION}" \
  --arg release_sha "${RELEASE_SHA}" \
  --arg default_ros_distro "${DEFAULT_ROS_DISTRO}" \
  --arg packager_sha "${PACKAGER_SHA}" \
  --arg plan_sha256 "${plan_sha256}" \
  --arg bundle_name "${bundle_name}" \
  --arg bundle_sha256 "${bundle_sha256}" \
  --argjson publish_latest_aliases "${PUBLISH_LATEST_ALIASES}" \
  --slurpfile scan release-input/scan/scan-metadata.json \
  --argjson evidence_exempt "$(jq -c '.evidence.exempt' "${plan_file}")" \
  --argjson evidence "$(jq -c '.evidence' "${plan_file}")" \
  --argjson bom "$(jq -c '(.releaseContext | {autoware, images, artifacts}) + {rosSnapshots}' "${plan_file}")" \
  '. + {
    openadkit_version: $version,
    release_sha: $release_sha,
    default_ros_distro: $default_ros_distro,
    packager_sha: $packager_sha,
    release_plan_sha256: $plan_sha256,
    bundles: [{name: $bundle_name, sha256: $bundle_sha256}],
    latest_aliases_updated: $publish_latest_aliases,
    scan: $scan[0],
    evidence_exempt: $evidence_exempt,
    evidence: $evidence,
    bom: $bom
  }' \
  release-input/build/build-metadata.json >release-metadata.json

jq -e '
  (.release_sha | test("^[0-9a-f]{40}$")) and
  (.packager_sha | test("^[0-9a-f]{40}$")) and
  (.release_plan_sha256 | test("^[0-9a-f]{64}$")) and
  .release_sha == .openadkit_sha and
  (.latest_aliases_updated | type == "boolean") and
  (.bundles | type == "array" and length == 1) and
  all(.bundles[];
    (.name | test("^[^/]+\\.tar\\.gz$")) and
    (.sha256 | test("^[0-9a-f]{64}$"))
  )
' release-metadata.json >/dev/null

autoware_input_ref=$(jq -r '.autoware_input_ref' release-metadata.json)
autoware_ref_type=$(jq -r '.autoware_ref_type' release-metadata.json)
autoware_ref=$(jq -r '.autoware_ref' release-metadata.json)
autoware_base_version=$(jq -r '.autoware_base_version' release-metadata.json)
autoware_lock_sha256=$(jq -r '.autoware_lock_sha256' release-metadata.json)
upstream_images_sha256=$(jq -r '.upstream_images_sha256' release-metadata.json)
ros_snapshots=$(jq -r '.bom.rosSnapshots | to_entries | map("\(.key) `\(.value)`") | join(", ")' release-metadata.json)
openadkit_sha=$(jq -r '.openadkit_sha' release-metadata.json)
build_tag=$(jq -r '.build_tag' release-metadata.json)

{
  echo '<!-- openadkit-release-workflow:v1 -->'
  echo ""
  echo "Open AD Kit ${VERSION} builds on Autoware ${autoware_base_version}. Every v$(printf '%s' "${VERSION#v}" | cut -d. -f1-2).x release builds on Autoware $(printf '%s' "${autoware_base_version}" | cut -d. -f1-2).x."
  echo ""
  echo "## Provenance"
  echo "| Key | Value |"
  echo "|-----|-------|"
  echo "| OpenADKit version | \`${VERSION}\` |"
  echo "| OpenADKit SHA | \`${openadkit_sha}\` |"
  echo "| Build tag | \`${build_tag}\` |"
  echo "| Packager SHA | \`${PACKAGER_SHA}\` |"
  echo "| Release plan SHA256 | \`${plan_sha256}\` |"
  echo "| Autoware input ref | \`${autoware_input_ref}\` |"
  echo "| Autoware ref type | \`${autoware_ref_type}\` |"
  echo "| Autoware resolved SHA | \`${autoware_ref}\` |"
  echo "| Autoware base version | \`${autoware_base_version}\` |"
  echo "| Autoware lock SHA256 | \`${autoware_lock_sha256}\` |"
  echo "| Upstream images SHA256 | \`${upstream_images_sha256}\` |"
  echo "| ROS snapshots | ${ros_snapshots} |"
  echo ""
  # Fixes this release line carries on top of the Autoware tag.
  backports=$(jq -r '.releaseContext.autoware.backports // [] | .[]
    | "- \(.subject) (`\(.repository)`): \(.upstream)"' "${plan_file}")
  if [ -n "${backports}" ]; then
    echo "## Backported Autoware fixes"
    echo ""
    echo "On top of Autoware ${autoware_base_version}, from upstream:"
    echo ""
    echo "${backports}"
    echo ""
  fi
  echo "## Open AD Kit Bundle"
  echo "| Asset | SHA256 |"
  echo "|-------|--------|"
  printf '%s\n' "| \`${bundle_name}\` | \`${bundle_sha256}\` |"
  printf '%s\n' "| \`openadkit\` | \`${installer_sha256}\` |"
  echo ""
  echo "## Install"
  echo ""
  echo "The versionless \`openadkit\` asset is the installer for this release:"
  echo ""
  echo '```bash'
  echo "curl -fsSL https://github.com/${GITHUB_REPOSITORY}/releases/download/${VERSION}/openadkit \\"
  echo "  | bash -s -- install --version ${VERSION}"
  echo '```'
  echo ""
  echo "## Images"
  while IFS=$'\t' read -r release_ref digest; do
    printf '%s\n' "- \`${release_ref}\` -> \`${digest}\`"
  done < <(jq -r '.images[] | [.releaseRef, .digest] | @tsv' "${plan_file}")

  echo ""
  echo "## Verification"
  echo ""
  jq '.evidence' "${plan_file}" >"${temporary}/current.json"
  python3 "${script_dir}/evidence/report.py" --current "${temporary}/current.json"
  echo ""
  echo "Default ROS distro: \`${DEFAULT_ROS_DISTRO}\`, selected in the release source manifest and covered by passing evidence."
  echo ""
  echo "Evidence run: $(jq -r '.evidence.url // "not recorded"' "${plan_file}")"
  echo "See [release verification](https://autowarefoundation.github.io/openadkit/releases/verification/) for how to verify the release."
  if [ "$(jq '.evidence.exempt | length' "${plan_file}")" -gt 0 ]; then
    echo ""
    echo "Not verified in CI (the CLI warns when you run these):"
    echo ""
    while IFS=$'\t' read -r deployment reason; do
      printf '%s\n' "- \`${deployment}\`: ${reason}"
    done < <(jq -r '.evidence.exempt[] | [.deployment, .reason] | @tsv' "${plan_file}")
  fi
  echo ""
  if [ "${PUBLISH_LATEST_ALIASES}" = true ]; then
    echo ""
    echo "## Stable Aliases"
    while IFS=$'\t' read -r alias digest; do
      printf '%s\n' "- \`${alias}\` -> \`${digest}\`"
    done < <(jq -r '.images[] | .digest as $digest | .aliases[] | [., $digest] | @tsv' "${plan_file}")
  elif [ "$(jq -r '.release.stable' "${plan_file}")" = true ]; then
    echo ""
    echo "## Stable Aliases"
    echo "Not updated because a newer stable OpenADKit release already exists."
  fi
} >release-notes.md
