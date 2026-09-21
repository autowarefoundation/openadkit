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
    # test-kernel-patches needs a pristine copy of the pinned kernel tree, and
    # a fresh checkout has no such tree. Skipping it there keeps the aggregate
    # honest: a red run should mean a real defect, not "did not run". Only the
    # runner skips. The test itself is unchanged, so it still fails loudly when
    # it is run on its own, and it still fails hard on a wrong or stale tree.
    if [ "$t" = test-kernel-patches.sh ] && [ -z "${KERNEL_SRC:-}" ]; then
        echo "TEST_SKIP test-kernel-patches reason=KERNEL_SRC_unset"
        continue
    fi
    # test-make-demo-dtb needs dtc, and the derivation it covers runs inside a
    # container for exactly that reason. Skipped on the same argument.
    if [ "$t" = test-make-demo-dtb.sh ] && ! command -v dtc >/dev/null 2>&1; then
        echo "TEST_SKIP test-make-demo-dtb reason=dtc_missing"
        continue
    fi
    if bash "$t"; then :; else rc=1; fi
done
[ $rc -eq 0 ] && echo "ALL_TESTS_PASS" || echo "ALL_TESTS_FAIL"
exit $rc
