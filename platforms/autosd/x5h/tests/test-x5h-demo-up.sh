#!/usr/bin/env bash
# x5h-demo-up.sh with a fake systemctl: starts the five units in order,
# regenerates the Quadlet output only when x5h-vp.service is unknown, and
# names the failing unit.
set -u
name=test-x5h-demo-up
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/x5h-demo-up.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/systemctl" <<'EOF'
#!/bin/sh
echo "$*" >> "$LOG"
case "$1" in
  cat) [ "${KNOWN:-1}" = 1 ] ;;
  start) [ "$2" != "${FAILING:-none}" ] ;;
  *) true ;;
esac
EOF
printf '#!/bin/sh\necho "quadlet $*" >> "$LOG"\n' > "$tmp/quadlet"
chmod +x "$tmp/systemctl" "$tmp/quadlet"
run() { LOG="$tmp/log" SYSTEMCTL="$tmp/systemctl" QUADLET="$tmp/quadlet" bash "$s"; }
: > "$tmp/log"; out=$(KNOWN=1 run) || fail "good_failed $out"
grep -q '^X5H_DEMO_UP units=5$' <<<"$out" || fail pass_marker
order=$(grep '^start' "$tmp/log" | tr '\n' ' ')
[ "$order" = "start x5h-si-link.service start x5h-demo-bridge.service start x5h-demo-restamp.service start x5h-demo-hb.service start x5h-vp.service " ] || fail "order=$order"
grep -q '^quadlet' "$tmp/log" && fail regenerated_when_known
: > "$tmp/log"; out=$(KNOWN=0 run) || fail "regen_failed $out"
grep -q '^quadlet /run/systemd/system /run/systemd/system /run/systemd/system$' "$tmp/log" || fail no_regen
grep -q '^daemon-reload' "$tmp/log" || fail no_reload
: > "$tmp/log"; out=$(KNOWN=1 FAILING=x5h-demo-hb.service run) && fail failure_hidden
grep -q '^X5H_DEMO_UP_FAIL reason=x5h-demo-hb.service$' <<<"$out" || fail "fail_reason out=$out"
echo "TEST_PASS $name"
