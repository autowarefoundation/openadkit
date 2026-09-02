#!/usr/bin/env bash
set -u
name=test-x5h-parity
here=$(cd "$(dirname "$0")" && pwd)
p="$here/../scripts/x5h-parity.sh"
mf="$here/../scripts/x5h-manifest.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -f "$p" ] || fail script_missing
[ -f "$mf" ] || fail manifest_missing
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
v1="$here/../boards/x5h1.vars"; v2="$here/../boards/x5h2.vars"

# Every manifest fixture must clear the completeness floor (kernel, cmdline,
# env.md5, one boot.*, one unit.*) or parity refuses it before diffing.
base1='boot.Image\t1111aaaa\nboot.x5h-env.txt\taaaa\ncmdline\tpd_ignore_unused root=X\nenv.md5\te0e0e0e0\nfile./etc/x5h/board.conf\t1111\nfs.yocto-root\tnone\nhostname\tautosd-x5h\nkernel\t6.1.102-autosd\npart.1.2\tyocto-root:8G:...5e12\nunit.x5h-role.service\tenabled\n'
base2='boot.Image\t1111aaaa\nboot.x5h-env.txt\tbbbb\ncmdline\tpd_ignore_unused root=X\nenv.md5\te0e0e0e0\nfile./etc/x5h/board.conf\t2222\nfs.yocto-root\text4\nhostname\tautosd-x5h-2\nkernel\t6.1.102-autosd\npart.1.2\tyocto-root:8G:...5e12\nunit.x5h-role.service\tenabled\n'
printf "$base1" > "$d/m1"
printf "$base2" > "$d/m2"

# --- original assertions -------------------------------------------------
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

# --- FIX 1: the completeness floor --------------------------------------
# An empty manifest used to compare clean against anything equally empty.
: > "$d/empty"
out=$(bash "$p" "$d/empty" "$v1" "$d/m2" "$v2"); rc=$?
[ $rc -eq 2 ] || fail "empty_manifest_rc: $rc"
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=incomplete_manifest' || fail "empty_manifest: $out"
printf '%s\n' "$out" | grep -q 'missing=all_keys' || fail "empty_manifest_names_gap: $out"
: > "$d/empty2"
out=$(bash "$p" "$d/empty" "$v1" "$d/empty2" "$v2")
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=incomplete_manifest' || fail "two_empty_manifests: $out"

# Each required prefix, dropped in turn, must be named.
for key in kernel cmdline env.md5 boot. unit.; do
    grep -v "^$key" "$d/m1" > "$d/gap"
    out=$(bash "$p" "$d/gap" "$v1" "$d/m2" "$v2"); rc=$?
    [ $rc -eq 2 ] || fail "floor_rc_$key: $rc"
    printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=incomplete_manifest' || fail "floor_$key: $out"
    printf '%s\n' "$out" | grep -q "manifest=$d/gap" || fail "floor_names_manifest_$key: $out"
done
# ... and specifically the boot.* case the reviewer proved false-PASSes.
grep -v '^boot\.' "$d/m1" > "$d/noboot"
bash "$p" "$d/noboot" "$v1" "$d/m2" "$v2" | grep -q 'missing=boot\.\*' || fail missing_boot_not_named

# A manifest that captured the manifest script's own failure marker (2>&1) is
# not data, whatever else it contains.
cp "$d/m1" "$d/marked"; printf 'X5H_MANIFEST_FAIL reason=boot_mount\n' >> "$d/marked"
bash "$p" "$d/marked" "$v1" "$d/m2" "$v2" | grep -q 'missing=manifest_marked_failed' || fail marker_in_manifest_accepted

# The reviewer's decisive experiment, both halves.
printf "$base1" | sed 's/^boot\.Image\t.*/boot.Image\tAAAAAAAA/' > "$d/r1"
printf "$base2" | sed 's/^boot\.Image\t.*/boot.Image\tBBBBBBBB/' > "$d/r2"
out=$(bash "$p" "$d/r1" "$v1" "$d/r2" "$v2"); rc=$?
[ $rc -eq 1 ] || fail "boot_image_diff_rc: $rc"
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=residual_diff' || fail "boot_image_diff: $out"
grep -v '^boot\.' "$d/r1" > "$d/r1nb"; grep -v '^boot\.' "$d/r2" > "$d/r2nb"
out=$(bash "$p" "$d/r1nb" "$v1" "$d/r2nb" "$v2"); rc=$?
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_PASS' && fail "mount_failed_on_both_still_passes: $out"
[ $rc -eq 2 ] || fail "mount_failed_on_both_rc: $rc"
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=incomplete_manifest' || fail "mount_failed_on_both: $out"

# The same manifest handed in twice always compares clean; refuse it.
out=$(bash "$p" "$d/m1" "$v1" "$d/m1" "$v2"); rc=$?
[ $rc -eq 2 ] || fail "same_manifest_rc: $rc"
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=same_manifest' || fail "same_manifest: $out"
out=$(bash "$p" "$d/m1" "$v1" "$d/./m1" "$v2")
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=same_manifest' || fail "same_manifest_via_path: $out"

# --- FIX 2: env.md5 is real, normalized, and not exempt ------------------
printf "$base1" | sed 's/^env\.md5\t.*/env.md5\tAAAA0000/' > "$d/e1"
printf "$base2" | sed 's/^env\.md5\t.*/env.md5\tBBBB0000/' > "$d/e2"
out=$(bash "$p" "$d/e1" "$v1" "$d/e2" "$v2"); rc=$?
[ $rc -eq 1 ] || fail "env_md5_diff_rc: $rc"
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=residual_diff' || fail "env_md5_diff: $out"
printf '%s\n' "$out" | grep -q 'env.md5' || fail "env_md5_diff_names_key: $out"

# x5h-manifest.sh must actually emit env.md5 (the plan's Interfaces line named
# it; the first implementation never wrote it).
grep -q 'emit env\.md5' "$mf" || fail manifest_no_env_md5_emit

# The normalization itself: lift the sed program straight out of the manifest
# script so the test cannot drift away from what the board runs.
raw=$(grep -F 'envmd5=$(sed ' "$mf") || fail manifest_no_env_md5_sed
expr=${raw#*sed \'}; expr=${expr%%\' *}
[ -n "$expr" ] || fail env_sed_extract
r="$here/../uboot/render-env.sh"
norm() { bash "$r" "$1" | sed "$expr" | md5sum | cut -c1-32; }
rawmd5() { bash "$r" "$1" | md5sum | cut -c1-32; }
[ "$(rawmd5 "$v1")" != "$(rawmd5 "$v2")" ] || fail env_raw_should_differ
[ "$(norm "$v1")" = "$(norm "$v2")" ] || fail env_norm_should_match
# ... and it must still see through to the content it exists to protect.
for probe in 's/clk_ignore_unused //' 's/5e02/5e99/' 's/oops=panic //' 's/0x61080000/0x61090000/'; do
    mutated=$(bash "$r" "$v1" | sed "$probe" | sed "$expr" | md5sum | cut -c1-32)
    [ "$mutated" != "$(norm "$v1")" ] || fail "env_norm_blind_to: $probe"
done

# --- FIX 3: the directories the aib manifest installs into ---------------
for dir in /etc/systemd/system-preset /etc/ssh/authorized_keys.d /etc/NetworkManager/conf.d /etc/tmpfiles.d; do
    grep -q -- "$dir" "$mf" || fail "manifest_missing_scan_dir: $dir"
done

# --- FIX 4: HAS_YOCTO actually decides the fs.yocto-* exemption ----------
printf 'BOARD_IP=192.168.0.99\nBOARD_HOSTNAME=autosd-x5h-3\nHAS_YOCTO=1\n' > "$d/v3"
printf 'BOARD_IP=192.168.0.98\nBOARD_HOSTNAME=autosd-x5h-4\nHAS_YOCTO=x\n' > "$d/vbad"
# m1/m2 differ in fs.yocto-root. HAS_YOCTO 0 vs 1 -> exempt.
printf "$base1" > "$d/y1"; printf "$base2" > "$d/y2"
out=$(bash "$p" "$d/y1" "$v1" "$d/y2" "$v2") || fail "yocto_exempt_when_differ_exit: $out"
printf '%s\n' "$out" | grep -qx 'BOARD_PARITY_PASS' || fail "yocto_exempt_when_differ: $out"
# Both boards HAS_YOCTO=1 -> the same divergence is a genuine defect.
out=$(bash "$p" "$d/y1" "$d/v3" "$d/y2" "$v2"); rc=$?
[ $rc -eq 1 ] || fail "yocto_compared_when_both_1_rc: $rc"
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=residual_diff' || fail "yocto_compared_when_both_1: $out"
printf '%s\n' "$out" | grep -q 'fs.yocto-root' || fail "yocto_compared_names_key: $out"
# Both boards HAS_YOCTO=0 -> likewise compared.
out=$(bash "$p" "$d/y1" "$v1" "$d/y2" "$v1"); rc=$?
[ $rc -eq 1 ] || fail "yocto_compared_when_both_0_rc: $rc"
printf '%s\n' "$out" | grep -q 'fs.yocto-root' || fail "yocto_compared_when_both_0: $out"
# An unreadable HAS_YOCTO is a broken vars file, not a default.
out=$(bash "$p" "$d/y1" "$d/vbad" "$d/y2" "$v2"); rc=$?
[ $rc -eq 2 ] || fail "bad_vars_rc: $rc"
printf '%s\n' "$out" | grep -q 'BOARD_PARITY_FAIL reason=bad_vars' || fail "bad_vars: $out"

echo "TEST_PASS $name"
