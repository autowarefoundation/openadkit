#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
ENV_FILE="$SCRIPT_DIR/config.env"
PYTHON_HELPER=$SCRIPT_DIR/carla_e2e_helper.py
BUILD_IMAGE=false
SKIP_VERIFY=false
AUTO_DRIVE=false
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage: ./start-carla-e2e-demo.sh [options]

Optional helpers for a running CARLA deployment. Start and stop the stack with:

  ./openadkit setup --gpu --verify
  ./openadkit run carla-simulation --gpu
  ./openadkit stop carla-simulation

Options:
  --build               Build the local CARLA interface image from components
  --drive               Set a forward route and engage autonomous mode
  --skip-verify         Skip topic, actor, and localization verification
  --dry-run             Print planned commands without running them
  -h, --help            Show this help text
EOF
}

while (($#)); do
  case "$1" in
    --build) BUILD_IMAGE=true ;;
    --drive) AUTO_DRIVE=true ;;
    --skip-verify) SKIP_VERIFY=true ;;
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage; exit 0 ;;
    --down|--no-visualizer|--no-drive|--skip-build)
      printf '%s is no longer supported. Start and stop with ./openadkit.\n' "$1" >&2
      usage >&2
      exit 2
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
  if [[ $DRY_RUN == false ]]; then
    "$@"
  fi
}

load_env() {
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  : "${ROS_DISTRO:?ROS_DISTRO is required}"
  : "${CARLA_INTERFACE_CONTAINER:?CARLA_INTERFACE_CONTAINER is required}"
}

run_helper() {
  local command=$1
  shift
  docker exec -i "$@" "$CARLA_INTERFACE_CONTAINER" \
    bash -lc "source /opt/ros/${ROS_DISTRO}/setup.bash; source /opt/autoware/setup.bash; python3 - $command" \
    < "$PYTHON_HELPER"
}

build_image() {
  local bake_file="$REPO_ROOT/components/docker-bake.hcl"
  local dockerfile="$REPO_ROOT/components/carla-interface/Dockerfile"
  if [[ ! -f $bake_file || ! -f $dockerfile ]]; then
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

verify_runtime() {
  if [[ $SKIP_VERIFY == true ]]; then
    return 0
  fi
  printf '+ verify CARLA e2e runtime\n'
  if [[ $DRY_RUN == true ]]; then
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
  printf 'Timed out waiting for CARLA e2e verification\n' >&2
  return 1
}

autonomous_drive() {
  printf '+ set forward route and engage autonomous mode\n'
  if [[ $DRY_RUN == false ]]; then
    run_helper set-route-and-engage \
      -e AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE="$AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE" \
      -e AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT="$AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT"
  fi
  if [[ $SKIP_VERIFY == true ]]; then
    return 0
  fi
  printf '+ verify autonomous CARLA motion\n'
  if [[ $DRY_RUN == false ]]; then
    run_helper verify-motion \
      -e AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT="$AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT" \
      -e AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE="$AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE"
  fi
}

if [[ $BUILD_IMAGE == false && $AUTO_DRIVE == false ]]; then
  usage
  exit 2
fi

cd "$SCRIPT_DIR"
load_env
if [[ $BUILD_IMAGE == true ]]; then
  build_image
fi
if [[ $AUTO_DRIVE == true ]]; then
  verify_runtime
  autonomous_drive
fi
