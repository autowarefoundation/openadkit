#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
ENV_FILE="$SCRIPT_DIR/config.env"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yaml"
SOURCE_BASE_DIR="$SCRIPT_DIR/../base"
COMPOSE_CMD=()
PYTHON_HELPER=$SCRIPT_DIR/carla_e2e_helper.py
DRY_RUN=false
BUILD_IMAGE=false
SKIP_VERIFY=false
START_VISUALIZER_OVERRIDE=
AUTO_DRIVE_OVERRIDE=
TEMP_FILES=()

usage() {
  cat <<'EOF'
Usage: ./start-carla-e2e-demo.sh [options]

Starts the closed-loop CARLA e2e demo using offscreen CARLA rendering by
default and Autoware's in-tree autoware_carla_interface.

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
  printf '+'
  printf ' %q' "${COMPOSE_CMD[@]}" "$@"
  printf '\n'
  if [[ "$DRY_RUN" == false ]]; then
    "${COMPOSE_CMD[@]}" "$@"
  fi
}

rollback() {
  local status=$?
  trap - EXIT INT TERM
  rm -f "${TEMP_FILES[@]}"
  exit "$status"
}
trap rollback EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

select_layout() {
  if [[ ! -f "$SOURCE_BASE_DIR/docker-compose.yaml" || ! -f "$SOURCE_BASE_DIR/runtime.env" ]]; then
    printf 'Missing shared deployment base under %s\n' "$SOURCE_BASE_DIR" >&2
    return 1
  fi
  COMPOSE_CMD=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
}

load_env() {
  local output line name
  local -A values=()
  local required=(
    AUTOWARE_E2E_AUTO_DRIVE
    AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE
    AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT
    AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE
    AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT
    AUTOWARE_E2E_START_VISUALIZER
    AUTOWARE_E2E_VERIFY_INTERVAL
    AUTOWARE_E2E_VERIFY_TIMEOUT
    CARLA_DISPLAY
    CARLA_E2E_LANELET2_URL
    CARLA_E2E_LANELET2_SHA256
    CARLA_E2E_POINTCLOUD_URL
    CARLA_E2E_POINTCLOUD_SHA256
    CARLA_INTERFACE_CONTAINER
    CARLA_INTERFACE_IMAGE
    CARLA_PYTHON_VERSION
    CARLA_RENDER_ARGS
    CARLA_RPC_HOST
    CARLA_RPC_PORT
    CARLA_VK_ICD_HOST_PATH
    MAP_PATH
    POINTCLOUD_MAP_FILE
    LANELET2_MAP_FILE
    ROS_DISTRO
  )

  if ! output=$("${COMPOSE_CMD[@]}" config --environment); then
    printf 'Failed to parse Compose environment\n' >&2
    return 1
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" == *=* ]] || continue
    name="${line%%=*}"
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    values["$name"]="${line#*=}"
  done <<< "$output"

  for name in "${required[@]}"; do
    if [[ ! -v "values[$name]" ]]; then
      printf 'Required environment variable %s is missing\n' "$name" >&2
      return 1
    fi
    printf -v "$name" '%s' "${values[$name]}"
    export "${name?}"
  done

  AUTOWARE_E2E_START_VISUALIZER=${START_VISUALIZER_OVERRIDE:-$AUTOWARE_E2E_START_VISUALIZER}
  AUTOWARE_E2E_AUTO_DRIVE=${AUTO_DRIVE_OVERRIDE:-$AUTOWARE_E2E_AUTO_DRIVE}
  export AUTOWARE_E2E_START_VISUALIZER AUTOWARE_E2E_AUTO_DRIVE
}

require_host_prerequisites() {
  local arch
  arch=$(uname -m)
  case "$arch" in
    x86_64|amd64) ;;
    *)
      printf 'CARLA simulation requires an amd64 host (detected %s).\n' "$arch" >&2
      return 1
      ;;
  esac
  printf '+ validate Ubuntu, Docker, NVIDIA runtime, GPU, and Vulkan prerequisites\n'
  if [[ "$DRY_RUN" == true ]]; then
    return 0
  fi

  if [[ ! -r /etc/os-release ]]; then
    printf 'Warning: /etc/os-release is unavailable; cannot verify host OS.\n' >&2
  else
    # shellcheck disable=SC1091
    source /etc/os-release
    if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 22.04 ]]; then
      # CARLA runs in a container; host OS is not a hard dependency. Warn on
      # non-22.04 so users know the tested configuration without blocking 24.04.
      printf 'Warning: CARLA demo is tested on Ubuntu 22.04 (detected %s %s).\n' \
        "${ID:-unknown}" "${VERSION_ID:-unknown}" >&2
    fi
  fi
  if ! command -v nvidia-smi >/dev/null || ! nvidia-smi >/dev/null; then
    printf 'A working NVIDIA GPU and driver are required for CARLA simulation.\n' >&2
    return 1
  fi
  docker info --format '{{json .Runtimes}}' | grep -q '"nvidia"' || {
    printf 'The Docker NVIDIA runtime is not available.\n' >&2
    return 1
  }
  if [[ ! -r "$CARLA_VK_ICD_HOST_PATH" ]]; then
    printf 'NVIDIA Vulkan ICD not found at %s.\n' "$CARLA_VK_ICD_HOST_PATH" >&2
    return 1
  fi
}

# CycloneDDS needs large kernel UDP buffers to carry PointCloud2 messages
# between the host-networked containers. With the stock 208 KiB limits the
# kernel drops message fragments: subscribers receive lidar at ~4 Hz instead
# of 10 Hz and localization never initializes.
UDP_MEM_MAX_REQUIRED=2147483647
UDP_MEM_DEFAULT_REQUIRED=134217728

require_udp_buffers() {
  printf '+ validate kernel UDP buffer sizes for DDS\n'
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

  printf 'Kernel UDP buffers are too small. Explicitly raise them and retry:\n' >&2
  printf '  sudo sysctl -w net.core.rmem_max=%s net.core.wmem_max=%s net.core.rmem_default=%s net.core.wmem_default=%s\n' \
    "$UDP_MEM_MAX_REQUIRED" "$UDP_MEM_MAX_REQUIRED" \
    "$UDP_MEM_DEFAULT_REQUIRED" "$UDP_MEM_DEFAULT_REQUIRED" >&2
  return 1
}

download_verified() {
  local url="$1"
  local expected="$2"
  local destination="$3"
  local tmp

  if [[ -f "$destination" ]] \
    && printf '%s  %s\n' "$expected" "$destination" | sha256sum --check --status; then
    return 0
  fi

  tmp=$(mktemp "${destination}.tmp.XXXXXX")
  TEMP_FILES+=("$tmp")
  if ! run curl -L --fail -A Mozilla/5.0 -o "$tmp" "$url"; then
    rm -f "$tmp"
    return 1
  fi
  if ! printf '%s  %s\n' "$expected" "$tmp" | sha256sum --check --status; then
    rm -f "$tmp"
    printf 'Checksum verification failed for %s\n' "$url" >&2
    return 1
  fi
  mv -f "$tmp" "$destination"
}

prepare_map() {
  local projector_tmp f
  if [[ "$DRY_RUN" == true ]]; then
    printf '+ prepare CARLA Town01 map at %s\n' "$MAP_PATH"
    return 0
  fi

  mkdir -p "$MAP_PATH"

  # Download into the directory Compose actually mounts (MAP_PATH), using the
  # same configured filenames the runtime reads, so preparation and runtime can
  # never point at different directories or filenames.
  download_verified "$CARLA_E2E_POINTCLOUD_URL" "$CARLA_E2E_POINTCLOUD_SHA256" \
    "$MAP_PATH/$POINTCLOUD_MAP_FILE"
  download_verified "$CARLA_E2E_LANELET2_URL" "$CARLA_E2E_LANELET2_SHA256" \
    "$MAP_PATH/$LANELET2_MAP_FILE"

  projector_tmp=$(mktemp "$MAP_PATH/map_projector_info.yaml.tmp.XXXXXX")
  TEMP_FILES+=("$projector_tmp")
  printf 'projector_type: Local\n' >"$projector_tmp"
  mv -f "$projector_tmp" "$MAP_PATH/map_projector_info.yaml"

  # Verify all three inputs the stack needs are present in the mounted directory
  # (not just the pointcloud) so a partial map surfaces here instead of as a
  # later localization or routing failure.
  for f in "$POINTCLOUD_MAP_FILE" "$LANELET2_MAP_FILE" map_projector_info.yaml; do
    if [[ ! -s "$MAP_PATH/$f" ]]; then
      printf 'Prepared map is missing %s in %s\n' "$f" "$MAP_PATH" >&2
      return 1
    fi
  done
}

build_image() {
  if [[ "$BUILD_IMAGE" != true ]]; then
    return 0
  fi

  local bake_file="$REPO_ROOT/components/docker-bake.hcl"
  local dockerfile="$REPO_ROOT/components/carla-interface/Dockerfile"
  if [[ ! -f "$bake_file" || ! -f "$dockerfile" ]]; then
    printf '%s\n' \
      'Cannot use --build: component sources and components/docker-bake.hcl are not included in release bundles.' \
      'Run without --build to use the published CARLA interface image, or run this script from a source checkout.' >&2
    return 1
  fi

  run docker buildx bake \
    --load \
    --progress=plain \
    -f "$bake_file" \
    --set "*.context=$REPO_ROOT" \
    --set "carla-interface.tags=$CARLA_INTERFACE_IMAGE" \
    --set "carla-interface.args.CARLA_PYTHON_VERSION=$CARLA_PYTHON_VERSION" \
    carla-interface
}

start_stack() {
  local display_num="${CARLA_DISPLAY##*:}"
  local -a services=(carla map system carla-interface sensing perception localization planning vehicle control api)
  display_num="${display_num%%.*}"
  if [[ "$DRY_RUN" == false && "${CARLA_RENDER_ARGS:-}" != *RenderOffScreen* && ! -S "/tmp/.X11-unix/X${display_num}" ]]; then
    printf 'X display socket for %s was not found under /tmp/.X11-unix\n' "$CARLA_DISPLAY" >&2
    return 1
  fi

  if [[ "$AUTOWARE_E2E_START_VISUALIZER" == true ]]; then
    services+=(visualizer)
  fi

  # The map loader is a one-shot. Remove its old result so every launch verifies
  # the configured world, then let Compose reconcile changed images/config.
  run_compose rm --stop --force carla-map-loader
  run_compose up -d "${services[@]}"

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

run_helper() {
  local command=$1
  shift
  docker exec -i "$@" "$CARLA_INTERFACE_CONTAINER" \
    bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash; source /opt/autoware/setup.bash; python3 - $command" \
    < "$PYTHON_HELPER"
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
    if output=$(run_helper verify-runtime \
      -e CARLA_RPC_HOST="$CARLA_RPC_HOST" \
      -e CARLA_RPC_PORT="$CARLA_RPC_PORT" \
      2>&1); then
      printf '%s\n' "$output"
      return 0
    fi
    sleep "$AUTOWARE_E2E_VERIFY_INTERVAL"
  done

  run_compose logs --tail 160 >&2 || true
  printf 'Timed out waiting for CARLA e2e verification\n' >&2
  return 1
}

autonomous_drive() {
  if [[ "$AUTOWARE_E2E_AUTO_DRIVE" != true ]]; then
    return 0
  fi

  printf '+ set forward route and engage autonomous mode\n'
  if [[ "$DRY_RUN" == false ]]; then
    run_helper set-route-and-engage \
      -e AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE="$AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE" \
      -e AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT="$AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT"
  fi

  if [[ "$SKIP_VERIFY" == true ]]; then
    return 0
  fi

  printf '+ verify autonomous CARLA motion\n'
  if [[ "$DRY_RUN" == false ]]; then
    run_helper verify-motion \
      -e AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT="$AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT" \
      -e AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE="$AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE"
  fi
}

main() {
  cd "$SCRIPT_DIR"
  select_layout
  load_env
  require_host_prerequisites
  require_udp_buffers
  prepare_map
  build_image
  start_stack
  verify_runtime
  autonomous_drive
}

main
