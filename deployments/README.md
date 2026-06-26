# Open AD Kit Deployments

This directory contains deployment configurations for Open AD Kit.

## Quick Links

For **complete documentation**, operational steps, and troubleshooting, see the [Open AD Kit Documentation Site](https://autowarefoundation.github.io/openadkit/deployment/).

## Available Deployments

- [Planning Simulation](./planning-simulation) — Planning stack with a sample map
- [Scenario Simulation](./scenario-simulation) — Predefined scenario validation with TIER IV Scenario Simulator
- [Logging Simulation](./logging-simulation) — End-to-end stack with rosbag replay
- [CARLA Simulation](./carla-simulation) — Closed-loop planning with CARLA as an external simulator (experimental, amd64 + GPU)
- [Zenoh Bridge](./zenoh-bridge) — Cloud-edge remote visualization with Zenoh ROS 2 bridging

## Directory Layout

```text
deployments/
├── base/                     # shared services pulled in by other deployments
├── planning-simulation/
├── scenario-simulation/
├── logging-simulation/
├── carla-simulation/         # downloads its own assets via start-carla-e2e-demo.sh
└── zenoh-bridge/
```
