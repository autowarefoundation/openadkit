#!/usr/bin/env bash
# Emit the build-all-images workflow summary as Markdown.
set -euo pipefail

: "${BUILD_TAG:?BUILD_TAG is required}"
: "${AUTOWARE_INPUT_REF:?AUTOWARE_INPUT_REF is required}"
: "${AUTOWARE_REF_TYPE:?AUTOWARE_REF_TYPE is required}"
: "${AUTOWARE_REF:?AUTOWARE_REF is required}"
: "${AUTOWARE_BASE_VERSION:?AUTOWARE_BASE_VERSION is required}"
: "${SCAN_REQUESTED:?SCAN_REQUESTED is required}"
: "${SOURCE_REF:?SOURCE_REF is required}"

echo "## Build Complete"
echo "| Key | Value |"
echo "|-----|-------|"
echo "| **build_tag** | \`${BUILD_TAG}\` |"
echo "| **autoware_input_ref** | \`${AUTOWARE_INPUT_REF}\` |"
echo "| **autoware_ref_type** | \`${AUTOWARE_REF_TYPE}\` |"
echo "| **autoware_ref** | \`${AUTOWARE_REF}\` |"
echo "| **autoware_base_version** | \`${AUTOWARE_BASE_VERSION}\` |"
echo "| **scan_requested** | \`${SCAN_REQUESTED}\` |"
echo ""
echo "## Release Eligibility"

autoware_stable_re='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
release_branch_re='^refs/heads/release/(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
if printf '%s\n' "${SOURCE_REF}" | grep -Eq "${release_branch_re}" \
  && [ "${AUTOWARE_REF_TYPE}" = "tag" ] \
  && printf '%s\n' "${AUTOWARE_INPUT_REF}" | grep -Eq "${autoware_stable_re}"; then
  echo "This build can be promoted within the ${SOURCE_REF#refs/heads/release/} OpenADKit release line after a passed full scan and source-pin validation."
  echo ""
  echo "To release this build, run **Actions -> release -> Run workflow** and set \`build_tag\` to \`${BUILD_TAG}\`."
elif [ "${SOURCE_REF}" = refs/heads/main ] \
  && { [ "${AUTOWARE_REF_TYPE}" = tag ] || [ "${AUTOWARE_REF_TYPE}" = sha ]; }; then
  echo "This build can only be promoted to a pre-release OpenADKit version after a passed full scan."
  echo ""
  echo "To pre-release this build, run **Actions -> release -> Run workflow** and set \`build_tag\` to \`${BUILD_TAG}\`."
else
  echo "This is a development build, not a release candidate. Stable releases require a release/X.Y source branch pinned to an Autoware SemVer tag."
fi

if [ "${SCAN_REQUESTED}" != "true" ]; then
  echo ""
  echo "If this build is otherwise release-eligible, run **Actions -> scan-images -> Run workflow** with \`build_tag\` set to \`${BUILD_TAG}\` before releasing."
fi
