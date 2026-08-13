#!/bin/sh
# Board smoke test for rpmsg-eth.service: assert the CR52's rpmsg-eth
# channel is on the rpmsg bus, tap0 is configured correctly (address AND
# the frozen MTU 462), then round-trip ping the CR52 side (172.16.52.2)
# requiring 100% reply.
#
# Unlike rpmsg-smoke.sh this does not drive remoteproc itself: rpmsg-
# eth.service is expected to already be running (systemctl start
# rpmsg-eth.service, or automatically at boot via its [Install]
# WantedBy=multi-user.target) -- this checks that an already-up link is
# healthy, the same shape as any other "is this link alive" smoke test.
#
# Markers on stdout (grep-able, one per line):
#   RPMSG_ETH_PING_PASS
#   RPMSG_ETH_PING_FAIL reason=<no_channel|no_tap|ping_loss>
#
# -n skips the rpmsg-bus channel assertion, for bench runs with no board
# attached (e.g. validating the tap0/ping plumbing against a manually
# wired peer that answers 172.16.52.2 without a real CR52 on the other
# end).
set -u

SERVICE=rpmsg-eth
IFACE=tap0
ADDR=172.16.52.1/24
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

# --- assert tap0 is up with the expected address and the frozen MTU --------
# MTU 462 is a frozen wire constant (max Ethernet frame 476 = 462 + the
# 14-byte Ethernet header, sized to the CR52 side's RPMsg payload budget --
# see rpmsg-eth-ifup.sh). Checking it here, not just "is tap0 up", catches
# an ifup regression that brings tap0 up at the kernel default (1500)
# instead: the daemon would then silently drop oversize frames
# (rpmsg-eth.c's dropped_oversize counter) rather than failing outright, so
# nothing else in this smoke test would ever notice.
LINE="$(ip -o link show "$IFACE" 2>/dev/null)"
[ -n "$LINE" ] || fail no_tap
FLAGS="$(echo "$LINE" | sed -n 's/.*<\([^>]*\)>.*/\1/p')"
up=0
IFS=,
for f in $FLAGS; do
    [ "$f" = "UP" ] && up=1
done
unset IFS
[ "$up" -eq 1 ] || fail no_tap
echo "$LINE" | grep -q " mtu $MTU " || fail no_tap
ip -4 -o addr show "$IFACE" 2>/dev/null | grep -q " $ADDR " || fail no_tap

# --- round-trip: 100% reply required ----------------------------------------
# ping's own exit code is not enough to prove zero loss: iputils only
# returns nonzero on ZERO packets received (or a local/usage error), so a
# link dropping half its replies still exits 0. Parse the summary line's
# transmitted/received counts instead and require them equal and nonzero --
# an "N received" that never showed up at all (grep miss) or a mismatched
# count both fail loudly via the same reason=ping_loss, rather than
# trusting the exit status alone.
OUT="$(ping -c "$COUNT" -i 0.2 "$PEER" 2>&1)" || true
echo "$OUT" | grep -q ' packets transmitted' || fail ping_loss
TX="$(echo "$OUT" | sed -n 's/^\([0-9][0-9]*\) packets transmitted.*/\1/p')"
RX="$(echo "$OUT" | sed -n 's/.*, \([0-9][0-9]*\) received.*/\1/p')"
[ -n "$TX" ] && [ -n "$RX" ] && [ "$TX" -gt 0 ] && [ "$TX" = "$RX" ] || fail ping_loss

echo RPMSG_ETH_PING_PASS
