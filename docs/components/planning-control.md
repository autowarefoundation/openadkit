# Planning & Control

## Overview

The `planning-control` image packages planning and control into a single build target. Planning produces the driving trajectory for the ego vehicle; control follows it by computing steering, throttle, and brake commands and translating them into vehicle-specific actuation. In Open AD Kit deployments the two containers run separately — sharing the image while allowing independent scaling, restarting, and monitoring.

## Planning

The planning pipeline covers four stages — route planning (high-level path selection), behavior planning (lane selection, intersection handling, emergency decisions), motion planning (smooth trajectory generation with obstacle avoidance), and goal planning (final approach and parking maneuvers):

- Route planning along lanelet2-based road networks
- Behavior planning for lane changes, intersection negotiation, and obstacle response
- Motion planning with smooth, kinematically feasible trajectory generation
- Goal planning for final approach, parking, and maneuvering near the destination
- Emergency planning and fallback trajectory generation (Minimum Risk Maneuver, MRM)
- **Launch file:** `tier4_planning_component.launch.xml`

## Control

The control stack supports PID feedback, Model Predictive Control, and a vehicle command interface:

- Lateral trajectory tracking (steering control)
- Longitudinal trajectory tracking (velocity and acceleration control)
- PID-based and MPC-based controller modes
- Raw vehicle command conversion to vehicle-specific actuation limits
- Emergency stop and external heartbeat monitoring
- **Launch file:** `tier4_control_component.launch.xml`

## Resource Usage

- **CPU**: Moderate — both components run entirely on CPU (multi-core recommended for complex scenarios)
- **GPU**: Not required
- **Memory**: ~2–4 GB combined, depending on map complexity and scenario density

## Used In

- [Planning Simulation](../deployment/planning-simulation/index.md) — Core planning and control stack with a demo map
- [Scenario Simulation](../deployment/scenario-simulation/index.md) — Predefined traffic scenarios
- [Logging Simulation](../deployment/logging-simulation/index.md) — Real-world replayed data
- [CARLA Simulation](../deployment/carla-simulation/index.md) — Simulated urban environment

## Related

- [Autoware planning design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/planning/)
- [Autoware control design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/control/)
- [Planning Simulation](../deployment/planning-simulation/index.md) — Run the full planning and control stack
