# Localization

## Overview

The localization component determines the vehicle's pose within the HD map by fusing multiple positioning sources. It provides the ego pose estimate that planning and control rely on for trajectory generation. It runs inside the `localization-mapping` image, which is shared with mapping.

## What This Image Contains

- **GNSS/RTK localization** — Global positioning with real-time kinematic correction
- **IMU dead reckoning** — Inertial measurement for short-term motion estimation
- **Visual odometry** — Camera-based motion estimation and pose tracking
- **LiDAR localization** — Point cloud matching against the pre-built HD map
- **Automatic pose initialization** — Initial pose estimation and reset handling
- **EKF state estimation** — Gyro odometry fusion and multi-sensor state filtering
- **Launch file:** `tier4_localization_component.launch.xml`

Typical resource usage:

- **CPU**: Moderate — runs entirely on CPU
- **GPU**: Not required
- **Memory**: Scales with map size (typically ~2–4 GB)

## Used In

- [Logging Simulation](../deployment/samples/logging-simulation/index.md)
- [Planning Simulation](../deployment/samples/planning-simulation/index.md)
- [Scenario Simulation](../deployment/samples/scenario-simulation/index.md)

## Related

- [Mapping](mapping.md) — Shares the same `localization-mapping` image
- [Autoware localization design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/localization/)
