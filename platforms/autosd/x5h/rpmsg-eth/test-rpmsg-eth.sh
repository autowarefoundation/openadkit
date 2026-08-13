#!/usr/bin/env bash
# Round-trips frames between a TAP device and a mock endpoint (socat pty).
#
# Self-wrapping: this needs a private network namespace so tap0/ip commands
# can't collide with other things on the box (no root required on CI
# runners that allow unprivileged user namespaces). Rather than making
# every caller remember an external 'unshare -rn' wrapper, re-exec
# ourselves under it if we don't already have one. If a private netns
# can't be created at all (e.g. a host policy denies unprivileged user
# namespaces), fail loudly and distinctly -- never silently skip, never
# exit 0.
set -euo pipefail
if [ -z "${RPMSG_ETH_TEST_UNSHARED:-}" ]; then
	if ! command -v unshare >/dev/null 2>&1; then
		echo "TEST_FAIL: unshare not available, cannot get a private netns" >&2
		exit 1
	fi
	if ! err=$(unshare -rn true 2>&1); then
		echo "TEST_FAIL: cannot create a private network namespace (unshare -rn): $err" >&2
		exit 1
	fi
	export RPMSG_ETH_TEST_UNSHARED=1
	exec unshare -rn "$0" "$@"
fi

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
# …and a frame written to epB must reach tap0 *intact* (checked via
# tcpdump on tap0, filtered on the injected frame's own src MAC -- tap0
# emits its own ARP retries with its *own* auto-assigned MAC while
# unresolved, and an unfiltered capture would count one of those as a
# false pass). Checking the payload survived, not just that a
# matching-source frame arrived, is what catches a truncated/short-written
# relay that a mere presence check would miss.
CAP="$PTY_DIR/cap.pcap"
# -Z root on both tcpdump invocations below: under 'unshare -r' only uid 0
# is mapped into the namespace, so tcpdump's default privilege-drop dance
# (to its own service user for the live capture, chowning the savefile; to
# the invoking user when re-reading it) targets a uid that doesn't exist
# in here and errors out -- on the live capture before it captures
# anything, on the re-read before it prints anything, in both cases
# silently starving the grep below rather than failing loudly itself.
# timeout's plain form only sends SIGTERM at the deadline: tcpdump's
# libpcap capture loop checks for a pending signal between packets, so
# when no matching packet ever arrives (the exact case this fault-check
# exists for) tcpdump doesn't act on the SIGTERM and hangs past the
# deadline, wedging this test instead of failing it. '-k 1' makes timeout
# escalate to SIGKILL 1s after SIGTERM if tcpdump is still alive, so a
# broken relay is reported as TEST_FAIL instead of hanging forever.
timeout -k 1 2 tcpdump -Z root -c1 -i tap0 -w "$CAP" 'ether src 02:5c:52:00:00:02' & TD=$!
sleep 0.3
printf '\xff\xff\xff\xff\xff\xff\x02\x5c\x52\x00\x00\x02\x08\x06test' > "$PTY_DIR/epB"
wait $TD || { echo "TEST_FAIL: no frame relayed endpoint->tap"; exit 1; }
tcpdump -Z root -r "$CAP" -A -n 2>/dev/null | grep -q 'test' \
  || { echo "TEST_FAIL: frame relayed endpoint->tap but payload truncated"; exit 1; }
kill $DAEMON $SOCAT; echo "TEST_PASS"
