#!/usr/bin/env bash
set -u
name=test-x5h-parity
here=$(cd "$(dirname "$0")" && pwd)
p="$here/../scripts/x5h-parity.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -f "$p" ] || fail script_missing
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
v1="$here/../boards/x5h1.vars"; v2="$here/../boards/x5h2.vars"
printf 'boot.x5h-env.txt\taaaa\ncmdline\tpd_ignore_unused root=X\nfile./etc/x5h/board.conf\t1111\nhostname\tautosd-x5h\npart.1.2\tyocto-root:8G:...5e12\nfs.yocto-root\tnone\n' > "$d/m1"
printf 'boot.x5h-env.txt\tbbbb\ncmdline\tpd_ignore_unused root=X\nfile./etc/x5h/board.conf\t2222\nhostname\tautosd-x5h-2\npart.1.2\tyocto-root:8G:...5e12\nfs.yocto-root\text4\n' > "$d/m2"
# Only vars-derived keys differ -> PASS
out=$(bash "$p" "$d/m1" "$v1" "$d/m2" "$v2") || fail "pass_case_exit: $out"
printf '%s\n' "$out" | grep -qx 'BOARD_PARITY_PASS' || fail "pass_case: $out"
# A non-vars difference -> FAIL naming the key
printf 'file./etc/systemd/system/x5h-npu.service\tabcd\n' >> "$d/m1"
printf 'file./etc/systemd/system/x5h-npu.service\tdcba\n' >> "$d/m2"
out=$(bash "$p" "$d/m1" "$v1" "$d/m2" "$v2"); rc=$?
[ $rc -eq 1 ] || fail fail_case_rc
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=residual_diff' || fail "fail_case_marker: $out"
printf '%s\n' "$out" | grep -q 'x5h-npu.service' || fail "fail_case_names_key: $out"
# A key present on one board only is also a residual
printf 'unit.extra.service\tenabled\n' >> "$d/m2"
bash "$p" "$d/m1" "$v1" "$d/m2" "$v2" | grep -q 'unit.extra.service' || fail one_sided_key
echo "TEST_PASS $name"
