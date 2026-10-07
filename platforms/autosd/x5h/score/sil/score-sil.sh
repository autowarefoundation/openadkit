#!/usr/bin/env bash
# Software-in-the-loop for the S-CORE container boundary, on the x86 host or
# on a board, as root. It copies build-score.sh's output to /var/tmp/score-sil
# (the bin_dir of config/sil) and runs the launch manager, the stub fault
# listener and the datarouter as transient systemd units. No python3: the
# board has none.
#   score-sil.sh boundary <src> <image>          one pass over every boundary row (P0)
#   score-sil.sh soak <src> <image> [minutes]    zero fallbacks (SG1)
#   score-sil.sh kill|slow <src> <image>         injection to stub fault, in ms (SG1)
#   score-sil.sh lm <src> <image>                LM SIGKILL to no container, in ms (SG1)
# <src> is the tar, or its unpacked score/ directory (the board has no tar).
# <image> is tagged localhost/score-sil:latest: on x86 build it from
# Containerfile, on the board pass localhost/x5h-visionpilot:latest.
# Markers: SIL_<CHECK>_OK|FAIL, then SIL_<SUB>_PASS ... | SIL_<SUB>_FAIL reason=<slug>
set -uo pipefail
sub=${1:-}; src=${2:-}; image=${3:-}
D=/var/tmp/score-sil
vp_pid=; cam_pid=
UNITS="score-sil-lm.service score-sil-stub.service score-sil-dr.service"
SUB=$(tr '[:lower:]' '[:upper:]' <<<"$sub")
cleanup() {
    # shellcheck disable=SC2086
    systemctl stop $UNITS 2>/dev/null
    # A killed transient unit stays loaded as failed, and systemd-run then
    # refuses its name.
    # shellcheck disable=SC2086
    systemctl reset-failed $UNITS 2>/dev/null
    podman rm -f sil-vp sil-camera >/dev/null 2>&1
    true
}
fail() { echo "SIL_${SUB}_FAIL reason=$1"; cleanup; exit 1; }
[ -n "$sub" ] && [ -e "$src" ] && [ -n "$image" ] || { echo "usage: $0 <sub> <src> <image>"; exit 2; }
[ "$(id -u)" = 0 ] || { echo "SIL_${SUB}_FAIL reason=not_root"; exit 2; }
now() { date +%s.%N; }
ms() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.0f", (b - a) * 1000 }'; }
wait_for() {  # wait_for <seconds> <command...>
    local end=$(( $(date +%s) + $1 )); shift
    until "$@"; do [ "$(date +%s)" -lt "$end" ] || return 1; sleep 0.05; done
}
lm_log() { journalctl -u score-sil-lm.service -o cat --no-pager --after-cursor="$cursor"; }
stub_fault_at() { journalctl -u score-sil-stub.service -o cat --no-pager --after-cursor="$cursor" \
    | sed -n 's/^SIL_STUB_FAULT at=//p' | tail -n 1; }
# podman ps cannot say whether the payloads are gone: a SIGKILL of the unit kills
# conmon with them, so podman keeps listing them as running, even with --sync.
read_pids() {
    vp_pid=$(podman inspect -f '{{.State.Pid}}' sil-vp 2>/dev/null)
    cam_pid=$(podman inspect -f '{{.State.Pid}}' sil-camera 2>/dev/null)
    [ "${vp_pid:-0}" -gt 0 ] 2>/dev/null && [ "${cam_pid:-0}" -gt 0 ] 2>/dev/null \
        && ! gone "$vp_pid" && ! gone "$cam_pid"  # a record left by a SIGKILL keeps the dead pid
}
gone() { local p; for p in "$@"; do kill -0 "$p" 2>/dev/null && return 1; done; return 0; }
no_containers() { gone "$vp_pid" "$cam_pid"; }
# A fallback transition that fails logs only 'activating recovery state'.
fell_back() { lm_log | grep -e 'State fallback' -e 'activating recovery state' >/dev/null; }
stub_faulted() { [ -n "$(stub_fault_at)" ]; }
start_lm() {
    systemctl reset-failed score-sil-lm.service 2>/dev/null
    rm -f /run/score-sil/vp.ready
    systemd-run --quiet --unit=score-sil-lm -p Restart=no \
        -E MW_LOG_CONFIG_FILE="$D/etc/gate/logging.json" \
        "$D/bin/launch_manager" -c "$D/etc/sil/launch_manager_config.bin" || fail lm_start
    wait_for 60 test -e /run/score-sil/vp.ready || fail vp_never_ready
    wait_for 10 read_pids || fail no_payload_pids
}

cleanup
rm -rf "$D"; mkdir -p "$D" || fail mkdir
if [ -d "$src" ]; then cp -a "$src"/. "$D"/ || fail copy
else tar -xf "$src" -C "$D" --strip-components=1 || fail untar; fi
cp "$D"/sil/*.sh "$D/bin/" && chmod +x "$D"/bin/* || fail install_scripts
podman tag "$image" localhost/score-sil:latest || fail tag_image
take_cursor() { cursor=$(journalctl -n 0 --show-cursor --no-pager | sed -n 's/^-- cursor: //p'); }
take_cursor
systemd-run --quiet --unit=score-sil-stub "$D/bin/sil-stub.sh" || fail stub_start

case "$sub" in
boundary)
    start_lm; echo SIL_READY_FILE_OK
    sleep 5
    if lm_log | grep 'switched to FAILED' >/dev/null; then echo SIL_ALIVE_FAIL; fail alive; fi
    echo SIL_ALIVE_OK
    n_tag=$(journalctl -t sil-vp -o cat --no-pager --after-cursor="$cursor" | grep -c 'standin running')
    # journald files a systemd-cat stream under the unit whose cgroup the writer is in,
    # so -u cannot tell a duplicate; a real one (podman printing it again) is a second entry.
    n_all=$(journalctl --after-cursor="$cursor" -o cat --no-pager | grep -c 'standin running')
    [ "$n_tag" -ge 1 ] && [ "$n_all" -eq "$n_tag" ] || { echo "SIL_JOURNAL_ONCE_FAIL tag=$n_tag all=$n_all"; fail journal; }
    echo SIL_JOURNAL_ONCE_OK
    systemctl stop score-sil-lm.service
    wait_for 10 no_containers || fail stop_left_containers
    echo SIL_STOP_OK
    start_lm; systemctl kill -s KILL score-sil-lm.service
    wait_for 10 no_containers || fail lm_kill_left_containers
    echo SIL_LM_KILL_OK
    start_lm; take_cursor; podman kill sil-vp >/dev/null
    wait_for 5 fell_back || fail kill_no_fallback
    wait_for 5 stub_faulted || fail kill_no_stub_fault
    echo SIL_KILL_FALLBACK_OK
    systemctl stop score-sil-lm.service
    # A slow stand-in makes the launch manager stop a LIVE payload through its
    # podman client while it keeps running: the signal proxy at work, not
    # systemd (the STOP row cannot show that, because a control-group stop
    # signals the payload directly). The camera is in the fallback target too,
    # so it must survive the switch.
    start_lm; take_cursor; podman kill --signal USR1 sil-vp >/dev/null
    wait_for 5 fell_back || fail slow_no_fallback
    wait_for 10 gone "$vp_pid" || fail proxy_vp_left
    gone "$cam_pid" && fail fallback_stopped_camera
    systemctl is-active --quiet score-sil-lm.service || fail lm_died_in_fallback
    echo SIL_PROXY_OK
    systemctl stop score-sil-lm.service
    systemd-run --quiet --unit=score-sil-dr --working-directory="$D" \
        -E MW_LOG_CONFIG_FILE="$D/etc/gate/logging.json" \
        "$D/bin/datarouter" --no_adaptive_runtime -c "$D/sil/log-channels.json" || fail dr_start
    timeout 30 tcpdump -n -c 1 -i lo udp dst port 3490 > /tmp/score-sil-dlt.txt 2>/dev/null &
    lp=$!; sleep 1; start_lm
    wait "$lp"; grep -q UDP /tmp/score-sil-dlt.txt || fail no_dlt
    echo SIL_DLT_OK
    cleanup; echo "SIL_BOUNDARY_PASS" ;;
soak)
    min=${4:-10}; start_lm; sleep $(( min * 60 ))
    lm_log | grep -e 'switched to FAILED' -e 'State fallback' -e 'activating recovery state' >/dev/null && fail fallback
    # A dead LM logs no fallback line at all.
    systemctl is-active --quiet score-sil-lm.service || fail lm_inactive
    stub_faulted && fail stub_fault
    cleanup; echo "SIL_SOAK_PASS minutes=$min" ;;
kill|slow)
    start_lm; sleep 3
    take_cursor; t0=$(now)
    if [ "$sub" = kill ]; then podman kill sil-vp >/dev/null; else podman kill --signal USR1 sil-vp >/dev/null; fi
    wait_for 5 stub_faulted || fail no_stub_fault
    t1=$(stub_fault_at)
    cleanup; echo "SIL_${SUB}_PASS ms=$(ms "$t0" "$t1")" ;;
lm)
    start_lm; sleep 3
    ! gone "$vp_pid" && ! gone "$cam_pid" || fail payloads_died_early
    t0=$(now); systemctl kill -s KILL score-sil-lm.service
    wait_for 10 no_containers || fail left_containers
    t1=$(now); cleanup; echo "SIL_LM_PASS ms=$(ms "$t0" "$t1")" ;;
*) echo "usage: $0 <boundary|soak|kill|slow|lm> <src> <image>"; exit 2 ;;
esac
