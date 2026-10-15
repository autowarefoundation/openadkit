#!/usr/bin/env bash
# The board's chrony configuration: rog-amd is the only source, and the clock
# is stepped only in the first three updates after boot. A step while the
# vehicle drives would move the board clock that the restamp node and DDS
# stamps use.
set -u
name=test-chrony-x5h
here=$(cd "$(dirname "$0")" && pwd); f="$here/../config/chrony-x5h.conf"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -f "$f" ] || fail missing
[ "$(grep -cE '^(server|pool) ' "$f")" = 1 ] || fail source_count
grep -qE '^server 192\.168\.0\.1( |$)' "$f" || fail not_rog_amd
[ "$(grep -c '^makestep' "$f")" = 1 ] || fail makestep_count
grep -qE '^makestep [0-9.]+ 3$' "$f" || fail makestep_not_boot_only
echo "TEST_PASS $name"
