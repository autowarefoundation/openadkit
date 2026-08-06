# Deployments

A **deployment** is a running instance of Open AD Kit, a specific combination of Autoware components configured to achieve a particular task, such as a simulation or a full autonomous driving stack.

Planning and logging Compose assets live under `deployments/<name>/` in the
repository. The remaining deployments retain their `samples/` or `demos/`
paths until their runtime migration lands.

Planning and logging include `deployments/base/` (`docker-compose.yaml` plus
`runtime.env` for container ROS/DDS) and each has one complete `config.env`:

```bash
docker compose --env-file config.env up -d
```

`runtime.env` is loaded by services via `env_file:`; `config.env` is loaded by
Compose via `--env-file`.

Fetch maps/rosbags with `./install.sh sample-data <name>` (see
[Getting Started](../getting-started/index.md)).

## Samples

Recommended for **learning and development**.

- [CARLA Simulation](samples/carla-simulation/index.md) — `deployments/samples/carla-simulation/`
- [Planning Simulation](samples/planning-simulation/index.md) — `deployments/planning-simulation/`
- [Scenario Simulation](samples/scenario-simulation/index.md) — `deployments/samples/scenario-simulation/`
- [Logging Simulation](samples/logging-simulation/index.md) — `deployments/logging-simulation/`

## Demos

Use-case specific topologies.

- [Zenoh Bridge](demos/zenoh-bridge/index.md) — `deployments/demos/zenoh-bridge/` (edge/cloud remote viz + teleop)
