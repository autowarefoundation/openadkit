#!/usr/bin/env bash
# rpmsg-ping's listen mode against a socat pty pair: it must say hello first,
# count heartbeat lines, forward the two fault signals, and judge gaps.
set -u
name=test-rpmsg-ping-listen
here=$(cd "$(dirname "$0")" && pwd)
fail() { echo "TEST_FAIL $name reason=$1"; exit 1; }
command -v socat >/dev/null || { echo "TEST_SKIP $name reason=socat_missing"; exit 0; }
command -v cc >/dev/null || { echo "TEST_SKIP $name reason=cc_missing"; exit 0; }
tmp=$(mktemp -d); SOCAT=
trap 'rm -rf "$tmp"; kill $SOCAT 2>/dev/null' EXIT
cc -O2 -Wall -Wextra -o "$tmp/rpmsg-ping" "$here/../scripts/rpmsg-ping.c" || fail compile
socat -d PTY,raw,echo=0,link="$tmp/epA" PTY,raw,echo=0,link="$tmp/epB" & SOCAT=$!
for _ in $(seq 1 50); do [ -e "$tmp/epA" ] && [ -e "$tmp/epB" ] && break; sleep 0.1; done
[ -e "$tmp/epB" ] || fail no_pty
exec 3<>"$tmp/epB"
"$tmp/rpmsg-ping" -s rpmsg-si -d "$tmp/epA" -l 4 > "$tmp/out" & PING=$!
read -r -t 5 hello <&3 || fail no_hello
[ "$hello" = hello ] || fail "hello_text=$hello"
printf 'hb seq=0 uptime_ms=1000 fault=0\nhb seq=1 uptime_ms=2000 fault=0\n' >&3
kill -USR1 $PING; read -r -t 5 f1 <&3 || fail no_fault_set
[ "$f1" = 'fault=1' ] || fail "fault_set_text=$f1"
kill -USR2 $PING; read -r -t 5 f0 <&3 || fail no_fault_clear
[ "$f0" = 'fault=0' ] || fail "fault_clear_text=$f0"
printf 'hb seq=2 uptime_ms=3000 fault=0\n' >&3
wait $PING; rc=$?
out=$(cat "$tmp/out")
[ "$rc" -eq 0 ] || fail "rc=$rc out=$out"
grep -q '^RPMSG_SI_RX hb seq=1 uptime_ms=2000 fault=0$' <<<"$out" || fail rx_line_missing
grep -q '^RPMSG_SI_TX fault=1$' <<<"$out" || fail tx_echo_missing
grep -q '^RPMSG_LISTEN_PASS n=3 gaps=0$' <<<"$out" || fail "pass_marker out=$out"
# A gap must fail.
"$tmp/rpmsg-ping" -s rpmsg-si -d "$tmp/epA" -l 2 > "$tmp/out2" & PING=$!
read -r -t 5 _ <&3
printf 'hb seq=5 uptime_ms=1 fault=0\nhb seq=7 uptime_ms=2 fault=0\n' >&3
wait $PING && fail gap_accepted
grep -q '^RPMSG_LISTEN_FAIL reason=seq_gap n=2$' "$tmp/out2" || fail "gap_reason $(cat "$tmp/out2")"
echo "TEST_PASS $name"
