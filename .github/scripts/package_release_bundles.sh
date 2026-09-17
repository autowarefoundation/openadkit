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
plan_file=release-plan.json

rm -rf dist staging
mkdir -p dist "${bundle_root}/deployments"

python3 "${planner}" \
  --source-root "${source_dir}" \
  --build-metadata "${build_metadata}" \
  --version "${VERSION}" \
  --release-sha "${RELEASE_SHA}" \
  --packager-sha "${PACKAGER_SHA}" \
  --default-ros-distro "${DEFAULT_ROS_DISTRO}" \
  --stable-release "${STABLE_RELEASE}" \
  --publish-latest-aliases "${PUBLISH_LATEST_ALIASES}" \
  --output "${plan_file}"

while IFS= read -r item; do
  cp -a "${source_dir}/${item}" "${bundle_root}/${item}"
done < <(jq -r '.bundle.runtime[]' "${plan_file}")

while IFS= read -r path; do
  mkdir -p "${bundle_root}/$(dirname "${path}")"
  cp -a "${source_dir}/${path}" "${bundle_root}/${path}"
done < <(jq -r '.releaseContext.deployments[].path' "${plan_file}")

while IFS= read -r item; do
  cp -a "${source_dir}/deployments/${item}" "${bundle_root}/deployments/${item}"
done < <(jq -r '.bundle.shared[]' "${plan_file}")

find "${bundle_root}" -type f \( -name config.local.env -o -name '*.pyc' \) -delete
find "${bundle_root}" -type d -name __pycache__ -prune -exec rm -rf {} +
if symlink=$(find "${bundle_root}" -type l -print -quit) && [ -n "${symlink}" ]; then
  echo "Release bundle must not contain symlinks: ${symlink}" >&2
  exit 1
fi

python3 "${planner}" \
  --verify \
  --source-root "${bundle_root}" \
  --output "${plan_file}" \
  --context-output "${bundle_root}/openadkit.json"

(cd "${bundle_root}" && ./openadkit list)
cp -a "${source_dir}/openadkit" dist/openadkit

while IFS=$'\t' read -r deployment ros_distro gpu; do
  validate_args=(./openadkit validate "${deployment}" --ros-distro "${ros_distro}")
  if [ "${gpu}" = true ]; then
    validate_args+=(--gpu)
  fi
  (cd "${bundle_root}" && "${validate_args[@]}")
done < <(jq -r '.bundle.validation[] | [.deployment, .rosDistro, (.gpu | tostring)] | @tsv' "${plan_file}")

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
