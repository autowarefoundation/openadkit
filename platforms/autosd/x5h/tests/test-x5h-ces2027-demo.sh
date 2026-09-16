#!/usr/bin/env bash
# x5h-ces2027-demo.sh check with a fake ssh: composes the READY line from the
# package sha, route.env and the board's unit states, and names a missing
# unit, a corrupt route.env, or a failed ssh transport distinctly.
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
case "$*" in
  *is-active*)
    [ -z "${SSH_FAIL:-}" ] || exit 1
    printf 'active\nactive\nactive\nactive\n%s\n' "${VP_STATE:-active}" ;;
  *journalctl*) echo 'RPMSG_SI_RX hb seq=41 uptime_ms=42000 fault=0' ;;
  *) true ;;
esac
EOF
chmod +x "$tmp/ssh"

out=$(SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si" bash "$s" check) || fail "check_failed $out"
exact "$out" 'X5H_CES_DEMO_READY sha=deadbeef spawn=63 units=5 hb=41' ready_line

out=$(VP_STATE=inactive SSH="$tmp/ssh" CARLA_PKG="$tmp/pkg" VP_SI="$tmp/si" bash "$s" check) && fail inactive_accepted
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

echo "TEST_PASS $name"
