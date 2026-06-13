# Open AD Kit Deployments

This directory contains deployment configurations for **Open AD Kit**. Each folder contains a README file with detailed instructions on how to deploy the deployment configuration.

- **Sample deployment** configurations for development and testing.
  - [AWSIM Simulation](./samples/awsim-simulation): Open AD Kit deployment that demonstrates the open-source planning stack with AWSIM v2 as an external simulator.
  - [CARLA Simulation](./samples/carla-simulation): Simple Open AD Kit deployment that demonstrates the open-source planning stack with CARLA as an external simulator.
  - [Planning Simulation](./samples/planning-simulation): Simple Open AD Kit deployment that demonstrates the autoware **planning features** with planning simulation.
  - [Scenario Simulation](./samples/scenario-simulation): Simple Open AD Kit deployment that demonstrates **scenario-based validation** with the TIER IV Scenario Simulator.
  - [Logging Simulation](./samples/logging-simulation): Simple Open AD Kit deployment that demonstrates the autoware **end-to-end functionality** with sensor simulation using rosbag.
- **Demo deployment** configurations with specific use case scenarios.
  - [Zenoh Bridge](./demos/zenoh-bridge): A demo of remote visualization with Zenoh bridge. See the [Zenoh Bridge documentation](../docs/deployments/demos/zenoh-bridge/index.md) for more details.
