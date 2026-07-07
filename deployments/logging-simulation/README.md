# Open AD Kit Logging Simulation

This deployment replays recorded sensor data through the full Autoware sensing, perception, and planning stack.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — Logging Simulation](https://autowarefoundation.github.io/openadkit/deployment/logging-simulation/)**

## Quick Start

```bash
../../install.sh sample-data logging-simulation
docker compose --env-file ../base/base.env --env-file logging-simulation.env up -d
```

*Release bundle: from the extracted directory, run `./install.sh sample-data logging-simulation` and `docker compose --env-file logging-simulation.env up -d` (the bundle ships a merged env file).*
