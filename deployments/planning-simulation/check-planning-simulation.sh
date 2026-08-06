#!/usr/bin/env bash
# Smoke test for the planning-simulation deployment.
# Validates the compose configuration and checks required files exist.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ENV_FILE="$SCRIPT_DIR/config.env"

BASE_DIR="$SCRIPT_DIR/base"
if [ ! -d "$BASE_DIR" ]; then
  BASE_DIR="$SCRIPT_DIR/../base"
fi
ENV_ARGS=(--env-file "$ENV_FILE")

usage() {
  cat <<'EOF'
Usage: ./check-planning-simulation.sh [options]

Smoke-tests the planning-simulation deployment: validates the Compose
configuration and required files, then prints the commands to start and
stop the deployment. It does not start the deployment itself.

Options:
  --dry-run   Print planned commands without running them
  -h, --help  Show this help text
EOF
  exit "${1:-0}"
}

DRY_RUN=false
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage 1 >&2 ;;
  esac
  shift
done

cd "$SCRIPT_DIR"

run() {
  if [ "$DRY_RUN" = true ]; then
    echo "[DRY-RUN] $*"
  else
    "$@"
  fi
}

echo "=== Planning-simulation smoke test ==="

echo "Checking required files..."
required_files=(
  "$ENV_FILE"
  "$BASE_DIR/docker-compose.yaml"
  "$BASE_DIR/cyclonedds.xml"
  "$BASE_DIR/runtime.env"
  "$BASE_DIR/config/vehicle_cmd_gate.param.yaml"
)
for f in "${required_files[@]}"; do
  if [ -f "$f" ]; then
    echo "  ok: $f"
  else
    echo "  ERROR: missing $f" >&2
    echo "  (if this path is missing, Compose may create a directory bind-mount and break control)" >&2
    exit 1
  fi
done

echo "Validating compose configuration..."
run docker compose "${ENV_ARGS[@]}" -f "$SCRIPT_DIR/docker-compose.yaml" config -q
echo "  compose config: valid"

echo "Smoke test passed."
echo ""
echo "To start the deployment:"
echo "  cd $SCRIPT_DIR"
printf '  docker compose'
printf ' %q' "${ENV_ARGS[@]}"
printf ' up -d\n'
echo ""
echo "To stop:"
echo "  cd $SCRIPT_DIR"
printf '  docker compose'
printf ' %q' "${ENV_ARGS[@]}"
printf ' down\n'
