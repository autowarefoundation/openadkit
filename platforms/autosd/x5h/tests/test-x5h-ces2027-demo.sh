#!/usr/bin/env bash
# x5h-ces2027-demo.sh check with a fake ssh: composes the READY line from the
# package sha, route.env and the board's unit states, and names a missing
# unit, a corrupt route.env, a dead VisionPilot, a latched Safety Island, or a
# failed ssh transport distinctly.
set -u
name=test-x5h-ces2027-demo
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/x5h-ces2027-demo.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
exact() { [ "$1" = "$2" ] || fail "$3 out=$1"; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/pkg" "$tmp/si" "$tmp/si-bad" "$tmp/si-nospawn"
echo deadbeef > "$tmp/pkg/ces2027-package-sha.txt"
printf 'SPAWN_INDEX=63\nLAP_M=1800\n' > "$tmp/si/route.env"
# The unterminated quote here is the exact shape that used to make sourcing
# route.env fail to parse partway through, leaving SPAWN_INDEX unset and (with
# the old ${SPAWN_INDEX:-?} fallback) still printing a false READY.
printf 'SPAWN_INDEX="63\nLAP_M=1800\n' > "$tmp/si-bad/route.env"
printf 'LAP_M=1800\n' > "$tmp/si-nospawn/route.env"
cat > "$tmp/ssh" <<'EOF'
#!/bin/sh
# $1 = host, rest = command
echo "$*" >> "$LOG"
case "$*" in
  *is-active*)
    [ -z "${SSH_FAIL:-}" ] || exit 1
    printf 'active\nactive\nactive\nactive\nactive\n%s\n' "${LM_STATE:-active}" ;;
  *vp.ready*)
    [ -z "${PROBE_RC:-}" ] || exit "$PROBE_RC"
    [ -z "${VP_READY_RC:-}" ] || exit "$VP_READY_RC"
    # The ready file is there; VisionPilot itself may not be.
    case "$*" in *'pgrep -x VisionPilot'*) [ -z "${VP_DEAD:-}" ] || exit 1 ;; esac ;;
  *journalctl*) echo "RPMSG_SI_RX hb seq=41 uptime_ms=42000 fault=${HB_FAULT:-0}" ;;
  *' true') [ -z "${SSH_FAIL:-}" ] || exit 255 ;;
  *) exit "${CMD_RC:-0}" ;;
esac
EOF
chmod +x "$tmp/ssh"
export LOG="$tmp/log"

out=$(SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si" bash "$s" check) || fail "check_failed $out"
exact "$out" 'X5H_CES_DEMO_READY sha=deadbeef spawn=63 units=6 hb=41' ready_line

out=$(LM_STATE=inactive SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si" bash "$s" check) && fail inactive_accepted
exact "$out" 'X5H_CES_DEMO_FAIL reason=unit_inactive' fail_reason

out=$(bash "$s" bogus 2>&1) && fail bogus_accepted
exact "$out" 'X5H_CES_DEMO_FAIL reason=usage' usage_reason

# A route.env with a syntax error must never be sourced, so it must never
# produce a false READY: it must fail with a marker and a non-zero exit.
rc=0
out=$(SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si-bad" bash "$s" check) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=bad_route' bad_route_syntax_reason
[ "$rc" -ne 0 ] || fail bad_route_syntax_exit_zero

# A route.env with no SPAWN_INDEX line at all fails the same way.
rc=0
out=$(SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si-nospawn" bash "$s" check) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=bad_route' bad_route_missing_reason
[ "$rc" -ne 0 ] || fail bad_route_missing_exit_zero

# ssh itself failing outright (binary missing, connection refused, truncated
# output) must be reported distinctly from "the units are not all active".
rc=0
out=$(SSH_FAIL=1 SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si" bash "$s" check) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=ssh_failed' ssh_failed_reason
[ "$rc" -ne 0 ] || fail ssh_failed_exit_zero

# vp.ready is the launch manager's own readiness: no file, no READY.
rc=0
out=$(VP_READY_RC=1 SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si" bash "$s" check) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=vp_not_ready' vp_not_ready_reason
[ "$rc" -ne 0 ] || fail vp_not_ready_exit_zero

# vp.ready outlives a killed VisionPilot, so the process must be there too.
rc=0
out=$(VP_DEAD=1 SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si" bash "$s" check) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=vp_not_ready' vp_dead_reason
[ "$rc" -ne 0 ] || fail vp_dead_exit_zero

# fault=1 in the heartbeat is the Safety Island's latch: not ready until reset.
rc=0
out=$(HB_FAULT=1 SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si" bash "$s" check) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=si_latched' si_latched_reason
[ "$rc" -ne 0 ] || fail si_latched_exit_zero

# ssh exits 255 on a transport failure: that is not a missing VisionPilot.
rc=0
out=$(PROBE_RC=255 SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si" bash "$s" check) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=ssh_failed' probe_ssh_failed_reason
[ "$rc" -ne 0 ] || fail probe_ssh_failed_exit_zero

# Each fault route runs one board command and prints the bench time of it.
for r in kill:'pkill -KILL -x VisionPilot' slow:'pkill -USR1 -x VisionPilot' lm:'systemctl kill -s KILL score-lm.service'; do
    route=${r%%:*}; cmd=${r#*:}
    : > "$LOG"
    out=$(SSH="$tmp/ssh" bash "$s" fault "$route") || fail "fault_${route}_failed $out"
    [[ $out =~ ^X5H_CES_DEMO_FAULT\ route=$route\ at=[0-9]+\.[0-9]+$ ]] || fail "fault_${route}_line out=$out"
    grep -qF "$cmd" "$LOG" || fail "fault_${route}_cmd log=$(cat "$LOG")"
    # The handshake comes first, on the same master the fault then reuses.
    [ "$(grep -c 'ControlMaster=auto' "$LOG")" = 2 ] || fail "fault_${route}_no_master log=$(cat "$LOG")"
    head -n 1 "$LOG" | grep -q ' true$' || fail "fault_${route}_no_preopen log=$(cat "$LOG")"
done

# A transport failure before the wait is not a failed injection.
rc=0
out=$(SSH_FAIL=1 SSH="$tmp/ssh" bash "$s" fault kill) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=ssh_failed' fault_ssh_failed_reason
[ "$rc" -ne 0 ] || fail fault_ssh_failed_exit_zero

# --at in the past injects at once.
out=$(SSH="$tmp/ssh" bash "$s" fault kill --at 1) || fail "fault_at_failed $out"
[[ $out =~ ^X5H_CES_DEMO_FAULT\ route=kill ]] || fail "fault_at_line out=$out"

rc=0
out=$(SSH="$tmp/ssh" bash "$s" fault bogus) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=usage' fault_usage_reason
[ "$rc" -ne 0 ] || fail fault_usage_exit_zero

rc=0
out=$(CMD_RC=1 SSH="$tmp/ssh" bash "$s" fault kill) || rc=$?
exact "$out" 'X5H_CES_DEMO_FAIL reason=fault_failed' fault_failed_reason
[ "$rc" -ne 0 ] || fail fault_failed_exit_zero

# reset stops the launch manager, clears the latch, then starts it again.
: > "$LOG"
out=$(SSH="$tmp/ssh" bash "$s" reset) || fail "reset_failed $out"
exact "$out" 'X5H_CES_DEMO_RESET' reset_line
grep -qF 'systemctl stop score-lm.service && systemctl kill -s USR2 x5h-si-link.service && systemctl start score-lm.service' "$LOG" || fail "reset_cmd log=$(cat "$LOG")"

# run ends with the booth reset: a board that booted before CARLA has fallen back.
out=$(COMPOSE_FILE=/c/docker-compose.yaml bash "$s" run) || fail "run_failed $out"
exact "$(tail -n 1 <<<"$out")" "$s reset" run_last_line

echo "TEST_PASS $name"
