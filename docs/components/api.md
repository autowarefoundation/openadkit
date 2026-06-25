# API

## Overview

The API component provides the [AD API](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-interfaces/ad-api/) interface for external systems to interact with the vehicle. It exposes a standardized set of ROS 2 services and topics that allow fleet management systems, HMIs, and scenario runners to query state, send commands, and orchestrate autonomous operation.

The API component exposes:

- Vehicle state queries (position, velocity, mode)
- Operation mode transitions (autonomous, manual, stop)
- Route and goal setting
- Emergency stop commands

## What This Image Contains

The `api` image packages the Autoware AD API layer:

- Vehicle state publishing (position, velocity, engage status)
- Operation mode management (autonomous, manual, stop, local, remote)
- Route and goal setting services
- Emergency stop and engage/disengage commands
- Scenario simulation integration (auto-engage and auto-route setting)
- **Launch file:** `tier4_autoware_api_component.launch.xml`

Typical resource usage:

- **CPU**: Minimal
- **GPU**: Not required
- **Memory**: ~500 MB–1 GB

## Used In

- [Planning Simulation](../deployment/planning-simulation/index.md) — Provides the API for setting initial pose and goal
- [Scenario Simulation](../deployment/scenario-simulation/index.md) — Used by the scenario runner to engage, set routes, and monitor state
- [Logging Simulation](../deployment/logging-simulation/index.md) — Provides API access during rosbag replay

All deployments include the `api` container because it is the standard entry point for external interaction with the Autoware stack.

## Related

- [Autoware Interface design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/interfaces/)
- [Autoware AD API documentation](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-interfaces/ad-api/)
- [Deployments](../deployment/index.md) — How the API container is composed with other components
