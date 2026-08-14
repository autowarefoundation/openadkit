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

# wait_until DESC MAX_TRIES PREDICATE...
# Polls PREDICATE every 0.1s until it succeeds, up to MAX_TRIES times.
# Bounds below are generous because this test also runs inside the real
# CI gate under QEMU TCG (no KVM) on top of a podman container on top of
# this script's own unshare'd netns -- there, plain process startup
# (fork+exec+dynamic-link, privilege drop, BPF filter compilation) has
# been measured taking one to two orders of magnitude longer in real
# seconds than on a dev box or a bare podman container. A fixed short
# sleep tuned for the fast case is not a safe stand-in for "the thing we
# are about to depend on is actually ready" -- it happened to be enough
# on every machine this test was written and reviewed on, and then
# wasn't, in the one environment that matters most. Every wait_until
# failure below is worded distinctly from the relay-broke TEST_FAILs
# further down, so a readiness timeout in CI is never misread as a
# protocol/relay bug, or vice versa.
wait_until() {
	local desc="$1" max_tries="$2"
	shift 2
	local i=0
	until "$@"; do
		i=$((i + 1))
		if [ "$i" -ge "$max_tries" ]; then
			echo "TEST_FAIL: timed out waiting for $desc" >&2
			exit 1
		fi
		sleep 0.1
	done
}

PTY_DIR=$(mktemp -d)
DAEMON_LOG="$PTY_DIR/daemon.log"
TCPDUMP_LOG="$PTY_DIR/tcpdump.log"

pty_pair_ready() {
	if ! kill -0 "$SOCAT" 2>/dev/null; then
		echo "TEST_FAIL: socat exited before creating its pty pair" >&2
		exit 1
	fi
	[ -e "$PTY_DIR/epA" ] && [ -e "$PTY_DIR/epB" ]
}

socat -d PTY,raw,echo=0,link="$PTY_DIR/epA" PTY,raw,echo=0,link="$PTY_DIR/epB" & SOCAT=$!
wait_until "socat's pty pair to appear" 300 pty_pair_ready

ip tuntap add dev tap0 mode tap && ip link set tap0 up && ip addr add 172.16.52.1/24 dev tap0

# The daemon prints "rpmsg-eth: ready" (see rpmsg-eth.c) once it has both
# the tap fd and the endpoint fd open and is about to enter its poll
# loop -- that is the one thing that actually matters here, so wait for
# it directly instead of guessing how long "fork, open two fds" takes.
daemon_ready() {
	if ! kill -0 "$DAEMON" 2>/dev/null; then
		echo "TEST_FAIL: daemon exited before becoming ready" >&2
		cat "$DAEMON_LOG" >&2 2>/dev/null || true
		exit 1
	fi
	grep -q 'rpmsg-eth: ready' "$DAEMON_LOG" 2>/dev/null
}

./rpmsg-eth -t tap0 -d "$PTY_DIR/epA" >"$DAEMON_LOG" 2>&1 & DAEMON=$!
wait_until "daemon to open both fds and become ready" 300 daemon_ready

# An ARP probe out of tap0 must appear on epB. Bounded generously (see
# wait_until's comment on why) rather than left at a couple of seconds;
# the daemon is already confirmed ready above, so this is only timing
# out on the actual relay, which is what should make it fail.
# Captured into a variable, then matched separately, rather than piped
# straight into `grep -q`: under `set -o pipefail`, grep -q exits (and
# closes its stdin) the instant it sees a match, and the still-running
# producer (dd | xxd here) can then be killed by SIGPIPE and report that
# as its own exit status -- which pipefail then reports as the whole
# pipeline's, even though the match was genuinely found. Capturing first
# means there is no live downstream reader left to close early.
# The trailing `|| true` on the capture is load-bearing, not decorative:
# under `set -e` a bare `VAR=$(...)` assignment (not part of an if/&&/||)
# still aborts the whole script on a non-zero pipeline status, and on the
# genuinely-broken-relay case this exercises, `timeout 10 dd` really does
# time out (exit 124) with nothing ever having arrived on epB -- that must
# fall through to the explicit grep-and-TEST_FAIL below, not vanish as a
# silent `set -e` exit with no diagnostic at all (confirmed against a
# fault-injected build that disables the relay: without `|| true` here the
# script died on the bare timeout exit code before ever printing
# TEST_FAIL).
ping -c1 -W1 172.16.52.2 >/dev/null 2>&1 || true
FRAME="$(timeout 10 dd if="$PTY_DIR/epB" bs=600 count=1 2>/dev/null | xxd)" || true
grep -qi '0806' <<<"$FRAME" \
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
# deadline, wedging this test instead of failing it. '-k 2' makes timeout
# escalate to SIGKILL 2s after SIGTERM if tcpdump is still alive, so a
# broken relay is reported as TEST_FAIL instead of hanging forever.
#
# The capture window is 5s (not the 2s this started at): once tcpdump is
# confirmed live (below) the frame is injected immediately, so this
# budget only has to cover the relay+capture itself, but it is kept
# generous for the same TCG-is-much-slower reason as wait_until.
timeout -k 2 5 tcpdump -Z root -c1 -i tap0 -w "$CAP" 'ether src 02:5c:52:00:00:02' \
  >"$TCPDUMP_LOG" 2>&1 & TD=$!

# tcpdump prints "... listening on tap0, ..." (to the log above) only
# once pcap_activate() has actually attached the BPF filter to the
# interface -- i.e. once the capture is genuinely live. This replaced a
# fixed 'sleep 0.3' before injecting the frame: on this test's very
# first real run under the CI gate's QEMU-TCG guest, tcpdump's own
# fork+exec+dynamic-link+filter-compile startup took long enough (on the
# order of a couple of real seconds, inferred from a ~2.6s gap between
# tap0 becoming ready and tcpdump actually entering promiscuous mode,
# plus tcpdump exiting well before the 2s SIGTERM deadline it was given)
# that the frame was written to epB, and presumably relayed, before
# tcpdump had attached at all -- the capture then correctly reported 0
# packets, because there was nothing left to see by the time it started
# watching.
tcpdump_ready() {
	if ! kill -0 "$TD" 2>/dev/null; then
		echo "TEST_FAIL: tcpdump exited before its capture became live" >&2
		cat "$TCPDUMP_LOG" >&2 2>/dev/null || true
		exit 1
	fi
	grep -q 'listening on' "$TCPDUMP_LOG" 2>/dev/null
}
wait_until "tcpdump to attach and start capturing on tap0" 300 tcpdump_ready

printf '\xff\xff\xff\xff\xff\xff\x02\x5c\x52\x00\x00\x02\x08\x06test' > "$PTY_DIR/epB"
wait $TD || {
	echo "TEST_FAIL: no frame relayed endpoint->tap"
	cat "$TCPDUMP_LOG" >&2 2>/dev/null || true
	exit 1
}
# Same capture-then-match rationale as the ARP check above -- grep -q
# closing this pipe early under pipefail must not turn a genuine pass into
# a SIGPIPE-flavored TEST_FAIL, and `|| true` keeps a genuine tcpdump -r
# failure falling through to the explicit TEST_FAIL below instead of
# aborting the script silently under set -e.
PAYLOAD="$(tcpdump -Z root -r "$CAP" -A -n 2>/dev/null)" || true
grep -q 'test' <<<"$PAYLOAD" \
  || { echo "TEST_FAIL: frame relayed endpoint->tap but payload truncated"; exit 1; }

# --- I7: exercise the discovery/rebind path (never triggered by anything
# above; CI would otherwise ship having never run open_endpoint()'s retry
# logic even once) ---------------------------------------------------------
# Killing socat tears down BOTH ends of the pty pair it manages ($PTY_DIR's
# epA and epB are just symlinks to the /dev/pts nodes socat allocated), so
# the daemon's open fd on epA sees the same read-EOF/write-failure shape a
# real CR52 reset produces. Confirm three things in order: the daemon
# survives instead of exiting, it logs the loss (the "endpoint lost" lines
# added in this review wave), and once a fresh pty pair reappears at the
# SAME link paths (device mode's -d only ever retries the one path it was
# given) it rebinds -- logged -- and the relay actually works again, not
# just that a log line printed.
OLD_SOCAT="$SOCAT"
kill "$OLD_SOCAT"
wait "$OLD_SOCAT" 2>/dev/null || true

rebind_loss_logged() {
	if ! kill -0 "$DAEMON" 2>/dev/null; then
		echo "TEST_FAIL: daemon exited after losing its endpoint (should rebind, not die)" >&2
		cat "$DAEMON_LOG" >&2 2>/dev/null || true
		exit 1
	fi
	grep -q 'endpoint lost' "$DAEMON_LOG" 2>/dev/null
}
wait_until "daemon to notice and log the endpoint loss" 300 rebind_loss_logged

# socat's PTY link= refuses to reuse an existing path, so the dead pair's
# stale symlinks must go before the replacement can claim the same names.
rm -f "$PTY_DIR/epA" "$PTY_DIR/epB"
socat -d PTY,raw,echo=0,link="$PTY_DIR/epA" PTY,raw,echo=0,link="$PTY_DIR/epB" & SOCAT=$!
wait_until "socat's replacement pty pair to appear" 300 pty_pair_ready

rebind_logged() {
	if ! kill -0 "$DAEMON" 2>/dev/null; then
		echo "TEST_FAIL: daemon exited before rebinding to the replacement endpoint" >&2
		cat "$DAEMON_LOG" >&2 2>/dev/null || true
		exit 1
	fi
	[ "$(grep -c 'endpoint bound' "$DAEMON_LOG" 2>/dev/null || true)" -ge 2 ]
}
wait_until "daemon to rebind to the recreated endpoint" 300 rebind_logged

# Second round trip, same shape as the first: an ARP probe out of tap0 must
# reach the NEW epB. Flush the stale neighbor entry first -- 172.16.52.2
# never actually answered the first probe, so without this the kernel may
# just replay its existing (failed) ARP resolution state instead of sending
# a fresh request the dd below can catch.
ip neigh flush to 172.16.52.2 dev tap0 2>/dev/null || true
ping -c1 -W1 172.16.52.2 >/dev/null 2>&1 || true
FRAME2="$(timeout 10 dd if="$PTY_DIR/epB" bs=600 count=1 2>/dev/null | xxd)" || true
grep -qi '0806' <<<"$FRAME2" \
  || { echo "TEST_FAIL: no ARP frame relayed tap->endpoint after rebind"; exit 1; }

kill $DAEMON $SOCAT; echo "TEST_PASS"
