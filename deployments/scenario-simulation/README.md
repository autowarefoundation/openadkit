# Open AD Kit Scenario Simulation

This deployment runs scenario-based simulation workflows with the TIER IV Scenario Simulator.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — Scenario Simulation](https://autowarefoundation.github.io/openadkit/deployment/scenario-simulation/)**

## Source Checkout

```bash
../../install.sh sample-data scenario-simulation
docker compose --env-file ../base/base.env --env-file scenario-simulation.env up -d
```

## Release Bundle

From the extracted directory:

```bash
./install.sh sample-data scenario-simulation
docker compose --env-file scenario-simulation.env up -d
```
