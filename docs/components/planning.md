# Planning

## Overview

The planning component produces the driving trajectory for the ego vehicle. It is part of the `planning-control` image, which packages both planning and control functionality into a single build target. In Open AD Kit deployments, the planning container runs separately from the control container to allow independent scaling and monitoring, while sharing the same underlying image.

The planning pipeline covers four stages:

- **Route planning** — High-level path selection from start to goal
- **Behavior planning** — Lane selection, intersection handling, emergency decisions
- **Motion planning** — Smooth trajectory generation with obstacle avoidance
- **Goal planning** — Final approach and parking maneuvers

## What This Image Contains

The `planning-control` image includes the full Autoware planning and control stack. For the planning side, this provides:

- Route planning along lanelet2-based road networks
- Behavior planning for lane changes, intersection negotiation, and obstacle response
- Motion planning with smooth, kinematically feasible trajectory generation
- Goal planning for final approach, parking, and maneuvering near the destination
- Emergency planning and fallback trajectory generation (MRM)
- **Launch file:** `tier4_planning_component.launch.xml`

Typical resource usage:

- **CPU**: Moderate (multi-core recommended for complex scenarios)
- **GPU**: Not required — planning runs entirely on CPU
- **Memory**: ~2–4 GB depending on map complexity and scenario density

## Used In

- [Planning Simulation](../deployment/samples/planning-simulation/index.md) — Core planning stack with a sample map
- [Scenario Simulation](../deployment/samples/scenario-simulation/index.md) — Planning in predefined traffic scenarios
- [Logging Simulation](../deployment/samples/logging-simulation/index.md) — Planning against real-world replayed data

## Related

- [Autoware planning design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/planning/)
- [Control](control.md) — The companion component in the same image that executes the planned trajectory
- [Planning Simulation](../deployment/samples/planning-simulation/index.md) — Run the planning stack in a virtual environment
