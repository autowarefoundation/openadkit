# Logging Simulation

Replays recorded sensor data through Autoware's sensing, perception and
localization. See the
[canonical documentation](https://autowarefoundation.github.io/openadkit/deployments/logging-simulation/).

```bash
cd ../..
./openadkit run logging-simulation
```

GPU:

```bash
cd ../..
./openadkit setup --gpu
./openadkit run logging-simulation --gpu
```

The CLI downloads the map and rosbag selected by the manifest. CenterPoint
models are fetched only for `./openadkit run logging-simulation --gpu` or
`./openadkit fetch logging-simulation`. Add `--ros-distro jazzy` to select
Jazzy; Humble is the default.
