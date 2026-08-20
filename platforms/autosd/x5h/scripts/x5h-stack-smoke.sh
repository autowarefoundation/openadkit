#!/bin/sh
# On-board smoke for the Open AD Kit stack (issue #120 M7).
# Runs ON the board. One terminal marker per invocation, judged by string
# match, following the repo's rpmsg-smoke.sh convention.
#
#   stack   -- units active, link at the frozen MTU, and control_cmd
#              demonstrably sourced on the CR52. Starts the scenario briefly,
#              because without an ego the CR52 emits nothing -- see the mode.
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
#   X5H_STACK_PASS cr52_control_cmd=1 cr52_packets=<n>
#   X5H_STACK_FAIL reason=<...>
#   X5H_DRIVE_PASS junit=<path> tests=<n> failures=<n> errors=<n> \
#                  mrm=succeeded stop_velocity=<v>
#   X5H_DRIVE_FAIL reason=<...>
#
# WHAT X5H_DRIVE_PASS ASSERTS. It asserts that the stack was cycled, the
# scenario ran to completion, a parseable junit result was produced, AND the
# MRM chain executed end to end:
#
#   fault injected -> operation-mode availability drops autonomous
#                  -> mrm_state reaches MRM_OPERATING with COMFORTABLE_STOP
#                  -> mrm_state reaches MRM_SUCCEEDED
#                  -> the gate's final commanded velocity is zero
#
# It deliberately does NOT grade the junit verdict, and that is now a
# measured decision rather than a deferred one (settled by the human
# 2026-08-19, with the board evidence in /var/log/awf/probe/). The junit
# CANNOT be green for this scenario by construction: the route is 156.8 m,
# the fault trigger sits ~81 m in, and a comfortable stop from 8.33 m/s
# consumes ~50 m, so the ego rests 25.5 m short of a goal whose
# ReachPositionCondition tolerance is 1 m. fault_injection latches the ERROR,
# availability never recovers, the MRM never cancels, and the scenario's own
# 180 s condition fires -- failures="1" at sim time 180.033, reproduced 4/4
# runs to 12 decimals. So failures="1" is the EXPECTED count on a healthy
# board, and the chain above is what "passing" means here. (The reference
# demo never got this far: its recorded junit is errors="1", an engage
# refused while Autoware was still INITIALIZING, and its run_after.sh never
# inspects the junit at all.)
#
# The chain is measured on domain 1 during the run (raw captures are left in
# $OUTPUT_DIRECTORY/drive-probe for the operator). The known-good stamps, for
# calibration: availability.autonomous false at fault+0.07 s, MRM_OPERATING/
# COMFORTABLE_STOP at +0.08 s, MRM_SUCCEEDED at +11.28 s.
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
#             no_operation_mode_state
#                                   no /system/operation_mode/state sample on
#                                   domain 1, i.e. Autoware itself is not live.
#                                   NOT a localization check: the ego pose
#                                   belongs to awf-oak-simulator, which this
#                                   mode deliberately does not start -- see the
#                                   comment on the assertion itself.
#             bridge_active         awf-oak-bridge is up, so this run is
#                                   NOT the unbridged domain-1-only case
#                                   this mode claims to measure
#   STACK:    usage                 unknown mode argument (also the
#                                   catch-all for a bad invocation)
#             rpmsg_eth_inactive    the CR52 link daemon is not running
#             tap0_mtu=<n>          tap0 is up at the wrong MTU
#             scenario_start        the scenario unit would not start, so no
#                                   ego could be brought up to give the CR52
#                                   something to follow
#             no_cr52_control_cmd   no sample on control_cmd_raw within
#                                   CR52_TIMEOUT. That name is published ONLY
#                                   by the bridge, carrying the CR52's
#                                   domain-2 control_cmd, so this means the
#                                   safety island produced nothing -- read the
#                                   CR52 console on ttyUSB1 next
#             no_tap0_counters      /sys/class/net/tap0/statistics is
#                                   unreadable, so the corroborating
#                                   packet delta could not be measured
#             no_cr52_packets_on_tap0
#                                   tap0 received nothing while the poll above
#                                   ran
#   DRIVE:    no_env_file           $ENVF missing/unreadable, so
#                                   OUTPUT_DIRECTORY cannot be resolved
#             stack_down            the stack would not stop
#             stack_up              the stack would not start
#             autoware_not_ready    /api/autoware/set/engage never appeared
#             scenario_start        the scenario unit failed to run
#             no_junit              the run produced no result.junit.xml. The
#                                   interpreter writes one only when it reaches
#                                   a VERDICT; if scenario_test_runner's
#                                   global_timeout preempts the scenario's own
#                                   exit conditions it writes NOTHING. So this
#                                   reason means "GLOBAL_TIMEOUT is too small",
#                                   not "the drive failed" -- see
#                                   awf-oak-x5h.env's GLOBAL_TIMEOUT note.
#             junit_unparsable      a junit file exists but its top-level
#                                   counts could not be read
#             mrm_no_fault_event    /simulation/events never carried the
#                                   scenario's cpu_temperature_is_high ERROR:
#                                   the ego never reached the trigger point
#                                   (lane 3238) or the interpreter never fired
#                                   the FaultInjectionAction
#             mrm_availability_never_dropped
#                                   the fault fired but
#                                   /system/operation_mode/availability never
#                                   showed autonomous: false -- the diagnostic
#                                   is not reaching the aggregator. NOTE the
#                                   wiring is a demo customization in this
#                                   image's diagnostics/perception.yaml (the
#                                   diag is named cpu_temperature_is_high, NOT
#                                   ": CPU Temperature"); check membership
#                                   with /diagnostics_graph/struct, never by
#                                   grepping yaml
#             mrm_no_comfortable_stop
#                                   availability dropped but mrm_state never
#                                   showed MRM_OPERATING with COMFORTABLE_STOP
#                                   (state 2, behavior 3)
#             mrm_never_succeeded   the MRM operated but never reached
#                                   MRM_SUCCEEDED with COMFORTABLE_STOP
#                                   (state 3, behavior 3) -- the stop did not
#                                   complete within the run
#             mrm_nonzero_final_velocity=<v>
#                                   the chain completed but the gate's last
#                                   commanded velocity was not zero
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
# The bridge's domain-1 name for the CR52's domain-2 control_cmd, set by
# `remap:` in components/bridge/bridge-config.yaml. The bridge is the ONLY
# publisher of this name on domain 1, which is what makes it proof of origin;
# the un-suffixed control_cmd is published locally by control_restamp.py and
# proves nothing about the CR52. Keep the two straight.
RAW_CMD=/control/trajectory_follower/control_cmd_raw
# How long `stack` waits for the CR52's first control_cmd after the scenario
# starts. It must cover the scenario's own initialisation before an ego exists
# (INITIALIZE_DURATION defaults to 90) plus the follower's first cycle, so it
# is deliberately larger than any single echo timeout in this script.
CR52_TIMEOUT="${X5H_CR52_TIMEOUT:-150}"

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
# either one down, a completely healthy board fails no_cr52_control_cmd: with
# the relay down the CR52 never receives a trajectory it can carry, and with
# restamp down control_cmd_raw still arrives but nothing rewrites it onto
# domain 1's clock. Either way the failure points at the bridge path.
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
    # A LIVE SAMPLE, and deliberately NOT /localization/kinematic_state.
    #
    # Three of the six bridged topics -- kinematic_state, steering_status and
    # localization/acceleration -- are published by scenario_simulator_v2's ego
    # entity in awf-oak-simulator, not by Autoware. awf-oak-autoware runs
    # planning_simulator.launch.xml with scenario_simulation:=true, and under
    # that flag the launch deliberately does NOT start a vehicle simulator of
    # its own, because the scenario runner owns the ego. Board-measured with
    # awf-oak-autoware alone (174 nodes up): kinematic_state has 0 publishers
    # and 29 subscribers, steering_status and localization/acceleration 0 each.
    #
    # So gating this mode on a kinematic_state sample was unsatisfiable BY
    # CONSTRUCTION -- Stage 1 exists precisely to run without the simulator, so
    # the one assertion could never pass, and it reported reason=no_kinematic_state
    # on a completely healthy stack. Indistinguishable, to an operator, from
    # Autoware failing to localize.
    #
    # /system/operation_mode/state is the right probe: it is also one of the six
    # bridged topics (so it stays load-bearing for Stage 2), its publisher is
    # Autoware's own operation mode transition manager, and it is up with
    # awf-oak-autoware alone -- board-measured, 1 publisher, sample received.
    # Asserting a SAMPLE rather than topic existence is what makes this liveness
    # rather than mere discovery: the trajectory check above is existence-only,
    # and existence alone is satisfied by any subscriber.
    ros1 "timeout 20 ros2 topic echo --once /system/operation_mode/state" >/dev/null \
        || fail "no_operation_mode_state" "AUTOWARE"
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

    # HOW THE SIX BRIDGED TOPICS ARE PROVEN, AND WHY NOT ONE ECHO PER TOPIC.
    #
    # The retired form of this check echoed each of the five domain 1 -> 2
    # topics ON DOMAIN 2, from a `ros2` process started inside the bridge
    # container. That instrument is structurally blind and its failures were
    # indistinguishable from a dead link. cyclonedds-x5h.xml gives domain 2
    # AllowMulticast=false and exactly ONE static peer, the CR52 -- so a
    # SECOND participant joining domain 2 has no discovery path to the
    # bridge's own domain-2 participant and cannot see anything the bridge
    # publishes there. Board-measured: all five topics reported
    # not_bridged_to_domain2 while tap0 simultaneously took 739 packets from
    # the CR52 on a stack that was working. The instrument before that one
    # was tcpdump, which is not in the board image at all (confirmed: no
    # tcpdump, no dnf, no rpm-ostree). Two instruments, both blind.
    #
    # What is used instead is the ONE observation that is both decisive and
    # made with a working instrument: a live control_cmd from the CR52,
    # observed on DOMAIN 1, where every container can see it.
    #
    # It proves BOTH directions at once, transitively:
    #   - 2 -> 1 directly. bridge-config.yaml lands the CR52's domain-2
    #     control_cmd on domain 1 under the REMAPPED name
    #     control/trajectory_follower/control_cmd_raw. The bridge is the only
    #     publisher of that name on domain 1 -- control_restamp.py subscribes
    #     to it and republishes the real topic -- so a sample on _raw came off
    #     the rpmsg-eth wire and nothing local can manufacture it. (Checking
    #     the real control_cmd instead would NOT prove this: restamp publishes
    #     that one locally.)
    #   - 1 -> 2 transitively. The CR52 runs the trajectory follower. It
    #     cannot emit control_cmd at all without having received the
    #     trajectory and the ego state over domain 2. So a control_cmd that
    #     exists is evidence the 1 -> 2 half delivered.
    #
    # WHY THIS MODE NOW STARTS THE SCENARIO. The ego -- and therefore
    # kinematic_state, steering_status and localization/acceleration -- is
    # published by scenario_simulator_v2, not by Autoware (see the `autoware`
    # mode's comment). With no ego the CR52 has nothing to follow and emits
    # nothing: board-measured, a full 25 s echo on _raw with the stack up and
    # no scenario running returned NOTHING, while tap0 still carried 237
    # discovery packets. So a pre-scenario X5H_STACK_PASS is not reachable by
    # any instrument, and this mode brings an ego into existence rather than
    # asserting something unsatisfiable.
    #
    # --no-block is required, not stylistic: the scenario unit is
    # Type=oneshot, so a plain `systemctl start` blocks until the whole run
    # finishes and there would be no live window left to observe.
    systemctl start --no-block "${SCENARIO_UNIT}.service" \
        || fail "scenario_start" "STACK"

    rx0=$(cat /sys/class/net/tap0/statistics/rx_packets 2>/dev/null)
    # Bounded poll rather than one long echo: the ego appears some way into
    # the scenario's initialisation, so the first echoes legitimately find
    # nothing. Deadline, not a retry count, so the wait is a stated duration.
    got=0
    deadline=$(( $(date +%s) + CR52_TIMEOUT ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if ros1 "timeout 10 ros2 topic echo --once $RAW_CMD" >/dev/null; then
            got=1; break
        fi
    done
    rx1=$(cat /sys/class/net/tap0/statistics/rx_packets 2>/dev/null)

    # Stopped before the verdict is printed, so this mode leaves the stack in
    # the state it found it in -- `drive` does its own full cycle and must not
    # inherit a half-run scenario.
    systemctl stop "${SCENARIO_UNIT}.service" >/dev/null 2>&1

    [ "$got" -eq 1 ] || fail "no_cr52_control_cmd" "STACK"

    for v in "$rx0" "$rx1"; do
        case "$v" in ''|*[!0-9]*) fail "no_tap0_counters" "STACK" ;; esac
    done
    n=$((rx1 - rx0))
    [ "$n" -ge 1 ] || fail "no_cr52_packets_on_tap0" "STACK"

    echo "X5H_STACK_PASS cr52_control_cmd=1 cr52_packets=$n"
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
    # by reaching one of the scenario's own exit conditions. What it leaves
    # behind is an Autoware that has already been
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

    # THE MRM-CHAIN CAPTURES, started before the scenario so the whole chain
    # is observed. All four topics live on domain 1 (nothing about the MRM is
    # bridged), so ros1 sees everything. PYTHONUNBUFFERED because these are
    # stopped by pkill after the run rather than by their own timeout, and a
    # block-buffered tail would lose exactly the samples the oracle needs.
    # The inner timeout is a backstop for a run that never ends.
    PROBE="${OUTPUT_DIRECTORY}/drive-probe"
    mkdir -p "$PROBE"
    ros1 "PYTHONUNBUFFERED=1 timeout $((${GLOBAL_TIMEOUT:-240} + 60)) ros2 topic echo /simulation/events" \
        > "$PROBE/events.txt" &
    ros1 "PYTHONUNBUFFERED=1 timeout $((${GLOBAL_TIMEOUT:-240} + 60)) ros2 topic echo /system/operation_mode/availability" \
        > "$PROBE/availability.txt" &
    ros1 "PYTHONUNBUFFERED=1 timeout $((${GLOBAL_TIMEOUT:-240} + 60)) ros2 topic echo /system/fail_safe/mrm_state" \
        > "$PROBE/mrm_state.txt" &
    ros1 "PYTHONUNBUFFERED=1 timeout $((${GLOBAL_TIMEOUT:-240} + 60)) ros2 topic echo /control/command/control_cmd --field longitudinal" \
        > "$PROBE/gate_cmd.txt" &

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
    # Counts reported, not graded -- see the header for why failures="1" is
    # the expected value. A junit whose top-level counts cannot be read at
    # all is still a failure: the file is not the result document it is
    # supposed to be and the numbers below would be a fiction.
    for v in "$tests" "$fails" "$errs"; do
        case "$v" in ''|*[!0-9]*) fail "junit_unparsable" "DRIVE" ;; esac
    done

    # End the captures. Everything the oracle needs happened before the
    # oneshot exited (MRM_SUCCEEDED lands ~11 s after the fault, the run ends
    # at 180 s), and PYTHONUNBUFFERED above means the files are already
    # current -- so kill rather than wait out the backstop timeout.
    podman exec awf-oak-autoware pkill -f "ros2 topic echo" >/dev/null 2>&1
    wait

    # THE MRM-CHAIN ORACLE, graded in causal order so the reason names the
    # EARLIEST break. Record-aware matching (RS="---") where two fields must
    # hold in the SAME sample: state 3 also occurs with behavior 2 during
    # post-run teardown, and a line-level grep would accept that.
    grep -q 'name: cpu_temperature_is_high' "$PROBE/events.txt" \
        || fail "mrm_no_fault_event" "DRIVE"
    grep -q '^autonomous: false' "$PROBE/availability.txt" \
        || fail "mrm_availability_never_dropped" "DRIVE"
    awk 'BEGIN{RS="---"} $0 ~ /(^|\n)state: 2(\n|$)/ && $0 ~ /(^|\n)behavior: 3(\n|$)/ {f=1} END{exit !f}' \
        "$PROBE/mrm_state.txt" || fail "mrm_no_comfortable_stop" "DRIVE"
    awk 'BEGIN{RS="---"} $0 ~ /(^|\n)state: 3(\n|$)/ && $0 ~ /(^|\n)behavior: 3(\n|$)/ {f=1} END{exit !f}' \
        "$PROBE/mrm_state.txt" || fail "mrm_never_succeeded" "DRIVE"
    stopv=$(grep '^velocity:' "$PROBE/gate_cmd.txt" | tail -1 | awk '{v=$2; print (v<0)?-v:v}')
    [ -n "$stopv" ] || fail "mrm_nonzero_final_velocity=none" "DRIVE"
    awk "BEGIN{exit !($stopv < 0.05)}" || fail "mrm_nonzero_final_velocity=$stopv" "DRIVE"

    echo "X5H_DRIVE_PASS junit=$junit tests=$tests failures=$fails errors=$errs mrm=succeeded stop_velocity=$stopv"
    ;;
*)
    fail "usage" "STACK"
    ;;
esac
