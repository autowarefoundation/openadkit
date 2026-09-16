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
n=0
for u in $UNITS; do
    "$SYSTEMCTL" start "$u" || { echo "X5H_DEMO_UP_FAIL reason=$u"; exit 1; }
    n=$((n + 1))
done
echo "X5H_DEMO_UP units=$n"
