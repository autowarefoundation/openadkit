# Autoware Open AD Kit Scenario Simulation

This sample deployment demonstrates the Open AD Kit scenario simulation workflow with the official TIER IV Scenario Simulator container.

## Documentation

For **complete operational instructions** including configuration, custom scenarios, and troubleshooting, see the canonical documentation:

**[Open AD Kit Docs — Scenario Simulation](https://autowarefoundation.github.io/openadkit/deployment/samples/scenario-simulation/)**

## Run It

Use the canonical documentation above for the supported bundle workflow. From a
cloned repository, this sample also needs the shared deployment base env first:

```bash
docker compose --env-file ../_base/base.env --env-file scenario-simulation.env up -d
```
