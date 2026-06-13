# Autoware Open AD Kit AWSIM E2E Simulation

This sample runs a closed-loop AWSIM v2 end-to-end simulation with modular OpenADKit containers.

## Source of Truth

The complete operational instructions for this deployment live alongside the deployment assets in [`deployments/samples/awsim-simulation/README.md`](https://github.com/autowarefoundation/openadkit/blob/main/deployments/samples/awsim-simulation/README.md).

That README covers:

- requirements and runtime images
- startup, RViz access, and shutdown commands
- optional autonomous drive check

## Quick Start

From `deployments/samples/awsim-simulation/`:

```bash
./start-awsim-e2e-demo.sh
```

Open the visualizer at:

```text
http://localhost:6080/vnc.html
```

To stop the deployment:

```bash
docker compose --env-file awsim-simulation.e2e.env -f docker-compose.yaml down
```
