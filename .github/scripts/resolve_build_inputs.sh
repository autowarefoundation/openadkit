#!/usr/bin/env bash
# Resolve shared build inputs for build-all-images.
# Writes GitHub Actions outputs directly to GITHUB_OUTPUT.
set -euo pipefail

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required}"
: "${GITHUB_EVENT_NAME:?GITHUB_EVENT_NAME is required}"

autoware_input_ref="${AUTOWARE_REF_INPUT:-main}"
build_tag="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"

scan_requested=false
if [ "${GITHUB_EVENT_NAME}" = "schedule" ]; then
  scan_requested=true
elif [ "${GITHUB_EVENT_NAME}" = "workflow_dispatch" ] && [ "${RUN_SCAN_INPUT:-false}" = "true" ]; then
  scan_requested=true
fi

git init autoware-metadata >&2
if git -C autoware-metadata remote get-url origin >/dev/null 2>&1; then
  git -C autoware-metadata remote set-url origin https://github.com/autowarefoundation/autoware
else
  git -C autoware-metadata remote add origin https://github.com/autowarefoundation/autoware
fi

fetch_ref="${autoware_input_ref}"
autoware_ref_type="ref"
if git -C autoware-metadata ls-remote --exit-code origin "refs/heads/${autoware_input_ref}" >/dev/null 2>&1; then
  fetch_ref="refs/heads/${autoware_input_ref}"
  autoware_ref_type="branch"
elif git -C autoware-metadata ls-remote --exit-code origin "refs/tags/${autoware_input_ref}" >/dev/null 2>&1; then
  fetch_ref="refs/tags/${autoware_input_ref}"
  autoware_ref_type="tag"
elif printf '%s\n' "${autoware_input_ref}" | grep -Eq '^[0-9a-fA-F]{40}$'; then
  autoware_ref_type="sha"
fi

if [ "${autoware_ref_type}" = "ref" ]; then
  echo "Could not resolve '${autoware_input_ref}' as a branch, tag, or SHA in the Autoware repository" >&2
  exit 1
fi

# Fetch the requested ref plus all tags so git describe can find the nearest semver tag.
# A single fetch keeps FETCH_HEAD pointed at the requested ref; a bare "git fetch --tags"
# would clobber FETCH_HEAD with the remote default branch and silently build from main.
git -C autoware-metadata fetch --filter=blob:none --tags --force origin "${fetch_ref}"
git -C autoware-metadata checkout --detach FETCH_HEAD

autoware_ref=$(git -C autoware-metadata rev-parse HEAD)
autoware_base_version=$(
  git -C autoware-metadata describe --tags --match 'v[0-9]*.[0-9]*.[0-9]*' --abbrev=0 2>/dev/null \
    || git -C autoware-metadata describe --tags --match '[0-9]*.[0-9]*.[0-9]*' --abbrev=0 2>/dev/null \
    || true
)
[ -n "${autoware_base_version}" ] || {
  echo "Could not infer Autoware base version from ${autoware_input_ref}" >&2
  exit 1
}

{
  echo "autoware_input_ref=${autoware_input_ref}"
  echo "autoware_ref_type=${autoware_ref_type}"
  echo "autoware_ref=${autoware_ref}"
  echo "autoware_base_version=${autoware_base_version}"
  echo "build_tag=${build_tag}"
  echo "scan_requested=${scan_requested}"
} >> "${GITHUB_OUTPUT}"
