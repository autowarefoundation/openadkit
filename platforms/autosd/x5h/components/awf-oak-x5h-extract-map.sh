#!/usr/bin/env bash
set -euo pipefail

image="${SCENARIO_SIMULATOR_IMAGE:-localhost/scenario-simulator-v2:latest}"
map_dir=/opt/tier4/kashiwanoha_map
map_parent=$(dirname "${map_dir}")
tmp_dir=$(mktemp -d "${map_parent}/kashiwanoha_map.tmp.XXXXXX")
old_dir="${map_parent}/kashiwanoha_map.old"

cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

/usr/bin/podman image exists "${image}"
/usr/bin/podman run --rm --pull=never --volume "${tmp_dir}":/autoware_map:Z "${image}" bash -lc '
  set -euo pipefail
  source_dir="$(ros2 pkg prefix --share kashiwanoha_map)/map"
  test -d "${source_dir}"
  cp -a "${source_dir}/." /autoware_map/
'

test -f "${tmp_dir}/lanelet2_map.osm"
test -f "${tmp_dir}/pointcloud_map.pcd"
printf '%s\n' "${image}" > "${tmp_dir}/.scenario-simulator-image"

rm -rf "${old_dir}"
if [ -d "${map_dir}" ]; then
  mv "${map_dir}" "${old_dir}"
fi

if ! mv "${tmp_dir}" "${map_dir}"; then
  if [ -d "${old_dir}" ]; then
    mv "${old_dir}" "${map_dir}"
  fi
  exit 1
fi

trap - EXIT
rm -rf "${old_dir}"
