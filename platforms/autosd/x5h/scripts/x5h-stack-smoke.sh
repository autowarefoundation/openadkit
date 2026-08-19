#!/bin/sh
# On-board smoke for the Open AD Kit stack (issue #120 M7).
# Runs ON the board. One terminal marker per invocation, judged by string
# match, following the repo's rpmsg-smoke.sh convention.
#
#   stack   -- units active, six bridged topics in the right direction,
#              control_cmd demonstrably sourced on the CR52
#   drive   -- cycle the stack, run the scenario once, report its junit
#   autoware-- domain 1 only: no bridge, no CR52. The Stage 1 isolation
#              hinge, so "Autoware does not run on this silicon" and "the
#              consolidation is misconfigured" cannot look alike.
#
# Output on stdout, grep-able, one item per line. Exactly one TERMINAL marker
# (a *_PASS or *_FAIL) is printed per invocation; the informational lines
# below are not markers and do not count against that:
#   X5H_AUTOWARE_MEM_KB=<n>   (informational, printed on the PASS path only,
#                              immediately before the marker -- MemAvailable
#                              at the moment Autoware was proven up)
#   X5H_AUTOWARE_PASS
#   X5H_AUTOWARE_FAIL reason=<...>
#   X5H_STACK_PASS bridged=6 cr52_packets=<n>
#   X5H_STACK_FAIL reason=<...>
#   X5H_DRIVE_PASS junit=<path> tests=<n> failures=<n> errors=<n>
#   X5H_DRIVE_FAIL reason=<...>
#
# WHAT X5H_DRIVE_PASS DOES AND DOES NOT ASSERT. It asserts that the stack was
# cycled, the scenario ran to completion, and a parseable junit result was
# produced -- nothing about its contents. The counts are printed on the
# marker line so a human can read the verdict; the script does not grade it.
# This is deliberate and it is not a gap to be closed casually: the reference
# demo's own recorded result for this scenario is errors="1" (an engage
# request refused because Autoware was still INITIALIZING), its run_after.sh
# never inspects the junit at all, and whether a green result is even
# reachable on this hardware is an open question. A pass/fail oracle invented
# here would either fail every healthy run or be tuned until it passed, and
# both are worse than reporting the number. When the human settles what a
# passing verdict looks like, that rule goes here.
#
# reason= vocabulary, per mode -- what an operator reads mid-session, so it
# is enumerated here rather than left to be reverse-engineered from the
# code:
#   any mode: unit_inactive:<unit>  a required unit is not active. NOTE this
#                                   also covers a unit systemd SKIPPED: both
#                                   map-consuming units carry
#                                   ConditionPathExists= on the two staged
#                                   map files, and an unmet condition is a
#                                   successful start job with an inactive
#                                   unit. Check the journal for the path.
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
#             stack_down            the stack would not stop
#             stack_up              the stack would not start
#             autoware_not_ready    /api/autoware/set/engage never appeared
#             scenario_start        the scenario unit failed to run
#             no_junit              the run produced no result.junit.xml
#             junit_unparsable      a junit file exists but its top-level
#                                   counts could not be read
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

# THE UNIT VOCABULARY. Three sets, and which unit is in which is the whole
# correctness argument of this script:
#
# CORE_UNITS is what "Autoware alone on domain 1" means -- one unit, because
# the nine componentized units collapsed into one monolithic container. It
# used to list seven component units AND awf-oak-simulator. That last name
# now means the SCENARIO RUNNER rather than tier4_simulator_component, so
# the Stage 1 isolation gate was requiring a scenario run to be active in
# order to pass, and (because a unit of that name still exists) it did so
# without erroring. That is the failure this vocabulary exists to prevent.
CORE_UNITS="awf-oak-autoware"
# The bridged stack. awf-oak-relay and awf-oak-restamp are LOAD-BEARING, not
# accessories: bridge-config.yaml routes the trajectory through traj_relay
# (domain 2's MTU 462 cannot carry a full trajectory) and control_cmd back
# through control_restamp (the CR52 stamps with its own uptime clock). With
# either one down, a completely healthy board fails
# not_bridged_to_domain2:/planning/scenario_planning/trajectory or
# no_control_cmd_on_domain1, and the failure points at the bridge.
STACK_UNITS="$CORE_UNITS awf-oak-bridge awf-oak-relay awf-oak-restamp"
# Never in a checked set, and never started except by `drive`. It has no
# [Install] section precisely so it cannot come up at boot, and it is
# Type=oneshot: after a run it sits "active (exited)", which is why no mode
# asserts anything about its state -- see the note in `autoware` below.
SCENARIO_UNIT=awf-oak-simulator
# Wall-clock bound on the wait for Autoware to answer, in seconds. A bound
# in seconds rather than a retry count because `drive` now cold-starts
# Autoware itself, so the per-probe cost is not constant: probes against a
# container that does not exist yet return instantly, probes against a
# starting one can block for the full timeout.
READY_TIMEOUT="${X5H_READY_TIMEOUT:-300}"

fail() { echo "X5H_${2}_FAIL reason=$1"; exit 1; }

ros1() { # run a ros2 command on domain 1 inside the Autoware container
    podman exec awf-oak-autoware bash -lc \
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
    # awf-oak-relay and awf-oak-restamp are deliberately NOT asserted either
    # way. Both are pure domain-1 <-> domain-2 plumbing driven by the
    # bridge's config; with the bridge down they publish to nothing, so they
    # cannot manufacture the trajectory or kinematic_state samples checked
    # below. Requiring them down would also make this mode unreachable on a
    # normal board, where they auto-enable at boot exactly as the bridge
    # does.
    #
    # $SCENARIO_UNIT is not asserted inactive either, and that is not an
    # oversight: RemainAfterExit=yes leaves it "active (exited)" after any
    # previous `drive` run, so an inactive-assertion would fail on a board
    # whose only sin is having been driven once. What matters for isolation
    # is the bridge, which is asserted above.
    #
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
    check_units "$STACK_UNITS" "STACK"
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
    #   - no other container joins domain 2. awf-oak-restamp republishes the
    #     bridge's output ON DOMAIN 1 and joins domain 2 not at all, so it
    #     cannot satisfy this check either.
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
    # Precondition, checked before anything is touched: this mode runs on a
    # stack that `stack` mode has already passed. A missing unit here is a
    # setup problem, and reporting it now is cheaper than reporting it after
    # a five-minute cycle.
    check_units "$STACK_UNITS" "DRIVE"
    # Guard before sourcing: under `set -u` a missing or truncated env file
    # makes the ${OUTPUT_DIRECTORY:?} below exit with a bare shell error and
    # NO marker at all, breaking the one-marker-per-invocation contract.
    [ -r "$ENVF" ] || fail "no_env_file" "DRIVE"
    # shellcheck disable=SC1090
    . "$ENVF"

    # A FULL STACK DOWN/UP, NOT `systemctl restart` OF THE SCENARIO UNIT.
    # This is the difference between two consecutive runs that mean
    # something and a second run that fails for a reason that has nothing to
    # do with the board.
    #
    # scenario_simulator_v2 is one-shot in a stronger sense than
    # Type=oneshot: it drives Autoware through a state machine, and it ends
    # by design at a fixed duration -- roughly 125 s of "timed out.
    # Forcibly inactivate", which is this scenario's NORMAL ending, not a
    # failure. What it leaves behind is an Autoware that has already been
    # routed and engaged and is sitting in a post-run state. Restarting only
    # the scenario against that leaves it in WAITING_FOR_ROUTE, and the
    # engage step never reproduces -- so run 2 fails while run 1 passed, on
    # an unchanged board. Established on the sister project's hardware; the
    # milestone requires two consecutive passing runs, so this is exactly
    # the case that would have been hit.
    #
    # The cost is real -- every `drive` pays a full Autoware cold start --
    # and is accepted, because it makes run N identical to run 1 by
    # construction.
    stop_list="${SCENARIO_UNIT}.service"
    for u in $STACK_UNITS; do stop_list="$stop_list ${u}.service"; done
    # One `systemctl stop` call, not a loop: systemd tears the transaction
    # down in dependency order, and the scenario unit is named first so an
    # in-flight run is not left publishing into a half-stopped stack.
    # shellcheck disable=SC2086
    systemctl stop $stop_list || fail "stack_down" "DRIVE"

    start_list=""
    for u in $STACK_UNITS; do start_list="$start_list ${u}.service"; done
    # Also one call: the units' After= edges (autoware and restamp after the
    # bridge, relay after both) put a single transaction in the right order,
    # which is the ordering the reference compose file expresses with
    # depends_on.
    # shellcheck disable=SC2086
    systemctl start $start_list || fail "stack_up" "DRIVE"
    # Re-checked after starting, and this is not belt-and-braces: an unmet
    # ConditionPathExists= (the staged map) makes `systemctl start` succeed
    # while leaving the unit inactive. Without this, a board with no map
    # would spend the whole READY_TIMEOUT below waiting for an Autoware that
    # was never started, then report autoware_not_ready -- which points at
    # the wrong thing entirely.
    check_units "$STACK_UNITS" "DRIVE"

    # Cleared after the cycle, not before: the stop above can still be
    # flushing a previous run's output when this mode is re-run quickly.
    rm -rf "${OUTPUT_DIRECTORY:?}"/* 2>/dev/null

    # Bounded wait for Autoware readiness. After= on the units only
    # guarantees the containers were started, not that Autoware itself is
    # up, and after the cold start above it will not be for a while. The
    # compose sample waits on this same API service before launching
    # scenario_test_runner.
    ready=0
    deadline=$(( $(date +%s) + READY_TIMEOUT ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        ros1 "timeout 5 ros2 service list" | grep -qFx '/api/autoware/set/engage' \
            && { ready=1; break; }
        sleep 2
    done
    [ "$ready" -eq 1 ] || fail "autoware_not_ready" "DRIVE"

    # `restart`, not `start`, even though the stop above already left this
    # unit inactive: RemainAfterExit=yes means a `start` on an
    # already-active unit returns immediately WITHOUT re-running ExecStart,
    # and this call must never be a no-op -- the output directory has just
    # been cleared, so a silent no-op would report no_junit on a healthy
    # stack. `restart` re-runs ExecStart regardless of prior state and still
    # blocks until the oneshot exits, so no is-active wait loop belongs
    # here. The run is bounded by the scenario's own GLOBAL_TIMEOUT.
    systemctl restart "${SCENARIO_UNIT}.service" || fail "scenario_start" "DRIVE"

    junit=$(find "${OUTPUT_DIRECTORY}" -name 'result.junit.xml' | head -1)
    [ -n "$junit" ] || fail "no_junit" "DRIVE"
    tests=$(grep -o 'tests="[0-9]*"' "$junit" | head -1 | tr -dc '0-9')
    fails=$(grep -o 'failures="[0-9]*"' "$junit" | head -1 | tr -dc '0-9')
    errs=$(grep -o 'errors="[0-9]*"' "$junit" | head -1 | tr -dc '0-9')
    # Reported, NOT graded -- see the header. The only failure mode left is
    # a junit whose top-level counts cannot be read at all, which means the
    # file is not the result document it is supposed to be and the numbers
    # below would be a fiction.
    for v in "$tests" "$fails" "$errs"; do
        case "$v" in ''|*[!0-9]*) fail "junit_unparsable" "DRIVE" ;; esac
    done
    echo "X5H_DRIVE_PASS junit=$junit tests=$tests failures=$fails errors=$errs"
    ;;
*)
    fail "usage" "STACK"
    ;;
esac
