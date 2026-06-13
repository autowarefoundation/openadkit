# Visualizer

## Overview

The `visualizer` image provides a **browser-accessible RViz2 environment** via noVNC, allowing remote inspection of Autoware topics and state without requiring a local ROS 2 installation or display server. It is designed as a lightweight component that can be deployed alongside the core stack or on a separate machine for remote monitoring. Accessing the visualizer requires only a web browser, making it ideal for distributed deployments, headless servers, and cloud-edge setups.

## What This Image Contains

The `visualizer` image bundles the following tools and capabilities:

- **noVNC web server** — Browser-based VNC client served over HTTPS (port 6080) with a self-signed SSL certificate for encrypted access
- **TigerVNC standalone server** — Native VNC backend (port 5900) that renders the desktop session
- **Openbox window manager** — Minimal X11 window manager to host RViz2 and other GUI tools
- **RViz2** — Official ROS 2 visualization tool pre-configured with Autoware display plugins for:
  - Detected objects and predicted trajectories
  - Planned paths, behavior states, and motion trajectories
  - Occupancy grid maps and point cloud data
  - Lane boundaries, traffic lights, and map markers
  - Vehicle state and diagnostic displays
- **SSL certificate for noVNC** — Pre-generated certificate for secure browser connections
- **Autoware visualization plugins** — Custom RViz2 plugins for Autoware-specific message types (e.g., `autoware_perception_msgs`, `autoware_planning_msgs`)

Typical resource usage:

- **CPU**: Low (rendering is handled by the VNC/RViz2 processes)
- **GPU**: Not required (CPU rendering via software OpenGL; GPU can improve RViz2 performance if available)
- **Memory**: ~500 MB–1 GB

## Visualizer Settings

The following environment variables can be configured when launching the visualizer container:

| Variable | Default Value | Possible Values | Description |
|----------|---------------|-----------------|-------------|
| `RVIZ_CONFIG` | `/opt/autoware/share/autoware_launch/rviz/autoware.rviz` | Any valid path | The full path to the RViz2 configuration file inside the container |
| `REMOTE_DISPLAY` | `true` | `true`, `false` | **(Recommended)** Browser-based RViz2 display accessible from any device. Set to `false` to launch a local RViz2 display |
| `REMOTE_PASSWORD` | — (required) | Any string without special characters | Password for the remote display. Required when `REMOTE_DISPLAY=true` (the default); the container exits if unset |

## Used In

- [Planning Simulation](../deployment/samples/planning-simulation/index.md) — Visualizes planning trajectories, goal poses, and vehicle motion
- [Scenario Simulation](../deployment/samples/scenario-simulation/index.md) — Displays scenario-driven traffic, ego vehicle behavior, and obstacle interactions
- [Logging Simulation](../deployment/samples/logging-simulation/index.md) — Replays rosbag data with full perception, localization, and planning visualization
- [Zenoh Bridge Demo](../deployment/demos/zenoh-bridge/index.md) — Remote visualization across isolated ROS 2 domains via Zenoh bridging

## Related

- [Autoware interface design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/interfaces/) — How visualization tools access component interfaces and AD API
- [Autoware node diagram](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/node-diagram/) — Overall architecture diagram showing topic flows
- [Deployments](../deployment/index.md) — How the visualizer container is composed with other components
