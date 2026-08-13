#!/usr/bin/env bash
# Round-trips frames between a TAP device and a mock endpoint (socat pty).
# Needs: unshared netns (no root on CI runners): run under 'unshare -rn'.
set -euo pipefail
cd "$(dirname "$0")"
make
PTY_DIR=$(mktemp -d)
socat -d PTY,raw,echo=0,link="$PTY_DIR/epA" PTY,raw,echo=0,link="$PTY_DIR/epB" & SOCAT=$!
sleep 0.3
ip tuntap add dev tap0 mode tap && ip link set tap0 up && ip addr add 172.16.52.1/24 dev tap0
./rpmsg-eth -t tap0 -d "$PTY_DIR/epA" & DAEMON=$!
sleep 0.3
# An ARP probe out of tap0 must appear on epB…
ping -c1 -W1 172.16.52.2 >/dev/null 2>&1 || true
timeout 2 dd if="$PTY_DIR/epB" bs=600 count=1 2>/dev/null | xxd | grep -qi '0806' \
  || { echo "TEST_FAIL: no ARP frame relayed tap->endpoint"; exit 1; }
# …and a frame written to epB must reach tap0 (checked via tcpdump on
# tap0, filtered on the injected frame's own src MAC -- tap0 emits its own
# ARP retries with its *own* auto-assigned MAC while unresolved, and an
# unfiltered capture would count one of those as a false pass).
timeout 2 tcpdump -c1 -i tap0 -w /dev/null 'ether src 02:5c:52:00:00:02' & TD=$!
sleep 0.3
printf '\xff\xff\xff\xff\xff\xff\x02\x5c\x52\x00\x00\x02\x08\x06test' > "$PTY_DIR/epB"
wait $TD || { echo "TEST_FAIL: no frame relayed endpoint->tap"; exit 1; }
kill $DAEMON $SOCAT; echo "TEST_PASS"
