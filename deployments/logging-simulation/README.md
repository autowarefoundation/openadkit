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

The CLI downloads the map and rosbag selected by the manifest. CenterPoint
models are fetched only for `./openadkit run logging-simulation --gpu` or
`./openadkit fetch logging-simulation`. Add `--ros-distro jazzy` to select
Jazzy; Humble is the default.
