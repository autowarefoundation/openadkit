#!/usr/bin/env bash
# Assemble and validate the unified Open AD Kit release bundle.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

: "${VERSION:?VERSION is required}"
: "${RELEASE_SHA:?RELEASE_SHA is required}"
: "${PACKAGER_SHA:?PACKAGER_SHA is required}"
: "${DEFAULT_ROS_DISTRO:?DEFAULT_ROS_DISTRO is required}"
: "${STABLE_RELEASE:?STABLE_RELEASE is required}"
: "${PUBLISH_LATEST_ALIASES:?PUBLISH_LATEST_ALIASES is required}"

source_dir=${SOURCE_DIR:-src}
build_metadata=${BUILD_METADATA_FILE:-release-input/build/build-metadata.json}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
planner=${RELEASE_PLAN_SCRIPT:-${script_dir}/release_plan.py}
root_name="openadkit-${VERSION}"
bundle_root="staging/${root_name}"
asset="dist/${root_name}.tar.gz"

rm -rf dist staging
mkdir -p dist "${bundle_root}/deployments"
cp -a "${source_dir}/openadkit" "${bundle_root}/openadkit"
cp -a "${source_dir}/openadkit.d" "${bundle_root}/openadkit.d"
for name in base logging-simulation planning-simulation scenario-simulation; do
  cp -a "${source_dir}/deployments/${name}" "${bundle_root}/deployments/${name}"
done

find "${bundle_root}" -type f \( -name config.local.env -o -name '*.pyc' \) -delete
find "${bundle_root}" -type d -name __pycache__ -prune -exec rm -rf {} +
if symlink=$(find "${bundle_root}" -type l -print -quit) && [ -n "${symlink}" ]; then
  echo "Release bundle must not contain symlinks: ${symlink}" >&2
  exit 1
fi

python3 "${planner}" \
  --source-root "${bundle_root}" \
  --build-metadata "${build_metadata}" \
  --version "${VERSION}" \
  --release-sha "${RELEASE_SHA}" \
  --packager-sha "${PACKAGER_SHA}" \
  --default-ros-distro "${DEFAULT_ROS_DISTRO}" \
  --stable-release "${STABLE_RELEASE}" \
  --publish-latest-aliases "${PUBLISH_LATEST_ALIASES}" \
  --output release-plan.json \
  --context-output "${bundle_root}/openadkit.d/context.json"

list_output=$(cd "${bundle_root}" && ./openadkit list)
printf '%s\n' "${list_output}"
for deployment in logging-simulation planning-simulation scenario-simulation; do
  if ! awk -F '\t' -v name="${deployment}" \
    '$1 == name && $2 == "verified" { found=1 } END { exit !found }' \
    <<<"${list_output}"; then
    echo "Packaged deployment is not verified: ${deployment}" >&2
    exit 1
  fi
done

for ros_distro in humble jazzy; do
  for deployment in planning-simulation scenario-simulation logging-simulation; do
    (cd "${bundle_root}" && ./openadkit validate "${deployment}" --ros-distro "${ros_distro}")
  done
  (cd "${bundle_root}" && ./openadkit validate logging-simulation \
    --ros-distro "${ros_distro}" --gpu)
done

if cache=$(find "${bundle_root}" \( -type d -name __pycache__ -o -type f -name '*.pyc' \) -print -quit) \
  && [ -n "${cache}" ]; then
  echo "Release bundle contains generated Python cache: ${cache}" >&2
  exit 1
fi

LC_ALL=C tar \
  --format=gnu \
  --sort=name \
  --mtime='@0' \
  --owner=0 \
  --group=0 \
  --numeric-owner \
  --mode='u+rwX,go+rX,go-w' \
  -C staging \
  -cf - \
  "${root_name}" \
  | gzip -n >"${asset}"
echo "packaged ${asset}"
