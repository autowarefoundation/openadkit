#!/usr/bin/env bash
# Before/after MRM demo orchestrator for the X5H board (issue #120,
# follow-on to milestone 7). Runs ON THE COMPANION HOST, never on the
# board: a demo leg reboots the board, and an on-board orchestrator would
# not survive its own flash step.
#
# One demo = flash the "before" payload -> reboot -> x5h-stack-smoke.sh
# drive -> flash "after" -> reboot -> drive -> compare stop distances. The
# fixed before->after order is load-bearing: it leaves the board on the
# tuned production firmware whatever happens after the last flash.
#
#   x5h-mrm-demo.sh check <before|after> <payload.bin>
#       Local gates only (no board, no site config): payload readable,
#       non-empty, carries the profile identity string
#       "actuation_param_profile=<profile>" the firmware banner embeds.
#       Prints DEMO_CHECK_PASS profile=<p> sha256=<h> bytes=<n>.
#   x5h-mrm-demo.sh run --before <payload.bin> --after <payload.bin> \
#                       [--only before|after]
#       The full demo (or one leg with --only). Exactly one terminal
#       marker per invocation:
#         X5H_DEMO_PASS before_stop_m=<a> after_stop_m=<b> delta_m=<d>
#         X5H_DEMO_LEG profile=<p> stop_distance_m=<d>      (--only)
#         X5H_DEMO_FAIL reason=<...>
#
# reason= vocabulary (earliest break names the reason):
#   usage                                  bad invocation
#   no_site_conf / site_conf_incomplete    run mode without slot geometry
#   demo_wrong_profile:<p>                 payload lacks the profile string
#   demo_flash_failed:<p>[:detail]         gate or slot write/verify failed
#   demo_board_no_boot:<p>                 board did not return after reboot
#   demo_drive_failed:<p>:<reason>         drive failed; <reason> is the
#                                          smoke script's own reason= value
#   demo_no_contrast                       before stop was not longer than
#                                          after stop
#
# SITE CONFIG -- THE NDA BOUNDARY. The CR52 slot's device, offset and
# extent derive from the vendor SDK (Renesas security portal) and are never
# committed to this repository (same discipline as cr52-slot-update.md:
# "numbers live elsewhere"). They are read from a site-local file,
# $X5H_DEMO_SITE_CONF (default ~/.config/x5h-demo/site.conf), which must
# define:
#   X5H_SLOT_DEV=<block device path on the board>
#   X5H_SLOT_SKIP=<slot offset in 4096-byte sectors>
#   X5H_SLOT_EXTENT_SECTORS=<slot extent in 4096-byte sectors>
#   X5H_SLOT_BASELINE=<path on THIS host to the pristine slot-orig.bin>
# and may override:
#   X5H_BOARD (default root@192.168.0.20)
#   X5H_SMOKE (default /usr/local/sbin/x5h-stack-smoke.sh)
#   X5H_BOOT_TIMEOUT (default 600 s), X5H_UNITS_TIMEOUT (default 300 s)
#
# Payloads are the flat slot binaries prepared from the CI-built ELFs per
# the site flash runbook (the ELF->payload step also stays outside this
# repository); the identity string survives the conversion because it
# lives in .rodata, which is loaded from the slot.
#
# On any failure: stop, recover nothing automatically, print the restore
# commands for the operator. The vendor-tool restore path documented in
# cr52-slot-update.md is the last resort.
set -u

MODE="${1:-}"

log() { echo "x5h-mrm-demo: $*" >&2; }

demo_fail() {
    echo "X5H_DEMO_FAIL reason=$1"
    if [ -n "${2:-}" ]; then
        log "board state: $2"
        log "restore: re-run a single after leg (x5h-mrm-demo.sh run --after <after.bin> --only after)"
        log "         or write back \$X5H_SLOT_BASELINE per cr52-slot-update.md"
    fi
    exit 1
}

# ---- local payload gates (no board, no site config) -----------------------

GATE_SHA=""
GATE_BYTES=""

gate_payload() { # profile payload -> sets GATE_SHA, GATE_BYTES
    local profile="$1" payload="$2"
    [ -r "$payload" ] || demo_fail "demo_flash_failed:${profile}:payload_unreadable"
    GATE_BYTES=$(stat -c %s "$payload")
    [ "$GATE_BYTES" -gt 0 ] || demo_fail "demo_flash_failed:${profile}:payload_empty"
    grep -aq "actuation_param_profile=${profile}" "$payload" \
        || demo_fail "demo_wrong_profile:${profile}"
    GATE_SHA=$(sha256sum "$payload" | awk '{print $1}')
}

# ---- site config -----------------------------------------------------------

X5H_BOARD="root@192.168.0.20"
X5H_SMOKE="/usr/local/sbin/x5h-stack-smoke.sh"
X5H_BOOT_TIMEOUT=600
X5H_UNITS_TIMEOUT=300
X5H_SLOT_DEV=""
X5H_SLOT_SKIP=""
X5H_SLOT_EXTENT_SECTORS=""
X5H_SLOT_BASELINE=""

load_site_conf() {
    local conf="${X5H_DEMO_SITE_CONF:-$HOME/.config/x5h-demo/site.conf}"
    [ -r "$conf" ] || demo_fail "no_site_conf"
    # shellcheck disable=SC1090
    . "$conf"
    for v in X5H_SLOT_DEV X5H_SLOT_SKIP X5H_SLOT_EXTENT_SECTORS X5H_SLOT_BASELINE; do
        [ -n "$(eval echo "\${$v}")" ] || demo_fail "site_conf_incomplete"
    done
    [ -r "$X5H_SLOT_BASELINE" ] || demo_fail "site_conf_incomplete"
}

bssh() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$X5H_BOARD" "$@"; }

# ---- one demo leg ----------------------------------------------------------

flash_payload() { # profile payload bytes
    local profile="$1" payload="$2" bytes="$3"
    local extent_bytes=$((X5H_SLOT_EXTENT_SECTORS * 4096))
    [ "$bytes" -le "$extent_bytes" ] \
        || demo_fail "demo_flash_failed:${profile}:payload_exceeds_extent"
    scp -o BatchMode=yes "$payload" "$X5H_BOARD:/var/tmp/x5h-demo-${profile}.bin" \
        || demo_fail "demo_flash_failed:${profile}:scp"
    # cr52-slot-update.md's procedure verbatim: erase the extent first (no
    # tail of the previous image may survive inside the region the boot
    # firmware loads), buffered write with fsync (O_DIRECT rejects the
    # final partial block of an unaligned payload), flush, then a direct
    # read-back compare so the verify reads media, not page cache.
    bssh "set -e
        dd if=/dev/zero of=${X5H_SLOT_DEV} bs=4096 seek=${X5H_SLOT_SKIP} count=${X5H_SLOT_EXTENT_SECTORS} conv=notrunc,fsync 2>/dev/null
        dd if=/var/tmp/x5h-demo-${profile}.bin of=${X5H_SLOT_DEV} bs=4096 seek=${X5H_SLOT_SKIP} conv=notrunc,fsync 2>/dev/null
        blockdev --flushbufs ${X5H_SLOT_DEV}
        dd if=${X5H_SLOT_DEV} bs=4096 skip=${X5H_SLOT_SKIP} count=${X5H_SLOT_EXTENT_SECTORS} iflag=direct 2>/dev/null \
          | head -c ${bytes} | cmp - /var/tmp/x5h-demo-${profile}.bin" \
        || demo_fail "demo_flash_failed:${profile}:write_verify" \
                     "slot content is NOT the ${profile} payload; do not reboot before restoring"
}

reboot_and_wait() { # profile
    local profile="$1"
    bssh reboot || true   # the connection dropping mid-command is expected
    local deadline=$(($(date +%s) + X5H_BOOT_TIMEOUT))
    sleep 20
    until bssh true 2>/dev/null; do
        [ "$(date +%s)" -lt "$deadline" ] \
            || demo_fail "demo_board_no_boot:${profile}" \
                         "board did not return within ${X5H_BOOT_TIMEOUT}s of the reboot"
        sleep 10
    done
    # Wait for the stack units the drive precondition checks; drive itself
    # fails fast on an inactive unit, so give the boot time to finish.
    deadline=$(($(date +%s) + X5H_UNITS_TIMEOUT))
    until bssh "systemctl is-active --quiet awf-oak-autoware.service awf-oak-bridge.service awf-oak-relay.service awf-oak-restamp.service rpmsg-eth.service" 2>/dev/null; do
        [ "$(date +%s)" -lt "$deadline" ] || break   # let drive name the culprit
        sleep 10
    done
}

run_leg() { # profile payload -> sets LEG_STOP_M
    local profile="$1" payload="$2"
    gate_payload "$profile" "$payload"
    local sha="$GATE_SHA" bytes="$GATE_BYTES"
    log "leg ${profile}: payload sha256=${sha} bytes=${bytes}"
    flash_payload "$profile" "$payload" "$bytes"
    reboot_and_wait "$profile"
    local out marker
    out=$(bssh "sh ${X5H_SMOKE} drive" 2>&1) || true
    printf '%s\n' "$out" > "${LOGDIR}/drive-${profile}.log"
    marker=$(printf '%s\n' "$out" | grep -E '^X5H_DRIVE_(PASS|FAIL)' | tail -1)
    log "leg ${profile}: ${marker:-<no marker>}"
    fetch_probe "$profile"
    case "$marker" in
        X5H_DRIVE_PASS*) ;;
        X5H_DRIVE_FAIL*)
            demo_fail "demo_drive_failed:${profile}:${marker#X5H_DRIVE_FAIL reason=}" \
                      "board is on the ${profile} payload and booted; drive failed"
            ;;
        *)
            demo_fail "demo_drive_failed:${profile}:no_marker" \
                      "board is on the ${profile} payload; smoke produced no marker"
            ;;
    esac
    LEG_STOP_M=$(printf '%s\n' "$marker" | grep -o 'stop_distance_m=[0-9.]*' | cut -d= -f2)
    [ -n "$LEG_STOP_M" ] \
        || demo_fail "demo_drive_failed:${profile}:no_stop_distance" \
                     "board is on the ${profile} payload and booted"
}

fetch_probe() { # profile -- best-effort evidence collection, never fatal
    local profile="$1" outdir
    outdir=$(bssh '. /etc/containers/systemd/awf-oak-x5h.env 2>/dev/null && echo "$OUTPUT_DIRECTORY"') || return 0
    [ -n "$outdir" ] || return 0
    scp -o BatchMode=yes -q -r "$X5H_BOARD:${outdir}/drive-probe" \
        "${LOGDIR}/drive-probe-${profile}" 2>/dev/null || true
}

# ---- entry points ----------------------------------------------------------

case "$MODE" in
check)
    PROFILE="${2:-}"
    PAYLOAD="${3:-}"
    case "$PROFILE" in before|after) ;; *) demo_fail "usage" ;; esac
    [ -n "$PAYLOAD" ] || demo_fail "usage"
    gate_payload "$PROFILE" "$PAYLOAD"
    echo "DEMO_CHECK_PASS profile=${PROFILE} sha256=${GATE_SHA} bytes=${GATE_BYTES}"
    ;;
run)
    shift
    BEFORE=""
    AFTER=""
    ONLY=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --before) BEFORE="${2:-}"; shift 2 ;;
            --after)  AFTER="${2:-}";  shift 2 ;;
            --only)
                case "${2:-}" in before|after) ONLY="$2" ;; *) demo_fail "usage" ;; esac
                shift 2 ;;
            *) demo_fail "usage" ;;
        esac
    done
    load_site_conf
    LOGDIR="${X5H_DEMO_LOGDIR:-$HOME/x5h-demo-logs}/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$LOGDIR"
    log "logs: $LOGDIR"
    LEG_STOP_M=""
    if [ "$ONLY" = "before" ] || [ "$ONLY" = "after" ]; then
        payload="$BEFORE"
        [ "$ONLY" = "after" ] && payload="$AFTER"
        [ -n "$payload" ] || demo_fail "usage"
        run_leg "$ONLY" "$payload"
        echo "X5H_DEMO_LEG profile=${ONLY} stop_distance_m=${LEG_STOP_M}"
        exit 0
    fi
    [ -n "$BEFORE" ] && [ -n "$AFTER" ] || demo_fail "usage"
    # Gate BOTH payloads before writing ANYTHING: a demo that flashes
    # "before" and then discovers the "after" payload is unusable would
    # strand the board on the untuned firmware.
    gate_payload "before" "$BEFORE"
    gate_payload "after" "$AFTER"
    run_leg "before" "$BEFORE"
    before_stop="$LEG_STOP_M"
    run_leg "after" "$AFTER"
    after_stop="$LEG_STOP_M"
    awk -v a="$before_stop" -v b="$after_stop" 'BEGIN { exit !(a > b) }' \
        || demo_fail "demo_no_contrast" \
                     "board is on the after payload (production state); both drives passed"
    delta=$(awk -v a="$before_stop" -v b="$after_stop" 'BEGIN { printf "%.2f", a - b }')
    echo "X5H_DEMO_PASS before_stop_m=${before_stop} after_stop_m=${after_stop} delta_m=${delta}"
    ;;
*)
    demo_fail "usage"
    ;;
esac
