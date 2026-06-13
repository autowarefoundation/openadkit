# Open AD Kit Deployments

This directory contains deployment configurations for Open AD Kit.

## Quick Links

For **complete documentation**, operational steps, and troubleshooting, see the [Open AD Kit Documentation Site](https://autowarefoundation.github.io/openadkit/deployment/).

## Available Deployments

### Samples

Single-machine deployments for learning and development:

- [Planning Simulation](./samples/planning-simulation) — Planning stack with a sample map
- [Scenario Simulation](./samples/scenario-simulation) — Predefined scenario validation with TIER IV Scenario Simulator
- [Logging Simulation](./samples/logging-simulation) — End-to-end stack with rosbag replay
- [CARLA Simulation](./samples/carla-simulation) — Closed-loop planning with CARLA as an external simulator (experimental, amd64 + GPU)

### Demos

Distributed deployments for advanced use cases:

- [Zenoh Bridge](./demos/zenoh-bridge) — Cloud-edge remote visualization with Zenoh ROS 2 bridging

## Directory Layout

```text
deployments/
├── samples/
│   ├── planning-simulation/
│   ├── scenario-simulation/
│   ├── logging-simulation/
│   └── carla-simulation/       # downloads its own assets via start-carla-e2e-demo.sh
├── demos/
│   └── zenoh-bridge/
└── scripts/
    └── fetch-sample-data.sh   # downloads sample maps/rosbags into ~/autoware_map
```
