#!/usr/bin/env bash
# x5h-ces2027-demo.sh check with a fake ssh: composes the READY line from the
# package sha, route.env and the board's unit states, and names a missing unit.
set -u
name=test-x5h-ces2027-demo
here=$(cd "$(dirname "$0")" && pwd); s="$here/../scripts/x5h-ces2027-demo.sh"
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
exact() { [ "$1" = "$2" ] || fail "$3 out=$1"; }
[ -x "$s" ] || fail script_missing
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/pkg" "$tmp/si"; echo deadbeef > "$tmp/pkg/ces2027-package-sha.txt"; printf 'SPAWN_INDEX=63\nLAP_M=1800\n' > "$tmp/si/route.env"
cat > "$tmp/ssh" <<'EOF'
#!/bin/sh
# $1 = host, rest = command
case "$*" in
  *is-active*) printf 'active\nactive\nactive\nactive\n%s\n' "${VP_STATE:-active}" ;;
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
echo "TEST_PASS $name"
