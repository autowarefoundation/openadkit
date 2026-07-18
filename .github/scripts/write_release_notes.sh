#!/usr/bin/env bash
# Write release-metadata.json and release-notes.md from validated metadata.
set -euo pipefail

: "${VERSION:?VERSION is required}"
: "${RELEASE_SHA:?RELEASE_SHA is required}"
: "${DEFAULT_ROS_DISTRO:?DEFAULT_ROS_DISTRO is required}"
: "${PUBLISH_LATEST_ALIASES:?PUBLISH_LATEST_ALIASES is required}"
: "${STABLE_RELEASE:?STABLE_RELEASE is required}"
: "${PACKAGER_SHA:?PACKAGER_SHA is required}"

stable_release="${STABLE_RELEASE:-false}"
tab=$(printf "\t")
bundles_file=$(mktemp)
trap 'rm -f "${bundles_file}"' EXIT

for bundle in dist/*.tar.gz; do
  [ -f "${bundle}" ] || {
    echo "No release bundles found under dist/" >&2
    exit 1
  }
  jq -n \
    --arg name "$(basename "${bundle}")" \
    --arg sha256 "$(sha256sum "${bundle}" | cut -d ' ' -f1)" \
    '{name: $name, sha256: $sha256}'
done | jq -s 'sort_by(.name)' >"${bundles_file}"

jq \
  --arg version "${VERSION}" \
  --arg release_sha "${RELEASE_SHA}" \
  --arg default_ros_distro "${DEFAULT_ROS_DISTRO}" \
  --arg packager_sha "${PACKAGER_SHA}" \
  --argjson publish_latest_aliases "${PUBLISH_LATEST_ALIASES}" \
  --slurpfile bundles "${bundles_file}" \
  --slurpfile scan release-input/scan/scan-metadata.json \
  '. + {openadkit_version: $version, release_sha: $release_sha, default_ros_distro: $default_ros_distro, packager_sha: $packager_sha, bundles: $bundles[0], latest_aliases_updated: $publish_latest_aliases, scan: $scan[0]}' \
  release-input/build/build-metadata.json > release-metadata.json

jq -e '
  (.release_sha | test("^[0-9a-f]{40}$")) and
  (.packager_sha | test("^[0-9a-f]{40}$")) and
  .release_sha == .openadkit_sha and
  (.latest_aliases_updated | type == "boolean") and
  (.bundles | type == "array" and length > 0) and
  ([.bundles[].name] | length == (unique | length)) and
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
  echo "| Autoware input ref | \`${autoware_input_ref}\` |"
  echo "| Autoware ref type | \`${autoware_ref_type}\` |"
  echo "| Autoware resolved SHA | \`${autoware_ref}\` |"
  echo "| Autoware base version | \`${autoware_base_version}\` |"
  echo "| Autoware lock SHA256 | \`${autoware_lock_sha256}\` |"
  echo "| Upstream images SHA256 | \`${upstream_images_sha256}\` |"
  echo ""
  echo "## Deployment Bundles"
  echo "| Asset | SHA256 |"
  echo "|-------|--------|"
  while IFS="${tab}" read -r name sha256; do
    printf '| `%s` | `%s` |\n' "${name}" "${sha256}"
  done < <(jq -r '.bundles[] | [.name, .sha256] | @tsv' release-metadata.json)
  echo ""
  echo "## Images"
  while IFS="${tab}" read -r repo target distro digest; do
    printf -- "- \`%s:%s-%s-%s\` -> \`%s\`\n" "${repo}" "${target}" "${distro}" "${VERSION}" "${digest}"
  done < <(jq -r '.images[] | [.repo, .target, .ros_distro, .digest] | @tsv' release-metadata.json)

  if [ "${stable_release}" = "true" ] && [ "${PUBLISH_LATEST_ALIASES}" = "true" ]; then
    echo ""
    echo "## Stable Aliases"
    while IFS="${tab}" read -r repo target distro digest; do
      printf -- "- \`%s:%s-%s\` -> \`%s\`\n" "${repo}" "${target}" "${distro}" "${digest}"
      printf -- "- \`%s:%s-%s-latest\` -> \`%s\`\n" "${repo}" "${target}" "${distro}" "${digest}"
      if [ "${distro}" = "${DEFAULT_ROS_DISTRO}" ]; then
        printf -- "- \`%s:%s\` -> \`%s\`\n" "${repo}" "${target}" "${digest}"
        printf -- "- \`%s:%s-latest\` -> \`%s\`\n" "${repo}" "${target}" "${digest}"
      fi
    done < <(jq -r '.images[] | [.repo, .target, .ros_distro, .digest] | @tsv' release-metadata.json)
  elif [ "${stable_release}" = "true" ]; then
    echo ""
    echo "## Stable Aliases"
    echo "Not updated because a newer stable OpenADKit release already exists."
  fi
} > release-notes.md
