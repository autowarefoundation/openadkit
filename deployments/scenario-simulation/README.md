# Scenario Simulation

Runs TIER IV Scenario Simulator workflows. See the
[canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/scenario-simulation/)
for configuration and troubleshooting.

## Source Checkout

```bash
../../install.sh sample-data scenario-simulation
docker compose --env-file ../base/base.env --env-file scenario-simulation.env up -d
```

## Release Bundle

```bash
./install.sh sample-data scenario-simulation
docker compose --env-file scenario-simulation.env up -d
```
