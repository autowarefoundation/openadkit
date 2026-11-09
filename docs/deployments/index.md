# Deployments

A deployment is a ready-to-run Autoware stack for one task. New users should
start with Planning Simulation.

| Deployment | Purpose | GPU |
|------------|---------|-----|
| [Planning Simulation](planning-simulation/index.md) | Plan and follow a route on a demo map | No |
| [Scenario Simulation](scenario-simulation/index.md) | Run predefined traffic scenarios | No |
| [Logging Simulation](logging-simulation/index.md) | Replay recorded sensor data through sensing, perception, and localization | Recommended |
| [CARLA Simulation](carla-simulation/index.md) | Drive a CARLA vehicle in closed loop | Required |
| [Split-host simulation](split-host.md) | Run Autoware on one host and the simulator on another over Zenoh | CARLA only |
| [Safety Island Simulation](https://github.com/autowarefoundation/openadkit/tree/main/deployments/safety-island-simulation) | Planning Simulation driven by the [Autoware Safety Island](https://autowarefoundation.github.io/autoware-safety-island/) controller instead of Autoware's trajectory follower | No |

## Running a Deployment

Complete the [Quickstart](../getting-started/index.md) setup first.

--8<-- "includes/cli-command-context.md"

```bash
openadkit list
openadkit run planning-simulation
openadkit status
openadkit logs --follow
openadkit stop
```

- Add `--ros-distro jazzy` to `validate`, `fetch`, or `run` to select Jazzy;
  Humble is the default.
- Add `--gpu` for the optional GPU mode of Logging Simulation. CARLA needs a GPU,
  so its GPU mode turns on by itself; it is Humble-only.
- Add `--node` to `validate` or `run` to start one node of a
  [split-host](split-host.md) run. `status`, `logs`, and `stop` find the
  running node themselves; they take `--node` only when several nodes of one
  deployment run on the same machine.
- Put host settings in `~/.config/openadkit/<name>.env`; see
  [Configuration](../getting-started/cli.md#configuration).

Scenario split-node evidence covers two isolated nodes on one hosted runner.
CARLA is explicitly exempt from hosted runtime CI. Neither is a claim of
arbitrary two-machine or vehicle compatibility; see the
[evidence policy](../releases/evidence.md).

To build your own stack, start a kit with `openadkit new` ([Custom
Deployment](custom-deployment.md)). It keeps its own kit manifest and
deployment in one directory, extending a deployment without copying it.
