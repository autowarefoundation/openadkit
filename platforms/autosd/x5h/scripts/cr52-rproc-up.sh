#!/usr/bin/env bash
# cr52-rproc-up.sh -- bring the CR52 remoteproc vdev up at boot.
#
# Linux does NOT load the CR52 payload: rcar_gen5_rproc's .load and .stop are
# no-ops, and the realtime core is already running whatever was flashed into its
# UFS slot before Linux even started. What `start` does is parse the resource
# table out of the ELF named in /sys/class/remoteproc/remoteprocN/firmware and
# publish the vrings, then ring the MFIS doorbell. So the staged ELF must match
# the flashed image or the vring layout will not agree -- a mismatch produces a
# link that looks configured and passes no traffic.
#
# Without this unit the two modprobes and the `start` write have to be repeated
# by hand after every boot, because neither survives a reboot. rpmsg-eth.service
# tolerates their absence (its endpoint-wait loop retries and logs why), so the
# failure mode was a link that never came up until someone remembered -- which
# is exactly the kind of thing that gets forgotten during a board session.
#
# Markers on stdout, so `systemctl status` and the journal are self-explaining:
#   CR52_RPROC_UP name=<n> firmware=<f>
#   CR52_RPROC_SKIP reason=<no_device|no_firmware>
#   CR52_RPROC_FAIL reason=<firmware_write|start_write|not_running> ...
set -uo pipefail

RPROC_DIR=${RPROC_DIR:-/sys/class/remoteproc/remoteproc0}
# Empty means "leave whatever the driver already has", which is the stock
# rproc-cr52_1-fw. Set CR52_FIRMWARE in /etc/default/cr52-remoteproc to point at
# a specific staged ELF (the one flashed into the slot).
CR52_FIRMWARE=${CR52_FIRMWARE:-}
FIRMWARE_DIR=${FIRMWARE_DIR:-/lib/firmware}
TIMEOUT=${TIMEOUT:-25}

if [ ! -d "$RPROC_DIR" ]; then
    echo "CR52_RPROC_SKIP reason=no_device dir=$RPROC_DIR"
    exit 0
fi

name=$(cat "$RPROC_DIR/name" 2>/dev/null || echo unknown)
state=$(cat "$RPROC_DIR/state" 2>/dev/null || echo unknown)

# Idempotent: a re-run (or a manual start before this unit ran) is success, not
# an error. `start` on a running rproc returns EBUSY, which would otherwise make
# a restart of this unit look like a failure.
if [ "$state" = running ]; then
    echo "CR52_RPROC_UP name=$name firmware=$(cat "$RPROC_DIR/firmware" 2>/dev/null) (already running)"
    exit 0
fi

# Select the firmware if one was configured.
if [ -n "$CR52_FIRMWARE" ]; then
    if [ ! -r "${FIRMWARE_DIR}/${CR52_FIRMWARE}" ]; then
        # Deliberately exit 0, not 1. On a freshly imaged board the CR52 ELF has
        # not been staged yet and that is the correct state -- failing here would
        # mean every first boot shows a failed unit. The operator is not left
        # guessing: this line names the missing file, and rpmsg-eth's own log
        # says the link is down and why.
        echo "CR52_RPROC_SKIP reason=no_firmware path=${FIRMWARE_DIR}/${CR52_FIRMWARE}"
        exit 0
    fi
    if ! echo "$CR52_FIRMWARE" > "$RPROC_DIR/firmware"; then
        echo "CR52_RPROC_FAIL reason=firmware_write firmware=$CR52_FIRMWARE"
        exit 1
    fi
    got=$(cat "$RPROC_DIR/firmware" 2>/dev/null)
    if [ "$got" != "$CR52_FIRMWARE" ]; then
        echo "CR52_RPROC_FAIL reason=firmware_write firmware=$CR52_FIRMWARE readback=$got"
        exit 1
    fi
fi

selected=$(cat "$RPROC_DIR/firmware" 2>/dev/null)
if [ ! -r "${FIRMWARE_DIR}/${selected}" ]; then
    echo "CR52_RPROC_SKIP reason=no_firmware path=${FIRMWARE_DIR}/${selected}"
    exit 0
fi

if ! echo start > "$RPROC_DIR/state"; then
    echo "CR52_RPROC_FAIL reason=start_write firmware=$selected"
    exit 1
fi

# Readiness polling rather than a fixed sleep: the vdev registration and the
# rpmsg host coming online take a variable moment.
i=0
while [ "$i" -lt "$TIMEOUT" ]; do
    [ "$(cat "$RPROC_DIR/state" 2>/dev/null)" = running ] && break
    i=$((i + 1))
    sleep 1
done

state=$(cat "$RPROC_DIR/state" 2>/dev/null || echo unknown)
if [ "$state" != running ]; then
    echo "CR52_RPROC_FAIL reason=not_running state=$state firmware=$selected waited=${i}s"
    exit 1
fi

echo "CR52_RPROC_UP name=$name firmware=$selected waited=${i}s"
