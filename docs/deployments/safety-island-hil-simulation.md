# Safety Island HIL Simulation

Planning Simulation driven by an
[Autoware Safety Island](https://autowarefoundation.github.io/autoware-safety-island/)
that runs outside Open AD Kit: on Arm Virtual Hardware (AVH), an FVP or a
board. It is [Safety Island Simulation](safety-island-simulation.md) with the
Safety Island in the loop on its own platform instead of in a container.
Autoware runs on DDS domain 1, the Safety Island on domain 2, and
[`domain_bridge`](https://github.com/ros2/domain_bridge) connects them over the
interface that reaches the Safety Island. No GPU is required.

![Safety Island HIL Simulation runs localization-mapping, planning, control, vehicle-system, simulator, Safety Island and visualizer, which talk over ROS 2](../assets/images/deployment-safety-island-hil-simulation-light.svg#only-light)
![Safety Island HIL Simulation runs localization-mapping, planning, control, vehicle-system, simulator, Safety Island and visualizer, which talk over ROS 2](../assets/images/deployment-safety-island-hil-simulation-dark.svg#only-dark)

## Requirements

- A Safety Island on DDS domain 2 that this host reaches over one network
  interface: `tap0` for AVH (over its VPN) and for an FVP, or the network
  interface on the board's network. The
  [Safety Island documentation](https://autowarefoundation.github.io/autoware-safety-island/)
  covers building and starting it on each platform.
- amd64 or arm64: no Safety Island binary is downloaded.
- No GPU mode: the deployment's diagnostics graph belongs to the rule-based
  planner. `validate` and `run` refuse `--gpu`.
- No CI evidence: the runners have no Safety Island, so a release ships this
  deployment without running it end to end.

## Settings

The bridge's domain 2 uses `SAFETY_ISLAND_DDS_INTERFACE`, `tap0` by default.
For a board, name its interface in the
[host settings file](../getting-started/cli.md#settings),
`~/.config/openadkit/safety-island-hil-simulation.env`:

```bash
SAFETY_ISLAND_DDS_INTERFACE=enp3s0
```

Domain 1 stays on the stack's interface, `lo` unless the host settings file
sets `CYCLONEDDS_NETWORK_INTERFACE`, so Autoware's own traffic does not reach
the Safety Island's network.

## Run

Start the Safety Island, then:

```bash
openadkit run safety-island-hil-simulation
```

`run` downloads the sample map and the pinned Safety Island release's bridge
contract, then starts Planning Simulation's services and one more:

| Service | What it runs |
|---------|--------------|
| `safety-island-bridge` | `domain_bridge` between the two domains, with the release's `bridge-config.yaml` topic contract and `cyclonedds-domain2.xml` DDS setting |

Autoware's trajectory follower is switched off, so the control command comes
from the Safety Island alone. `run` returns once the bridge's healthcheck
confirms it: the command's only publisher is the bridge, and the follower is
not running. That needs the Safety Island running and reachable; if it is not
within ten minutes, `run` fails.

`run` warns that a config override adds `autoware-safety-island.yaml`, which
`autoware_launch` does not have. The file is new: Autoware's main diagnostics
graph without the follower's diagnostics.

## Drive

Open the [visualizer](index.md#open-the-visualizer). In RViz, set an initial
pose and a goal pose, then engage. The vehicle follows the Safety Island's
control command.

## Verify

```bash
openadkit run safety-island-hil-simulation --verify
```

`--verify` runs the same drive-to-goal check as Planning Simulation, with the
Safety Island on its platform producing the control command.

## Troubleshooting

If `run` times out waiting for `safety-island-bridge`:

- Check that `SAFETY_ISLAND_DDS_INTERFACE` names an interface that exists and is
  up on this host, and that the Safety Island's own network settings point at
  this host on it.
- `openadkit shell safety-island-bridge ros2 topic info --verbose /control/trajectory_follower/control_cmd`
  shows who publishes the control command on domain 1; the healthcheck waits
  for the bridge to be its only publisher, which happens once the Safety
  Island publishes on domain 2.
