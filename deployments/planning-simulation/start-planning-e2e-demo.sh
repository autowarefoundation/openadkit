#!/usr/bin/env bash
# Compatibility wrapper — this script only smoke-tests; it does not start the stack.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec "$SCRIPT_DIR/check-planning-simulation.sh" "$@"
