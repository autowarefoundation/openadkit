# Logging Simulation

Replay a demo rosbag through sensing, perception, and localization. An NVIDIA
GPU with at least 4 GB VRAM is recommended; CPU mode works but is much slower.

Complete the [Quickstart](../../getting-started/index.md) setup first. For GPU
mode, run `openadkit setup --gpu --verify`.

## Run

--8<-- "includes/cli-command-context.md"

```bash
openadkit run logging-simulation         # CPU: clustering-based detection
openadkit run logging-simulation --gpu   # GPU: CenterPoint on CUDA (amd64 only)
```

--8<-- "includes/ros-distro.md"

`run` downloads the sample map and rosbag, and with `--gpu` also the CenterPoint
models (to `~/autoware_data/lidar_centerpoint`). The rosbag starts playing once
Autoware is ready.

The demo rosbag is Copyright 2020 TIER IV, Inc. It has no camera images, so
traffic-light recognition is unavailable and detection is less complete than
with a full recording.

--8<-- "includes/visualizer-remote-access.md"

## Stop and Recover

```bash
openadkit stop logging-simulation
```

To replace missing sample data, run `openadkit fetch logging-simulation --force`;
it also refreshes the CenterPoint models. For other issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
