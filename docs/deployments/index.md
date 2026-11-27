# Deployments

A deployment is a ready-to-run Autoware stack for one task. The deployments a
release ships are its catalog. New users should start with Planning Simulation.

| Deployment | Purpose | GPU | Architectures | CI evidence |
|------------|---------|-----|---------------|-------------|
| [Planning Simulation](planning-simulation.md) | Plan and follow a route on a sample map with the built-in simulator; `--gpu` plans with the Diffusion Planner | Optional | amd64, arm64 | Yes, in CPU mode |
| [Scenario Simulation](scenario-simulation.md) | Run predefined traffic scenarios in Scenario Simulator | No | amd64, arm64 | Yes |
| [Logging Simulation](logging-simulation.md) | Replay recorded sensor data through sensing, perception and localization | Optional | amd64, arm64 | Yes, in CPU mode |
| [CARLA Simulation](carla-simulation.md) | Drive in closed loop with the CARLA simulator | Required | amd64 | Exempt |
| [Safety Island Simulation](safety-island-simulation.md) | Planning Simulation driven by the [Autoware Safety Island](https://autowarefoundation.github.io/autoware-safety-island/) controller | No | amd64 | Yes |
| [Safety Island HIL Simulation](safety-island-hil-simulation.md) | Safety Island Simulation with the Safety Island on Arm Virtual Hardware, an FVP or a board | No | amd64, arm64 | Exempt |

All run on Humble and Jazzy except CARLA Simulation, which is Humble-only, and
the GPU modes are amd64-only. **CI evidence** says whether a release runs the
deployment end to end before it ships; an exempt deployment ships without that
check. Evidence runs on every architecture the deployment supports. See the
[Evidence Policy](../releases/evidence.md).

Scenario and CARLA Simulation can also run as
[split-host](split-host.md) roles, with Autoware on one host and the simulator
on another over Zenoh (experimental).

## Every Deployment

Complete the [Quickstart](../getting-started/index.md) setup first, with
`openadkit setup --gpu` for a GPU mode.

```bash
openadkit list
openadkit run planning-simulation
openadkit status
openadkit logs --follow
openadkit stop
```

- Add `--ros-distro jazzy` to `validate`, `run` or `build` to select Jazzy;
  Humble is the default. `fetch` takes no distro: the data is the same for both.
- Add `--gpu` for the optional GPU mode of Planning Simulation (the Diffusion
  Planner) or Logging Simulation (CenterPoint). CARLA needs a GPU, so its GPU
  mode turns on by itself.
- Put host settings in `~/.config/openadkit/<deployment>.env`; see
  [Settings](../getting-started/cli.md#settings).

[CLI & Maintenance](../getting-started/cli.md) covers the other commands, and
[Troubleshooting](../getting-started/troubleshooting.md) what goes wrong.

### Open the Visualizer

--8<-- "includes/visualizer-remote-access.md"

## Your Own Kit

Start a kit with `openadkit new` ([Create a Kit](../kits/create-a-kit.md)). It
is your own project: it runs one or more of these deployments with your
vehicle's files on top, without copying them, and keeps only your differences. The
[Kit Guide](../kits/kit-guide.md) is the reference for every
extension point.
