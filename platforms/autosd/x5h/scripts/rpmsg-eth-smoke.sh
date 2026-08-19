#!/bin/sh
# Board smoke test for rpmsg-eth.service: assert the CR52's rpmsg-eth
# channel is on the rpmsg bus, tap0 is configured correctly (address, the
# frozen MAC 02:5c:52:00:00:01 AND the frozen MTU 462), then round-trip
# ping the CR52 side (172.16.52.2) requiring 100% reply.
#
# Unlike rpmsg-smoke.sh this does not drive remoteproc itself: rpmsg-
# eth.service is expected to already be running (systemctl start
# rpmsg-eth.service, or automatically at boot via its [Install]
# WantedBy=multi-user.target) -- this checks that an already-up link is
# healthy, the same shape as any other "is this link alive" smoke test.
#
# Markers on stdout (grep-able, one per line):
#   RPMSG_ETH_PING_PASS
#   RPMSG_ETH_PING_FAIL reason=<bad_args|no_channel|service_inactive|no_tap|no_carrier|no_ping|ping_loss>
#
# -n skips the rpmsg-bus channel assertion, for bench runs with no board
# attached (e.g. validating the tap0/ping plumbing against a manually
# wired peer that answers 172.16.52.2 without a real CR52 on the other
# end).
set -u

SERVICE=rpmsg-eth
IFACE=tap0
ADDR=172.16.52.1/24
MAC=02:5c:52:00:00:01
MTU=462
PEER=172.16.52.2
COUNT=20
NOBOARD=0

while [ $# -gt 0 ]; do
    case "$1" in
        -n) NOBOARD=1; shift ;;
        *)
            echo "RPMSG_ETH_PING_FAIL reason=bad_args"
            echo "usage: $0 [-n]"
            exit 2
            ;;
    esac
done

fail() {
    echo "RPMSG_ETH_PING_FAIL reason=$1"
    exit 1
}

# --- assert the rpmsg-eth channel is on the bus (skippable with -n) --------
# rpmsg-eth.c's find_service() discovers its endpoint the same way: scan
# /sys/bus/rpmsg/devices/*/name for an exact match on the service name.
if [ "$NOBOARD" -eq 0 ]; then
    found=0
    for dev in /sys/bus/rpmsg/devices/*; do
        [ -e "$dev/name" ] || continue
        if [ "$(cat "$dev/name")" = "$SERVICE" ]; then
            found=1
            break
        fi
    done
    [ "$found" -eq 1 ] || fail no_channel
fi

# --- assert rpmsg-eth.service is actually running --------------------------
# ifup creates tap0 persistent, addressed and UP as an ExecStartPre step
# that runs independently of whether the daemon itself ever gets past its
# endpoint wait (see rpmsg-eth.c's create_ept()/open_endpoint() retry loop)
# or even started at all. Without this check, a configured-but-unattached
# tap0 -- address, MAC, MTU and UP flag all correct -- passes every
# assertion below and this script would only fail at the ping step,
# pointing the operator at the CR52 for what is actually a stopped or
# stuck local daemon. Checked before the interface assertions so that case
# gets its own specific reason instead of a misleading ping_loss.
if ! systemctl is-active --quiet "$SERVICE.service" 2>/dev/null; then
    systemctl status "$SERVICE.service" --no-pager 2>&1 | head -10 >&2
    fail service_inactive
fi

# --- assert tap0 is up with the expected address, MAC and the frozen MTU --
# MTU 462 is a frozen wire constant (max Ethernet frame 476 = 462 + the
# 14-byte Ethernet header, sized to the CR52 side's RPMsg payload budget --
# see rpmsg-eth-ifup.sh). Checking it here, not just "is tap0 up", catches
# an ifup regression that brings tap0 up at the kernel default (1500)
# instead: the daemon would then silently drop oversize frames
# (rpmsg-eth.c's dropped_oversize counter) rather than failing outright, so
# nothing else in this smoke test would ever notice.
#
# The MAC (02:5c:52:00:00:01) is likewise frozen -- see rpmsg-eth-ifup.sh
# for why a kernel-random MAC is wrong even though ARP means it doesn't
# blackhole traffic today.
LINE="$(ip -o link show "$IFACE" 2>/dev/null)"
if [ -z "$LINE" ]; then
    echo "no such interface: $IFACE" >&2
    fail no_tap
fi
FLAGS="$(echo "$LINE" | sed -n 's/.*<\([^>]*\)>.*/\1/p')"
up=0
no_carrier=0
IFS=,
for f in $FLAGS; do
    [ "$f" = "UP" ] && up=1
    [ "$f" = "NO-CARRIER" ] && no_carrier=1
done
unset IFS
if [ "$up" -ne 1 ]; then
    echo "$LINE" >&2
    fail no_tap
fi
# NO-CARRIER on a persistent tap the daemon holds open the way I2/I3 of the
# final review wave require (a fatal tap-side poll condition exits the
# daemon rather than spinning silently) is the interface-level echo of
# "the daemon isn't actually attached to this tap" -- check it as its own
# reason distinct from the systemctl check above, since a stale or
# externally-recreated tap0 can show this even when the unit itself
# reports active.
if [ "$no_carrier" -eq 1 ]; then
    echo "$LINE" >&2
    fail no_carrier
fi
if ! echo "$LINE" | grep -q " mtu $MTU "; then
    echo "$LINE" >&2
    fail no_tap
fi
if ! echo "$LINE" | grep -qi " link/ether $MAC "; then
    echo "$LINE" >&2
    fail no_tap
fi
if ! ip -4 -o addr show "$IFACE" 2>/dev/null | grep -q " $ADDR "; then
    ip -4 -o addr show "$IFACE" >&2 2>/dev/null
    fail no_tap
fi

# --- confirm ping is actually available before blaming the link for it ----
# Parsing ping's own summary line (below) silently reads a missing binary,
# a permissions error and a routing error all as the same reason=ping_loss
# unless this is checked first and given its own reason code.
command -v ping >/dev/null 2>&1 || fail no_ping

# --- round-trip: 100% reply required ----------------------------------------
# ping's own exit code is not enough to prove zero loss: iputils only
# returns nonzero on ZERO packets received (or a local/usage error), so a
# link dropping half its replies still exits 0. Parse the summary line's
# transmitted/received counts instead and require them equal and nonzero --
# an "N received" that never showed up at all (grep miss) or a mismatched
# count both fail loudly via the same reason=ping_loss, rather than
# trusting the exit status alone.
OUT="$(ping -c "$COUNT" -i 0.2 "$PEER" 2>&1)" || true
if ! echo "$OUT" | grep -q ' packets transmitted'; then
    echo "$OUT" >&2
    fail ping_loss
fi
TX="$(echo "$OUT" | sed -n 's/^\([0-9][0-9]*\) packets transmitted.*/\1/p')"
RX="$(echo "$OUT" | sed -n 's/.*, \([0-9][0-9]*\) received.*/\1/p')"
if [ -z "$TX" ] || [ -z "$RX" ] || [ "$TX" -eq 0 ] || [ "$TX" != "$RX" ]; then
    echo "$OUT" >&2
    fail ping_loss
fi

echo RPMSG_ETH_PING_PASS
