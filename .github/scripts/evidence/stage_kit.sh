#!/usr/bin/env bash
set -euo pipefail

# Stage a release-like kit from a build, so evidence runs use the exact image
# digests that build published instead of the moving prefix aliases. The layout
# mirrors a release bundle: openadkit.json (kind: release), cli/, openadkit,
# deployments/.
#
# Usage: stage_kit.sh <source-root> <build-metadata.json> <kit-dir> <source-sha>

source_root=$1
metadata=$2
kit=$3
sha=$4

[ -f "${metadata}" ] || { echo "missing build metadata: ${metadata}" >&2; exit 1; }
[ -f "${source_root}/openadkit" ] || { echo "missing launcher under ${source_root}" >&2; exit 1; }

build_tag=$(jq -r '.build_tag' "${metadata}")
if [ -z "${build_tag}" ] || [ "${build_tag}" = "null" ]; then
    echo "build metadata has no build_tag" >&2
    exit 1
fi

rm -rf "${kit}"
mkdir -p "${kit}"

python3 "${source_root}/.github/scripts/release_plan.py" \
    --source-root "${source_root}" \
    --output "${kit}.release-plan.json" \
    --context-output "${kit}/openadkit.json" \
    --build-metadata "${metadata}" \
    --version "v0.0.0-evidence.${build_tag}" \
    --release-sha "${sha}" \
    --packager-sha "${sha}" \
    --default-ros-distro humble \
    --stable-release false \
    --publish-latest-aliases false

cp "${source_root}/openadkit" "${kit}/openadkit"
cp -r "${source_root}/cli" "${kit}/cli"
cp -r "${source_root}/deployments" "${kit}/deployments"
if [ -d "${source_root}/examples" ]; then
    # Keep the relative extends path intact. Never stage an old workspace build.
    mkdir -p "${kit}/examples"
    tar -C "${source_root}/examples" --exclude=build --exclude=install --exclude=log \
        --exclude=__pycache__ -cf - . | tar -C "${kit}/examples" -xf -
fi

echo "staged evidence kit at ${kit} (build_tag ${build_tag})"
