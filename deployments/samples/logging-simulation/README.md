# Autoware Open AD Kit Logging Simulation

This sample deployment demonstrates the Open AD Kit logging simulation workflow.

## Documentation

For **complete operational instructions** including map/rosbag download, artifact setup, and troubleshooting, see the canonical documentation:

**[Open AD Kit Docs — Logging Simulation](https://autowarefoundation.github.io/openadkit/deployment/samples/logging-simulation/)**

## Run It

Use the canonical documentation above for the supported bundle workflow. From a
cloned repository, this sample also needs the shared deployment base env first:

```bash
docker compose --env-file ../_base/base.env --env-file logging-simulation.env up -d
```
