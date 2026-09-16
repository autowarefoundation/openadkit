#!/usr/bin/env bash
# Bring the CES 2027 demo stack up on the board. Run by x5h-demo.service at
# boot and by the booth script after a reset.
#
# The Quadlet generator did not always run at boot on this image (memory:
# the stack did not survive a cold boot on 2026-08-21, generator masked).
# The durable fix is in place, but the demo must not depend on it: when
# systemd does not know x5h-vp.service, run the generator into
# /run/systemd/system and reload, exactly as x5h-mrm-demo.sh recovers.
#
# Markers: X5H_DEMO_UP units=<n> | X5H_DEMO_UP_FAIL reason=<unit|quadlet>
set -uo pipefail
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
QUADLET="${QUADLET:-/usr/libexec/podman/quadlet}"
UNITS="x5h-si-link.service x5h-demo-bridge.service x5h-demo-restamp.service x5h-demo-hb.service x5h-vp.service"
if ! "$SYSTEMCTL" cat x5h-vp.service >/dev/null 2>&1; then
    "$QUADLET" /run/systemd/system /run/systemd/system /run/systemd/system \
        || { echo "X5H_DEMO_UP_FAIL reason=quadlet"; exit 1; }
    "$SYSTEMCTL" daemon-reload
fi
# systemd returns rc=0 for a unit it SKIPPED because a Condition failed (board-
# verified: ConditionPathExists on a missing binary gives START RC=0,
# is-active: inactive). `start` succeeding is therefore not proof the unit
# runs; check `is-active` too. The container units can take a moment to
# report active, so retry a few times with a short, bounded wait -- three
# tries, 0.2s apart, well under a second -- rather than trusting one
# immediate check or waiting unboundedly.
is_active() {
    local tries=3
    while [ "$tries" -gt 0 ]; do
        [ "$("$SYSTEMCTL" is-active "$1" 2>/dev/null)" = active ] && return 0
        tries=$((tries - 1))
        [ "$tries" -eq 0 ] || sleep 0.2
    done
    return 1
}
n=0
for u in $UNITS; do
    "$SYSTEMCTL" start "$u" || { echo "X5H_DEMO_UP_FAIL reason=$u"; exit 1; }
    is_active "$u" || { echo "X5H_DEMO_UP_FAIL reason=$u"; exit 1; }
    n=$((n + 1))
done
echo "X5H_DEMO_UP units=$n"
