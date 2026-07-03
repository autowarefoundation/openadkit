#!/usr/bin/env bash
# Smoke test for the planning-simulation deployment.
# Validates the compose configuration and checks required files exist.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ENV_FILE=planning-simulation.env
BASE_ENV_FILE=../base/base.env

usage() {
  cat <<'EOF'
Usage: ./start-planning-e2e-demo.sh [options]

Starts the planning-simulation deployment.  Runs Autoware planning/control
stack against a pre-recorded map in the built-in simulator.

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
for f in "$SCRIPT_DIR/$ENV_FILE" "$SCRIPT_DIR/../base/base.env" "$SCRIPT_DIR/../base/docker-compose.yaml" "$SCRIPT_DIR/../base/cyclonedds.xml"; do
  if [ -f "$f" ]; then
    echo "  ok: $f"
  else
    echo "  ERROR: missing $f" >&2
    exit 1
  fi
done

echo "Validating compose configuration..."
run docker compose --env-file "$BASE_ENV_FILE" --env-file "$SCRIPT_DIR/$ENV_FILE" -f "$SCRIPT_DIR/docker-compose.yaml" config -q
echo "  compose config: valid"

echo "Smoke test passed."
echo ""
echo "To start the deployment:"
echo "  cd $SCRIPT_DIR"
echo "  docker compose --env-file $BASE_ENV_FILE --env-file $ENV_FILE up -d"
echo ""
echo "To stop:"
echo "  cd $SCRIPT_DIR"
echo "  docker compose --env-file $BASE_ENV_FILE --env-file $ENV_FILE down"
