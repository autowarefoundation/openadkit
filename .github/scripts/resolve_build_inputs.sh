#!/usr/bin/env bash
# Resolve shared build inputs for build-all-images and build-single-image.
# Writes GitHub Actions outputs directly to GITHUB_OUTPUT.
#
# .github/autoware.ref names the Autoware release tag (such as 2.0.0) whose
# sources and upstream images the build uses.
set -euo pipefail

: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
: "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
: "${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required}"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=.github/scripts/registry_lookup.sh
# shellcheck disable=SC1091
source "${script_dir}/registry_lookup.sh"

autoware_input_ref=$(cat .github/autoware.ref)
[ -n "${autoware_input_ref}" ] || { echo "The Autoware pin is empty" >&2; exit 1; }
build_tag="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
# Registry caches per branch, so main and a maintenance branch do not evict
# each other; pull requests read their base branch's.
cache_scope=$(printf '%s' "${GITHUB_BASE_REF:-${GITHUB_REF_NAME:?GITHUB_REF_NAME is required}}" | tr -c 'A-Za-z0-9_.-' '-')

git init autoware-metadata >&2
if git -C autoware-metadata remote get-url origin >/dev/null 2>&1; then
  git -C autoware-metadata remote set-url origin https://github.com/autowarefoundation/autoware
else
  git -C autoware-metadata remote add origin https://github.com/autowarefoundation/autoware
fi

printf '%s\n' "${autoware_input_ref}" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' \
  || { echo "The Autoware pin must be a release tag such as 2.0.0 (got '${autoware_input_ref}')" >&2; exit 1; }
git -C autoware-metadata ls-remote --exit-code origin "refs/tags/${autoware_input_ref}" >/dev/null 2>&1 \
  || { echo "Autoware has no release tag ${autoware_input_ref}" >&2; exit 1; }

git -C autoware-metadata fetch --filter=blob:none --force origin "refs/tags/${autoware_input_ref}"
git -C autoware-metadata checkout --detach FETCH_HEAD
autoware_ref=$(git -C autoware-metadata rev-parse HEAD)

{
  echo "autoware_input_ref=${autoware_input_ref}"
  echo "autoware_ref_type=tag"
  echo "autoware_ref=${autoware_ref}"
  echo "autoware_base_version=${autoware_input_ref}"
  echo "upstream_tag=${autoware_input_ref}"
  echo "cache_scope=${cache_scope}"
  echo "build_tag=${build_tag}"
} >> "${GITHUB_OUTPUT}"
