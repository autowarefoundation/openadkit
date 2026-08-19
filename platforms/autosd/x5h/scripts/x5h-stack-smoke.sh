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
# Markers on stdout (grep-able, one per line, exactly one per invocation):
#   X5H_AUTOWARE_PASS
#   X5H_AUTOWARE_FAIL reason=<...>
#   X5H_STACK_PASS bridged=6 cr52_packets=<n>
#   X5H_STACK_FAIL reason=<...>
#   X5H_DRIVE_PASS junit=<path>
#   X5H_DRIVE_FAIL reason=<...>
#
# reason= vocabulary, per mode -- what an operator reads mid-session, so it
# is enumerated here rather than left to be reverse-engineered from the
# code:
#   any mode: unit_inactive:<unit>  a required unit is not active
#   AUTOWARE: no_trajectory_topic   domain 1 has no planning trajectory
#             no_kinematic_state    no localization sample on domain 1
#             bridge_active         awf-oak-bridge is up, so this run is
#                                   NOT the unbridged domain-1-only case
#                                   this mode claims to measure
#   STACK:    usage                 unknown mode argument (also the
#                                   catch-all for a bad invocation)
#             rpmsg_eth_inactive    the CR52 link daemon is not running
#             tap0_mtu=<n>          tap0 is up at the wrong MTU
#             not_bridged_to_domain2:<topic>
#                                   a domain 1 -> 2 topic never arrived
#             no_control_cmd_on_domain1
#                                   nothing republished control_cmd onto
#                                   domain 1
#             no_control_cmd_on_domain2
#                                   nothing published control_cmd on
#                                   domain 2 -- i.e. no CR52 (see below)
#             no_tap0_counters      /sys/class/net/tap0/statistics is
#                                   unreadable, so the corroborating
#                                   packet delta could not be measured
#             no_cr52_packets_on_tap0
#                                   tap0 received nothing while the
#                                   domain-2 echo above ran
#   DRIVE:    no_env_file           $ENVF missing/unreadable, so
#                                   OUTPUT_DIRECTORY cannot be resolved
#             autoware_not_ready    /api/autoware/set/engage never appeared
#             scenario_start        systemctl restart of the scenario unit
#                                   failed
#             no_junit              the run produced no result.junit.xml
#             junit_failures=<n>_errors=<n>
#                                   the scenario ran and did not pass
#
# No `set -e`: every failure must reach exactly one marker rather than
# exiting silently mid-check.
set -u

MODE="${1:-stack}"
ENVF=/etc/containers/systemd/awf-oak-x5h.env
DDS_URI=file:///autoware/cyclonedds.xml
# Frozen link constants, hoisted here rather than inlined at their point of
# use, matching rpmsg-eth-smoke.sh. Do not retune: MTU 462 is sized to the
# CR52's RPMsg payload budget (see scripts/rpmsg-eth-ifup.sh) and PEER is
# domain 2's single static peer in components/cyclonedds-x5h.xml.
MTU=462
# PEER has no code reference left: the tcpdump src-host filter that used to
# be the only inline use of it is gone (see the domain-2 check below). It is
# kept, and hoisted, because the CR52-origin argument below depends on this
# address being domain 2's single static peer -- a reader checking that
# argument needs the value in front of them, not just in prose.
# shellcheck disable=SC2034
PEER=172.16.52.2
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
    # This mode's whole value is being unambiguous about WHAT ran, so the
    # absence of the bridge is asserted, not assumed. awf-oak-bridge.container
    # carries [Install] WantedBy=default.target, so it auto-enables and
    # starts at boot: without this check a Stage 1 PASS could be collected
    # on a board where the bridge was up and the CR52 was feeding
    # control_cmd into domain 1, which is precisely the reading this mode
    # exists to rule out.
    systemctl is-active --quiet awf-oak-bridge.service && fail "bridge_active" "AUTOWARE"
    # rpmsg-eth.service is deliberately NOT gated here. It only creates
    # tap0 and shuttles frames to the CR52's rpmsg endpoint; it joins no
    # DDS domain. With the bridge down no container joins domain 2, so the
    # CR52 cannot reach domain 1 whether or not the link is up, and the
    # isolation this mode asserts holds either way. Gating it would also
    # fail spuriously on a normal board, because the bridge unit's
    # Requires=rpmsg-eth.service starts the link at boot and stopping the
    # bridge does not stop it again.
    #
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
    [ "$mtu" = "$MTU" ] || fail "tap0_mtu=$mtu" "STACK"

    # Five topics domain 1 -> domain 2: present on domain 2.
    for t in /vehicle/status/steering_status /planning/scenario_planning/trajectory \
             /system/operation_mode/state /localization/kinematic_state \
             /localization/acceleration; do
        ros2dom "timeout 20 ros2 topic echo --once $t" >/dev/null \
            || fail "not_bridged_to_domain2:$t" "STACK"
    done

    # One topic domain 2 -> domain 1. Presence on domain 1 is necessary but
    # NOT sufficient evidence: a stray local publisher on domain 1 would
    # satisfy it just as well, so it is checked first and then backed by
    # the domain-2 check below.
    ros1 "timeout 20 ros2 topic echo --once /control/trajectory_follower/control_cmd" >/dev/null \
        || fail "no_control_cmd_on_domain1" "STACK"

    # The decisive check, the one the milestone turns on: the same topic
    # echoed ON DOMAIN 2, which only the CR52 can satisfy.
    #   - awf-oak-bridge SUBSCRIBES to control_cmd on domain 2 and
    #     republishes it on domain 1 (components/bridge/bridge-config.yaml);
    #     it never publishes it on domain 2.
    #   - domain 2 has AllowMulticast=false and exactly one static peer,
    #     $PEER, over tap0 (components/cyclonedds-x5h.xml), so there is no
    #     discovery path to anything else.
    #   - no other container joins domain 2.
    # So a sample arriving here came off the rpmsg-eth wire from the safety
    # island. This deliberately needs no tooling beyond what the stack
    # already runs: the previous form of this check shelled out to tcpdump,
    # which is absent from the board image, so it always yielded zero and
    # reported reason=control_cmd_not_from_cr52 -- a dead-link verdict on a
    # healthy stack, on the single check that proves the milestone.
    rx0=$(cat /sys/class/net/tap0/statistics/rx_packets 2>/dev/null)
    ros2dom "timeout 20 ros2 topic echo --once /control/trajectory_follower/control_cmd" >/dev/null \
        || fail "no_control_cmd_on_domain2" "STACK"
    rx1=$(cat /sys/class/net/tap0/statistics/rx_packets 2>/dev/null)

    # Corroboration, not the primary evidence: tap0 must actually have
    # received frames across that window, so a PASS carries a number the
    # operator can read rather than a bare assertion. Bounded by the echo
    # above -- no polling loop.
    for v in "$rx0" "$rx1"; do
        case "$v" in ''|*[!0-9]*) fail "no_tap0_counters" "STACK" ;; esac
    done
    n=$((rx1 - rx0))
    [ "$n" -ge 1 ] || fail "no_cr52_packets_on_tap0" "STACK"

    echo "X5H_STACK_PASS bridged=6 cr52_packets=$n"
    ;;
drive)
    check_units "$CORE_UNITS awf-oak-bridge" "DRIVE"
    # Guard before sourcing: under `set -u` a missing or truncated env file
    # makes the ${OUTPUT_DIRECTORY:?} below exit with a bare shell error and
    # NO marker at all, breaking the one-marker-per-invocation contract.
    [ -r "$ENVF" ] || fail "no_env_file" "DRIVE"
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
