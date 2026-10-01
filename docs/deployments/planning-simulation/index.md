# Planning Simulation

Run the Autoware planning and control stack on a demo map with the built-in
simulator, then set a route in browser-based RViz2. No GPU is required.

Complete the [Quickstart](../../getting-started/index.md) setup first.

## Run

--8<-- "includes/cli-command-context.md"

```bash
openadkit run planning-simulation
```

--8<-- "includes/ros-distro.md"

`run` downloads the sample map, pulls the images, and starts the stack. The demo
map is Copyright 2020 TIER IV, Inc. and is provided for demonstration only.

--8<-- "includes/visualizer-remote-access.md"

In RViz2, set an initial pose and a goal pose, then watch the vehicle drive the
route. See the
[Autoware planning simulation guide](https://autowarefoundation.github.io/autoware-documentation/main/demos/planning-sim/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle)
for details.

## Stop and Recover

```bash
openadkit stop planning-simulation
```

To replace missing or incomplete map data, run
`openadkit fetch planning-simulation --force`. For other issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
