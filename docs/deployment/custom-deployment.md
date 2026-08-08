# Custom Deployment

Use the published component images to compose a deployment for your own task.
Start from the [Planning Simulation Compose file](https://github.com/autowarefoundation/openadkit/blob/main/deployments/planning-simulation/docker-compose.yaml)
and the shared [deployment base](https://github.com/autowarefoundation/openadkit/blob/main/deployments/base/docker-compose.yaml)
rather than assembling a complete stack from scratch. The
[component catalog](../components/index.md#image-reference) lists image targets
and supported platforms.

## Base + Overlay Pattern

Create `deployments/<your-deployment>/` with a Compose file, complete
`config.env`, and an `openadkit.json` manifest. Base-backed deployments
`include` `deployments/base/docker-compose.yaml` and declare the shared assets:

```json
{
  "schemaVersion": 1,
  "name": "your-deployment",
  "description": "Describe the deployment",
  "shared": ["base"],
  "compose": {
    "files": ["docker-compose.yaml"],
    "gpuFiles": [],
    "profiles": [],
    "services": ["map", "planning", "visualizer"],
    "verifyServices": ["map", "planning", "visualizer"],
    "resetServices": [],
    "waitTimeout": 300,
    "groups": {},
    "features": {}
  },
  "requirements": {
    "architectures": ["amd64", "arm64"],
    "rosDistros": ["humble", "jazzy"],
    "gpu": "none"
  },
  "data": [],
  "hooks": {}
}
```

`./openadkit list` discovers valid manifests dynamically and marks additions as
`custom/unverified`. The base's `runtime.env` is loaded inside containers and
should contain only ROS/DDS runtime values. See [Deployments](index.md) for the
operator model.

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
  `config.local.env`). Do not expose the
  visualizer on untrusted networks without TLS and a non-default password.

With host networking, open the visualizer at
`https://localhost:6080/vnc.html` and accept the self-signed certificate.

## Operate

From the source checkout or release bundle root:

```bash
./openadkit validate your-deployment
./openadkit run your-deployment
./openadkit status your-deployment
./openadkit logs your-deployment --follow
./openadkit down your-deployment
```

See [Logging Simulation](logging-simulation/index.md) for a GPU overlay and
[Zenoh Bridge](zenoh-bridge/index.md) for distributed ROS 2 domains.
