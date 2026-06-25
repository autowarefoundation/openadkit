# Autoware Open AD Kit Planning Simulation

This deployment demonstrates the Open AD Kit planning simulation workflow.

## Documentation

For **complete operational instructions** including map download, startup, visualizer access, and troubleshooting, see the canonical documentation:

**[Open AD Kit Docs — Planning Simulation](https://autowarefoundation.github.io/openadkit/deployment/planning-simulation/)**

## Run It

Use the canonical documentation above for the supported bundle workflow. From a
cloned repository, this deployment also needs the shared base env first:

```bash
docker compose --env-file ../_base/base.env --env-file planning-simulation.env up -d
```
