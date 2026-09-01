# CARLA Simulation

Run the full modular Autoware stack against CARLA 0.9.16 in closed loop.

## Requirements

Host (no ROS install required):

- amd64 and Ubuntu 22.04
- Docker with NVIDIA Container Toolkit
- NVIDIA GPU and Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`
- Host X access only for optional windowed rendering; offscreen mode is default

Container images use ROS 2 Humble (including the default
`sensing-perception-cuda` Autoware image). CARLA 0.9.16 uses Unreal Engine 4.26
and is not validated on Ubuntu 24.04.

## Setup

Install Docker and the NVIDIA toolkit once:

```bash
./openadkit setup --gpu --verify
```

--8<-- "includes/docker-group-activation.md"

CARLA is a curated CLI deployment in both source checkouts and the release
bundle. It is Humble-only and requires `--gpu`. Setup configures NVIDIA and the
DDS UDP buffers; `run` downloads the Town01 map.

## Run

```bash
./openadkit run carla-simulation --gpu
```

`run` checksum-validates the Town01 assets, starts CARLA and the modular stack,
and waits for Compose readiness. If startup fails after containers are created,
use the stop command below to release their GPU and host resources.

`sensor_mapping.yaml` enables LiDAR, IMU, and GNSS by default. Camera entries
are available but commented out.

--8<-- "includes/visualizer-remote-access.md"

Set a goal with **2D Goal Pose** and select **Auto** in RViz2. After the stack
is running, optional helpers can bake a local interface image or engage a
forward route:

```bash
./start-carla-e2e-demo.sh --drive
./start-carla-e2e-demo.sh --build
```

## Stop

```bash
./openadkit stop carla-simulation
```

If autonomous mode is unavailable, inspect `/system/command_mode/availability`
and `/diagnostics_graph/status` rather than overriding availability. For common
Docker, GPU, and visualizer issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
