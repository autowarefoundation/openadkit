# Deployments

A deployment is a ready-to-run Autoware stack for one task. New users should
start with Planning Simulation.

| Deployment | Purpose | GPU |
|------------|---------|-----|
| [Planning Simulation](planning-simulation/index.md) | Plan and follow a route on a demo map | No |
| [Scenario Simulation](scenario-simulation/index.md) | Run predefined traffic scenarios | No |
| [Logging Simulation](logging-simulation/index.md) | Replay recorded sensor data through sensing, perception, and localization | Recommended |
| [CARLA Simulation](carla-simulation/index.md) | Drive a CARLA vehicle in closed loop | Required |
| [Zenoh Bridge](zenoh-bridge/index.md) | Split Autoware and visualization into separate ROS domains | No |

## Running a Deployment

Complete the [Quickstart](../getting-started/index.md) setup first.

--8<-- "includes/cli-command-context.md"

```bash
openadkit list
openadkit run planning-simulation
openadkit status planning-simulation
openadkit logs planning-simulation --follow
openadkit stop planning-simulation
```

- Add `--ros-distro jazzy` to `validate`, `fetch`, or `run` to select Jazzy;
  Humble is the default.
- Add `--gpu` for GPU mode. CARLA requires it and is Humble-only.
- Put local settings in `config.local.env`; see
  [Configuration](../getting-started/cli.md#configuration).

The Zenoh bridge is not managed by the CLI. It runs from a source checkout with
its own scripts; see its page.

To build your own stack, see [Custom Deployment](custom-deployment.md).
