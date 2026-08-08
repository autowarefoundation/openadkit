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

This standalone deployment requires a source checkout and is not included in
the unified release bundle or manifest-driven CLI. Setup configures the
required DDS UDP buffers; the launcher downloads the Town01 map.

## Run

```bash
cd deployments/carla-simulation
./start-carla-e2e-demo.sh
```

The entry point verifies Docker, NVIDIA, Vulkan, and UDP settings; downloads and
checksum-validates the Town01 assets; starts CARLA and the modular stack; and
checks localization, LiDAR, and the ego actor. If startup fails after containers
are created, use the stop command below to release their GPU and host resources.

`sensor_mapping.yaml` enables LiDAR, IMU, and GNSS by default. Camera entries
are available but commented out.

--8<-- "includes/visualizer-remote-access.md"

Set a goal with **2D Goal Pose** and select **Auto** in RViz2. To enable
automatic route selection, engagement, and movement verification, put this in
`deployments/carla-simulation/config.local.env` before running:

```dotenv
AUTOWARE_E2E_AUTO_DRIVE=true
```

## Stop

```bash
docker compose --env-file config.env down --remove-orphans
```

If autonomous mode is unavailable, inspect `/system/command_mode/availability`
and `/diagnostics_graph/status` rather than overriding availability. For common
Docker, GPU, and visualizer issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
