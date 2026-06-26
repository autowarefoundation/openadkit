# Open AD Kit Scenario Simulation

This deployment runs scenario-based simulation workflows with the TIER IV Scenario Simulator.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — Scenario Simulation](https://autowarefoundation.github.io/openadkit/deployment/scenario-simulation/)**

## Quick Start

```bash
./install.sh sample-data scenario-simulation
docker compose --env-file scenario-simulation.env up -d
```

*Cloned repo: run `../../install.sh` instead; pass `--env-file ../base/base.env` before the deployment env file.*
