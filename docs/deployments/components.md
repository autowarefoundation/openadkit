# Components

Open AD Kit packages Autoware Universe into focused container images. Each image
groups closely related Autoware functions, and deployments run them as separate
containers that talk over ROS 2. External clients use the
[Autoware AD API](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/interfaces/ad-api/);
the images use Autoware's component interfaces between them.

All images build on a shared `universe-common` layer; see
[Build from Source](../development/build-from-source.md#build-system) for the
build graph. The [image reference](../releases/container-images.md#image-reference) lists tags and platforms.

The runtime images hold what Autoware runs. They leave out what only a
compiler reads, such as headers and static libraries, and only the visualizer
carries RViz and its plugins. A kit compiles its overlay workspace in the
`universe-common-devel` image, which keeps both.

## Component Images

| Image | Services | Deployments |
|-------|----------|-------------|
| `sensing-perception` | `sensing`, `perception`, Logging's `rosbag` | Logging, CARLA; CARLA's `perception` runs the CUDA variant |
| `localization-mapping` | `map`, `localization` | `map` in all; `localization` in Logging and CARLA |
| `planning` | `planning` | Planning, Scenario, CARLA, Safety Island |
| `control` | `control` | Planning, Scenario, CARLA, Safety Island |
| `vehicle-system` | `vehicle`, `system`, `api`, `safety-island-bridge`, `safety-island` | All; the last two in Safety Island |
| `simulator` | `simulator`, `simulated-perception`, `mrm-state-relay`, `traffic-light-relay`, `carla-interface`, `carla-map-loader` | Planning, Scenario, Safety Island; the relays in Scenario; `carla-*` in CARLA |
| `visualizer` | `visualizer` | All |

### Sensing & Perception {: #sensing-perception }

Sensor preprocessing and object recognition, as two services from one image.

- **`sensing`** — launch: `component_sensing.launch.xml`
- **`perception`** — launch: `component_perception.launch.xml`
- **CUDA variant** — `sensing-perception-cuda` builds the same packages with
  CUDA and TensorRT, for detection models such as CenterPoint. It is amd64-only
  and requires the NVIDIA Container Toolkit. `perception` runs it in
  [Logging Simulation](logging-simulation.md) (`--gpu`) and
  [CARLA Simulation](carla-simulation.md); `sensing` stays on the CPU image.

`sensing`, `perception` and `localization` each run their point cloud nodes in
a component container of their own, so one service restarts without the others.
The point cloud crosses between them as a ROS message.

### Localization & Mapping {: #localization-mapping }

Serves the Lanelet2 and point cloud maps and estimates the vehicle's pose on
them, as two services from one image.

- **`map`** — launch: `component_map.launch.xml`
- **`localization`** — launch: `component_localization.launch.xml`

Planning, Scenario and Safety Island Simulation run only `map`: the simulator
stands in for localization. Logging and CARLA Simulation also run
`localization`.

### Planning {: #planning }

Plans the route and the trajectory, and publishes `/planning/trajectory`.
Launch: `component_planning.launch.xml`

- **CUDA variant** — `planning-cuda` builds the same packages with CUDA and
  TensorRT, so `planning_setting:=diffusion_planner` runs Autoware 2.0's
  Diffusion Planner. It is amd64-only and requires the NVIDIA Container
  Toolkit. Used by [Planning Simulation](planning-simulation.md)
  (`--gpu`).

### Control {: #control }

Follows `/planning/trajectory` and publishes the control command. Control reads
only that trajectory, so it stays the same whichever planner produces it.
Launch: `component_control.launch.xml`

### Vehicle & System {: #vehicle-and-system }

The vehicle interface, the system diagnostics and the AD API, as three services
from one image. Autoware keeps the AD API with the system packages.

- **`vehicle`** — launch: `tier4_vehicle_launch/vehicle.launch.xml`
- **`system`** — launch: `tier4_system_component.launch.xml`
- **`api`** {: #api } — the [Autoware AD API](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/interfaces/ad-api/),
  the external entry point of every deployment: clients initialize
  localization, set a route and change the operation mode through it. Launch:
  `tier4_autoware_api_component.launch.xml`

### Simulator {: #simulator }

The built-in simulator: a simulated vehicle and simulated perception in place
of real sensors and vehicle hardware.

- **`simulator`** — launch: `tier4_simulator_component.launch.xml`
- **`simulated-perception`** — dummy objects, tracking, prediction and the
  occupancy grid map. Launch: `planning_simulator/perception_simulation.launch.xml`

The image also carries the CARLA bridge; see CARLA Interface below.

### Visualizer {: #visualizer }

RViz in the browser through noVNC: RViz with Autoware plugins, Openbox,
TigerVNC, and a noVNC server over plain HTTP. The VNC backend stays
loopback-only, and so does noVNC by default; reach it remotely through an SSH
tunnel. To serve HTTPS, mount your own certificate into the visualizer from a
[kit](../kits/kit-guide.md#4-extra-services) (the release mounts
none) and name its files in `NOVNC_CERT` and `NOVNC_KEY`; it stays the same
across starts, so a browser exception for it holds.

Set these in the [host settings file](../getting-started/cli.md#settings):

| Variable | Default | Values | Description |
|----------|---------|--------|-------------|
| `RVIZ_CONFIG` | <code>/tmp/<wbr>openadkit/<wbr>autoware_launch/<wbr>share/<wbr>autoware_launch/<wbr>rviz/<wbr>autoware.rviz</code> | Path | RViz configuration inside the container: the deployment's (`autoware.rviz`, or `scenario_simulator.rviz` in Scenario Simulation), with config overrides applied |
| `REMOTE_DISPLAY` | `true` | `true`, `false` | RViz in the browser; `false` opens RViz on your own desktop instead, using the session's `DISPLAY` and `XAUTHORITY` |
| `REMOTE_PASSWORD` | `openadkit` | String | noVNC password, required when `REMOTE_DISPLAY=true`. The deployments set this default; the image itself has none |
| `WEBSOCKIFY_BIND` | `127.0.0.1` | IP address | noVNC bind address. `0.0.0.0` exposes noVNC on every interface of the host: put an authenticated reverse proxy in front of it |
| `RVIZ_GPU` | `auto` | `auto`, `on`, `off` | Automatic, forced, or disabled VirtualGL acceleration |
| `NOVNC_CERT`, `NOVNC_KEY` | unset | Paths | Certificate and key inside the container; set both to serve HTTPS only |

To open it, see the
[Quickstart](../getting-started/index.md#open-the-visualizer).

### CARLA Interface {: #carla-interface }

The simulator image's `autoware_carla_interface` translates Autoware control
commands to CARLA and CARLA sensor data to ROS 2 messages. Launch:
`autoware_carla_interface.launch.xml`

CARLA publishes its Python client for x86_64 only, so only the amd64 simulator
image has it (Humble and Jazzy);
[CARLA Simulation](carla-simulation.md) is Humble-only and needs
an NVIDIA GPU.
