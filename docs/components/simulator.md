# Simulator

## Overview

The `simulator` image is a **standalone component** for simulation workloads in the Open AD Kit ecosystem. It packages the Autoware simulation modules, providing a virtual environment for testing the autonomous driving stack without requiring real-world sensors or vehicles. The simulator enables closed-loop validation by emulating vehicle dynamics, sensor outputs, and traffic scenarios so that planning, control, and perception logic can be exercised safely on a development workstation or in CI pipelines.

## What This Image Contains

The `simulator` image bundles the following capabilities:

- **Closed-loop vehicle simulation** — Simple planning simulator that computes vehicle motion from control commands using configurable kinematic/dynamic models (ideal, delay, actuation-based, and learned models)
- **Dummy perception** — Simulated object detection and recognition pipeline for scenarios where real sensor data is unavailable
- **Dummy vehicle interface** — Emulated vehicle state reporting and actuation feedback
- **Dummy doors and infrastructure** — Simulated door status and traffic infrastructure for end-to-end stack testing
- **Scenario simulator v2 adapter** — Integration layer for the TIER IV Scenario Simulator v2, enabling predefined scenario execution
- **Localization simulation mode** — Direct map-to-odometry TF publishing for simulation contexts where localization modules are bypassed
- **Point cloud preprocessing** — Point cloud filtering and container management for simulated LiDAR data
- **Object tracking and shape estimation** — Multi-object tracker and shape estimation for perceived obstacles
- **Occupancy grid mapping** — Probabilistic occupancy grid generation from simulated sensor data
- **Map-based prediction** — Predictive modeling of agent behavior based on map topology
- **Elevation map loading** — Ground elevation data handling for simulated environments
- **Vehicle command conversion** — Raw vehicle command conversion and external command selection for simulation-specific control paths
- **Launch file:** `tier4_simulator_component.launch.xml`

Typical resource usage:

- **CPU**: Low to moderate (depends on model complexity and sensor emulation)
- **GPU**: Not required (CPU-only simulation)
- **Memory**: ~1–2 GB

## Used In

- [Planning Simulation](../deployment/planning-simulation/index.md) — Provides the simulated vehicle and environment for planning and control testing
- [Scenario Simulation](../deployment/scenario-simulation/index.md) — Feeds the stack with scenario-driven simulated data and acts as the ego vehicle interface
- [Logging Simulation](../deployment/logging-simulation/index.md) — Supports simulated localization and vehicle states during rosbag replay

## Related

- [Autoware node diagram](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/node-diagram/) — Overall architecture diagram showing simulation nodes
- [Autoware interface design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/interfaces/) — How simulators access AD API and component interfaces
- [Planning simulation demos](https://autowarefoundation.github.io/autoware-documentation/main/demos/planning-sim/) — Official Autoware planning simulation guides
- [Scenario simulation demos](https://autowarefoundation.github.io/autoware-documentation/main/demos/scenario-simulation/) — Official Autoware scenario simulation guides
- [Deployments](../deployment/index.md) — How the simulator container is composed with other components
