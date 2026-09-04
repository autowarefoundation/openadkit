#!/usr/bin/env bash
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
CARLA=$(cd -- "$HERE/../carla-simulation" && pwd)

usage() {
  cat <<'EOF'
Usage: ./start.sh [options]

Starts Open AD Kit CARLA simulation with Safety Island overlays:
stubbed Autoware trajectory follower and sensors-only carla-interface.

Requires SAFETY_ISLAND_REPO (absolute path to the autoware-safety-island
checkout). Does not start the Safety Island binary, vcan, domain-bridge,
or CAN-CARLA bridge; those run from that repository.

Options are forwarded to ../carla-simulation/start-carla-e2e-demo.sh.
--drive is ignored; engage from RViz after the Safety Island CAN path is live.
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
  esac
done

: "${SAFETY_ISLAND_REPO:?Set SAFETY_ISLAND_REPO to the autoware-safety-island checkout}"
if [[ ! "$SAFETY_ISLAND_REPO" = /* ]]; then
  printf 'SAFETY_ISLAND_REPO must be an absolute path (got %s)\n' "$SAFETY_ISLAND_REPO" >&2
  exit 1
fi
if [[ ! -f "$SAFETY_ISLAND_REPO/demo/launch/control.launch.xml" ]]; then
  printf 'SAFETY_ISLAND_REPO=%s is missing demo/launch/control.launch.xml\n' "$SAFETY_ISLAND_REPO" >&2
  exit 1
fi
if [[ ! -f "$SAFETY_ISLAND_REPO/demo/carla-closed-loop/overlay/patch_sensors_only.py" ]]; then
  printf 'SAFETY_ISLAND_REPO=%s is missing the sensors-only overlay\n' "$SAFETY_ISLAND_REPO" >&2
  exit 1
fi
export SAFETY_ISLAND_REPO

if [[ " $* " == *" --down "* ]]; then
  exec "$CARLA/start-carla-e2e-demo.sh" --down
fi

forwarded=()
for arg in "$@"; do
  case "$arg" in
    --drive)
      printf 'ignoring --drive; engage from RViz after SI CAN is live\n' >&2
      ;;
    *)
      forwarded+=("$arg")
      ;;
  esac
done

"$CARLA/start-carla-e2e-demo.sh" --no-drive "${forwarded[@]}"

printf '+ recreate control and carla-interface with Safety Island overlays\n'
docker compose \
  -p "$(basename "$CARLA")" \
  --env-file "$CARLA/config.env" \
  -f "$CARLA/docker-compose.yaml" \
  -f "$HERE/docker-compose.yaml" \
  up -d control carla-interface
