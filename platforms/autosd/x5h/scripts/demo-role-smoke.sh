#!/usr/bin/env bash
# demo-role-smoke.sh -- gate D1a: the board booted the derived device tree,
# with the NPU tree intact and the CR52 carveout relocated to 0x5da00000.
# demo and dev boot that same tree, so either role satisfies this gate and
# the marker reports which one it found. Read-only: it writes nothing to
# sysfs and never starts the remoteproc. Run it after every such boot.
#
# Markers on stdout:
#   DEMO_ROLE_PASS role=<demo|dev> carveout=0x5da00000 vdev=0x5dc00000 remoteproc=<state>
#   DEMO_ROLE_FAIL reason=<wrong_role|carveout_not_reserved|carveout_node_missing|
#                          carveout_phandle|<name>_not_reserved|<name>_node_missing|
#                          <name>_phandle|<name>_not_linked|
#                          cr52_memory_region|cr52_node_ambiguous|
#                          npu_region_<base>_missing|uio2_missing|cmem_probe_missing|
#                          remoteproc_missing>
set -uo pipefail
CMDLINE_FILE=${CMDLINE_FILE:-/proc/cmdline}
IOMEM_FILE=${IOMEM_FILE:-/proc/iomem}
DT_ROOT=${DT_ROOT:-/proc/device-tree}
UIO_DIR=${UIO_DIR:-/sys/class/uio}
RPROC_DIR=${RPROC_DIR:-/sys/class/remoteproc/remoteproc0}
# journalctl -k -b, NOT dmesg. The cmem probe lines this gate looks for are
# printed at boot, and dmesg reads a ring buffer that WRAPS: on board 2 on
# 2026-09-18, after about 10 hours of uptime and heavy container and DDS
# traffic, the oldest surviving dmesg line was t+38008s and the gate reported
# cmem_probe_missing on a board whose four cmem devices were all present. The
# boot journal still held all four lines. A booth board is exactly the
# long-uptime case, so dmesg makes this check expire silently.
DMESG_CMD=${DMESG_CMD:-"journalctl -k -b --no-pager"}
BASE=5da00000
# 2 MiB. The end address is derived from the base and the size rather than
# written out, so moving BASE alone cannot leave a reservation check that no
# board can ever satisfy.
SIZE=200000
END=$(printf '%x' $((0x$BASE + 0x$SIZE - 1)))
VDEV_BASE=5dc00000
# The four carveouts cr52_1 must list, in the order it must list them, as
# make-demo-dtb.sh writes them: name base size. The three vdev names are what
# rproc_alloc_vring() and rproc_add_virtio_dev() look the carveouts up by, so
# this gate checks the names, not just that four windows exist. Without them
# remoteproc allocates the vrings and the rpmsg buffer pool from
# linux,cma@40000000, which no CR52 MPU region maps, and the firmware
# data-aborts in rpmsg_init_vdev. That was gate D1b on board 2, 2026-09-17,
# and nothing in this gate reported it.
#
# No phandle is written here except cr52_ram1's. make-demo-dtb.sh allocates the
# three vdev phandles above the highest one the vendor tree uses, so their
# values are not fixed. What this gate checks instead is the linkage: each
# node's own phandle must sit at that node's position in cr52_1's
# memory-region list. That is the property the kernel actually depends on.
REGIONS="cr52_ram1 $BASE $SIZE
vdev0vring0 5dc00000 3000
vdev0vring1 5dc03000 3000
vdev0buffer 5dc10000 100000"
fail() { echo "DEMO_ROLE_FAIL reason=$1"; exit 1; }
hex32() { od -An -tx1 "$1" 2>/dev/null | tr -d ' \n'; }
# Is [start,end] covered by some reserved range in /proc/iomem?
#
# Containment, not an exact base-end match. The kernel COALESCES adjacent
# reserved regions into one line, and three of these four windows are
# contiguous, so on a correct board they render as a single
# "5da00000-5dc05fff : reserved" and an exact match finds none of them.
# Board-observed on board 2, 2026-09-18: the exact-match version of this check
# failed with carveout_not_reserved on a boot whose carveouts were all correct.
reserved_covers() {
    local want_start=$1 want_end=$2 range rest s e
    while read -r range rest; do
        case "$rest" in *reserved*) ;; *) continue ;; esac
        case "$range" in *-*) ;; *) continue ;; esac
        s=${range%%-*}; e=${range##*-}
        [ $((0x$s)) -le $((0x$want_start)) ] && [ $((0x$e)) -ge $((0x$want_end)) ] && return 0
    done < "$IOMEM_FILE"
    return 1
}

role=$(tr ' ' '\n' < "$CMDLINE_FILE" | sed -n 's/^x5h\.role=//p' | tail -1)
case "$role" in demo|dev) ;; *) fail "wrong_role role=${role:-unset}" ;; esac
reserved_covers "$BASE" "$END" || fail carveout_not_reserved
node="$DT_ROOT/reserved-memory/cr52_ram1@$BASE"
[ -d "$node" ] || fail carveout_node_missing
[ "$(hex32 "$node/phandle")" = "0000010a" ] || fail carveout_phandle
# cr52_1's memory-region first, because every node below is checked against its
# own slot in that list. Exactly one cr52_1* node may carry the property.
matches=()
for f in "$DT_ROOT"/soc/cr52_1*/memory-region; do [ -e "$f" ] && matches+=("$f"); done
case "${#matches[@]}" in
    0) fail cr52_memory_region ;;
    1) ;;
    *) fail cr52_node_ambiguous ;;
esac
mr=$(hex32 "${matches[0]}")
# Four phandles, 4 bytes each, so 32 hex characters and no more.
[ "${#mr}" -eq 32 ] || fail cr52_memory_region
# Each window: reserved in /proc/iomem, present as a node, and its phandle in
# its own slot of the list.
i=0
while read -r rname rbase rsize; do
    rend=$(printf '%x' $((0x$rbase + 0x$rsize - 1)))
    reserved_covers "$rbase" "$rend" || fail "${rname}_not_reserved"
    rnode="$DT_ROOT/reserved-memory/$rname@$rbase"
    [ -d "$rnode" ] || fail "${rname}_node_missing"
    rph=$(hex32 "$rnode/phandle")
    [ "${#rph}" -eq 8 ] || fail "${rname}_phandle"
    [ "$rph" = "${mr:$((i * 8)):8}" ] || fail "${rname}_not_linked"
    i=$((i + 1))
done <<<"$REGIONS"
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
dmesg_out=$($DMESG_CMD)
grep -q 'assigned reserved memory node linux,npu_region' <<<"$dmesg_out" || fail cmem_probe_missing
state=$(cat "$RPROC_DIR/state" 2>/dev/null) || fail remoteproc_missing
echo "DEMO_ROLE_PASS role=$role carveout=0x$BASE vdev=0x$VDEV_BASE remoteproc=$state"
