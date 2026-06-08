# Autoware Open AD Kit Scenario Simulation

This sample deployment demonstrates the Open AD Kit scenario simulation workflow with the official [TIER IV Scenario Simulator container](https://github.com/tier4/scenario_simulator_v2/pkgs/container/scenario_simulator_v2).

The [TIER IV Scenario Simulator](https://tier4.github.io/scenario_simulator_v2-docs/) enables users to test their autonomous driving system in a virtual environment. It uses a scenario runner to execute more complex simulations based on predefined scenarios, and it can be used both in CI and on a local machine.

Open AD Kit deployments use the official TIER IV runtime image directly instead of building a custom wrapper image.

## Source of Truth

The complete operational instructions for this deployment live alongside the deployment assets in `deployments/samples/scenario-simulation/README.md`.

## Quick Start

From `deployments/samples/scenario-simulation/`:

```bash
docker compose --env-file scenario-simulation.env up -d
```

Open the visualizer at:

```text
http://localhost:6080/vnc.html
```

For remote servers, use `http://<server-ip>:6080/vnc.html` and allow inbound access to port `6080`.

To stop the deployment:

```bash
docker compose --env-file scenario-simulation.env down
```

## Related Documentation

[Scenario test simulation](https://autowarefoundation.github.io/autoware-documentation/main/demos/scenario-simulation/scenario-simulator/scenario-test-simulation/)
