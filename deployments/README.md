# Open AD Kit Deployments

This directory contains deployment configurations for Open AD Kit.

## Quick Links

For **complete documentation**, operational steps, and troubleshooting, see the [Open AD Kit Documentation Site](https://autowarefoundation.github.io/openadkit/deployments/).

## Available Deployments

- [Planning Simulation](./planning-simulation) — Planning stack with a sample map
- [Scenario Simulation](./scenario-simulation) — Predefined scenario validation with TIER IV Scenario Simulator
- [Logging Simulation](./logging-simulation) — End-to-end stack with rosbag replay
- [CARLA Simulation](./carla-simulation) — Closed-loop planning with CARLA (`./openadkit run carla-simulation --gpu`)

## Directory Layout

```text
deployments/
├── base/                     # shared Compose + Zenoh fragment + container runtime.env
├── planning-simulation/      # complete deployment config.env
├── scenario-simulation/      # complete deployment config.env
├── logging-simulation/       # complete deployment config.env
└── carla-simulation/         # CLI deployment (Humble, amd64, GPU)
```

Scenario and CARLA also provide split-host roles over Zenoh: see the
[split-host runbook](https://autowarefoundation.github.io/openadkit/deployments/samples/split-host/).
