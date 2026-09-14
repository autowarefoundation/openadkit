#!/usr/bin/env bash
# cr52-rproc-up.sh must never write `start` under a role whose device tree
# has no CR52 carveout: under the npu tree that write panics the kernel.
set -u
name=test-cr52-rproc-up
here=$(cd "$(dirname "$0")" && pwd)
s="$here/../scripts/cr52-rproc-up.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/rproc" "$tmp/fw"
echo cr52_1 > "$tmp/rproc/name"
echo offline > "$tmp/rproc/state"
echo actuation_x5h.elf > "$tmp/rproc/firmware"
: > "$tmp/fw/actuation_x5h.elf"
run() { # $1 = cmdline text; prints stdout, returns script status
    printf '%s\n' "$1" > "$tmp/cmdline"
    CMDLINE_FILE="$tmp/cmdline" RPROC_DIR="$tmp/rproc" FIRMWARE_DIR="$tmp/fw" TIMEOUT=1 bash "$s"
}
# npu role: skip, and the state file is untouched.
out=$(run 'root=/dev/sda2 x5h.role=npu quiet') || fail npu_nonzero
grep -q '^CR52_RPROC_SKIP reason=role role=npu$' <<<"$out" || fail npu_no_skip_marker
[ "$(cat "$tmp/rproc/state")" = offline ] || fail npu_wrote_state
# yocto role and an unset role: same.
out=$(run 'x5h.role=yocto') || fail yocto_nonzero
grep -q 'reason=role role=yocto' <<<"$out" || fail yocto_no_skip_marker
out=$(run 'root=/dev/sda2') || fail unset_nonzero
grep -q 'reason=role role=unset' <<<"$out" || fail unset_no_skip_marker
# demo role: proceeds to the start write. With a fake sysfs nothing flips the
# state to running, so the script reports not_running, which proves the
# write happened.
out=$(run 'x5h.role=demo'); rc=$?
[ "$rc" -eq 1 ] || fail demo_rc_$rc
grep -q 'CR52_RPROC_FAIL reason=not_running' <<<"$out" || fail demo_no_start_attempt
[ "$(cat "$tmp/rproc/state")" = start ] || fail demo_state_not_written
# cr52 role: same path as demo.
echo offline > "$tmp/rproc/state"
out=$(run 'x5h.role=cr52'); rc=$?
[ "$rc" -eq 1 ] && [ "$(cat "$tmp/rproc/state")" = start ] || fail cr52_not_started
echo "TEST_PASS $name"
