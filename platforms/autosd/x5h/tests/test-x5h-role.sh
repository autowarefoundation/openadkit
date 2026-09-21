#!/usr/bin/env bash
set -u
name=test-x5h-role
here=$(cd "$(dirname "$0")" && pwd)
x="$here/../scripts/x5h-role"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -f "$x" ] || fail script_missing
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
printf 'BOARD_HOSTNAME=autosd-x5h\nHAS_YOCTO=0\n' > "$d/board.conf"
printf 'console=ttySC0 x5h.role=dev root=PARTUUID=x\n' > "$d/cmdline"
run() { X5H_BOOT_DIR="$d/boot" X5H_BOARD_CONF="$d/board.conf" X5H_CMDLINE="$d/cmdline" sh "$x" "$@"; }
mkdir -p "$d/boot"
# show: current from cmdline, next unset when no file
out=$(run) || fail show_exit
printf '%s\n' "$out" | grep -qx 'current=dev' || fail "show_current: $out"
printf '%s\n' "$out" | grep -qx 'next=unset' || fail "show_next_unset: $out"
# set demo writes the file atomically with the exact format U-Boot imports
out=$(run set demo) || fail set_demo_exit
printf '%s\n' "$out" | grep -qx 'ROLE_SET next=demo' || fail "set_marker: $out"
[ "$(cat "$d/boot/x5h-role.txt")" = "role=demo" ] || fail "file_content: $(cat "$d/boot/x5h-role.txt")"
ls "$d/boot" | grep -q '\.tmp' && fail tmp_left_behind
out=$(run); printf '%s\n' "$out" | grep -qx 'next=demo' || fail "show_next: $out"
# invalid role refused, file untouched. cr52 and npu were roles once and are
# not any more, so the setter has to refuse them by name rather than silently
# writing a role U-Boot would fall back out of.
for bogus in bogus cr52 npu; do
    run set "$bogus" >/dev/null 2>&1 && fail "accepts_$bogus"
    [ "$(cat "$d/boot/x5h-role.txt")" = "role=demo" ] || fail "${bogus}_changed_file"
done
# dev is the other AD Kit role and the setter must accept it like demo.
out=$(run set dev) || fail set_dev_exit
printf '%s\n' "$out" | grep -qx 'ROLE_SET next=dev' || fail "set_dev_marker: $out"
[ "$(cat "$d/boot/x5h-role.txt")" = "role=dev" ] || fail "dev_file_content: $(cat "$d/boot/x5h-role.txt")"
# yocto refused on a board without it, accepted with HAS_YOCTO=1
out=$(run set yocto 2>&1); printf '%s\n' "$out" | grep -q 'ROLE_SET_FAIL reason=yocto_absent' || fail "yocto_absent: $out"
printf 'BOARD_HOSTNAME=autosd-x5h-2\nHAS_YOCTO=1\n' > "$d/board.conf"
run set yocto >/dev/null || fail yocto_accept
[ "$(cat "$d/boot/x5h-role.txt")" = "role=yocto" ] || fail yocto_file
# unwritable boot dir -> fail, nothing changed
chmod 500 "$d/boot"
out=$(run set dev 2>&1); printf '%s\n' "$out" | grep -q 'ROLE_SET_FAIL reason=write_failed' || { chmod 700 "$d/boot"; fail "write_failed: $out"; }
chmod 700 "$d/boot"
[ "$(cat "$d/boot/x5h-role.txt")" = "role=yocto" ] || fail write_failed_changed_file
# banner
b="$here/../scripts/x5h-role-banner.sh"
out=$(X5H_CMDLINE="$d/cmdline" X5H_RUN_DIR="$d/run" X5H_MOTD_DIR="$d/motd" sh "$b") || fail banner_exit
[ "$(cat "$d/run/role")" = "dev" ] || fail banner_run_file
grep -q 'role: dev' "$d/motd/x5h-role" || fail banner_motd
echo "TEST_PASS $name"
