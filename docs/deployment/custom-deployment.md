# Custom Deployment

Use the published component images to compose a deployment for your own task.
Start from the [Planning Simulation Compose file](https://github.com/autowarefoundation/openadkit/blob/main/deployments/planning-simulation/docker-compose.yaml)
and the shared [deployment base](https://github.com/autowarefoundation/openadkit/blob/main/deployments/base/docker-compose.yaml)
rather than assembling a complete stack from scratch. The
[component catalog](../components/index.md#image-reference) lists image targets
and supported platforms.

## Base + overlay pattern

Base-backed deployments `include` `deployments/base/docker-compose.yaml` and
pass two env files from a source checkout (base first, last-wins):

```bash
cd deployments/<your-deployment>
docker compose \
  --env-file ../base/base.env \
  --env-file <your-deployment>.env \
  up -d
```

Release bundles vendor `base/` and merge env into a single `<deployment>.env`,
so they use only that file. See [Deployments](index.md) for the operator model.

## Core Patterns

```yaml
services:
  planning:
    image: {{ registry }}:planning-control
    network_mode: host
    ipc: host
    environment:
      - RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
      - ROS_DOMAIN_ID=1
    command: >
      ros2 launch autoware_launch tier4_planning_component.launch.xml
      component_wise_launch:=true
      use_sim_time:=true
      vehicle_model:=sample_vehicle

  visualizer:
    image: {{ registry }}:visualizer
    network_mode: host
    ipc: host
    environment:
      - RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
      - ROS_DOMAIN_ID=1
      - REMOTE_PASSWORD=openadkit
      - USE_SIM_TIME=true
```

Keep these invariants:

- All services use the same `RMW_IMPLEMENTATION` and `ROS_DOMAIN_ID`.
- Launch files are not always `tier4_<component>_component.launch.xml`. Match
  the command used in the base or deployment compose, for example:
  - map / planning / system / control / simulator: `tier4_*_component.launch.xml`
    under `autoware_launch`
  - vehicle: `tier4_vehicle_launch vehicle.launch.xml`
  - API: `tier4_autoware_api_component.launch.xml`
  - CARLA bridge: `autoware_carla_interface.launch.xml`
- Do not override the visualizer command; its entrypoint starts noVNC and RViz2.
- Add map, vehicle, system, simulator, and API services as required by the task.
- Use `sensing-perception-cuda` only on amd64 hosts with NVIDIA Container
  Toolkit (Logging Simulation GPU overlay and CARLA default).
- Prefer loopback-bound noVNC and a strong `REMOTE_PASSWORD` (source:
  `../base/base.env`; release bundle: `<deployment>.env`). Do not expose the
  visualizer on untrusted networks without TLS and a non-default password.

With host networking, open the visualizer at
`https://localhost:6080/vnc.html` and accept the self-signed certificate.

## Operate

From a source checkout of a base-backed deployment:

```bash
docker compose --env-file ../base/base.env --env-file <your-deployment>.env up -d
docker compose --env-file ../base/base.env --env-file <your-deployment>.env ps
docker compose --env-file ../base/base.env --env-file <your-deployment>.env logs -f
docker compose --env-file ../base/base.env --env-file <your-deployment>.env down
```

From a release bundle (merged env only):

```bash
docker compose --env-file <your-deployment>.env up -d
docker compose --env-file <your-deployment>.env down
```

See [Logging Simulation](logging-simulation/index.md) for a GPU overlay and
[Zenoh Bridge](zenoh-bridge/index.md) for distributed ROS 2 domains.
