# Safety Island CARLA Simulation

Run CARLA and the modular Autoware stack with the Safety Island as the
controller. Final actuation leaves the stack over classic CAN instead of the
CARLA interface applying control directly.

## Requirements

Host (no ROS install required):

- amd64 and Ubuntu 22.04
- Docker with NVIDIA Container Toolkit
- NVIDIA GPU and Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`
- An `autoware-safety-island` checkout for the Safety Island binary and the
  host CAN bridge

Container images use ROS 2 Humble. CARLA 0.9.16 uses Unreal Engine 4.26 and
is not validated on Ubuntu 24.04.

## Setup

--8<-- "includes/cli-command-context.md"

Install Docker and the NVIDIA toolkit once:

```bash
openadkit setup --gpu --verify
```

--8<-- "includes/docker-group-activation.md"

CARLA requires `--gpu`. `run` downloads the Town01 map. The image references
in this deployment's `config.env` are digest-pinned.

## Run

```bash
openadkit run safety-island-carla-simulation --gpu
```

The deployment starts CARLA, a sensors-only `autoware_carla_interface`, and
the loopback domain-bridge. Autoware keeps computing trajectories so
Auto/Engage works, but the Safety Island CAN path is the only actuator.

Then follow the Safety Island
[closed-loop guide](https://github.com/autowarefoundation/autoware-safety-island/blob/main/documentation/user_guide/can_carla_closed_loop.rst):
bring up `vcan0`, run `freertos-posix --control-output CAN_ONLY`, and start
`demo/can_carla_bridge/bridge.py --ego-role ego_vehicle`.

--8<-- "includes/visualizer-remote-access.md"

Do not pass `--drive`, and do not start `carla-simulation` first and recreate
`carla-interface`. Set a goal with **2D Goal Pose** and select **Auto** in
RViz2 after the CAN path is live.

For Zephyr FVP TAP, add the deployment's `docker-compose.fvp.yaml` overlay so
the domain-bridge's domain 2 binds to `tap0`.

## Stop

```bash
openadkit stop safety-island-carla-simulation
```

If autonomous mode is unavailable, inspect the Safety Island bridge and
`candump vcan0` before overriding availability. For common Docker, GPU, and
visualizer issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).