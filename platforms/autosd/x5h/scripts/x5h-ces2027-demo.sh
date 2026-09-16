#!/usr/bin/env bash
# Booth operator script for the CES 2027 demo. Runs on the companion host
# (rog-amd), never on the board.
#   x5h-ces2027-demo.sh check            everything ready? prints the package sha
#   x5h-ces2027-demo.sh run              print the compose command that brings
#                                         the stack up, then restart the board
#   x5h-ces2027-demo.sh fault kill|channel   inject the fault (the demo moment)
#   x5h-ces2027-demo.sh reset            VisionPilot back, fault cleared
# Markers: X5H_CES_DEMO_READY sha=<sha> spawn=<idx> units=5 hb=<seq> | X5H_CES_DEMO_FAIL reason=<slug>
#
# Compose (components/demo/docker-compose.yaml) owns starting carla-server and
# bridge: this script does not shell out to `docker` to start its own
# siblings, so it never needs the host's docker socket mounted in. `run`
# below only prints the command; the operator (or the `demo` compose
# service's own shell) actually runs it.
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
UNITS="x5h-si-link x5h-demo-bridge x5h-demo-restamp x5h-demo-hb x5h-vp"
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
    # connection mid-output) shows up here as fewer than 5 lines, including
    # zero. That must be reported as its own reason: sending the operator to
    # check the board's units when the real problem is the network wastes
    # the minutes a booth doesn't have.
    n_lines=$(grep -c '.' <<<"$states")
    [ "$n_lines" -eq 5 ] || fail ssh_failed
    n=$(grep -c '^active$' <<<"$states")
    [ "$n" -eq 5 ] || fail unit_inactive
    hb=$($SSH "$BOARD" 'journalctl -u x5h-si-link -n 1 --no-pager -o cat') || true
    seq=$(sed -n 's/.*hb seq=\([0-9]*\).*/\1/p' <<<"$hb"); [ -n "$seq" ] || fail no_heartbeat
    echo "X5H_CES_DEMO_READY sha=$sha spawn=$spawn units=$n hb=$seq" ;;
  run)
    # Bringing carla-server/bridge/si-gate up is compose's job, not this
    # script's: printing the two commands keeps the booth operator off
    # `docker` directly and this script out of needing the host's
    # /var/run/docker.sock mounted into any container.
    if [ -z "$COMPOSE_FILE" ]; then
        d=$(cd "$(dirname "$0")/../components/demo" 2>/dev/null && pwd) || true
        [ -n "$d" ] || fail no_compose_file
        COMPOSE_FILE="$d/docker-compose.yaml"
    fi
    echo "CARLA_PKG=$CARLA_PKG VP_SI=$VP_SI docker compose -f $COMPOSE_FILE up -d"
    echo "$SSH $BOARD 'systemctl restart x5h-demo.service && systemctl status x5h-demo.service --no-pager | grep X5H_DEMO_UP'" ;;
  fault)
    case "${2:-}" in
      kill|channel)
        # This is the demo moment: a missing or failing fault script must
        # say so, not do nothing.
        [ -f "$VP_SI/si_fault.sh" ] || fail no_fault_script
        bash "$VP_SI/si_fault.sh" "$2" || fail fault_failed ;;
      *) fail usage ;;
    esac ;;
  reset)
    $SSH "$BOARD" 'systemctl kill -s USR2 x5h-si-link.service; systemctl start x5h-vp.service' || fail reset
    echo "X5H_CES_DEMO_RESET" ;;
  *) fail usage ;;
esac
