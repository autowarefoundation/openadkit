#!/usr/bin/env bash
# demo-role-smoke.sh judges a derived-tree boot from /proc and /sys. Feed it
# a fake tree of each and check its verdicts. demo and dev boot that same
# tree, so both must pass and the retired roles must not.
set -u
name=test-demo-role-smoke
here=$(cd "$(dirname "$0")" && pwd)
s="$here/../scripts/demo-role-smoke.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
# A large, matching-line-early dmesg is the point: the real bug is a race
# (grep -q closes the pipe on its first match, dmesg then SIGPIPEs on its
# next write, pipefail turns that 141 into a false FAIL) and a race needs
# enough trailing output that the producer is still writing when the
# consumer exits. A single short line never reaches the pipe buffer, so the
# old fixture could not have caught this.
write_big_dmesg() {
    {
        echo '#!/bin/sh'
        echo 'echo "[1.0] assigned reserved memory node linux,npu_region@8e400000"'
        echo 'i=0; while [ $i -lt 5000 ]; do echo "[1.$i] filler line padding dmesg well past a pipe buffer"; i=$((i+1)); done'
    } > "$tmp/g/dmesg"
    chmod +x "$tmp/g/dmesg"
}
good() {
    rm -rf "$tmp/g"; mkdir -p "$tmp/g/dt/reserved-memory/cr52_ram1@5da00000" "$tmp/g/dt/soc/cr52_1" "$tmp/g/uio/uio2" "$tmp/g/rproc"
    for r in 1400000000 1c00000000 64000000 8e400000; do mkdir -p "$tmp/g/dt/reserved-memory/linux,npu_region@$r"; done
    printf '\0\0\1\n' > "$tmp/g/dt/reserved-memory/cr52_ram1@5da00000/phandle"   # 0x0000010a
    # The three vdev carveouts. Their phandles are derived by make-demo-dtb.sh
    # from the vendor tree's highest, so the fixture uses values well away from
    # 0x10a (0x205 0x206 0x207, what the real tree yields today) and the script
    # must judge them by their linkage, not by any constant.
    for v in vdev0vring0@5dc00000:'\005' vdev0vring1@5dc03000:'\006' vdev0buffer@5dc10000:'\007'; do
        mkdir -p "$tmp/g/dt/reserved-memory/${v%:*}"
        printf '\0\0\2%b' "${v#*:}" > "$tmp/g/dt/reserved-memory/${v%:*}/phandle"
    done
    printf '\0\0\1\n\0\0\2\005\0\0\2\006\0\0\2\007' > "$tmp/g/dt/soc/cr52_1/memory-region"
    echo 'root=x x5h.role=demo' > "$tmp/g/cmdline"
    # The REAL /proc/iomem from board 2 after the fix, 2026-09-18, not an
    # invented one. The kernel coalesces the three contiguous windows into a
    # single reserved line, which is exactly what broke the first version of
    # this gate, so the fixture has to carry that shape.
    cat > "$tmp/g/iomem" <<'IOMEM'
40000000-5d9fffff : System RAM
  40000000-5d9fffff : reserved
5da00000-5dc05fff : reserved
5dc06000-5dc0ffff : System RAM
5dc10000-5dd0ffff : reserved
5dd10000-8affffff : System RAM
IOMEM
    echo offline > "$tmp/g/rproc/state"
    write_big_dmesg
}
run() { CMDLINE_FILE="$tmp/g/cmdline" IOMEM_FILE="$tmp/g/iomem" DT_ROOT="$tmp/g/dt" UIO_DIR="$tmp/g/uio" RPROC_DIR="$tmp/g/rproc" DMESG_CMD="$tmp/g/dmesg" bash "$s"; }
# Both AD Kit roles pass, and the marker reports which one was found rather
# than asserting demo, so a dev boot cannot be read back as a demo boot.
for role in demo dev; do
    good; echo "root=x x5h.role=$role" > "$tmp/g/cmdline"
    out=$(run) || fail "good_tree_rejected_$role"
    grep -q "^DEMO_ROLE_PASS role=$role carveout=0x5da00000 vdev=0x5dc00000 remoteproc=offline$" <<<"$out" || fail "no_pass_marker_$role"
done
# Each vdev carveout, missing three ways. These are the checks gate D1a did not
# have on 2026-09-17, when it passed a tree whose vrings remoteproc then
# allocated from linux,cma@40000000 and the CR52 data-aborted on.
while read -r vn vb vsize; do
    good; rm -r "$tmp/g/dt/reserved-memory/$vn@$vb"; out=$(run) && fail "missing_${vn}_accepted"
    grep -q "reason=${vn}_node_missing" <<<"$out" || fail "${vn}_node_reason"
    # A node whose phandle is not the one cr52_1 lists in that slot: the tree
    # carries the window but nothing routes the core to it.
    good; printf '\0\0\2\377' > "$tmp/g/dt/reserved-memory/$vn@$vb/phandle"; out=$(run) && fail "unlinked_${vn}_accepted"
    grep -q "reason=${vn}_not_linked" <<<"$out" || fail "${vn}_link_reason"
    # The node and its linkage are right but the kernel never reserved the
    # window, so remoteproc still allocates it from linux,cma@40000000. The
    # fixture splits its reservation around this one window, leaving every
    # earlier window covered, because a fixture that drops all reserved lines
    # stops at carveout_not_reserved and never reaches this check.
    good
    { printf '%s-%x : reserved\n' 5da00000 $((0x$vb - 1))
      printf '%x-%s : reserved\n' $((0x$vb + 0x$vsize)) 8affffff; } > "$tmp/g/iomem"
    out=$(run) && fail "unreserved_${vn}_accepted"
    grep -q "reason=${vn}_not_reserved" <<<"$out" || fail "${vn}_reservation_reason"
done <<'EOF'
vdev0vring0 5dc00000 3000
vdev0vring1 5dc03000 3000
vdev0buffer 5dc10000 100000
EOF
# A tree carrying only cr52_ram1 -- exactly the 2026-09-17 tree -- is refused.
good; for vn in vdev0vring0@5dc00000 vdev0vring1@5dc03000 vdev0buffer@5dc10000; do rm -r "$tmp/g/dt/reserved-memory/$vn"; done
printf '\0\0\1\n' > "$tmp/g/dt/soc/cr52_1/memory-region"
out=$(run) && fail pre_fix_tree_accepted
# yocto, the two retired roles, and no role word at all are all refused.
for bad in yocto cr52 npu; do
    good; echo "x5h.role=$bad" > "$tmp/g/cmdline"; out=$(run) && fail "${bad}_accepted"
    grep -q "reason=wrong_role role=$bad" <<<"$out" || fail "${bad}_reason"
done
good; echo 'root=x quiet' > "$tmp/g/cmdline"; out=$(run) && fail unset_accepted
grep -q 'reason=wrong_role role=unset' <<<"$out" || fail unset_reason
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
good; mkdir -p "$tmp/g/dt/soc/cr52_1a"; printf '\0\0\1\n' > "$tmp/g/dt/soc/cr52_1a/memory-region"; out=$(run) && fail ambiguous_node_accepted
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
