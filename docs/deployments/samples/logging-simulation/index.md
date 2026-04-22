# Autoware Open AD Kit Logging Simulation

This sample deployment demonstrates the Open AD Kit logging simulation workflow.

## Source of Truth

The complete operational instructions for this deployment live alongside the deployment assets in [`deployments/samples/logging-simulation/README.md`](https://github.com/autowarefoundation/openadkit/blob/main/deployments/samples/logging-simulation/README.md).

That README covers:

- sample map and rosbag download and extraction
- required Autoware artifacts
- visualizer access
- startup and shutdown commands

## Quick Start

From `deployments/samples/logging-simulation/`:

```bash
docker compose --env-file logging-simulation.env up -d
docker compose --env-file logging-simulation.env up rosbag -d
```

Open the visualizer at:

```text
http://localhost:6080/vnc.html
```

To stop the deployment:

```bash
docker compose --env-file logging-simulation.env --profile rosbag down
```
