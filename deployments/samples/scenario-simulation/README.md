# Autoware Open AD Kit Scenario Simulation

This sample deployment demonstrates the Open AD Kit scenario simulation workflow with the official TIER IV Scenario Simulator container.

## Documentation

For **complete operational instructions** including configuration, custom scenarios, and troubleshooting, see the canonical documentation:

**[Open AD Kit Docs — Scenario Simulation](https://autowarefoundation.github.io/openadkit/deployment/samples/scenario-simulation/)**

## Quick Start

```bash
# From this directory
# 1. Download the Kashiwanoha map (from a cloned repo: ../../scripts/fetch-sample-data.sh)
./fetch-sample-data.sh scenario-simulation

# 2. Start the deployment
docker compose --env-file scenario-simulation.env up -d
```

Open the visualizer at `http://localhost:6080/vnc.html` (password: `openadkit`).

## Stop

```bash
docker compose --env-file scenario-simulation.env down
```
