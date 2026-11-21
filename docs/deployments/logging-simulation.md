# Logging Simulation

Replay a sample rosbag through sensing, perception and localization. An NVIDIA
GPU with at least 4 GB of VRAM is recommended; CPU mode detects objects by
clustering instead of CenterPoint.

![Logging Simulation runs sensing-perception, localization-mapping, vehicle-system, rosbag and visualizer, which talk over ROS 2](../assets/images/deployment-logging-simulation-light.svg#only-light)
![Logging Simulation runs sensing-perception, localization-mapping, vehicle-system, rosbag and visualizer, which talk over ROS 2](../assets/images/deployment-logging-simulation-dark.svg#only-dark)

## Run

```bash
openadkit run logging-simulation         # CPU: clustering-based detection
openadkit run logging-simulation --gpu   # GPU: CenterPoint on CUDA (amd64 only)
```

`run` downloads the sample map and rosbag, and with `--gpu` also the CenterPoint
models (to `~/autoware_data/lidar_centerpoint`). The rosbag starts playing once
sensing subscribes to its LiDAR topic, at 0.4× speed (`ROSBAG_RATE`), and plays
once: `openadkit restart rosbag` plays it again.

`run` returns once the stack is ready: the services stay up and the AD API can
initialize localization. `openadkit run logging-simulation --verify` then
follows the replay: it passes once localization is initialized and the pose and
the tracked objects keep arriving. Every release runs that check in CPU mode;
the GPU mode is checked by hand on a GPU host.

The sample rosbag is Copyright 2020 TIER IV, Inc. It has no camera images, so
traffic-light recognition is unavailable and detection is less complete than
with a full recording.

## Your Own Recording

Point `ROSBAG_PATH` at a rosbag directory, the one that holds `metadata.yaml`,
in your [host settings file](../getting-started/cli.md#settings) or in a kit's
`settings.env`:

```bash
ROSBAG_PATH=$HOME/recordings/my-drive
ROSBAG_FORMAT=mcap                              # sqlite3 by default
ROSBAG_READY_TOPIC=/sensing/lidar/top/pointcloud_raw_ex
```

The CLI uses a directory that holds your files as it is: it never checks it,
downloads into it, replaces it or removes it. The recording starts once something
subscribes to `ROSBAG_READY_TOPIC`, so name a topic of yours that sensing
reads. A recording of another vehicle needs that vehicle's map (`MAP_PATH`)
and its vehicle and sensor kit packages, which a
[kit](../kits/new-vehicle.md) holds.
