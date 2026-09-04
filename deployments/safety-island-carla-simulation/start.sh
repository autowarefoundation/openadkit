#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ROOT=$(cd -- "$HERE/../.." && pwd -P)

usage() {
  cat <<'EOF'
Usage: ./start.sh [options]

Starts CARLA + sensors-only carla-interface via the Open AD Kit CLI.

Requires SAFETY_ISLAND_REPO (absolute path to autoware-safety-island).
Does not start the Safety Island binary, vcan, domain-bridge, or
CAN-CARLA bridge.

Options:
  --down     Stop and remove the stack
  --gpu      Forwarded to ./openadkit run (default)
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
export SAFETY_ISLAND_REPO

if [[ " $* " == *" --down "* ]]; then
  exec "$ROOT/openadkit" stop safety-island-carla-simulation
fi

forwarded=()
for arg in "$@"; do
  case "$arg" in
    --down|--drive|-h|--help) ;;
    *) forwarded+=("$arg") ;;
  esac
done
exec "$ROOT/openadkit" run safety-island-carla-simulation --gpu "${forwarded[@]}"
