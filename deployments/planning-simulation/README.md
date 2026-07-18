# Planning Simulation

Runs the Autoware planning and control stack with a pre-recorded point cloud
map. See the [canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/planning-simulation/)
for configuration and troubleshooting.

## Source Checkout

```bash
../../install.sh sample-data planning-simulation
docker compose --env-file ../base/base.env --env-file planning-simulation.env up -d
```

## Release Bundle

```bash
./install.sh sample-data planning-simulation
docker compose --env-file planning-simulation.env up -d
```
