#!/usr/bin/env bash
# Resolve shared build inputs for build-all-images and build-single-image.
# Writes GitHub Actions outputs directly to GITHUB_OUTPUT.
#
# .github/autoware.ref selects the Autoware sources: a release tag builds on
# that release's upstream images. A branch name builds on upstream's
# development manifest, resolved anew each build, for experiments.
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

fetch_ref="${autoware_input_ref}"
autoware_ref_type="ref"
if git -C autoware-metadata ls-remote --exit-code origin "refs/heads/${autoware_input_ref}" >/dev/null 2>&1; then
  fetch_ref="refs/heads/${autoware_input_ref}"
  autoware_ref_type="branch"
elif git -C autoware-metadata ls-remote --exit-code origin "refs/tags/${autoware_input_ref}" >/dev/null 2>&1; then
  fetch_ref="refs/tags/${autoware_input_ref}"
  autoware_ref_type="tag"
else
  alt_tag=""
  if printf '%s\n' "${autoware_input_ref}" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+'; then
    alt_tag="${autoware_input_ref#v}"
  elif printf '%s\n' "${autoware_input_ref}" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+'; then
    alt_tag="v${autoware_input_ref}"
  fi
  if [ -n "${alt_tag}" ] && git -C autoware-metadata ls-remote --exit-code origin "refs/tags/${alt_tag}" >/dev/null 2>&1; then
    fetch_ref="refs/tags/${alt_tag}"
    autoware_ref_type="tag"
  fi
fi

if [ "${autoware_ref_type}" = "ref" ]; then
  echo "Could not resolve '${autoware_input_ref}' as a branch or tag in the Autoware repository" >&2
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
if printf '%s\n' "${autoware_input_ref}" | grep -Eq '^v?[0-9]+\.[0-9]+\.[0-9]+$'; then
  autoware_base_version="${autoware_input_ref#v}"
fi
[ -n "${autoware_base_version}" ] || {
  echo "Could not infer Autoware base version from ${autoware_input_ref}" >&2
  exit 1
}

# Release builds use that release's upstream images; a development branch
# compiles core itself from upstream's development manifest.
upstream_tag=""
autoware_overlay=autoware-metadata/repositories/autoware-nightly.repos
if [ "${autoware_ref_type}" = tag ]; then
  upstream_tag="${autoware_base_version}"
  autoware_overlay=""
elif [ ! -f "${autoware_overlay}" ]; then
  echo "Development manifest not found: ${autoware_overlay}" >&2
  exit 1
fi

{
  echo "autoware_input_ref=${autoware_input_ref}"
  echo "autoware_ref_type=${autoware_ref_type}"
  echo "autoware_ref=${autoware_ref}"
  echo "autoware_base_version=${autoware_base_version}"
  echo "upstream_tag=${upstream_tag}"
  echo "autoware_overlay=${autoware_overlay}"
  echo "cache_scope=${cache_scope}"
  echo "build_tag=${build_tag}"
} >> "${GITHUB_OUTPUT}"
