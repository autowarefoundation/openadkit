# Planning Simulation

Runs the Autoware planning and control stack with a pre-recorded point cloud
map and the dummy simulator. Checkout assets live under
`deployments/planning-simulation/`.

## Prerequisites

- Host setup via [Getting Started](../../../getting-started/index.md)
- Sample map:

```bash
./openadkit fetch planning-simulation
```

## Run

From a source checkout:

```bash
./openadkit run planning-simulation
```

Open the visualizer at `https://localhost:6080/vnc.html` (accept the
self-signed certificate). Use `REMOTE_PASSWORD` from `config.env`.

Then follow the [Autoware planning simulation instructions](https://autowarefoundation.github.io/autoware-documentation/main/demos/planning-sim/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle)
to set an initial pose and engage.

Smoke-test compose without starting containers:

```bash
./openadkit validate planning-simulation
```

## Stop

```bash
./openadkit stop planning-simulation
```

## Notes

- `config.env` is the complete Compose configuration for this deployment.
- `map-check` fails fast if `MAP_PATH` is missing `lanelet2_map.osm` /
  `pointcloud_map.pcd` — run `./openadkit fetch planning-simulation` first.
- Single-stack per host (`network_mode: host`; `ROS_DOMAIN_ID=1` in `base/runtime.env`).
