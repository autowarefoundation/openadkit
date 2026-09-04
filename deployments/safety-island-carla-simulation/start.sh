#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
CARLA=$(cd -- "$HERE/../carla-simulation" && pwd -P)
PROJECT=openadkit-safety-island-carla-simulation

usage() {
  cat <<'EOF'
Usage: ./start.sh [options]

Starts CARLA simulation with a sensors-only carla-interface in one compose
pass so a second ego is not left in the world.

Requires SAFETY_ISLAND_REPO (absolute path to autoware-safety-island).
Does not start the Safety Island binary, vcan, domain-bridge, or
CAN-CARLA bridge.

Options:
  --down     Stop and remove the stack
  -h, --help Show this help
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    --drive)
      printf 'ignoring --drive; engage from RViz after SI CAN is live\n' >&2
      ;;
  esac
done

: "${SAFETY_ISLAND_REPO:?Set SAFETY_ISLAND_REPO to the autoware-safety-island checkout}"
if [[ ! "$SAFETY_ISLAND_REPO" = /* ]]; then
  printf 'SAFETY_ISLAND_REPO must be an absolute path (got %s)\n' "$SAFETY_ISLAND_REPO" >&2
  exit 1
fi
if [[ ! -f "$SAFETY_ISLAND_REPO/demo/carla-closed-loop/overlay/carla_autoware.py" ]]; then
  printf 'SAFETY_ISLAND_REPO=%s is missing the sensors-only overlay\n' "$SAFETY_ISLAND_REPO" >&2
  exit 1
fi

compose=(
  docker compose
  --project-name "$PROJECT"
  --env-file "$CARLA/config.env"
  -f "$HERE/docker-compose.yaml"
)

if [[ " $* " == *" --down "* ]]; then
  exec "${compose[@]}" down --remove-orphans
fi

"${compose[@]}" up --detach --wait --wait-timeout 480 --remove-orphans
printf 'visualizer: https://localhost:6080/vnc.html\n'
printf 'stop with: %s --down\n' "$0"
