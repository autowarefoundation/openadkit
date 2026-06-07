#!/usr/bin/env bash
# Shared map-init script for Open AD Kit scenario-simulator deployments.
# Extracts the Kashiwanoha map from the upstream TIER IV image when needed.
set -euo pipefail

image="${SCENARIO_SIMULATOR_IMAGE:?ERROR: SCENARIO_SIMULATOR_IMAGE is not set}"
marker="${MAP_MARKER_PATH:-/autoware_map/.scenario-simulator-image}"
volume_path="${MAP_VOLUME_PATH:-/autoware_map}"
required_files="${REQUIRED_FILES:-lanelet2_map.osm pointcloud_map.pcd}"
auto_extract="${AUTO_EXTRACT_MAP:-true}"
map_path="${MAP_PATH:-}"

needs_extract=false
marker_matches=false

if [ -f "$marker" ] && [ "$(cat "$marker")" = "$image" ]; then
  marker_matches=true
fi

if [ -f "$marker" ] && [ "$marker_matches" = false ]; then
  needs_extract=true
fi

if [ "$auto_extract" = true ] && [ ! -f "$marker" ]; then
  needs_extract=true
fi

for file in $required_files; do
  if [ ! -f "$volume_path/$file" ]; then
    needs_extract=true
  fi
done

if [ "$needs_extract" = true ]; then
  if [ "$auto_extract" != true ]; then
    echo "ERROR: Map at $volume_path is missing required files and AUTO_EXTRACT_MAP is false." >&2
    exit 1
  fi

  echo "Extracting kashiwanoha map from $image..."
  source /opt/ros/humble/setup.bash
  map_dir="$(ros2 pkg prefix --share kashiwanoha_map)/map"
  if [ ! -d "$map_dir" ]; then
    echo "ERROR: Kashiwanoha map not found in $image; check that the image contains the kashiwanoha_map package." >&2
    exit 1
  fi

  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' EXIT
  cp -a "$map_dir/." "$tmp_dir/"

  for file in $required_files; do
    if [ ! -f "$tmp_dir/$file" ]; then
      echo "ERROR: Extracted map is missing $file." >&2
      exit 1
    fi
  done

  # Check if existing files match (skip destructive rm+cp if identical)
  if [ ! -f "$marker" ]; then
    needs_extract=false
    for file in $required_files; do
      if [ ! -f "$volume_path/$file" ] || ! cmp -s "$tmp_dir/$file" "$volume_path/$file"; then
        needs_extract=true
      fi
    done
  fi

  if [ "$needs_extract" = true ]; then
    # Guardrail for bind mounts
    if [ -n "$map_path" ]; then
      case "$map_path" in
        */autoware_map/*|*/kashiwanoha_map) ;;
        *)
          echo "ERROR: MAP_PATH must be a dedicated map directory (contains 'autoware_map' or 'kashiwanoha_map')." >&2
          exit 1
          ;;
      esac
    fi

    rm -rf "${volume_path:?}"/* "${volume_path:?}"/.[!.]* "${volume_path:?}"/..?*
    cp -a "$tmp_dir/." "$volume_path/"
  fi

  echo "$image" > "$marker"
  rm -rf "$tmp_dir"
  trap - EXIT
  echo "Map extraction complete."
else
  echo "Using validated map at $volume_path"
fi

# Ensure marker is written even if we skipped extraction (first run with existing files)
if [ ! -f "$marker" ]; then
  echo "$image" > "$marker"
fi
