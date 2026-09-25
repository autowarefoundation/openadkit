# CARLA Simulation

Run the full modular Autoware stack against CARLA 0.9.16 in closed loop.

## Requirements

- amd64 host with Ubuntu 22.04 (CARLA 0.9.16 is not validated on 24.04)
- NVIDIA GPU with the Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`
- ROS 2 Humble images; this deployment does not support Jazzy

Install Docker and the NVIDIA toolkit once, as described in the
[Quickstart](../../getting-started/index.md), with GPU support:

```bash
openadkit setup --gpu --verify
```

## Run

--8<-- "includes/cli-command-context.md"

```bash
openadkit run carla-simulation --gpu
```

`run` downloads and verifies the Town01 map, then starts CARLA and the Autoware
stack. CARLA renders offscreen by default.

To run Autoware and CARLA on separate hosts, see
[Split-host simulation](../split-host.md).

`config/sensor_mapping.yaml` enables LiDAR, IMU, and GNSS. Camera entries are
available but commented out.

--8<-- "includes/visualizer-remote-access.md"

In RViz2, set a goal with **2D Goal Pose** and select **Auto**.

## Stop and Recover

```bash
openadkit stop carla-simulation
```

Run `stop` also after a failed start, to release the GPU. If autonomous mode is
unavailable, inspect `/system/command_mode/availability` and
`/diagnostics_graph/status`. For other issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
