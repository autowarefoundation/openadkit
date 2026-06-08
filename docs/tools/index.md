# Tools

Open AD Kit uses containerized third-party tools for testing, deploying, and managing autonomous driving systems. These tools complement the **Autoware components** and can be integrated into deployments as needed.

## Scenario Simulator

The [TIER IV Scenario Simulator](https://tier4.github.io/scenario_simulator_v2-docs/) enables users to test their autonomous driving system in a virtual environment. It uses a scenario runner to execute more complex simulations based on predefined scenarios, and it can be used both in CI and on a local machine.

Open AD Kit deployments use the official TIER IV runtime image directly instead of building a custom wrapper image. See the [Scenario Simulation sample](../deployments/samples/scenario-simulation/index.md) for a runnable Open AD Kit workflow using `ghcr.io/tier4/scenario_simulator_v2`.
