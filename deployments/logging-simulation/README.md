# Autoware Open AD Kit Logging Simulation

This deployment demonstrates the Open AD Kit logging simulation workflow.

## Documentation

For **complete operational instructions** including map/rosbag download, artifact setup, and troubleshooting, see the canonical documentation:

**[Open AD Kit Docs — Logging Simulation](https://autowarefoundation.github.io/openadkit/deployment/logging-simulation/)**

## Run It

Use the canonical documentation above for the supported bundle workflow. From a
cloned repository, this deployment also needs the shared base env first:

```bash
docker compose --env-file ../base/base.env --env-file logging-simulation.env up -d
```
