# Autoware Open AD Kit Scenario Simulation

This deployment demonstrates the Open AD Kit scenario simulation workflow with the official TIER IV Scenario Simulator container.

## Documentation

For **complete operational instructions** including configuration, custom scenarios, and troubleshooting, see the canonical documentation:

**[Open AD Kit Docs — Scenario Simulation](https://autowarefoundation.github.io/openadkit/deployment/scenario-simulation/)**

## Run It

Use the canonical documentation above for the supported bundle workflow. From a
cloned repository, this deployment also needs the shared base env first:

```bash
docker compose --env-file ../base/base.env --env-file scenario-simulation.env up -d
```
