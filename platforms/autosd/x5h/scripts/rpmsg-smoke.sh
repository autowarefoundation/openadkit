#!/bin/sh
# RPMsg dual-boot smoke for the X5H CR52 (runs unchanged on BSP Yocto and
# AutoSD): bring up the RPMsg vdev via remoteproc, verify the service comes
# up, run verified round-trips, stop.
#
# The CR52 firmware is NOT loaded by this script, and not by Linux at all:
# rcar_gen5_rproc's .load and .stop are both no-ops, so the realtime core runs
# whatever was flashed into its slot and is already live before Linux boots.
# `start` only parses the resource table out of the ELF, publishes the vrings
# and rings the MFIS doorbell. The ELF in /lib/firmware must therefore still
# match the flashed image, or the vring layout will not agree.
#
# Markers on stdout (grep-able, one per line):
#   RPMSG_SMOKE_PASS cycles=<c> msgs=<n>
#   RPMSG_SMOKE_FAIL cycle=<i> reason=<...>
#
# --check runs the read-only preflight only (no state changes) so it is safe
# on a board whose CR52 state is still unknown.
set -u

FW=rpmsg-echo-cr52.elf
SERVICE=rpmsg-client-sample
MSGS=100
# One session per boot: the CR52 firmware creates and announces its endpoint
# exactly once, so after a stop/start the channel never reappears and cycle 2
# would fail on service_timeout no matter how long it waited. Board-confirmed
# 2026-08-06. More cycles need a hardware reset between them, so -c >1 is
# opt-in and only meaningful for a firmware that re-announces.
CYCLES=1
CHECK=0

while [ $# -gt 0 ]; do
    case "$1" in
        -f|-s|-n|-c)
            [ $# -ge 2 ] || {
                echo "RPMSG_SMOKE_FAIL cycle=0 reason=bad_args"
                exit 1
            }
            ;;
    esac
    case "$1" in
        -f) FW=$2; shift 2 ;;
        -s) SERVICE=$2; shift 2 ;;
        -n) MSGS=$2; shift 2 ;;
        -c) CYCLES=$2; shift 2 ;;
        --check) CHECK=1; shift ;;
        *)
            echo "RPMSG_SMOKE_FAIL cycle=0 reason=bad_args"
            echo "usage: $0 [-f fw] [-s service] [-n msgs] [-c cycles] [--check]"
            exit 2
            ;;
    esac
done

# Reject non-numeric/zero -c or -n now: an unvalidated CYCLES/MSGS falls
# straight through the cycle loop below and prints RPMSG_SMOKE_PASS without
# running anything. This is a pure argument-validation failure, so it is
# checked before the hardware probe below and fires the same way regardless
# of board state.
case "$CYCLES" in
    ''|*[!0-9]*) echo "RPMSG_SMOKE_FAIL cycle=0 reason=bad_cycles"; exit 1 ;;
esac
[ "$CYCLES" -ge 1 ] || { echo "RPMSG_SMOKE_FAIL cycle=0 reason=bad_cycles"; exit 1; }
case "$MSGS" in
    ''|*[!0-9]*) echo "RPMSG_SMOKE_FAIL cycle=0 reason=bad_msgs"; exit 1 ;;
esac
[ "$MSGS" -ge 1 ] || { echo "RPMSG_SMOKE_FAIL cycle=0 reason=bad_msgs"; exit 1; }

# rpmsg-ping next to this script wins; else rely on PATH.
HERE=$(dirname "$0")
PING="$HERE/rpmsg-ping"
[ -x "$PING" ] || PING=rpmsg-ping

# --- locate the CR52 remoteproc ---------------------------------------------
RPROC=""
for d in /sys/class/remoteproc/remoteproc*; do
    [ -e "$d/name" ] || continue
    case "$(cat "$d/name")" in
        cr52*) RPROC=$d; break ;;
    esac
done
if [ -z "$RPROC" ]; then
    echo "RPMSG_SMOKE_FAIL cycle=0 reason=no_cr52_remoteproc"
    exit 1
fi
echo "INFO rproc=$RPROC name=$(cat "$RPROC/name") state=$(cat "$RPROC/state")"

if [ "$CHECK" = 1 ]; then
    echo "INFO firmware=$(cat "$RPROC/firmware")"
    echo "INFO rpmsg devices:"
    if [ -n "$(ls -A /sys/bus/rpmsg/devices/ 2>/dev/null)" ]; then
        ls /sys/bus/rpmsg/devices/
    else
        echo "  (none)"
    fi
    echo "INFO modules: $(lsmod 2>/dev/null | grep -cE 'rpmsg_(char|ctrl)') rpmsg char/ctrl loaded"
    if [ -e "/lib/firmware/$FW" ]; then
        echo "INFO fw_staged=yes fw=/lib/firmware/$FW"
    else
        echo "INFO fw_staged=no fw=/lib/firmware/$FW"
    fi
    if command -v "$PING" >/dev/null 2>&1; then
        echo "INFO ping=$PING"
    else
        echo "INFO ping=missing (expected next to this script or on PATH)"
    fi
    if lsmod 2>/dev/null | grep -q '^rpmsg_client_sample'; then
        echo "INFO rpmsg_client_sample=loaded (will contend for the channel; see Notes)"
    else
        echo "INFO rpmsg_client_sample=not_loaded"
    fi
    echo "RPMSG_SMOKE_CHECK_DONE"
    exit 0
fi

[ -e "/lib/firmware/$FW" ] || {
    echo "RPMSG_SMOKE_FAIL cycle=0 reason=firmware_missing fw=/lib/firmware/$FW"
    exit 1
}
modprobe rpmsg_char 2>/dev/null || true
modprobe rpmsg_ctrl 2>/dev/null || true

wait_state() {  # $1=want  $2=timeout_s
    t=0
    while [ "$t" -lt "$2" ]; do
        [ "$(cat "$RPROC/state")" = "$1" ] && return 0
        sleep 1; t=$((t + 1))
    done
    return 1
}

wait_service() {  # $1=timeout_s
    t=0
    while [ "$t" -lt "$1" ]; do
        for dev in /sys/bus/rpmsg/devices/*; do
            [ -e "$dev/name" ] || continue
            [ "$(cat "$dev/name")" = "$SERVICE" ] && return 0
        done
        sleep 1; t=$((t + 1))
    done
    return 1
}

i=1
while [ "$i" -le "$CYCLES" ]; do
    if [ "$(cat "$RPROC/state")" != "offline" ]; then
        echo stop > "$RPROC/state"
        wait_state offline 10 || {
            echo "RPMSG_SMOKE_FAIL cycle=$i reason=cannot_reach_offline state=$(cat "$RPROC/state")"
            exit 1
        }
    fi
    echo "$FW" > "$RPROC/firmware" || {
        echo "RPMSG_SMOKE_FAIL cycle=$i reason=firmware_write_error"
        exit 1
    }
    [ "$(cat "$RPROC/firmware")" = "$FW" ] || {
        echo "RPMSG_SMOKE_FAIL cycle=$i reason=firmware_readback_mismatch"
        exit 1
    }
    echo start > "$RPROC/state" || {
        echo "RPMSG_SMOKE_FAIL cycle=$i reason=start_write_error"
        exit 1
    }
    wait_state running 10 || {
        echo "RPMSG_SMOKE_FAIL cycle=$i reason=not_running state=$(cat "$RPROC/state")"
        echo stop > "$RPROC/state"
        exit 1
    }
    wait_service 15 || {
        echo "RPMSG_SMOKE_FAIL cycle=$i reason=service_timeout service=$SERVICE"
        echo stop > "$RPROC/state"
        exit 1
    }
    "$PING" -s "$SERVICE" -n "$MSGS" || {
        echo "RPMSG_SMOKE_FAIL cycle=$i reason=ping"
        echo stop > "$RPROC/state"
        exit 1
    }
    echo stop > "$RPROC/state"
    wait_state offline 10 || {
        echo "RPMSG_SMOKE_FAIL cycle=$i reason=stop_timeout"
        exit 1
    }
    echo "INFO cycle $i/$CYCLES OK"
    i=$((i + 1))
done
echo "RPMSG_SMOKE_PASS cycles=$CYCLES msgs=$MSGS"
