#!/usr/bin/env bash
set -u
name=test-x5h-role
here=$(cd "$(dirname "$0")" && pwd)
x="$here/../scripts/x5h-role"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -f "$x" ] || fail script_missing
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
printf 'BOARD_HOSTNAME=autosd-x5h\nHAS_YOCTO=0\n' > "$d/board.conf"
printf 'console=ttySC0 x5h.role=npu root=PARTUUID=x\n' > "$d/cmdline"
run() { X5H_BOOT_DIR="$d/boot" X5H_BOARD_CONF="$d/board.conf" X5H_CMDLINE="$d/cmdline" sh "$x" "$@"; }
mkdir -p "$d/boot"
# show: current from cmdline, next unset when no file
out=$(run) || fail show_exit
printf '%s\n' "$out" | grep -qx 'current=npu' || fail "show_current: $out"
printf '%s\n' "$out" | grep -qx 'next=unset' || fail "show_next_unset: $out"
# set cr52 writes the file atomically with the exact format U-Boot imports
out=$(run set cr52) || fail set_cr52_exit
printf '%s\n' "$out" | grep -qx 'ROLE_SET next=cr52' || fail "set_marker: $out"
[ "$(cat "$d/boot/x5h-role.txt")" = "role=cr52" ] || fail "file_content: $(cat "$d/boot/x5h-role.txt")"
ls "$d/boot" | grep -q '\.tmp' && fail tmp_left_behind
out=$(run); printf '%s\n' "$out" | grep -qx 'next=cr52' || fail "show_next: $out"
# invalid role refused, file untouched
run set bogus >/dev/null 2>&1 && fail accepts_bogus
[ "$(cat "$d/boot/x5h-role.txt")" = "role=cr52" ] || fail bogus_changed_file
# yocto refused on a board without it, accepted with HAS_YOCTO=1
out=$(run set yocto 2>&1); printf '%s\n' "$out" | grep -q 'ROLE_SET_FAIL reason=yocto_absent' || fail "yocto_absent: $out"
printf 'BOARD_HOSTNAME=autosd-x5h-2\nHAS_YOCTO=1\n' > "$d/board.conf"
run set yocto >/dev/null || fail yocto_accept
[ "$(cat "$d/boot/x5h-role.txt")" = "role=yocto" ] || fail yocto_file
# unwritable boot dir -> fail, nothing changed
chmod 500 "$d/boot"
out=$(run set npu 2>&1); printf '%s\n' "$out" | grep -q 'ROLE_SET_FAIL reason=write_failed' || { chmod 700 "$d/boot"; fail "write_failed: $out"; }
chmod 700 "$d/boot"
[ "$(cat "$d/boot/x5h-role.txt")" = "role=yocto" ] || fail write_failed_changed_file
# banner
b="$here/../scripts/x5h-role-banner.sh"
out=$(X5H_CMDLINE="$d/cmdline" X5H_RUN_DIR="$d/run" X5H_MOTD_DIR="$d/motd" sh "$b") || fail banner_exit
[ "$(cat "$d/run/role")" = "npu" ] || fail banner_run_file
grep -q 'role: npu' "$d/motd/x5h-role" || fail banner_motd
echo "TEST_PASS $name"
