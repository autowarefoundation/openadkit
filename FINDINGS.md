# Open AD Kit Planning-Simulation Findings

## Summary

Three issues block the planning-simulation deployment from running
end-to-end without manual intervention. Two are fixed in committed code
(image rebuild needed); one is a missing system node that requires a
code-level fix or a workaround in the compose file.

---

## Issue 1: Hardcoded Monolithic Build Paths (FIXED)

**Root cause:** `deployments/base/docker-compose.yaml` used paths like
`/opt/autoware/share/<pkg>/...` which match the legacy monolithic colcon
install layout. Our component-based build installs each package under its
own prefix: `/opt/autoware/<pkg>/share/<pkg>/...`.

**Symptom:** Simulator launch immediately crashes with:
```
[Errno 2] No such file or directory: '/opt/autoware/share/sample_vehicle_description/config/vehicle_info.param.yaml'
```
This sends SIGINT to all sub-processes before the occupancy_grid_map
container's `load_node` service registers, causing a secondary Python
`InvalidHandle` crash in `load_composable_nodes.py`.

**Fix (commit 5ebd3d3):** Updated three paths in
`deployments/base/docker-compose.yaml`:
- `raw_vehicle_cmd_converter_param_path` (vehicle + simulator services)
- `vehicle_info_param_file` (simulator service)

---

## Issue 2: vehicle_cmd_gate Emergency Heartbeat Deadlock (FIXED)

**Root cause:** `vehicle_cmd_gate` has `use_emergency_handling: true` by
default, which makes it wait for a system emergency heartbeat
(`/system/emergency/control_cmd`) that the MRM handler never publishes
during normal operation. This creates a circular deadlock:

```
vehicle_cmd_gate waits for emergency heartbeat
  → won't publish /control/command/control_cmd
    → topic_state_monitor reports ERROR diagnostic
      → autonomous mode unavailable
        → MRM handler can't proceed → no heartbeat published
          → back to start
```

**Symptom:** `vehicle_cmd_gate` stays at "waiting topics..." and
`emergency_state_heartbeat_received_time_ is false` forever. The
`control/command/control_cmd` topic is never published.

**Fix (commit e4e9243):** Set `use_emergency_handling: false` in both
config files via `sed` in `components/planning-control/Dockerfile`:
- `/opt/autoware/autoware_vehicle_cmd_gate/share/autoware_vehicle_cmd_gate/config/vehicle_cmd_gate.param.yaml`
- `/opt/autoware/autoware_launch/share/autoware_launch/config/control/vehicle_cmd_gate/vehicle_cmd_gate.param.yaml`

**Runtime workaround:** `ros2 param set /control/vehicle_cmd_gate use_emergency_handling false`

---

## Issue 3: Missing /system/command_mode/availability Publisher (UNFIXED)

**Root cause:** The `diagnostic_graph_aggregator`'s `aggregator_node` is
supposed to publish `/system/command_mode/availability` based on
component states, but it is NOT running in the system container for
unknown reasons. Without this topic:

1. `/system/converter` (which subscribes to it) never publishes
   `/system/operation_mode/availability`
2. AD API's `/adapi/node/operation_mode` (which subscribes to that)
   reports `is_autonomous_mode_available: false`
3. RViz "Auto" button is unavailable

**Symptom:** `ros2 topic info /system/command_mode/availability` shows
`Publisher count: 0, Subscription count: 1`.

**Evidence:**
- `/system/converter` IS running (subscribes to `/system/command_mode/availability`,
  publishes `/system/operation_mode/availability`)
- Converter param maps mode IDs: stop=1001, autonomous=1002, local=1003, remote=1004
- Publishing a valid `CommandModeAvailability` message with these IDs
  immediately makes `is_autonomous_mode_available: true` on the AD API

**Runtime workaround:**
```bash
ros2 topic pub --once /system/command_mode/availability \
  tier4_system_msgs/msg/CommandModeAvailability \
  "{items: [{mode: 1001, available: true}, {mode: 1002, available: true}, \
            {mode: 1003, available: true}, {mode: 1004, available: true}]}"
```

**Possible permanent fixes:**
1. Fix the `aggregator_node` so it starts correctly
2. Set `use_control_command_gate=true` in
   `tier4_system_launch/launch/system.launch.xml` to enable
   `command_mode_switcher` + `command_mode_decider` (which publish this topic)
3. Add a periodic `ros2 topic pub` in the compose command for the system service
4. Write a simple monitoring node that publishes based on component states

---

## Issue 4: Pose Initializer /initialpose3d Publication (OBSERVED WORKING)

**Previous concern:** Thought the pose_initializer wasn't publishing to
`/initialpose3d` after the `InitializeLocalization` service call.

**Actual behavior:** It DOES work. The flow is:
1. RViz publishes `/initialpose`
2. `initial_pose_adaptor` receives it, adjusts Z via map height fitter
3. Adaptor calls `/api/localization/initialize` (async)
4. AD API forwards to pose_initializer with `method=AUTO`
5. Pose initializer publishes to `pose_reset` → remapped to `/initialpose3d`
6. `simple_planning_simulator` receives it and starts publishing odometry

**The earlier "failure" was a timing issue in diagnostics.** When
checking `/initialpose3d` immediately after publishing `/initialpose`,
the service chain hadn't completed yet. Waiting a few seconds shows the
message arrives with Z correctly adjusted by the map height fitter
(e.g., 19.3 → 19.3201).

No fix needed.

---

## Files Changed

| File | Change |
|------|--------|
| `deployments/base/cyclonedds.xml` | Added `<Domain><General><NetworkInterfaceAddress>eth0` |
| `deployments/base/docker-compose.yaml` | Fixed monolithic build paths (3 occurrences) |
| `components/planning-control/Dockerfile` | Added `sed` to set `use_emergency_handling=false` |
| `components/universe-common/Dockerfile` | Added `autoware_launch` dependency |
| `components/vehicle-system/Dockerfile` | Added sensor/vehicle description packages |
| `components/planning-control/Dockerfile` | Added `sample_vehicle_description` |
| `components/simulator/Dockerfile` | Added `sample_vehicle_description`, `tier4_perception_launch` |

---

## End-to-End Startup Sequence (Manual)

To get the planning-simulation deployment driving:

```bash
# 1. Launch
docker compose -f deployments/planning-simulation/docker-compose.yaml \
  --env-file deployments/base/base.env \
  --env-file deployments/planning-simulation/planning-simulation.env up -d

# 2. Wait for all containers (35s)
sleep 35

# 3. User sets 2D Pose Estimate + 2D Nav Goal in RViz (http://<host>:6080/vnc.html)

# 4. Fix vehicle_cmd_gate deadlock
docker exec autoware-control bash -c "source /opt/ros/humble/setup.bash; \
  source /opt/autoware/setup.bash; \
  ros2 param set /control/vehicle_cmd_gate use_emergency_handling false"

# 5. Fix autonomous mode availability
docker exec autoware-system bash -c "source /opt/ros/humble/setup.bash; \
  source /opt/autoware/setup.bash; \
  ros2 topic pub --once /system/command_mode/availability \
  tier4_system_msgs/msg/CommandModeAvailability \
  '{items: [{mode: 1001, available: true}, {mode: 1002, available: true}, \
            {mode: 1003, available: true}, {mode: 1004, available: true}]}'"

# 6. Wait for route computation (5s)
sleep 5

# 7. Engage
docker exec autoware-simulator bash -c "source /opt/ros/humble/setup.bash; \
  source /opt/autoware/setup.bash; \
  ros2 service call /api/autoware/set/engage tier4_external_api_msgs/srv/Engage \
  '{engage: true}'"
```
