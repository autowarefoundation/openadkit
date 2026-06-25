# Custom Deployment

This guide shows how to compose your own Open AD Kit deployment from OAK component images using Docker Compose.

## Prerequisites

- Docker Engine (set up via `setup.sh`)
- Optional: NVIDIA Container Toolkit (for GPU-accelerated components)
- Optional: a deployment bundle as a starting reference — download from the [latest release](https://github.com/autowarefoundation/openadkit/releases/latest)

## Component Selection

Choose which OAK images to use based on your use case:

### Minimal Stack

The simplest useful deployment runs just planning and visualization:

| Component | Image | Purpose |
|-----------|-------|---------|
| `visualizer` | `{{ registry }}:visualizer` | Browser-accessible RViz2 |
| `planning-control` | `{{ registry }}:planning-control` | Planning and control logic |

### Full Simulation Stack

Add a simulator to test planning without real sensors:

| Component | Image | Purpose |
|-----------|-------|---------|
| `visualizer` | `{{ registry }}:visualizer` | Browser-accessible RViz2 |
| `planning-control` | `{{ registry }}:planning-control` | Planning and control logic |
| `simulator` | `{{ registry }}:simulator` | Virtual vehicle and environment |

### Full Perception Stack

Run the complete Autoware pipeline with sensing and perception:

| Component | Image | Purpose |
|-----------|-------|---------|
| `visualizer` | `{{ registry }}:visualizer` | Browser-accessible RViz2 |
| `sensing-perception` | `{{ registry }}:sensing-perception` | Sensor preprocessing and perception |
| `localization-mapping` | `{{ registry }}:localization-mapping` | Localization and map serving |
| `planning-control` | `{{ registry }}:planning-control` | Planning and control logic |
| `vehicle-system` | `{{ registry }}:vehicle-system` | Vehicle interface and system services |
| `api` | `{{ registry }}:api` | External API services |

!!! tip "GPU-Accelerated Perception"
    Use the `sensing-perception-cuda` image instead of `sensing-perception` for GPU-accelerated inference. This is **amd64-only** and requires NVIDIA Container Toolkit.

## Example Compose File

Here is a minimal `docker-compose.yaml` showing the two essential patterns — an Autoware component launched via its `autoware_launch` per-component launch file, and the visualizer running its built-in noVNC entrypoint:

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
      - REMOTE_PASSWORD=openadkit # required — the container exits if unset
      - USE_SIM_TIME=true
```

With host networking, the visualizer is reachable directly at `http://localhost:6080/vnc.html`.

!!! warning "Patterns to keep"
    - Components are launched with `ros2 launch autoware_launch tier4_<component>_component.launch.xml component_wise_launch:=true ...` — there are no per-component ROS packages named after the images.
    - Do **not** override the visualizer's `command`: its entrypoint starts the VNC/noVNC stack and RViz2.
    - All services need the same `RMW_IMPLEMENTATION` and `ROS_DOMAIN_ID` for DDS discovery; deployments use `network_mode: host` with CycloneDDS.

!!! note "A runnable stack needs more services"
    A planning stack that actually does something also needs map serving, a simulator or vehicle interface, system services, and the API container. Use the [planning-simulation `docker-compose.yaml`](https://github.com/autowarefoundation/openadkit/blob/main/deployments/planning-simulation/docker-compose.yaml) as the reference and prune from there.

## Environment Configuration

Create a `.env` file alongside your `docker-compose.yaml`:

```bash
# Required
ROS_DOMAIN_ID=0

# Optional: NVIDIA runtime (for GPU-accelerated images)
# NVIDIA_VISIBLE_DEVICES=all
# NVIDIA_DRIVER_CAPABILITIES=all
```

## Starting the Deployment

```bash
# Start the stack
docker compose up -d

# Verify all containers are running
docker compose ps

# View logs
docker compose logs -f

# Stop the stack
docker compose down
```

## Next Steps

- For a complete, ready-to-run example, see the [Planning Simulation](planning-simulation/index.md)
- For GPU-accelerated deployments, see the [Logging Simulation](logging-simulation/index.md)
- For distributed deployments, see the [Zenoh Bridge](zenoh-bridge/index.md)

!!! note "Future Work"
    A unified master deployment configuration is planned to serve as both documentation and a golden-path setup for all OAK components.

## Related

- [Component Overview](../components/index.md) — Understand the full OAK architecture
- [Container Image Tags](../getting-started/image-tags.md) — Choose the right tag
- [Getting Started](../getting-started/index.md) — Environment setup
