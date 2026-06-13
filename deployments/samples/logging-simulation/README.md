# Autoware Open AD Kit Logging Simulation

This sample deployment demonstrates the Open AD Kit logging simulation workflow.

## Documentation

For **complete operational instructions** including map/rosbag download, artifact setup, and troubleshooting, see the canonical documentation:

**[Open AD Kit Docs — Logging Simulation](https://autowarefoundation.github.io/openadkit/deployment/samples/logging-simulation/)**

## Quick Start

```bash
# From this directory
# 1. Download the sample map and rosbag (from a cloned repo: ../../scripts/fetch-sample-data.sh)
./fetch-sample-data.sh logging-simulation

# 2. Start the base deployment
docker compose --env-file logging-simulation.env up -d

# 3. Start the rosbag playback
docker compose --env-file logging-simulation.env up rosbag -d
```

Open the visualizer at `http://localhost:6080/vnc.html` (password: `openadkit`).

## Stop

```bash
docker compose --env-file logging-simulation.env --profile rosbag down
```
