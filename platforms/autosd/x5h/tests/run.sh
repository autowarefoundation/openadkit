#!/usr/bin/env bash
# Runs every host-side test in this directory. No board, no root, no network.
# Each test prints TEST_PASS <name> or TEST_FAIL <name> reason=<slug> and
# exits 0/1; this runner just aggregates.
set -u
shopt -s nullglob
cd "$(dirname "$0")"
tests=(test-*.sh)
if [ ${#tests[@]} -eq 0 ]; then
    echo "ALL_TESTS_FAIL reason=no_tests"
    exit 1
fi
rc=0
for t in "${tests[@]}"; do
    if bash "$t"; then :; else rc=1; fi
done
[ $rc -eq 0 ] && echo "ALL_TESTS_PASS" || echo "ALL_TESTS_FAIL"
exit $rc
