# Logging Simulation

Replay a demo rosbag through sensing, perception, and localization while map,
system, and visualization services provide the supporting runtime. An NVIDIA
GPU with at least 4 GB VRAM is strongly recommended; CPU operation is supported
but substantially slower.

## Setup

From an extracted release bundle or source checkout root:

```bash
./openadkit setup --verify
```

Use `./openadkit setup --gpu --verify` to install and verify the NVIDIA
Container Toolkit. GPU mode downloads the pinned CenterPoint models into
`~/autoware_data/lidar_centerpoint`; CPU mode uses clustering and does not
select those models.

--8<-- "includes/docker-group-activation.md"

The demo rosbag is Copyright 2020 TIER IV, Inc. It contains no camera images,
so traffic-light recognition is unavailable and object detection is less
complete than with a full recording.

## Start the Stack

```bash
./openadkit run logging-simulation
```

For NVIDIA acceleration:

```bash
./openadkit run logging-simulation --gpu
```

The CUDA image is amd64-only.
Add `--ros-distro jazzy` to either run command to select Jazzy; Humble is the
default.

--8<-- "includes/visualizer-remote-access.md"

## Play the Rosbag

The rosbag profile starts automatically with the deployment.

Playback waits for `ROSBAG_READY_TOPIC` for up to `ROSBAG_READY_TIMEOUT` seconds
before starting.

## Stop and Recover

```bash
./openadkit status logging-simulation
./openadkit logs logging-simulation --follow
./openadkit stop logging-simulation
```

The rosbag service uses a digest-pinned upstream `autoware:universe` image in a
release. Put local overrides in
`deployments/logging-simulation/config.local.env`. To replace missing sample
data, run `./openadkit fetch logging-simulation --force`. For common issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
