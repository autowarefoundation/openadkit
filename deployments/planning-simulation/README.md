# Planning Simulation

Runnable assets for the Autoware planning simulation.

**Guide (source of truth):**
[Planning Simulation docs](https://autowarefoundation.github.io/openadkit/deployments/samples/planning-simulation/)

```bash
../../install.sh sample-data planning-simulation
docker compose --env-file config.env up -d
```

Smoke-test without starting: `./check-planning-simulation.sh`
