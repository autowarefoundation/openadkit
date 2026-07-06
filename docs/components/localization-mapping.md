# Localization & Mapping

## Overview

The `localization-mapping` image packages two closely related functions into a single build target. Mapping loads and serves HD map data — Lanelet2 vector maps and 3D point cloud maps — providing the static environmental context the rest of the stack consumes. Localization determines the vehicle's pose within that map by fusing multiple positioning sources, producing the ego pose estimate that planning and control rely on.

## Localization

- **GNSS/RTK localization** — Global positioning with real-time kinematic correction
- **IMU dead reckoning** — Inertial measurement for short-term motion estimation
- **Visual odometry** — Camera-based motion estimation and pose tracking
- **LiDAR localization** — Point cloud matching against the pre-built HD map
- **Automatic pose initialization** — Initial pose estimation and reset handling
- **EKF state estimation** — Gyro odometry fusion and multi-sensor state filtering
- **Launch file:** `tier4_localization_component.launch.xml`

## Mapping

- **Lanelet2 map serving** — Vector-based lane geometry, traffic rules, and routing graph distribution
- **Point cloud map serving** — Pre-built 3D point cloud map loading and distribution
- **Occupancy grid mapping** — 2D grid-based environment representation construction
- **Point cloud map construction** — 3D map building from LiDAR data
- **Map transform management** — Coordinate frame transformations between map and vehicle frames
- **Launch file:** `tier4_map_component.launch.xml`

## Resource Usage

- **CPU**: Low to moderate — map serving is cheap; localization runs entirely on CPU
- **GPU**: Not required
- **Memory**: Scales with map size (typically ~2–4 GB for demo maps)

## Used In

- [Logging Simulation](../deployment/logging-simulation/index.md)
- [Planning Simulation](../deployment/planning-simulation/index.md)
- [Scenario Simulation](../deployment/scenario-simulation/index.md)
- [CARLA Simulation](../deployment/carla-simulation/index.md)

The `localization-mapping` image is also used for the `map` service in Planning and Scenario simulations, but the localization component itself (`tier4_localization_component.launch.xml`) runs only in Logging and CARLA. In Planning and Scenario, the simulator provides map→odom TF instead.

## Related

- [Autoware localization design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/localization/)
- [Autoware mapping design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/map/)
