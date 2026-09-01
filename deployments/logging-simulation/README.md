# Logging Simulation

Replays recorded sensor data through the Autoware sensing, perception, and
localization stack. Install the host dependencies as described in the
[canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/logging-simulation/)
before starting.

```bash
cd ../..
./openadkit run logging-simulation
```

GPU:

```bash
cd ../..
./openadkit setup --gpu --verify
./openadkit run logging-simulation --gpu
```

The CLI downloads the map, rosbag, and pinned GPU models selected by the
manifest. Add `--ros-distro jazzy` to select Jazzy; Humble is the default.
