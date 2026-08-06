# Open AD Kit Deployments

This directory contains deployment configurations for Open AD Kit.

## Quick Links

For **complete documentation**, operational steps, and troubleshooting, see the [Open AD Kit Documentation Site](https://autowarefoundation.github.io/openadkit/deployments/).

## Available Deployments

- [Planning Simulation](./planning-simulation) — Planning stack with a sample map
- [Logging Simulation](./logging-simulation) — End-to-end stack with rosbag replay
- [Scenario Simulation](./samples/scenario-simulation) — Predefined scenario validation with TIER IV Scenario Simulator
- [CARLA Simulation](./samples/carla-simulation) — Closed-loop planning with CARLA as an external simulator (experimental, amd64 + GPU)
- [Zenoh Bridge](./demos/zenoh-bridge) — Cloud-edge remote visualization with Zenoh ROS 2 bridging

## Directory Layout

```text
deployments/
├── base/                     # shared Compose + container runtime.env
├── planning-simulation/      # complete deployment config.env
├── logging-simulation/       # complete deployment config.env
├── samples/                  # scenario and CARLA deployments
└── demos/                    # Zenoh bridge deployment
```
