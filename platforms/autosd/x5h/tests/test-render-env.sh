#!/usr/bin/env bash
set -u
name=test-render-env
here=$(cd "$(dirname "$0")" && pwd)
r="$here/../uboot/render-env.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$r" ] || fail renderer_missing
e1=$(bash "$r" "$here/../boards/x5h1.vars") || fail render_x5h1
e2=$(bash "$r" "$here/../boards/x5h2.vars") || fail render_x5h2
# Both boards must define the same variable names in the same order.
[ "$(printf '%s\n' "$e1" | cut -d= -f1)" = "$(printf '%s\n' "$e2" | cut -d= -f1)" ] || fail key_set_differs
# The only lines allowed to differ carry the board's ip/hostname.
diff <(printf '%s\n' "$e1") <(printf '%s\n' "$e2") | grep '^[<>]' | grep -v 'ip=192.168.0' && fail non_vars_diff
# Every role has a bootcmd and the common bootargs carry the load-bearing arguments.
for role in cr52 npu yocto; do
    printf '%s\n' "$e1" | grep -q "^bootcmd_${role}=" || fail "no_bootcmd_${role}"
done
printf '%s\n' "$e1" | grep '^bootargs_common=' | grep -q 'pd_ignore_unused clk_ignore_unused' || fail no_clk_args
printf '%s\n' "$e1" | grep '^bootargs_common=' | grep -q 'panic=10 oops=panic' || fail no_panic_args
printf '%s\n' "$e1" | grep '^bootargs_common=' | grep -q 'ip=192.168.0.20::192.168.0.1:255.255.255.0:autosd-x5h:tsn5:none' || fail bad_ip_form
printf '%s\n' "$e2" | grep '^bootargs_common=' | grep -q 'ip=192.168.0.21::192.168.0.1:255.255.255.0:autosd-x5h-2:tsn5:none' || fail bad_ip_form_2
printf '%s\n' "$e2" | grep '^bootargs_yocto=' | grep -q 'yocto-x5h-2' || fail yocto_hostname
printf '%s\n' "$e1" | grep -q '^load_role=.*x5h-role.txt' || fail no_role_file_loader
printf '%s\n' "$e1" | grep -q '^probe_lu=.*x5h-env.txt' || fail probe_not_env_file
printf '%s\n' "$e1" | grep '^bootcmd=' | grep -q 'run find_autosd; run load_role; run check_role' || fail bootcmd_order
printf '%s\n' "$e1" | grep '^check_role=' | grep -q 'setenv role npu' || fail check_role_no_fallback
printf '%s\n' "$e1" | grep '^load_role=' | grep -q 'if ' && fail load_role_uses_if
for role in cr52 npu; do
    printf '%s\n' "$e1" | grep "^bootcmd_${role}=" | grep -q '&& booti' || fail "bootcmd_${role}_booti_not_chained"
done
# No placeholder survives rendering, and no line is empty (env import -t would still accept it, but it hides mistakes).
printf '%s\n' "$e1" | grep -q '@' && fail placeholder_left
printf '%s\n' "$e1" | grep -q '^$' && fail empty_line
# A vars file missing a key must be refused.
tmp=$(mktemp); printf 'BOARD_IP=1.2.3.4\n' > "$tmp"
bash "$r" "$tmp" >/dev/null 2>&1 && fail accepts_incomplete_vars
rm -f "$tmp"
echo "TEST_PASS $name"
