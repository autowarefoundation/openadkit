#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ROOT=$(cd -- "$HERE/../.." && pwd -P)

usage() {
  cat <<'EOF'
Usage: ./start.sh [options]

Starts CARLA, sensors-only carla-interface and the domain-bridge via the
Open AD Kit CLI. Does not start the Safety Island binary, vcan, or
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
