# Planning Simulation

Run the Autoware planning and control stack against a demo point cloud map,
then set an initial pose and goal in browser-based RViz2. No GPU is required or
selected by this deployment.

## Run

From an extracted release bundle or source checkout root:

```bash
./openadkit setup --verify
./openadkit run planning-simulation
```

Add `--ros-distro jazzy` to select Jazzy; Humble is the default.

The entry point downloads and verifies the sample map, pulls missing images,
starts the stack, and checks that its persistent services are running. Release
image references are digest-pinned.

The demo map is Copyright 2020 TIER IV, Inc. and is provided for demonstration
only.

--8<-- "includes/visualizer-remote-access.md"

In RViz2, set the initial pose, set a goal pose, and observe the planned route.
See the [Autoware planning simulation guide](https://autowarefoundation.github.io/autoware-documentation/main/demos/planning-sim/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle)
for the RViz workflow.

## Stop and Recover

```bash
./openadkit status planning-simulation
./openadkit logs planning-simulation --follow
./openadkit stop planning-simulation
./openadkit stop planning-simulation
```

Put local overrides in
`deployments/planning-simulation/config.local.env`. To replace missing or
incomplete map data, run `./openadkit fetch planning-simulation --force`. For
common Docker and visualizer issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
