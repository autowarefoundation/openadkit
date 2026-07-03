# Open AD Kit — Remaining Issue

## Missing `/system/command_mode/availability` Publisher (UNFIXED — upstream)

`diagnostic_graph_aggregator`'s `aggregator_node` should publish `/system/command_mode/availability` based on component health states, but it does not start in the system container. Without this topic, RViz never enables the "Auto" button because the upstream converter and AD API nodes see no availability data.

This is an **upstream Autoware issue** — the `diagnostic_graph_aggregator` comes from `autoware_universe/system` and its launch integration is not owned by this repository. A fix requires either:

- Debugging why `aggregator_node` fails to launch inside the container
- Enabling `command_mode_switcher` + `command_mode_decider` via `use_control_command_gate=true` in `tier4_system_launch`

**Workaround** (manual `ros2 topic pub` inside the system container):

```bash
ros2 topic pub --once /system/command_mode/availability \
  tier4_system_msgs/msg/CommandModeAvailability \
  '{items: [{mode: 1001, available: true}, {mode: 1002, available: true}, \
            {mode: 1003, available: true}, {mode: 1004, available: true}]}'
```

All other issues found during this audit have been fixed in code. This is the only remaining blocker.
