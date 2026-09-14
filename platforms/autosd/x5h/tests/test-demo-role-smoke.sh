#!/usr/bin/env bash
# demo-role-smoke.sh judges the demo boot from /proc and /sys. Feed it a
# fake tree of each and check its verdicts.
set -u
name=test-demo-role-smoke
here=$(cd "$(dirname "$0")" && pwd)
s="$here/../scripts/demo-role-smoke.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
good() {
    rm -rf "$tmp/g"; mkdir -p "$tmp/g/dt/reserved-memory/cr52_ram1@5da00000" "$tmp/g/dt/soc/cr52_1" "$tmp/g/uio/uio2" "$tmp/g/rproc"
    for r in 1400000000 1c00000000 64000000 8e400000; do mkdir -p "$tmp/g/dt/reserved-memory/linux,npu_region@$r"; done
    printf '\0\0\1\n' > "$tmp/g/dt/reserved-memory/cr52_ram1@5da00000/phandle"   # 0x0000010a
    printf '\0\0\1\n' > "$tmp/g/dt/soc/cr52_1/memory-region"
    echo 'root=x x5h.role=demo' > "$tmp/g/cmdline"
    printf '40000000-8affffff : System RAM\n  5da00000-5dbfffff : reserved\n' > "$tmp/g/iomem"
    echo offline > "$tmp/g/rproc/state"
    printf '#!/bin/sh\necho "[1.0] assigned reserved memory node linux,npu_region@8e400000"\n' > "$tmp/g/dmesg"; chmod +x "$tmp/g/dmesg"
}
run() { CMDLINE_FILE="$tmp/g/cmdline" IOMEM_FILE="$tmp/g/iomem" DT_ROOT="$tmp/g/dt" UIO_DIR="$tmp/g/uio" RPROC_DIR="$tmp/g/rproc" DMESG_CMD="$tmp/g/dmesg" bash "$s"; }
good; out=$(run) || fail good_tree_rejected
grep -q '^DEMO_ROLE_PASS role=demo carveout=0x5da00000 remoteproc=offline$' <<<"$out" || fail no_pass_marker
good; echo 'x5h.role=npu' > "$tmp/g/cmdline"; out=$(run) && fail npu_accepted
grep -q 'reason=role_not_demo' <<<"$out" || fail npu_reason
good; echo '40000000-8affffff : System RAM' > "$tmp/g/iomem"; out=$(run) && fail missing_reservation_accepted
grep -q 'reason=carveout_not_reserved' <<<"$out" || fail reservation_reason
good; printf '\0\0\1\v' > "$tmp/g/dt/reserved-memory/cr52_ram1@5da00000/phandle"; out=$(run) && fail wrong_phandle_accepted
grep -q 'reason=carveout_phandle' <<<"$out" || fail phandle_reason
good; rm -r "$tmp/g/dt/reserved-memory/cr52_ram1@5da00000"; out=$(run) && fail missing_carveout_node_accepted
grep -q 'reason=carveout_node_missing' <<<"$out" || fail carveout_node_reason
good; rm -r "$tmp/g/dt/soc/cr52_1"; out=$(run) && fail missing_memory_region_accepted
grep -q 'reason=cr52_memory_region' <<<"$out" || fail memory_region_missing_reason
good; printf '\0\0\1\v' > "$tmp/g/dt/soc/cr52_1/memory-region"; out=$(run) && fail wrong_memory_region_accepted
grep -q 'reason=cr52_memory_region' <<<"$out" || fail memory_region_wrong_reason
good; mkdir -p "$tmp/g/dt/soc/cr52_1a"; printf '\0\0\1\v' > "$tmp/g/dt/soc/cr52_1/memory-region"; printf '\0\0\1\n' > "$tmp/g/dt/soc/cr52_1a/memory-region"; out=$(run) && fail ambiguous_node_accepted
grep -q 'reason=cr52_node_ambiguous' <<<"$out" || fail ambiguous_node_reason
for r in 1400000000 1c00000000 64000000 8e400000; do
    good; rm -r "$tmp/g/dt/reserved-memory/linux,npu_region@$r"; out=$(run) && fail missing_npu_region_accepted
    grep -q "reason=npu_region_${r}_missing" <<<"$out" || fail npu_region_reason
done
good; rmdir "$tmp/g/uio/uio2"; out=$(run) && fail missing_uio_accepted
grep -q 'reason=uio2_missing' <<<"$out" || fail uio_reason
good; printf '#!/bin/sh\necho "[1.0] nothing relevant"\n' > "$tmp/g/dmesg"; chmod +x "$tmp/g/dmesg"; out=$(run) && fail missing_cmem_probe_accepted
grep -q 'reason=cmem_probe_missing' <<<"$out" || fail cmem_probe_reason
good; rm "$tmp/g/rproc/state"; out=$(run) && fail missing_remoteproc_accepted
grep -q 'reason=remoteproc_missing' <<<"$out" || fail remoteproc_reason
echo "TEST_PASS $name"
