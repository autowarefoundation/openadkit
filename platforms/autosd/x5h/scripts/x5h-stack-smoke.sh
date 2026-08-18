#!/bin/sh
# On-board smoke for the Open AD Kit component stack (issue #120 M7).
# Runs ON the board. One terminal marker per invocation, judged by string
# match, following the repo's rpmsg-smoke.sh convention.
#
#   stack   -- units active, six bridged topics in the right direction,
#              control_cmd demonstrably sourced on the CR52
#   drive   -- run the scenario and grade its junit output
#   autoware-- domain 1 only: no bridge, no CR52. The Stage 1 isolation
#              hinge, so "Autoware does not run on this silicon" and "the
#              consolidation is misconfigured" cannot look alike.
#
# No `set -e`: every failure must reach exactly one marker rather than
# exiting silently mid-check.
set -u

MODE="${1:-stack}"
ENVF=/etc/containers/systemd/awf-oak-x5h.env
DDS_URI=file:///autoware/cyclonedds.xml
CORE_UNITS="awf-oak-map awf-oak-planning awf-oak-vehicle awf-oak-system awf-oak-control awf-oak-simulator awf-oak-api"

fail() { echo "X5H_${2}_FAIL reason=$1"; exit 1; }

ros1() { # run a ros2 command on domain 1 inside the map container
    podman exec awf-oak-map bash -lc \
      "source /opt/ros/\$ROS_DISTRO/setup.bash && source /opt/autoware/setup.bash && $1" 2>/dev/null
}
ros2dom() { # run a ros2 command on domain 2, from inside the bridge
            # container (podman exec uses the container's mounts)
    podman exec -e ROS_DOMAIN_ID=2 -e CYCLONEDDS_URI="$DDS_URI" awf-oak-bridge bash -lc \
      "source /opt/ros/\$ROS_DISTRO/setup.bash && source /opt/autoware/setup.bash && $1" 2>/dev/null
}

check_units() {
    for u in $1; do
        systemctl is-active --quiet "${u}.service" || fail "unit_inactive:$u" "$2"
    done
}

case "$MODE" in
autoware)
    check_units "$CORE_UNITS" "AUTOWARE"
    # The point of Stage 1: prove the stack runs before anything is bridged.
    ros1 "timeout 20 ros2 topic list" | grep -q '/planning/scenario_planning/trajectory' \
        || fail "no_trajectory_topic" "AUTOWARE"
    ros1 "timeout 20 ros2 topic echo --once /localization/kinematic_state" >/dev/null \
        || fail "no_kinematic_state" "AUTOWARE"
    echo "X5H_AUTOWARE_MEM_KB=$(awk '/MemAvailable/{print $2}' /proc/meminfo)"
    echo "X5H_AUTOWARE_PASS"
    ;;
stack)
    check_units "$CORE_UNITS awf-oak-bridge" "STACK"
    systemctl is-active --quiet rpmsg-eth.service || fail "rpmsg_eth_inactive" "STACK"
    # The frozen link parameters, re-asserted: a tap0 that came up at the
    # kernel default MTU loses oversize frames silently rather than failing.
    mtu=$(cat /sys/class/net/tap0/mtu 2>/dev/null)
    [ "$mtu" = "462" ] || fail "tap0_mtu=$mtu" "STACK"

    # Five topics domain 1 -> domain 2: present on domain 2.
    for t in /vehicle/status/steering_status /planning/scenario_planning/trajectory \
             /system/operation_mode/state /localization/kinematic_state \
             /localization/acceleration; do
        ros2dom "timeout 20 ros2 topic echo --once $t" >/dev/null \
            || fail "not_bridged_to_domain2:$t" "STACK"
    done

    # One topic domain 2 -> domain 1, and it must ORIGINATE on the CR52.
    # Presence on domain 1 alone would also be satisfied by a local
    # publisher, so the decisive check is the wire: RTPS data arriving on
    # tap0 sourced from the CR52's address.
    ros1 "timeout 20 ros2 topic echo --once /control/trajectory_follower/control_cmd" >/dev/null \
        || fail "no_control_cmd_on_domain1" "STACK"
    n=$(timeout 15 tcpdump -ni tap0 -c 5 "src host 172.16.52.2 and udp" 2>/dev/null | grep -c 'IP ')
    [ "${n:-0}" -ge 1 ] || fail "control_cmd_not_from_cr52" "STACK"

    echo "X5H_STACK_PASS bridged=6 cr52_packets=$n"
    ;;
drive)
    check_units "$CORE_UNITS awf-oak-bridge" "DRIVE"
    # shellcheck disable=SC1090
    . "$ENVF"
    rm -rf "${OUTPUT_DIRECTORY:?}"/* 2>/dev/null

    # Bounded wait for Autoware readiness: After= on the component units
    # only guarantees the containers were started, not that Autoware
    # itself is up. The compose sample waits on this same API service
    # before launching scenario_test_runner; a fixed number of retries
    # (not an unbounded loop) does the same here.
    ready=0
    i=0
    while [ "$i" -lt 30 ]; do
        ros1 "timeout 5 ros2 service list" | grep -qFx '/api/autoware/set/engage' \
            && { ready=1; break; }
        i=$((i + 1))
        sleep 2
    done
    [ "$ready" -eq 1 ] || fail "autoware_not_ready" "DRIVE"

    # `systemctl restart` (not `start`): RemainAfterExit=yes leaves the
    # unit active (exited) after a successful run, and `start` on an
    # already-active unit returns immediately WITHOUT re-running
    # ExecStart -- fatal for this smoke, which runs `drive` more than
    # once per boot and always rm -rf's the output directory first, so a
    # second `start` would report no_junit on a perfectly healthy stack.
    # `restart` always re-runs ExecStart regardless of the unit's prior
    # state, and still blocks until the oneshot's ExecStart exits, so the
    # rule below is unaffected: do NOT add an `is-active` wait loop here,
    # and do not "simplify" this back to `start`. scenario_test_runner is
    # itself bounded by GLOBAL_TIMEOUT.
    systemctl restart awf-oak-scenario.service || fail "scenario_start" "DRIVE"
    junit=$(find "${OUTPUT_DIRECTORY}" -name 'result.junit.xml' | head -1)
    [ -n "$junit" ] || fail "no_junit" "DRIVE"
    fails=$(grep -o 'failures="[0-9]*"' "$junit" | head -1 | tr -dc '0-9')
    errs=$(grep -o 'errors="[0-9]*"' "$junit" | head -1 | tr -dc '0-9')
    [ "${fails:-1}" = "0" ] && [ "${errs:-1}" = "0" ] \
        || fail "junit_failures=${fails:-?}_errors=${errs:-?}" "DRIVE"
    echo "X5H_DRIVE_PASS junit=$junit"
    ;;
*)
    fail "usage" "STACK"
    ;;
esac
