#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ENV_FILE=awsim-simulation.e2e.env
PYTHON_HELPER=$SCRIPT_DIR/awsim_e2e_helper.py
DRY_RUN=false
BUILD_IMAGE=auto
SKIP_VERIFY=false
START_VISUALIZER_OVERRIDE=
AUTO_DRIVE_OVERRIDE=

usage() {
  cat <<'EOF'
Usage: ./start-awsim-e2e-demo.sh [options]

Starts the closed-loop AWSIM v2 e2e demo using the AWSIM demo binary and
modular OpenADKit Autoware containers.

Options:
  --build               Build the local AWSIM runtime image before starting
  --skip-build          Do not build the AWSIM image; require it to exist
  --skip-verify         Skip topic and localization verification
  --no-visualizer       Do not start the browser RViz/noVNC visualizer container
  --drive               Set a forward route and engage autonomous mode
  --no-drive            Start the stack without setting a route or engaging
  --dry-run             Print planned commands without running them
  -h, --help            Show this help text
EOF
}

while (($#)); do
  case "$1" in
    --build)
      BUILD_IMAGE=true
      ;;
    --skip-build)
      BUILD_IMAGE=false
      ;;
    --skip-verify)
      SKIP_VERIFY=true
      ;;
    --no-visualizer)
      START_VISUALIZER_OVERRIDE=false
      ;;
    --drive)
      AUTO_DRIVE_OVERRIDE=true
      ;;
    --no-drive)
      AUTO_DRIVE_OVERRIDE=false
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

run() {
  printf '+ %s\n' "$*"
  if [[ "$DRY_RUN" == false ]]; then
    "$@"
  fi
}

run_compose() {
  printf '+ docker compose --env-file %s -f docker-compose.yaml %s\n' "$ENV_FILE" "$*"
  if [[ "$DRY_RUN" == false ]]; then
    docker compose --env-file "$ENV_FILE" -f docker-compose.yaml "$@"
  fi
}

load_env() {
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a

  if [[ -z "${SENSING_PERCEPTION_IMAGE:-}" ]]; then
    SENSING_PERCEPTION_IMAGE=ghcr.io/autowarefoundation/openadkit:sensing-perception-cuda
  fi

  if [[ -n "$START_VISUALIZER_OVERRIDE" ]]; then
    AUTOWARE_E2E_START_VISUALIZER=$START_VISUALIZER_OVERRIDE
  fi

  if [[ -n "$AUTO_DRIVE_OVERRIDE" ]]; then
    AUTOWARE_E2E_AUTO_DRIVE=$AUTO_DRIVE_OVERRIDE
  fi
}

UDP_MEM_MAX_REQUIRED=2147483647
UDP_MEM_DEFAULT_REQUIRED=134217728

ensure_udp_buffers() {
  printf '+ ensure kernel UDP buffer sizes for DDS\n'
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  local rmem_max wmem_max rmem_default wmem_default
  rmem_max=$(sysctl -n net.core.rmem_max)
  wmem_max=$(sysctl -n net.core.wmem_max)
  rmem_default=$(sysctl -n net.core.rmem_default)
  wmem_default=$(sysctl -n net.core.wmem_default)
  if ((rmem_max >= UDP_MEM_MAX_REQUIRED && wmem_max >= UDP_MEM_MAX_REQUIRED \
    && rmem_default >= UDP_MEM_DEFAULT_REQUIRED && wmem_default >= UDP_MEM_DEFAULT_REQUIRED)); then
    return 0
  fi

  local sysctl_args=(
    "net.core.rmem_max=$UDP_MEM_MAX_REQUIRED"
    "net.core.wmem_max=$UDP_MEM_MAX_REQUIRED"
    "net.core.rmem_default=$UDP_MEM_DEFAULT_REQUIRED"
    "net.core.wmem_default=$UDP_MEM_DEFAULT_REQUIRED"
  )
  local sudo_cmd=()
  if [[ $EUID -ne 0 ]]; then
    if [[ -t 0 ]]; then
      sudo_cmd=(sudo)
    else
      sudo_cmd=(sudo -n)
    fi
  fi
  if run "${sudo_cmd[@]}" sysctl -qw "${sysctl_args[@]}"; then
    return 0
  fi

  printf 'Failed to raise kernel UDP buffer limits. Run this and retry:\n' >&2
  printf '  sudo sysctl -w %s %s %s %s\n' "${sysctl_args[@]}" >&2
  return 1
}

prepare_map() {
  if [[ "$DRY_RUN" == true ]]; then
    printf '+ prepare AWSIM Shinjuku map at %s\n' "$AWSIM_E2E_MAP_PATH"
    return 0
  fi

  mkdir -p "$AWSIM_E2E_MAP_PATH"
  if [[ -s "$AWSIM_E2E_MAP_PATH/$POINTCLOUD_MAP_FILE" && -s "$AWSIM_E2E_MAP_PATH/$LANELET2_MAP_FILE" ]]; then
    return 0
  fi

  local cache_dir tmp_dir archive
  cache_dir=${DATA_PATH:-$HOME/autoware_data}/cache
  archive=$cache_dir/Shinjuku-Map.zip
  tmp_dir=$(mktemp -d)
  mkdir -p "$cache_dir"
  trap 'rm -rf "$tmp_dir"; trap - RETURN' RETURN

  if [[ ! -s "$archive" ]]; then
    run curl -L --fail -A Mozilla/5.0 -o "$archive" "$AWSIM_E2E_MAP_URL"
  fi
  if [[ -n "${AWSIM_E2E_MAP_SHA256:-}" ]]; then
    echo "${AWSIM_E2E_MAP_SHA256}  $archive" | sha256sum -c -
  fi
  run unzip -o -q "$archive" -d "$tmp_dir"

  local pcd osm projector
  pcd=$(find "$tmp_dir" -name "$POINTCLOUD_MAP_FILE" -print -quit)
  osm=$(find "$tmp_dir" -name "$LANELET2_MAP_FILE" -print -quit)
  if [[ -z "$pcd" ]]; then
    pcd=$(find "$tmp_dir" -name '*.pcd' -print -quit)
  fi
  if [[ -z "$osm" ]]; then
    osm=$(find "$tmp_dir" -name '*.osm' -print -quit)
  fi
  projector=$(find "$tmp_dir" -name map_projector_info.yaml -print -quit)
  if [[ -z "$pcd" || -z "$osm" ]]; then
    printf 'Shinjuku map archive did not contain %s and %s\n' "$POINTCLOUD_MAP_FILE" "$LANELET2_MAP_FILE" >&2
    return 1
  fi

  run cp "$pcd" "$AWSIM_E2E_MAP_PATH/$POINTCLOUD_MAP_FILE"
  run cp "$osm" "$AWSIM_E2E_MAP_PATH/$LANELET2_MAP_FILE"
  if [[ -n "$projector" ]]; then
    run cp "$projector" "$AWSIM_E2E_MAP_PATH/map_projector_info.yaml"
  elif [[ ! -s "$AWSIM_E2E_MAP_PATH/map_projector_info.yaml" ]]; then
    printf 'projector_type: MGRS\nvertical_datum: WGS84\n' > "$AWSIM_E2E_MAP_PATH/map_projector_info.yaml"
  fi
}

ensure_awsim_image() {
  if [[ "$BUILD_IMAGE" == false ]]; then
    return 0
  fi

  if [[ "$DRY_RUN" == false && "$BUILD_IMAGE" == auto ]] && docker image inspect "$AWSIM_IMAGE" >/dev/null 2>&1; then
    printf '+ AWSIM image %s present, skipping build\n' "$AWSIM_IMAGE"
    return 0
  fi

  run_compose build awsim
}

start_awsim() {
  run docker rm -f "$AWSIM_CONTAINER_NAME" || true
  run_compose up -d --force-recreate awsim
  if [[ "$DRY_RUN" == false && "$AWSIM_START_GRACE_SECONDS" != 0 ]]; then
    run sleep "$AWSIM_START_GRACE_SECONDS"
  fi
  wait_for_awsim_clock
}

wait_for_awsim_clock() {
  printf '+ wait for AWSIM /clock topic\n'
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  printf '+ docker pull %s\n' "$AWSIM_E2E_HELPER_IMAGE"
  docker pull "$AWSIM_E2E_HELPER_IMAGE" >/dev/null 2>&1 || true

  local deadline=$((SECONDS + AWSIM_START_TIMEOUT))
  while ((SECONDS < deadline)); do
    if docker run --rm --network host \
      "$AWSIM_E2E_HELPER_IMAGE" \
      bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash; source /opt/autoware/setup.bash; ros2 topic echo /clock --once --timeout 3" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  printf 'Timed out waiting for AWSIM /clock on host network\n' >&2
  return 1
}

start_autoware() {
  run_compose up -d --force-recreate \
    map \
    system \
    sensing \
    perception \
    localization \
    planning \
    vehicle \
    control \
    api

  if [[ "$DRY_RUN" == false ]] \
    && ! run_compose exec -T map test -s "/autoware_map/$POINTCLOUD_MAP_FILE"; then
    printf 'Pointcloud map not visible in container at /autoware_map/%s; check MAP_PATH=%s\n' \
      "$POINTCLOUD_MAP_FILE" "$MAP_PATH" >&2
    return 1
  fi
}

start_visualizer() {
  if [[ "$AUTOWARE_E2E_START_VISUALIZER" != true ]]; then
    return 0
  fi

  run docker rm -f autoware-e2e-visualizer || true
  run_compose up -d --force-recreate visualizer
}

verify_runtime() {
  if [[ "$SKIP_VERIFY" == true ]]; then
    return 0
  fi

  printf '+ verify AWSIM e2e runtime\n'
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  local deadline=$((SECONDS + AUTOWARE_E2E_VERIFY_TIMEOUT))
  local output=""
  while ((SECONDS < deadline)); do
    if output=$(docker exec -i \
      -e ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
      -e AUTOWARE_E2E_VERIFY_RUNTIME_TIMEOUT="${AUTOWARE_E2E_VERIFY_RUNTIME_TIMEOUT:-20.0}" \
      autoware-api \
      bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash; source /opt/autoware/setup.bash; python3 - verify-runtime" \
      < "$PYTHON_HELPER" 2>&1); then
      printf '%s\n' "$output"
      return 0
    fi
    sleep "$AUTOWARE_E2E_VERIFY_INTERVAL"
  done

  docker compose --env-file "$ENV_FILE" -f docker-compose.yaml logs --tail 160 >&2 || true
  printf 'Timed out waiting for AWSIM e2e verification\n' >&2
  return 1
}

start_autonomous_drive() {
  if [[ "$AUTOWARE_E2E_AUTO_DRIVE" != true ]]; then
    return 0
  fi

  printf '+ set route and engage autonomous mode\n'
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  docker exec \
    -i \
    -e AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE="$AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE" \
    -e AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT="$AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT" \
    -e AWSIM_E2E_GOAL_X="${AWSIM_E2E_GOAL_X:-}" \
    -e AWSIM_E2E_GOAL_Y="${AWSIM_E2E_GOAL_Y:-}" \
    -e AWSIM_E2E_GOAL_YAW="${AWSIM_E2E_GOAL_YAW:-}" \
    autoware-api \
    bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash; source /opt/autoware/setup.bash; python3 - set-route-and-engage" \
    < "$PYTHON_HELPER"
}

verify_autonomous_drive() {
  if [[ "$AUTOWARE_E2E_AUTO_DRIVE" != true || "$SKIP_VERIFY" == true ]]; then
    return 0
  fi

  printf '+ verify autonomous AWSIM motion\n'
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  docker exec \
    -i \
    -e AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT="$AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT" \
    -e AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE="$AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE" \
    autoware-api \
    bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash; source /opt/autoware/setup.bash; python3 - verify-motion" \
    < "$PYTHON_HELPER"
}

main() {
  cd "$SCRIPT_DIR"
  load_env
  ensure_udp_buffers
  prepare_map
  ensure_awsim_image
  start_awsim
  start_autoware
  start_visualizer
  verify_runtime
  start_autonomous_drive
  verify_autonomous_drive
}

main
