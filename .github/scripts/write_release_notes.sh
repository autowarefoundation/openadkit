#!/usr/bin/env bash
# Write release metadata and notes from the immutable release plan.
set -euo pipefail

plan_file=${RELEASE_PLAN_FILE:-release-plan.json}
jq -e '
  .schemaVersion == 1 and
  (.release.version | type == "string") and
  (.release.releaseSha | test("^[0-9a-f]{40}$")) and
  (.release.packagerSha | test("^[0-9a-f]{40}$")) and
  (.bundle.asset | type == "string") and
  (.bundle.root | type == "string") and
  (.releaseContext.images.humble | length == 9) and
  (.releaseContext.images.jazzy | length == 9) and
  (.releaseContext.deployments | length == 4) and
  (.releaseContext.shared | length == 1)
' "${plan_file}" >/dev/null

VERSION=$(jq -r '.release.version' "${plan_file}")
RELEASE_SHA=$(jq -r '.release.releaseSha' "${plan_file}")
DEFAULT_ROS_DISTRO=$(jq -r '.release.defaultRosDistro' "${plan_file}")
PACKAGER_SHA=$(jq -r '.release.packagerSha' "${plan_file}")
PUBLISH_LATEST_ALIASES=$(jq -r '.release.publishLatestAliases' "${plan_file}")
bundle_name=$(jq -r '.bundle.asset' "${plan_file}")
bundle_root=$(jq -r '.bundle.root' "${plan_file}")
bundle="dist/${bundle_name}"

[ -f "${bundle}" ] || {
  echo "Expected release bundle is missing: ${bundle}" >&2
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
  '. + {
    openadkit_version: $version,
    release_sha: $release_sha,
    default_ros_distro: $default_ros_distro,
    packager_sha: $packager_sha,
    release_plan_sha256: $plan_sha256,
    bundles: [{name: $bundle_name, sha256: $bundle_sha256}],
    latest_aliases_updated: $publish_latest_aliases,
    scan: $scan[0]
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
openadkit_sha=$(jq -r '.openadkit_sha' release-metadata.json)
build_tag=$(jq -r '.build_tag' release-metadata.json)

{
  echo '<!-- openadkit-release-workflow:v1 -->'
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
  echo ""
  echo "## Open AD Kit Bundle"
  echo "| Asset | SHA256 |"
  echo "|-------|--------|"
  printf '%s\n' "| \`${bundle_name}\` | \`${bundle_sha256}\` |"
  echo ""
  echo "## Images"
  while IFS=$'\t' read -r release_ref digest; do
    printf '%s\n' "- \`${release_ref}\` -> \`${digest}\`"
  done < <(jq -r '.images[] | [.releaseRef, .digest] | @tsv' "${plan_file}")

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
