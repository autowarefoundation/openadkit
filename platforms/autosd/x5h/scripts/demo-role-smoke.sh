#!/usr/bin/env bash
# demo-role-smoke.sh -- gate D1a: the board booted the derived device tree,
# with the NPU tree intact and the CR52 carveout relocated to 0x5da00000.
# demo and dev boot that same tree, so either role satisfies this gate and
# the marker reports which one it found. Read-only: it writes nothing to
# sysfs and never starts the remoteproc. Run it after every such boot.
#
# Markers on stdout:
#   DEMO_ROLE_PASS role=<demo|dev> carveout=0x5da00000 remoteproc=<state>
#   DEMO_ROLE_FAIL reason=<wrong_role|carveout_not_reserved|carveout_node_missing|
#                          carveout_phandle|cr52_memory_region|cr52_node_ambiguous|
#                          npu_region_<base>_missing|uio2_missing|cmem_probe_missing|
#                          remoteproc_missing>
set -uo pipefail
CMDLINE_FILE=${CMDLINE_FILE:-/proc/cmdline}
IOMEM_FILE=${IOMEM_FILE:-/proc/iomem}
DT_ROOT=${DT_ROOT:-/proc/device-tree}
UIO_DIR=${UIO_DIR:-/sys/class/uio}
RPROC_DIR=${RPROC_DIR:-/sys/class/remoteproc/remoteproc0}
DMESG_CMD=${DMESG_CMD:-dmesg}
BASE=5da00000
# 2 MiB. The end address is derived from the base and the size rather than
# written out, so moving BASE alone cannot leave a reservation check that no
# board can ever satisfy.
SIZE=200000
END=$(printf '%x' $((0x$BASE + 0x$SIZE - 1)))
fail() { echo "DEMO_ROLE_FAIL reason=$1"; exit 1; }
hex32() { od -An -tx1 "$1" 2>/dev/null | tr -d ' \n'; }

role=$(tr ' ' '\n' < "$CMDLINE_FILE" | sed -n 's/^x5h\.role=//p' | tail -1)
case "$role" in demo|dev) ;; *) fail "wrong_role role=${role:-unset}" ;; esac
grep -q "$BASE-$END : reserved" "$IOMEM_FILE" || fail carveout_not_reserved
node="$DT_ROOT/reserved-memory/cr52_ram1@$BASE"
[ -d "$node" ] || fail carveout_node_missing
[ "$(hex32 "$node/phandle")" = "0000010a" ] || fail carveout_phandle
matches=()
for f in "$DT_ROOT"/soc/cr52_1*/memory-region; do [ -e "$f" ] && matches+=("$f"); done
case "${#matches[@]}" in
    0) fail cr52_memory_region ;;
    1) [ "$(hex32 "${matches[0]}")" = "0000010a" ] || fail cr52_memory_region ;;
    *) fail cr52_node_ambiguous ;;
esac
for r in 1400000000 1c00000000 64000000 8e400000; do
    [ -d "$DT_ROOT/reserved-memory/linux,npu_region@$r" ] || fail "npu_region_${r}_missing"
done
[ -e "$UIO_DIR/uio2" ] || fail uio2_missing
# Capture, then match on the string. `dmesg | grep -q` lets grep exit at the
# first match, closing the pipe under this script's `set -o pipefail` --
# dmesg then takes a SIGPIPE on its next write and reports 141, which
# pipefail turns into a FAIL on the very invariant this check exists to
# confirm is present. Board-confirmed 2026-09-14: 5/5 false failures on
# board 1, 3/5 on board 2, on an otherwise healthy boot.
dmesg_out=$("$DMESG_CMD")
grep -q 'assigned reserved memory node linux,npu_region' <<<"$dmesg_out" || fail cmem_probe_missing
state=$(cat "$RPROC_DIR/state" 2>/dev/null) || fail remoteproc_missing
echo "DEMO_ROLE_PASS role=$role carveout=0x$BASE remoteproc=$state"
