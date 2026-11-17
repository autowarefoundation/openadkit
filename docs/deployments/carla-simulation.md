# CARLA Simulation

Run the full modular Autoware stack against CARLA 0.9.16 in closed loop.

## Requirements

- amd64 host with Ubuntu 22.04 or 24.04
- NVIDIA GPU with at least 8 GB of VRAM, 16 GB recommended, with the NVIDIA
  Container Toolkit and the OpenGL/Vulkan libraries that
  `openadkit setup --gpu` installs. The default sensors (LiDAR, IMU and GNSS)
  used about 4.5 GB in a measured run; cameras need more.
- ROS 2 Humble images; this deployment does not support Jazzy

Complete the [Quickstart](../getting-started/index.md) setup with GPU
support:

```bash
openadkit setup --gpu
```

## Run

```bash
openadkit run carla-simulation
```

`run` downloads and verifies the Town01 map, then starts CARLA and the Autoware
stack. CARLA renders offscreen by default. `run` returns once CARLA accepts
connections and the services stay up; this deployment declares no readiness
check of Autoware itself and is
[exempt from CI evidence](../releases/evidence.md#ci-exemptions).

To run Autoware and CARLA on separate hosts, see
[Split-host Simulation](split-host.md).

`config/sensor_mapping.yaml` enables LiDAR, IMU, and GNSS. Camera entries are
available but commented out.

## Drive

Open the [visualizer](index.md#open-the-visualizer). In RViz, set a goal with **2D Goal Pose** and select **Auto**.

## Stop and Recover

Run `stop` also after a failed start, to release the GPU. If autonomous mode is
unavailable, inspect `/system/command_mode/availability` and
`/diagnostics_graph/status`. See [Stop and Recover](index.md#stop-and-recover) for the rest.
