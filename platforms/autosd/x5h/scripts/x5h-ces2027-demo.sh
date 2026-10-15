#!/usr/bin/env bash
# Booth operator script for the CES 2027 demo. Runs on the companion host
# (rog-amd), never on the board.
#   x5h-ces2027-demo.sh check            everything ready (VisionPilot running, SI
#                                         not latched)? prints the package sha
#   x5h-ces2027-demo.sh run              print the compose command that brings
#                                         the stack up, the board restart, and
#                                         the reset to run once CARLA is up
#   x5h-ces2027-demo.sh fault kill|slow|lm [--at <epoch-s>]   inject a fault
#   x5h-ces2027-demo.sh reset            stop the launch manager, clear the SI
#                                         latch, start the launch manager
# Markers: X5H_CES_DEMO_READY sha=<sha> spawn=<idx> units=6 hb=<seq>
#        | X5H_CES_DEMO_FAULT route=<r> at=<epoch.ns> | X5H_CES_DEMO_FAIL reason=<slug>
#
# Compose (components/demo/docker-compose.yaml) owns starting carla-server and
# bridge: this script does not shell out to `docker` to start its own
# siblings, so it never needs the host's docker socket mounted in. `run`
# below only prints the commands; the operator (or the `demo` compose
# service's own shell) actually runs them.
set -uo pipefail
SSH="${SSH:-ssh}"; BOARD="${X5H_BOARD:-root@192.168.0.20}"
CARLA_PKG="${CARLA_PKG:-$HOME/carla-pkg}"; VP_SI="${VP_SI:-$HOME/vp-ros2/si}"
# When run directly on the host, $0 sits next to ../components/demo and the
# default below resolves. Inside the `demo` container this script is mounted
# alone at /usr/local/bin, so that directory does not exist there -- the
# container's own COMPOSE_FILE env var (set by docker-compose.yaml from the
# host's $PWD) is what makes it correct in that context; see README.md,
# "Running the demo". Do not resolve a directory that is not there: an empty
# `cd` result used to silently become "/docker-compose.yaml".
COMPOSE_FILE="${COMPOSE_FILE:-}"
UNITS="x5h-si-link x5h-demo-bridge x5h-demo-restamp x5h-demo-hb score-datarouter score-lm"
fail() { echo "X5H_CES_DEMO_FAIL reason=$1"; exit 1; }
cmd="${1:-}"
case "$cmd" in
  check)
    [ -f "$CARLA_PKG/ces2027-package-sha.txt" ] || fail no_package_sha
    sha=$(cat "$CARLA_PKG/ces2027-package-sha.txt")
    [ -f "$VP_SI/route.env" ] || fail no_route
    # route.env is data, never code: sourcing it would let a syntax error, an
    # unset-variable reference, or a bare `exit` hijack this script's own
    # control flow (observed: a syntax error made an earlier version of this
    # script print a false X5H_CES_DEMO_READY with spawn=?). Read the one
    # value needed with sed instead, and reject anything that does not look
    # like exactly one well-formed assignment.
    spawn=$(sed -n 's/^SPAWN_INDEX=\([0-9]\{1,\}\)$/\1/p' "$VP_SI/route.env" | head -n 1)
    [ -n "$spawn" ] || fail bad_route
    states=$($SSH "$BOARD" "systemctl is-active $UNITS")
    # A transport failure (no ssh binary, connection refused, a dropped
    # connection mid-output) shows up here as fewer than 6 lines, including
    # zero. That must be reported as its own reason: sending the operator to
    # check the board's units when the real problem is the network wastes
    # the minutes a booth doesn't have.
    n_lines=$(grep -c '.' <<<"$states")
    [ "$n_lines" -eq 6 ] || fail ssh_failed
    n=$(grep -c '^active$' <<<"$states")
    [ "$n" -eq 6 ] || fail unit_inactive
    # vp.ready outlives a killed VisionPilot, so the process must be there too.
    # ssh exits 255 on a transport failure, which is not a missing VisionPilot.
    rc=0; $SSH "$BOARD" 'test -e /run/score/vp.ready && pgrep -x VisionPilot >/dev/null' || rc=$?
    [ "$rc" -ne 255 ] || fail ssh_failed
    [ "$rc" -eq 0 ] || fail vp_not_ready
    hb=$($SSH "$BOARD" 'journalctl -u x5h-si-link -n 1 --no-pager -o cat') || true
    seq=$(sed -n 's/.*hb seq=\([0-9]*\).*/\1/p' <<<"$hb"); [ -n "$seq" ] || fail no_heartbeat
    # fault= is the Safety Island's latch: a stop that only reset clears.
    fault=$(sed -n 's/.*hb seq=.* fault=\([0-9]*\).*/\1/p' <<<"$hb"); [ "$fault" = 0 ] || fail si_latched
    echo "X5H_CES_DEMO_READY sha=$sha spawn=$spawn units=$n hb=$seq" ;;
  run)
    if [ -z "$COMPOSE_FILE" ]; then
        d=$(cd "$(dirname "$0")/../components/demo" 2>/dev/null && pwd) || true
        [ -n "$d" ] || fail no_compose_file
        COMPOSE_FILE="$d/docker-compose.yaml"
    fi
    echo "CARLA_PKG=$CARLA_PKG VP_SI=$VP_SI docker compose -f $COMPOSE_FILE up -d"
    echo "$SSH $BOARD 'systemctl restart x5h-demo.service && systemctl status x5h-demo.service --no-pager | grep X5H_DEMO_UP'"
    # A board that booted before CARLA has fallen back after ready_timeout,
    # and restarting x5h-demo.service does not restart a launch manager that
    # is still active in fallback. The booth reset does.
    echo "$0 reset" ;;
  fault)
    case "${2:-}" in
      # pkill, not the podman CLI: VisionPilot runs in the host PID namespace,
      # and podman's own start cost 0.3-0.4 s on the board (2026-10-01).
      kill) remote='pkill -KILL -x VisionPilot' ;;
      slow) remote='pkill -USR1 -x VisionPilot' ;;
      lm)   remote='systemctl kill -s KILL score-lm.service' ;;
      *) fail usage ;;
    esac
    # Pay the ssh handshake before the wait and let the fault reuse the
    # master connection: a cold handshake landed every fault 0.44-0.75 s
    # after --at on board 2, and the gate measures from --at. ControlPersist
    # has to outlive the wait.
    FSSH="$SSH -o ControlMaster=auto -o ControlPath=${TMPDIR:-/tmp}/x5h-demo-%C -o ControlPersist=600"
    $FSSH "$BOARD" true || fail ssh_failed
    # --at <epoch-s> waits for that second, so si_stop_gate.py can be started
    # first with the same value as --fault-at.
    if [ "${3:-}" = --at ]; then
        [[ ${4:-} =~ ^[0-9]+$ ]] || fail usage
        while [ "$(date +%s)" -lt "$4" ]; do sleep 0.05; done
    fi
    at=$(date +%s.%N)
    $FSSH "$BOARD" "$remote" >/dev/null || fail fault_failed
    echo "X5H_CES_DEMO_FAULT route=$2 at=$at" ;;
  reset)
    # Stop first, so a si_fault forked during the stop cannot latch after the clear.
    $SSH "$BOARD" 'systemctl stop score-lm.service && systemctl kill -s USR2 x5h-si-link.service && systemctl start score-lm.service' || fail reset
    echo "X5H_CES_DEMO_RESET" ;;
  *) fail usage ;;
esac
