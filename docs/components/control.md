# Control

## Overview

The control component follows the planned trajectory by computing steering, throttle, and brake commands and translating them into vehicle-specific actuation. It is part of the `planning-control` image, which packages both planning and control functionality into a single build target. The control container runs independently in Open AD Kit deployments so that it can be scaled, restarted, or monitored separately from planning.

The control stack supports:

- **PID control** — Proportional-Integral-Derivative feedback for steering and velocity
- **MPC control** — Model Predictive Control for optimal trajectory tracking
- **Vehicle command interface** — Translation of control outputs to vehicle-specific actuation

## What This Image Contains

The `planning-control` image includes the full Autoware planning and control stack. For the control side, this provides:

- Lateral trajectory tracking (steering control)
- Longitudinal trajectory tracking (velocity and acceleration control)
- PID-based and MPC-based controller modes
- Raw vehicle command conversion to vehicle-specific actuation limits
- Emergency stop and external heartbeat monitoring
- **Launch file:** `tier4_control_component.launch.xml`

Typical resource usage:

- **CPU**: Low to moderate
- **GPU**: Not required — control runs entirely on CPU
- **Memory**: ~1–2 GB

## Used In

- [Planning Simulation](../deployment/planning-simulation/index.md) — Executes planned trajectories in a virtual environment
- [Scenario Simulation](../deployment/scenario-simulation/index.md) — Control in predefined traffic scenarios
- [Logging Simulation](../deployment/logging-simulation/index.md) — Control against real-world replayed data
- [CARLA Simulation](../deployment/carla-simulation/index.md) — Control of the CARLA ego vehicle

## Related

- [Autoware control design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/control/)
- [Planning](planning.md) — The companion component in the same image that generates the trajectory
- [Planning Simulation](../deployment/planning-simulation/index.md) — Run the full planning and control stack
