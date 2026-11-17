# Safety Island Simulation

Planning Simulation driven by the
[Autoware Safety Island](https://autowarefoundation.github.io/autoware-safety-island/)
instead of Autoware's own trajectory follower. Autoware runs on DDS domain 1,
the Safety Island on domain 2, and
[`domain_bridge`](https://github.com/ros2/domain_bridge) connects them. No GPU
is required.

## Requirements

- amd64 host: the pinned Safety Island release ships a `linux/amd64` binary.
- No GPU mode: the deployment's diagnostics graph belongs to the rule-based
  planner. `validate` and `run` refuse arm64 and `--gpu`.

## Run

```bash
openadkit run safety-island-simulation
```

`run` downloads the sample map and the pinned Safety Island release, then
starts Planning Simulation's services and two more:

| Service | What it runs |
|---------|--------------|
| `safety-island` | The release's actuation binary (FreeRTOS on POSIX) |
| `safety-island-bridge` | `domain_bridge` between the two domains, with the release's `bridge-config.yaml` topic contract |

Autoware's trajectory follower is switched off, so the control command comes
from the Safety Island alone. `run` returns once the bridge's healthcheck
confirms it: the command's only publisher is the bridge, and the follower is
not running.

Two messages are expected:

- `run` warns that a config override adds `autoware-safety-island.yaml`, which
  `autoware_launch` does not have. The file is new: Autoware's main diagnostics
  graph without the follower's diagnostics.
- The `safety-island` container logs `Waiting for ... data` until localization
  is initialized.

## Drive

Open the [visualizer](index.md#open-the-visualizer). In RViz, set an initial pose and a goal pose, then engage. The vehicle follows
the Safety Island's control command.

## Verify

```bash
openadkit run safety-island-simulation --verify
```

`--verify` runs the same drive-to-goal check as Planning Simulation, as the
deployment's evidence cells do on Humble and Jazzy.
