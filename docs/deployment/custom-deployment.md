# Custom Deployment

Use the published component images to compose a deployment for your own task.
Start from the [Planning Simulation Compose file](https://github.com/autowarefoundation/openadkit/blob/main/deployments/planning-simulation/docker-compose.yaml)
rather than assembling a complete stack from scratch. The
[component catalog](../components/index.md#image-reference) lists image targets
and supported platforms.

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
- Launch component images with their `tier4_<component>_component.launch.xml`
  launch file; image names are not ROS package names.
- Do not override the visualizer command; its entrypoint starts noVNC and RViz2.
- Add map, vehicle, system, simulator, and API services as required by the task.
- Use `sensing-perception-cuda` only on amd64 hosts with NVIDIA Container
  Toolkit.

With host networking, open the visualizer at
`https://localhost:6080/vnc.html` and accept the self-signed certificate.

## Operate

```bash
docker compose up -d
docker compose ps
docker compose logs -f
docker compose down
```

See [Logging Simulation](logging-simulation/index.md) for a GPU overlay and
[Zenoh Bridge](zenoh-bridge/index.md) for distributed ROS 2 domains.
