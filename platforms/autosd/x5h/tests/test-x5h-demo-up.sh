#!/usr/bin/env bash
# x5h-demo-up.sh with a fake systemctl: starts the five units in order,
# regenerates the Quadlet output only when x5h-vp.service is unknown, names
# the failing unit, and treats a unit systemd SKIPPED (start rc=0, but
# is-active reports inactive -- the shape of a failed Condition=) the same
# as a hard failure.
set -u
name=test-x5h-demo-up
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/x5h-demo-up.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
exact() { [ "$1" = "$2" ] || fail "$3 out=$1"; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/systemctl" <<'EOF'
#!/bin/sh
echo "$*" >> "$LOG"
case "$1" in
  cat) [ "${KNOWN:-1}" = 1 ] ;;
  start) [ "$2" != "${FAILING:-none}" ] ;;
  is-active)
    if [ "$2" = "${INACTIVE:-none}" ]; then echo inactive; exit 3
    else echo active; exit 0
    fi ;;
  *) true ;;
esac
EOF
printf '#!/bin/sh\necho "quadlet $*" >> "$LOG"\n' > "$tmp/quadlet"
chmod +x "$tmp/systemctl" "$tmp/quadlet"
run() { LOG="$tmp/log" SYSTEMCTL="$tmp/systemctl" QUADLET="$tmp/quadlet" bash "$s"; }
: > "$tmp/log"; out=$(KNOWN=1 run) || fail "good_failed $out"
exact "$out" 'X5H_DEMO_UP units=5' pass_marker
order=$(grep '^start' "$tmp/log" | tr '\n' ' ')
[ "$order" = "start x5h-si-link.service start x5h-demo-bridge.service start x5h-demo-restamp.service start x5h-demo-hb.service start x5h-vp.service " ] || fail "order=$order"
grep -q '^quadlet' "$tmp/log" && fail regenerated_when_known
: > "$tmp/log"; out=$(KNOWN=0 run) || fail "regen_failed $out"
grep -q '^quadlet /run/systemd/system /run/systemd/system /run/systemd/system$' "$tmp/log" || fail no_regen
grep -q '^daemon-reload' "$tmp/log" || fail no_reload
: > "$tmp/log"; out=$(KNOWN=1 FAILING=x5h-demo-hb.service run) && fail failure_hidden
exact "$out" 'X5H_DEMO_UP_FAIL reason=x5h-demo-hb.service' fail_reason

# systemd returns rc=0 for a unit it SKIPPED because a Condition failed
# (board-verified: ConditionPathExists on a missing binary). The orchestrator
# must not take that silent "success" at face value -- it has to notice the
# unit never became active and fail, naming that unit.
: > "$tmp/log"; out=$(KNOWN=1 INACTIVE=x5h-si-link.service run) && fail condition_skip_hidden
exact "$out" 'X5H_DEMO_UP_FAIL reason=x5h-si-link.service' condition_skip_reason

echo "TEST_PASS $name"
