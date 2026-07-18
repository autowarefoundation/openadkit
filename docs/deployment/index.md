# Deployment

A deployment combines Open AD Kit images, environment files, and Docker Compose
configuration for a specific task.

| Deployment | Purpose | Topology | GPU |
|------------|---------|----------|-----|
| [Planning Simulation](planning-simulation/index.md) | Plan and follow a route on a demo map | Single host | Optional |
| [Scenario Simulation](scenario-simulation/index.md) | Execute predefined traffic scenarios | Single host | Optional |
| [Logging Simulation](logging-simulation/index.md) | Replay recorded sensor data through the full stack | Single host | Recommended |
| [CARLA Simulation](carla-simulation/index.md) | Drive a CARLA ego vehicle in closed loop | Single host | Required |
| [Zenoh Bridge](zenoh-bridge/index.md) | Separate edge compute from visualization and control | One or two hosts | Varies |

New users should start with Planning Simulation.

## Base and Overlay Model

Planning, Scenario, Logging, and CARLA Simulation include the shared
`deployments/base/docker-compose.yaml`. The base defines map, planning, vehicle,
system, control, simulator, API, and visualizer services; each deployment adds
only its delta.

In a source checkout, load shared defaults before deployment overrides:

```bash
docker compose --env-file ../base/base.env --env-file planning-simulation.env up -d
```

Release bundles vendor the base and merge both env files, so they use one
`--env-file`. Zenoh Bridge is self-contained and uses a local `.env` copied from
`.env.example`.

See [Custom Deployment](custom-deployment.md) to compose a different stack and
[Container Images & Versioning](../getting-started/container-images.md) for tag
selection.
