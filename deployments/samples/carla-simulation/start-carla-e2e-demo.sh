#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../../.." && pwd)
ENV_FILE=carla-simulation.env
PYTHON_HELPER=$SCRIPT_DIR/carla_e2e_helper.py
DRY_RUN=false
BUILD_IMAGE=false
SKIP_VERIFY=false
START_VISUALIZER_OVERRIDE=
AUTO_DRIVE_OVERRIDE=

usage() {
  cat <<'EOF'
Usage: ./start-carla-e2e-demo.sh [options]

Starts the closed-loop CARLA e2e demo using CARLA on the host display and
Autoware's in-tree autoware_carla_interface.

Options:
  --build               Build the local CARLA interface image from components
  --skip-build          Do not build the local CARLA interface image (default)
  --skip-verify         Skip topic, actor, and localization verification
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

  if [[ -n "$START_VISUALIZER_OVERRIDE" ]]; then
    AUTOWARE_E2E_START_VISUALIZER=$START_VISUALIZER_OVERRIDE
  fi

  if [[ -n "$AUTO_DRIVE_OVERRIDE" ]]; then
    AUTOWARE_E2E_AUTO_DRIVE=$AUTO_DRIVE_OVERRIDE
  fi
}

# CycloneDDS needs large kernel UDP buffers to carry PointCloud2 messages
# between the host-networked containers. With the stock 208 KiB limits the
# kernel drops message fragments: subscribers receive lidar at ~4 Hz instead
# of 10 Hz and localization never initializes.
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
    printf '+ prepare CARLA Town01 map at %s\n' "$CARLA_E2E_MAP_PATH"
    return 0
  fi

  mkdir -p "$CARLA_E2E_MAP_PATH"

  if [[ ! -s "$CARLA_E2E_MAP_PATH/pointcloud_map.pcd" ]]; then
    run curl -L --fail -A Mozilla/5.0 -o "$CARLA_E2E_MAP_PATH/pointcloud_map.pcd" "$CARLA_E2E_POINTCLOUD_URL"
  fi

  if [[ ! -s "$CARLA_E2E_MAP_PATH/lanelet2_map.osm" ]]; then
    run curl -L --fail -A Mozilla/5.0 -o "$CARLA_E2E_MAP_PATH/lanelet2_map.osm" "$CARLA_E2E_LANELET2_URL"
  fi

  printf 'projector_type: Local\n' > "$CARLA_E2E_MAP_PATH/map_projector_info.yaml"
}

build_image() {
  if [[ "$BUILD_IMAGE" != true ]]; then
    return 0
  fi

  run docker buildx bake \
    --load \
    --progress=plain \
    -f "$REPO_ROOT/components/docker-bake.hcl" \
    --set "*.context=$REPO_ROOT" \
    --set "carla-interface.tags=$CARLA_INTERFACE_IMAGE" \
    --set "carla-interface.args.CARLA_PYTHON_VERSION=$CARLA_PYTHON_VERSION" \
    carla-interface
}

wait_for_carla_rpc() {
  printf '+ wait for CARLA RPC on %s:%s\n' "$CARLA_RPC_HOST" "$CARLA_RPC_PORT"
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  local deadline=$((SECONDS + CARLA_START_TIMEOUT))
  while ((SECONDS < deadline)); do
    if timeout 1 bash -c "</dev/tcp/${CARLA_RPC_HOST}/${CARLA_RPC_PORT}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  printf 'Timed out waiting for CARLA RPC on %s:%s\n' "$CARLA_RPC_HOST" "$CARLA_RPC_PORT" >&2
  return 1
}

wait_for_carla_api() {
  printf '+ wait for CARLA Python API on %s:%s\n' "$CARLA_RPC_HOST" "$CARLA_RPC_PORT"
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  local deadline=$((SECONDS + CARLA_START_TIMEOUT))
  while ((SECONDS < deadline)); do
    if docker run --rm --network host \
      -e CARLA_RPC_HOST="$CARLA_RPC_HOST" \
      -e CARLA_RPC_PORT="$CARLA_RPC_PORT" \
      -e CARLA_API_TIMEOUT=5 \
      "$CARLA_INTERFACE_IMAGE" python3 - wait-api < "$PYTHON_HELPER" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done

  printf 'Timed out waiting for CARLA Python API on %s:%s\n' "$CARLA_RPC_HOST" "$CARLA_RPC_PORT" >&2
  return 1
}

stop_container_carla() {
  run docker rm -f "$CARLA_CONTAINER_NAME" || true
}

start_container_carla() {
  local display_num="${CARLA_DISPLAY##*:}"
  display_num="${display_num%%.*}"
  if [[ "$DRY_RUN" == false && ! -S "/tmp/.X11-unix/X${display_num}" ]]; then
    printf 'X display socket for %s was not found under /tmp/.X11-unix\n' "$CARLA_DISPLAY" >&2
    return 1
  fi

  stop_container_carla
  run_compose up -d --force-recreate carla

  wait_for_carla_rpc
  wait_for_carla_api
}

preload_carla_world() {
  if [[ "$DRY_RUN" == true ]]; then
    printf '+ docker run --rm --network host ... %s python3 - preload-world < %s\n' "$CARLA_INTERFACE_IMAGE" "$PYTHON_HELPER"
    return 0
  fi

  local deadline=$((SECONDS + CARLA_LOAD_TIMEOUT))
  while ((SECONDS < deadline)); do
    if docker run --rm --network host \
      -e CARLA_RPC_HOST="$CARLA_RPC_HOST" \
      -e CARLA_RPC_PORT="$CARLA_RPC_PORT" \
      -e CARLA_LOAD_TIMEOUT=30 \
      -e CARLA_WORLD="$CARLA_WORLD" \
      "$CARLA_INTERFACE_IMAGE" python3 - preload-world < "$PYTHON_HELPER"; then
      return 0
    fi
    sleep 5
  done

  printf 'Timed out preloading CARLA world %s\n' "$CARLA_WORLD" >&2
  return 1
}

start_autoware() {
  run docker rm -f "$CARLA_INTERFACE_CONTAINER" || true
  run_compose up -d --force-recreate \
    map \
    system \
    carla-interface \
    sensing \
    perception \
    localization \
    planning \
    vehicle \
    control \
    api

  # Fail fast if the pointcloud map is not visible inside the container. A
  # wrong or empty bind mount (for example MAP_PATH expanded with the wrong
  # HOME) otherwise surfaces much later as an NDT/localization timeout, which
  # is hard to diagnose.
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

  printf '+ verify CARLA e2e runtime\n'
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  local deadline=$((SECONDS + AUTOWARE_E2E_VERIFY_TIMEOUT))
  local output
  while ((SECONDS < deadline)); do
    if output=$(docker exec -i \
      -e CARLA_RPC_HOST="$CARLA_RPC_HOST" \
      -e CARLA_RPC_PORT="$CARLA_RPC_PORT" \
      "$CARLA_INTERFACE_CONTAINER" \
      bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash; source /opt/autoware/setup.bash; python3 - verify-runtime" \
      < "$PYTHON_HELPER" 2>&1); then
      printf '%s\n' "$output"
      return 0
    fi
    sleep "$AUTOWARE_E2E_VERIFY_INTERVAL"
  done

  docker compose --env-file "$ENV_FILE" -f docker-compose.yaml logs --tail 160 >&2 || true
  printf 'Timed out waiting for CARLA e2e verification\n' >&2
  return 1
}

start_autonomous_drive() {
  if [[ "$AUTOWARE_E2E_AUTO_DRIVE" != true ]]; then
    return 0
  fi

  printf '+ set forward route and engage autonomous mode\n'
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  docker exec \
    -i \
    -e AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE="$AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE" \
    -e AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT="$AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT" \
    "$CARLA_INTERFACE_CONTAINER" \
    bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash; source /opt/autoware/setup.bash; python3 - set-route-and-engage" \
    < "$PYTHON_HELPER"
}

verify_autonomous_drive() {
  if [[ "$AUTOWARE_E2E_AUTO_DRIVE" != true || "$SKIP_VERIFY" == true ]]; then
    return 0
  fi

  printf '+ verify autonomous CARLA motion\n'
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  docker exec \
    -i \
    -e AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT="$AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT" \
    -e AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE="$AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE" \
    "$CARLA_INTERFACE_CONTAINER" \
    bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash; source /opt/autoware/setup.bash; python3 - verify-motion" \
    < "$PYTHON_HELPER"
}

main() {
  cd "$SCRIPT_DIR"
  load_env
  ensure_udp_buffers
  prepare_map
  build_image
  start_container_carla
  preload_carla_world
  start_autoware
  start_visualizer
  verify_runtime
  start_autonomous_drive
  verify_autonomous_drive
}

main
