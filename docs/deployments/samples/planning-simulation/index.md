# Autoware Open AD Kit Planning Simulation

This sample deployment demonstrates the Open AD Kit planning simulation workflow.

## Source of Truth

The complete operational instructions for this deployment live alongside the deployment assets in [`deployments/samples/planning-simulation/README.md`](https://github.com/autowarefoundation/openadkit/blob/main/deployments/samples/planning-simulation/README.md).

That README covers:

- sample map download and extraction
- visualizer access
- startup and shutdown commands

## Quick Start

From `deployments/samples/planning-simulation/`:

```bash
docker compose --env-file planning-simulation.env up -d
```

Open the visualizer at:

```text
http://localhost:6080/vnc.html
```

To stop the deployment:

```bash
docker compose --env-file planning-simulation.env down
```
