# Vehicle and System

## Overview

The `vehicle-system` image packages both the **vehicle interface** and **system-level services** used by Open AD Kit deployments. These two services are built from the same image but are deployed as separate containers so that vehicle actuation and system diagnostics can be scaled and monitored independently.

## What This Image Contains

### Vehicle Services

The vehicle container provides the bridge between Autoware's generic control commands and the vehicle's physical actuators:

- Vehicle actuation and state reporting
- Raw vehicle command conversion (steering, throttle, brake, gear, turn signal)
- Vehicle info parameter management (dimensions, limits, kinematics)
- **Launch file:** `tier4_vehicle_launch/vehicle.launch.xml`

### System Services

The system container provides health monitoring, diagnostics, and orchestration:

- System health monitoring and heartbeat management
- Diagnostic aggregation and publishing
- Emergency handling (MRM — Minimum Risk Maneuver)
- System monitor for CPU, memory, and process health
- **Launch file:** `tier4_system_component.launch.xml`

### Difference Between Vehicle and System Services

| | Vehicle | System |
|---|---|---|
| **Purpose** | Talks to the real or simulated vehicle hardware | Monitors the overall Autoware stack and reports system health |
| **Outputs** | Actuation commands (steering, throttle, brake) | Diagnostic status, health reports, emergency state signals |
| **When it runs** | Required whenever the vehicle moves or reports state | Required in all deployments for system health and diagnostic monitoring |
| **Typical customization** | Vehicle model, sensor model, interface type | System monitor enablement, dummy diag publisher, run mode |

Typical resource usage for both services combined:

- **CPU**: Low
- **GPU**: Not required
- **Memory**: ~1–2 GB total across both containers

## Used In

- [Planning Simulation](../deployment/planning-simulation/index.md)
- [Scenario Simulation](../deployment/scenario-simulation/index.md)
- [Logging Simulation](../deployment/logging-simulation/index.md)

All deployments use the `vehicle-system` image because every running stack requires both vehicle actuation and system-level health monitoring.

## Related

- [Autoware vehicle design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/vehicle/)
- [Autoware system design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/system/)
- [Deployments](../deployment/index.md) — How vehicle and system containers are composed into running stacks
