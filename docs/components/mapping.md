# Mapping

## Overview

The mapping component loads and serves HD map data to the rest of the Autoware stack. It manages Lanelet2 vector maps and 3D point cloud maps, providing the static environmental context required for localization, planning, and perception. It runs inside the `localization-mapping` image, which is shared with localization.

## What This Image Contains

- **Lanelet2 map serving** — Vector-based lane geometry, traffic rules, and routing graph distribution
- **Point cloud map serving** — Pre-built 3D point cloud map loading and distribution
- **Occupancy grid mapping** — 2D grid-based environment representation construction
- **Point cloud map construction** — 3D map building from LiDAR data
- **Map transform management** — Coordinate frame transformations between map and vehicle frames
- **Launch file:** `tier4_map_component.launch.xml`

Typical resource usage:

- **CPU**: Low — serves map data with minimal processing
- **GPU**: Not required
- **Memory**: Scales with map size (typically ~2–4 GB for demo maps)

## Used In

- [Logging Simulation](../deployment/logging-simulation/index.md)
- [Planning Simulation](../deployment/planning-simulation/index.md)
- [Scenario Simulation](../deployment/scenario-simulation/index.md)

## Related

- [Localization](localization.md) — Shares the same `localization-mapping` image
- [Autoware mapping design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/map/)
