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

kill $DAEMON $SOCAT

# --- OAK round 2 (final review finding 3, residual): wait_for_dev_or_tap()
# must treat POLLERR/POLLHUP/POLLNVAL on the tap fd as fatal during the
# endpoint wait, not just in the steady-state relay loop -- 627df09 fixed
# only the relay loop (see rpmsg-eth.c's "POLLERR/POLLHUP handling below"
# comment on the relay loop's own poll() check); wait_for_dev_or_tap()
# itself still ignored them. That matters because BOTH the initial
# endpoint wait (the daemon is normally started before the CR52 firmware
# is up on the real board, so this is the ordinary startup state, not an
# edge case) and the rebind wait after a CR52 reset go through this exact
# function. Left unfixed: `ip link del` on the tap latches POLLERR, so
# poll() returns immediately forever instead of waiting out its 1s
# timeout, and open_endpoint()'s retry loop spins at full speed instead of
# pacing at ~1Hz or exiting -- a pegged core and a flooded serial console
# on a safety-adjacent ECU, not a clean, diagnosable failure.
#
# Exercise the endpoint-wait state specifically -- not the relay state
# already covered above -- by pointing a fresh daemon at a device path
# that can never appear, so it never leaves open_endpoint()'s retry loop,
# then deleting its tap device out from under it. Correct behavior: the
# daemon exits nonzero and logs the fatal condition, naming the interface
# and which flags fired.
WAIT_DAEMON_LOG="$PTY_DIR/wait-daemon.log"
ip tuntap add dev tap1 mode tap && ip link set tap1 up

wait_daemon_waiting() {
	if ! kill -0 "$WAIT_DAEMON" 2>/dev/null; then
		echo "TEST_FAIL: endpoint-wait daemon exited before ever entering its wait" >&2
		cat "$WAIT_DAEMON_LOG" >&2 2>/dev/null || true
		exit 1
	fi
	grep -q 'waiting for endpoint' "$WAIT_DAEMON_LOG" 2>/dev/null
}

./rpmsg-eth -t tap1 -d "$PTY_DIR/does-not-exist" >"$WAIT_DAEMON_LOG" 2>&1 & WAIT_DAEMON=$!
wait_until "endpoint-wait daemon to enter open_endpoint()'s retry loop" 300 wait_daemon_waiting

ip link del tap1

# Bounded via wait_until, not a fixed sleep: on the unfixed code this
# predicate never becomes true (see the header comment above -- the
# daemon busy-spins instead of exiting) and wait_until's own timeout is
# what turns that into a reported TEST_FAIL instead of this script hanging
# forever -- exactly the failure-demonstration case this test exists for.
wait_daemon_exited() {
	! kill -0 "$WAIT_DAEMON" 2>/dev/null
}
wait_until "endpoint-wait daemon to exit after its tap fd hit a fatal poll condition" 300 wait_daemon_exited

wait "$WAIT_DAEMON" && WAIT_DAEMON_STATUS=0 || WAIT_DAEMON_STATUS=$?
[ "$WAIT_DAEMON_STATUS" -ne 0 ] \
  || { echo "TEST_FAIL: endpoint-wait daemon exited 0 after a fatal tap condition, expected nonzero"; cat "$WAIT_DAEMON_LOG" >&2; exit 1; }
grep -q 'fatal poll condition' "$WAIT_DAEMON_LOG" \
  || { echo "TEST_FAIL: endpoint-wait daemon did not log the fatal tap condition"; cat "$WAIT_DAEMON_LOG" >&2; exit 1; }
grep -q 'tap1' "$WAIT_DAEMON_LOG" \
  || { echo "TEST_FAIL: fatal tap condition log did not name the interface"; cat "$WAIT_DAEMON_LOG" >&2; exit 1; }

# --- Defect B: a wedged endpoint that accepts a bind but then services
# neither reads nor writes must trip the -T progress deadline and exit
# nonzero, not peg a core silently. This reproduces the board defect: the
# CR52 wedged, and the daemon (no O_NONBLOCK anywhere) burned 100% of one
# core in system time forever, never returning to userspace, while
# systemd kept reporting "active (running)" because the process never
# exited. The existing round-trip test above cannot catch this class of
# bug at all -- its mock endpoint (epB) is continuously drained by a `dd`
# read, so the daemon's write() there always has room and never blocks.
#
# Reuses the same two-pty-bridge mock as the round-trip test above (epA
# exposed to the daemon via -d, epB the corresponding far end) but never
# reads epB: held open (so it behaves like a connected far end, not a
# dead one) via a bare `exec` onto an fd this script never reads from.
# socat, which bridges epA and epB internally, backs off relaying once
# its own write into epB's unread buffer can no longer proceed, which in
# turn leaves epA's buffer with nowhere to drain -- so the daemon's own
# write() to epA is what ultimately sees EAGAIN forever, the same shape
# as a CR52 that has stopped returning TX buffers.
STALL_PTY_DIR=$(mktemp -d)
STALL_DAEMON_LOG="$STALL_PTY_DIR/stall-daemon.log"

socat PTY,raw,echo=0,link="$STALL_PTY_DIR/epA" PTY,raw,echo=0,link="$STALL_PTY_DIR/epB" & STALL_SOCAT=$!
stall_pty_pair_ready() {
	if ! kill -0 "$STALL_SOCAT" 2>/dev/null; then
		echo "TEST_FAIL: stall-test socat exited before creating its pty pair" >&2
		exit 1
	fi
	[ -e "$STALL_PTY_DIR/epA" ] && [ -e "$STALL_PTY_DIR/epB" ]
}
wait_until "stall-test socat's pty pair to appear" 300 stall_pty_pair_ready

# Opened but never read and never written -- exactly the mock shape the
# defect needs: a far end that is live (so writes into it don't just
# bounce off a closed pty with nobody home) but never services anything,
# so its buffer fills and stays full. Closed explicitly in the cleanup
# below, not left to script exit.
exec {STALL_EPB_FD}<>"$STALL_PTY_DIR/epB"

# A distinct subnet from tap0's 172.16.52.0/24 (tap0 is still up at this
# point in the script -- only its daemon and socat were killed, not the
# interface itself): with both on the same subnet the kernel prefers
# tap0's route, which has nothing reading it any more, and the flood
# below would silently vanish down the wrong interface instead of ever
# reaching this test's daemon.
ip tuntap add dev tap2 mode tap && ip link set tap2 up && ip addr add 172.16.99.1/24 dev tap2
# A permanent, unresolved-free neighbor entry for the mock CR52 IP:
# nothing on epB will ever answer an ARP request (the mock never reads,
# let alone replies), and without this the kernel's neighbor subsystem
# queues only a handful of packets per unresolved destination and drops
# the rest -- starving the flood below of the volume it needs to fill
# both pty buffers in the chain.
ip neigh add 172.16.99.2 lladdr 02:5c:52:00:00:02 dev tap2 nud permanent

# -T 2: a short deadline so this test runs quickly; RPMSG_ETH_EPT_PROGRESS_TIMEOUT_S's
# real-world default of 10s is sized against the kernel's own 15s
# "timeout waiting for a tx buffer" warning, not against test runtime.
./rpmsg-eth -t tap2 -d "$STALL_PTY_DIR/epA" -T 2 >"$STALL_DAEMON_LOG" 2>&1 & STALL_DAEMON=$!
stall_daemon_ready() {
	if ! kill -0 "$STALL_DAEMON" 2>/dev/null; then
		echo "TEST_FAIL: stall-test daemon exited before becoming ready" >&2
		cat "$STALL_DAEMON_LOG" >&2 2>/dev/null || true
		exit 1
	fi
	grep -q 'rpmsg-eth: ready' "$STALL_DAEMON_LOG" 2>/dev/null
}
wait_until "stall-test daemon to open both fds and become ready" 300 stall_daemon_ready

# Flood tap2 toward the never-draining mock with one long-lived socat
# rather than many short-lived ones -- both to avoid hundreds of
# fork+exec calls under QEMU TCG (see wait_until's comment on how slow
# that gets) and because a continuous stream, not a fixed packet count,
# is what reliably overruns the buffer chain regardless of its exact
# size on a given kernel. -b keeps each UDP datagram at 400 bytes,
# comfortably under the 462 netif MTU so each one leaves as a single
# unfragmented frame.
socat -u -b 400 OPEN:/dev/zero UDP-SENDTO:172.16.99.2:9 >/dev/null 2>&1 & STALL_FLOOD=$!

# Captured immediately after the flood starts, not after the SIGUSR1 case
# below -- this is what "stall-test: daemon exited Xs after the wedge
# began" further down, and STALL_WAIT_ELAPSED's bound, measure against.
# Capturing it any later would make both drift lenient by however long the
# SIGUSR1 case takes to run.
STALL_WAIT_START=$(date +%s)

# --- OAK final review, item 4: a SIGUSR1 sent while the endpoint is
# wedged must produce a counter dump promptly (well inside the -T
# deadline), not be silently absorbed until the deadline expires. Reuses
# this same stall fixture, not a fresh one -- the flood above is already
# under way and the daemon's write() to epA is already retrying against
# EAGAIN by the time this runs, the same wedge Defect B's own
# deadline-expiry check below depends on and relies on forming quickly.
# Before this fix, write_full()'s retry loop honoured g_stop but never
# g_dump, so the daemon stays inside a single write_full() call for the
# whole wedge and the relay loop's own top-of-loop g_dump handling never
# runs again until the deadline fires -- and the deadline path exits
# without ever returning to that check. No "counters" line is printed for
# this SIGUSR1 at all in that case; only wait_until's timeout below fires.
#
# Sending SIGUSR1 right after starting the flood, rather than once the
# daemon is confirmed genuinely wedged, races: land too early and it is
# answered by the ordinary top-of-relay-loop g_dump handling instead --
# that path has always existed, is untouched by this fix, and would make
# this assertion pass against the unfixed code too (confirmed empirically
# the first time this test was written, with a fixed sleep in place of
# the wait_until below: it passed against reverted code). A fixed sleep
# doesn't fix this properly either -- long enough here is not guaranteed
# long enough on a much slower CI runner (see wait_until's own comment on
# how much slower QEMU TCG can be), so a short sleep risks the same false
# pass there instead of here. wait_until on write_full()'s "not ready,
# retrying" log line (see rpmsg-eth.c's retry branch) avoids guessing at
# timing altogether: that line only appears once the daemon's write() has
# actually returned EAGAIN, i.e. once it is genuinely inside the retry
# loop this task's fix targets, regardless of how fast or slow
# buffer-fill happens to be on the machine running this.
stall_write_retrying() {
	if ! kill -0 "$STALL_DAEMON" 2>/dev/null; then
		echo "TEST_FAIL: wedged-endpoint daemon exited before its write ever had to retry" >&2
		cat "$STALL_DAEMON_LOG" >&2 2>/dev/null || true
		exit 1
	fi
	grep -q 'not ready' "$STALL_DAEMON_LOG" 2>/dev/null
}
wait_until "the wedged-endpoint daemon's write to start retrying" 300 stall_write_retrying

kill -USR1 "$STALL_DAEMON"
STALL_DUMP_WAIT_START_MS=$(date +%s%3N)
stall_dump_logged() {
	if ! kill -0 "$STALL_DAEMON" 2>/dev/null; then
		echo "TEST_FAIL: wedged-endpoint daemon exited before answering SIGUSR1" >&2
		cat "$STALL_DAEMON_LOG" >&2 2>/dev/null || true
		exit 1
	fi
	grep -q 'rpmsg-eth: counters ' "$STALL_DAEMON_LOG" 2>/dev/null
}
wait_until "the wedged-endpoint daemon to answer SIGUSR1 with a counter dump" 300 stall_dump_logged
STALL_DUMP_WAIT_ELAPSED_MS=$(( $(date +%s%3N) - STALL_DUMP_WAIT_START_MS ))
# A real bound, not just wait_until's 30s ceiling -- same rationale as
# STALL_WAIT_ELAPSED further below: this is pure signal-response time (the
# daemon was already confirmed genuinely wedged, via the wait_until
# above, before the signal was sent), not QEMU-TCG process-startup
# latency, so the generous 30s ceiling that covers the latter does not
# excuse this one. write_full()'s retry loop rechecks g_dump at least
# once per second even in the worst case (its poll() is bounded to
# 1000ms once a deadline applies), and SIGUSR1's handler has no
# SA_RESTART (see main()), so it interrupts that poll() immediately with
# EINTR instead of the daemon waiting it out -- this should be
# near-instant. Millisecond resolution (date +%s%3N), not whole seconds:
# a genuinely sub-second latency measured with whole-second `date +%s`
# could round up to a misleadingly large number purely from where the two
# reads happen to straddle a second boundary, flaking this bound
# independently of the daemon's real behaviour. 1500ms (75% of the -T 2
# deadline below) leaves generous headroom for scheduling jitter on a
# slower machine while still being unambiguously "well inside" the
# deadline, not merely a dump that happens to land close to it.
[ "$STALL_DUMP_WAIT_ELAPSED_MS" -le 1500 ] \
  || { echo "TEST_FAIL: wedged-endpoint daemon took ${STALL_DUMP_WAIT_ELAPSED_MS}ms to answer SIGUSR1, expected well under the 2000ms -T deadline"; cat "$STALL_DAEMON_LOG" >&2; exit 1; }

# Bounded via wait_until, not a fixed sleep, for the same reason as the
# endpoint-wait case above: on daemon code with no O_NONBLOCK/deadline,
# this predicate never becomes true (the daemon is genuinely blocked
# inside a kernel write(), not merely slow) and wait_until's own ceiling
# is what turns that into a reported TEST_FAIL instead of this script
# hanging forever -- the failure-demonstration case this test exists for.
# (STALL_WAIT_START was already captured right after the flood started,
# above the SIGUSR1 case, so it still measures from when the wedge
# actually began, not from whenever that case finishes.)
stall_daemon_exited() {
	! kill -0 "$STALL_DAEMON" 2>/dev/null
}
wait_until "the wedged-endpoint daemon to exit once its progress deadline expires" 300 stall_daemon_exited
STALL_WAIT_ELAPSED=$(( $(date +%s) - STALL_WAIT_START ))
echo "stall-test: daemon exited ${STALL_WAIT_ELAPSED}s after the wedge began (deadline was 2s)"
# A real bound, not just wait_until's 30s ceiling: by this point the daemon
# was already confirmed `ready` and the flood was already running, so this
# wait is pure wedge-to-exit time, not QEMU-TCG startup latency -- the
# generous-slack reasoning that justifies the 30s ceiling elsewhere does
# not apply to it. 15s against a 2s deadline is still generous (7.5x), but
# a deadline that silently stopped enforcing itself and instead relied on
# some unrelated timeout (or no timeout at all) could still exit within
# 30s and must not be able to pass this assertion.
[ "$STALL_WAIT_ELAPSED" -le 15 ] \
  || { echo "TEST_FAIL: wedged-endpoint daemon took ${STALL_WAIT_ELAPSED}s to exit, expected close to the 2s -T deadline"; cat "$STALL_DAEMON_LOG" >&2; exit 1; }

kill "$STALL_FLOOD" 2>/dev/null || true
wait "$STALL_FLOOD" 2>/dev/null || true
exec {STALL_EPB_FD}<&-
kill "$STALL_SOCAT" 2>/dev/null || true
wait "$STALL_SOCAT" 2>/dev/null || true
ip link del tap2 2>/dev/null || true

wait "$STALL_DAEMON" && STALL_DAEMON_STATUS=0 || STALL_DAEMON_STATUS=$?
[ "$STALL_DAEMON_STATUS" -ne 0 ] \
  || { echo "TEST_FAIL: wedged-endpoint daemon exited 0, expected nonzero (the -T progress deadline should have made it exit fatal)"; cat "$STALL_DAEMON_LOG" >&2; exit 1; }
grep -q 'did not finish writing a frame' "$STALL_DAEMON_LOG" \
  || { echo "TEST_FAIL: wedged-endpoint daemon did not name the stall condition in its log"; cat "$STALL_DAEMON_LOG" >&2; exit 1; }

echo "TEST_PASS"
