# Autoware Open AD Kit CARLA E2E Simulation

This sample runs a closed-loop CARLA 0.9.16 end-to-end simulation with modular OpenADKit containers and Autoware's `autoware_carla_interface`.

## Source of Truth

The complete operational instructions for this deployment live alongside the deployment assets in [`deployments/samples/carla-simulation/README.md`](https://github.com/autowarefoundation/openadkit/blob/main/deployments/samples/carla-simulation/README.md).

That README covers:

- requirements and runtime images
- startup, RViz access, and shutdown commands
- optional autonomous drive check and faster relaunch

## Quick Start

From `deployments/samples/carla-simulation/`:

```bash
./start-carla-e2e-demo.sh
```

Open the visualizer at:

```text
http://localhost:6080/vnc.html
```

To stop the deployment:

```bash
docker compose --env-file carla-simulation.e2e.env -f docker-compose.yaml down
```
