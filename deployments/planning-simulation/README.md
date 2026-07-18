# Open AD Kit Planning Simulation

This deployment runs the Autoware planning and control stack with a pre-recorded point cloud map.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — Planning Simulation](https://autowarefoundation.github.io/openadkit/deployment/planning-simulation/)**

## Source Checkout

```bash
../../install.sh sample-data planning-simulation
docker compose --env-file ../base/base.env --env-file planning-simulation.env up -d
```

## Release Bundle

From the extracted directory:

```bash
./install.sh sample-data planning-simulation
docker compose --env-file planning-simulation.env up -d
```
