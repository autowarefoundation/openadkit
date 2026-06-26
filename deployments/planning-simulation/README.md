# Open AD Kit Planning Simulation

This deployment runs the Autoware planning and control stack with a pre-recorded point cloud map.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — Planning Simulation](https://autowarefoundation.github.io/openadkit/deployment/planning-simulation/)**

## Quick Start

```bash
./install.sh sample-data planning-simulation
docker compose --env-file planning-simulation.env up -d
```

*Cloned repo: run `../../install.sh` instead; pass `--env-file ../base/base.env` before the deployment env file.*
