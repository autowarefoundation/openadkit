#!/usr/bin/env bash
# cr52-rproc-up.sh must never write `start` under a role whose device tree
# has no CR52 carveout: under a vendor NPU tree that write panics the kernel.
# demo and dev boot the derived tree and both carry the carveout; yocto does
# not, and neither does a boot with no role word at all.
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
# yocto role: skip, and the state file is untouched.
out=$(run 'root=/dev/sda2 x5h.role=yocto quiet') || fail yocto_nonzero
grep -q '^CR52_RPROC_SKIP reason=role role=yocto$' <<<"$out" || fail yocto_no_skip_marker
[ "$(cat "$tmp/rproc/state")" = offline ] || fail yocto_wrote_state
# An unset role, and the two retired ones. cr52 and npu must not keep working
# by accident: a board still holding a stale x5h-role.txt has to be skipped,
# not started, because U-Boot will have booted it into the dev fallback tree
# and this script's own verdict is the second of the two enforcement points.
out=$(run 'root=/dev/sda2') || fail unset_nonzero
grep -q 'reason=role role=unset' <<<"$out" || fail unset_no_skip_marker
for gone in cr52 npu; do
    out=$(run "x5h.role=$gone") || fail "${gone}_nonzero"
    grep -q "reason=role role=$gone" <<<"$out" || fail "${gone}_no_skip_marker"
    [ "$(cat "$tmp/rproc/state")" = offline ] || fail "${gone}_wrote_state"
done
# demo role: proceeds to the start write. With a fake sysfs nothing flips the
# state to running, so the script reports not_running, which proves the
# write happened.
out=$(run 'x5h.role=demo'); rc=$?
[ "$rc" -eq 1 ] || fail demo_rc_$rc
grep -q 'CR52_RPROC_FAIL reason=not_running' <<<"$out" || fail demo_no_start_attempt
[ "$(cat "$tmp/rproc/state")" = start ] || fail demo_state_not_written
# dev role: same path as demo, because it boots the same tree.
echo offline > "$tmp/rproc/state"
out=$(run 'x5h.role=dev'); rc=$?
[ "$rc" -eq 1 ] && [ "$(cat "$tmp/rproc/state")" = start ] || fail dev_not_started
echo "TEST_PASS $name"
