#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

# Stage a release-like kit from a build, so evidence runs use the exact image
# digests that build published instead of the moving prefix aliases. The kit is
# staged and verified by the same release_plan.py step that assembles release
# bundles, plus the example kits without their host colcon products.
#
# Usage: stage_kit.sh <source-root> <build-metadata.json> <kit-dir> <build-sha> [<source-sha>]
#
# <source-sha> is the commit of <source-root> when it is not the build's own,
# for a change tested against an existing build's images.

source_root=$1
metadata=$2
kit=$3
sha=$4
packager_sha=${5:-$4}

[ -f "${metadata}" ] || { echo "missing build metadata: ${metadata}" >&2; exit 1; }
[ -f "${source_root}/openadkit" ] || { echo "missing launcher under ${source_root}" >&2; exit 1; }

build_tag=$(jq -r '.build_tag' "${metadata}")
if [ -z "${build_tag}" ] || [ "${build_tag}" = "null" ]; then
    echo "build metadata has no build_tag" >&2
    exit 1
fi

planner="${source_root}/.github/scripts/release_plan.py"
plan="${kit}.release-plan.json"
rm -rf "${kit}"

python3 "${planner}" \
    --source-root "${source_root}" \
    --output "${plan}" \
    --build-metadata "${metadata}" \
    --version "v0.0.0-evidence.${build_tag}" \
    --release-sha "${sha}" \
    --packager-sha "${packager_sha}" \
    --stable-release false \
    --publish-latest-aliases false

python3 "${planner}" \
    --source-root "${source_root}" \
    --output "${plan}" \
    --stage "${kit}" \
    --include-example-kits

echo "staged evidence kit at ${kit} (build_tag ${build_tag})"
