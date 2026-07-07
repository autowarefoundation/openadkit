# Open AD Kit Planning Simulation

This deployment runs the Autoware planning and control stack with a pre-recorded point cloud map.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — Planning Simulation](https://autowarefoundation.github.io/openadkit/deployment/planning-simulation/)**

## Quick Start

```bash
../../install.sh sample-data planning-simulation
docker compose --env-file ../base/base.env --env-file planning-simulation.env up -d
```

*Release bundle: from the extracted directory, run `./install.sh sample-data planning-simulation` and `docker compose --env-file planning-simulation.env up -d` (the bundle ships a merged env file).*
