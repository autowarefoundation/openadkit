#!/usr/bin/env bash
# Smoke test for the planning-simulation deployment.
# Validates the compose configuration and checks required files exist.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ENV_FILE="$SCRIPT_DIR/planning-simulation.env"

if [ -f "$SCRIPT_DIR/base/docker-compose.yaml" ]; then
  BASE_DIR="$SCRIPT_DIR/base"
  ENV_ARGS=(--env-file "$ENV_FILE")
else
  BASE_DIR="$SCRIPT_DIR/../base"
  ENV_ARGS=(--env-file "$BASE_DIR/base.env" --env-file "$ENV_FILE")
fi

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
required_files=("$ENV_FILE" "$BASE_DIR/docker-compose.yaml" "$BASE_DIR/cyclonedds.xml")
if [ "$BASE_DIR" = "$SCRIPT_DIR/../base" ]; then
  required_files+=("$BASE_DIR/base.env")
fi
for f in "${required_files[@]}"; do
  if [ -f "$f" ]; then
    echo "  ok: $f"
  else
    echo "  ERROR: missing $f" >&2
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
