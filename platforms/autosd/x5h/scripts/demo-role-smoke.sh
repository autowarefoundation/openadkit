#!/usr/bin/env bash
# demo-role-smoke.sh -- gate D1a: the board booted the demo role with the NPU
# tree intact and the CR52 carveout relocated to 0x5da00000. Read-only: it
# writes nothing to sysfs and never starts the remoteproc. Run it on the
# board after every demo-role boot.
#
# Markers on stdout:
#   DEMO_ROLE_PASS role=demo carveout=0x5da00000 remoteproc=<state>
#   DEMO_ROLE_FAIL reason=<role_not_demo|carveout_not_reserved|carveout_node_missing|
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
fail() { echo "DEMO_ROLE_FAIL reason=$1"; exit 1; }
hex32() { od -An -tx1 "$1" 2>/dev/null | tr -d ' \n'; }

grep -qw 'x5h.role=demo' "$CMDLINE_FILE" || fail role_not_demo
grep -q "${BASE}-5dbfffff : reserved" "$IOMEM_FILE" || fail carveout_not_reserved
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
"$DMESG_CMD" | grep -q 'assigned reserved memory node linux,npu_region' || fail cmem_probe_missing
state=$(cat "$RPROC_DIR/state" 2>/dev/null) || fail remoteproc_missing
echo "DEMO_ROLE_PASS role=demo carveout=0x$BASE remoteproc=$state"
