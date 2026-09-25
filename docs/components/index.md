# Components

Open AD Kit packages Autoware Universe into focused container images. Each image
groups closely related Autoware functions, and deployments run them as separate
containers that talk over ROS 2. External clients use the
[Autoware AD API](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/interfaces/ad-api/);
the images use Autoware's component interfaces between them.

All images build on a shared `universe-common` layer; see
[Build from Source](../development/build-from-source.md#build-system) for the
build graph. The [image reference](#image-reference) lists tags and platforms.

## Component Images

### Sensing & Perception {: #sensing-perception }

Sensor preprocessing and environment understanding in one image.

- **Sensing** — LiDAR distortion correction, filtering, and point cloud
  preprocessing; camera and radar preprocessing; GNSS/INS preprocessing; shared
  point cloud container. Launch: `tier4_sensing_component.launch.xml`
- **Perception** — camera, LiDAR, and radar object detection and fusion;
  multi-object tracking and trajectory prediction; traffic light recognition;
  occupancy grid mapping. Launch: `tier4_perception_component.launch.xml`
- **CUDA variant** — `sensing-perception-cuda` accelerates point cloud
  processing and neural-network inference on NVIDIA GPUs. It is amd64-only and
  requires the NVIDIA Container Toolkit. Used by
  [Logging Simulation](../deployments/logging-simulation/index.md) (`--gpu`) and
  [CARLA Simulation](../deployments/carla-simulation/index.md).

### Localization & Mapping {: #localization-mapping }

Serves HD maps and estimates the vehicle pose within them.

- **Localization** — GNSS/RTK positioning and IMU dead reckoning; visual
  odometry and LiDAR map matching; automatic pose initialization; EKF state
  estimation. Launch: `tier4_localization_component.launch.xml`
- **Mapping** — Lanelet2 vector map and point cloud map serving; occupancy grid
  and point cloud map construction; map coordinate transforms. Launch:
  `tier4_map_component.launch.xml`

Planning and Scenario Simulation run only the `map` service; the simulator
supplies map-to-odometry transforms. Logging and CARLA Simulation also run
localization.

### Planning & Control {: #planning-control }

Trajectory generation and vehicle control. Deployments run them as separate
containers from the same image.

- **Planning** — route planning on Lanelet2 road networks; behavior planning for
  lanes, intersections, and obstacles; kinematically feasible motion planning;
  goal and parking maneuvers; emergency fallback trajectories. Launch:
  `tier4_planning_component.launch.xml`
- **Control** — lateral steering and longitudinal velocity control; PID and
  Model Predictive Control modes; vehicle-specific command conversion;
  emergency stop and heartbeat monitoring. Launch:
  `tier4_control_component.launch.xml`

### Vehicle and System {: #vehicle-and-system }

Vehicle actuation and system diagnostics, run as separate containers from one
image.

- **Vehicle** — actuation and state reporting; steering, throttle, brake, gear,
  and turn-signal conversion; vehicle dimensions, limits, and kinematic
  parameters. Launch: `tier4_vehicle_launch/vehicle.launch.xml`
- **System** — health monitoring and heartbeat management; diagnostic
  aggregation; Minimum Risk Maneuver handling; CPU, memory, and process
  monitoring. Launch: `tier4_system_component.launch.xml`

### API {: #api }

Packages the [Autoware AD API](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/interfaces/ad-api/)
used by fleet managers, HMIs, and scenario runners. It provides ROS 2 services
and topics for:

- vehicle position, velocity, engage status, and operation mode
- autonomous, manual, stop, local, and remote mode transitions
- route and goal setting
- emergency stop and engage/disengage commands
- scenario simulation auto-engage and route integration

Launch: `tier4_autoware_api_component.launch.xml`. It is the standard external
entry point for the modular simulation deployments.

### Simulator {: #simulator }

Closed-loop vehicle and environment simulation without real sensors or vehicle
hardware:

- configurable kinematic and dynamic vehicle models
- dummy perception, vehicle, door, and traffic-infrastructure interfaces
- Scenario Simulator v2 adapter and localization simulation mode
- simulated point cloud preprocessing, object tracking, shape estimation, and
  map-based prediction
- occupancy and elevation map handling; vehicle command conversion

Launch: `tier4_simulator_component.launch.xml`. `carla-interface` builds on this
image for CARLA-specific sensor and control translation.

### Visualizer {: #visualizer }

Browser-accessible RViz2 through noVNC: RViz2 with Autoware plugins, Openbox,
TigerVNC, and a TLS-enabled noVNC server. The VNC backend stays loopback-only,
and each container creates its own self-signed certificate at startup.

| Variable | Default | Values | Description |
|----------|---------|--------|-------------|
| `RVIZ_CONFIG` | <code>/opt/<wbr>autoware/<wbr>autoware_launch/<wbr>share/<wbr>autoware_launch/<wbr>rviz/<wbr>autoware.rviz</code> | Path | RViz2 configuration inside the container |
| `REMOTE_DISPLAY` | `true` | `true`, `false` | Use browser-based RViz2; `false` launches a local display |
| `REMOTE_PASSWORD` | — | String | Required when `REMOTE_DISPLAY=true` |
| `WEBSOCKIFY_BIND` | `127.0.0.1` | IP address | noVNC bind address; bridge networking uses `0.0.0.0` with a host loopback port mapping |
| `USE_SIM_TIME` | `false` | `true`, `false` | Use the ROS simulation clock |
| `RVIZ_GPU` | `auto` | `auto`, `on`, `off` | Automatic, forced, or disabled VirtualGL acceleration |

For access and remote use, see the
[Quickstart](../getting-started/index.md#open-the-visualizer).

### CARLA Interface {: #carla-interface }

Packages `autoware_carla_interface`, translating Autoware control commands to
CARLA and CARLA sensor data to ROS 2 messages:

- CARLA world initialization and synchronous simulation
- ego vehicle spawning and sensor-kit configuration
- camera, LiDAR, IMU, and GNSS message translation
- vehicle command calibration and traffic light state publication
- lightweight sensor mappings for constrained hosts

Launch: `autoware_carla_interface.launch.xml`. The image is amd64-only (Humble
and Jazzy); the [CARLA Simulation](../deployments/carla-simulation/index.md)
deployment is Humble-only and needs an NVIDIA GPU.

## Image Reference

Generated from the image catalog (`.github/image-inventory.json`), so it always
matches what CI builds. Tag names are explained in
[Container Images & Versioning](../getting-started/container-images.md).

{{ component_table() }}
