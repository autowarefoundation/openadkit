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
evidence_summary=${EVIDENCE_SUMMARY_FILE:-release-input/evidence-summary.json}
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
planner=${RELEASE_PLAN_SCRIPT:-${script_dir}/release_plan.py}
root_name="openadkit-${VERSION}"
bundle_root="staging/${root_name}"
asset="dist/${root_name}.tar.gz"
plan_file=release-plan.json

rm -rf dist staging
mkdir -p dist

python3 "${planner}" \
  --source-root "${source_dir}" \
  --build-metadata "${build_metadata}" \
  --evidence-summary "${evidence_summary}" \
  --version "${VERSION}" \
  --release-sha "${RELEASE_SHA}" \
  --packager-sha "${PACKAGER_SHA}" \
  --default-ros-distro "${DEFAULT_ROS_DISTRO}" \
  --stable-release "${STABLE_RELEASE}" \
  --publish-latest-aliases "${PUBLISH_LATEST_ALIASES}" \
  --output "${plan_file}"

# Copies, scrubs and verifies the planned kit and pins its release context;
# evidence stages its kit through the same step.
python3 "${planner}" \
  --source-root "${source_dir}" \
  --output "${plan_file}" \
  --stage "${bundle_root}"

# The installer asset and the bundle entrypoint come from the packager
# revision, not from the promoted build being released. A promoted build can
# predate the install/upgrade launcher while release notes and docs advertise
# those commands for every release.
installer_dir=${INSTALLER_SOURCE_DIR:-$(cd -- "${script_dir}/../.." && pwd -P)}
installer="${installer_dir}/openadkit"
[[ -x $installer ]] || {
  echo "Expected an executable installer at ${installer}" >&2
  exit 1
}
"$installer" install --help >/dev/null 2>&1 || {
  echo "Installer ${installer} does not support 'install'; update the packager revision" >&2
  exit 1
}
cp -a "$installer" "${bundle_root}/openadkit"

(cd "${bundle_root}" && ./openadkit list)
cp -a "$installer" dist/openadkit

# Split-host node views require Zenoh endpoints. These dummies only render and
# validate the Compose graphs; they never start a bridge.
export ZENOH_LISTEN="${ZENOH_LISTEN:-tcp/127.0.0.1:7447}"
export ZENOH_PEER="${ZENOH_PEER:-tcp/127.0.0.1:7447}"

while IFS=$'\t' read -r deployment ros_distro gpu node; do
  validate_args=(./openadkit validate "${deployment}" --ros-distro "${ros_distro}")
  if [ "${gpu}" = true ]; then
    validate_args+=(--gpu)
  fi
  if [ -n "${node}" ]; then
    validate_args+=(--node "${node}")
  fi
  (cd "${bundle_root}" && "${validate_args[@]}")
done < <(jq -r '.bundle.validation[] | [.deployment, .rosDistro, (.gpu | tostring), .node] | @tsv' "${plan_file}")

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
