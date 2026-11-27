# Open AD Kit Deployments

The deployments the CLI and the release bundle ship. The
[documentation site](https://autowarefoundation.github.io/openadkit/deployments/)
is the canonical reference for running, configuring and troubleshooting them.

| Directory | Deployment |
| --- | --- |
| [`planning-simulation/`](./planning-simulation) | Plan and follow a route on a sample map with the built-in simulator; `--gpu` plans with the Diffusion Planner |
| [`scenario-simulation/`](./scenario-simulation) | Run predefined traffic scenarios in Scenario Simulator |
| [`logging-simulation/`](./logging-simulation) | Replay recorded sensor data through sensing, perception and localization |
| [`carla-simulation/`](./carla-simulation) | Drive in closed loop with the CARLA simulator (Humble, amd64, NVIDIA GPU) |
| [`safety-island-simulation/`](./safety-island-simulation) | Planning Simulation driven by the Autoware Safety Island controller |
| `shared/` | What the deployments share: Autoware's services (`services/*.yaml`), `runtime.env`, `cyclonedds.xml`, launch files and checks |

Each deployment directory holds its deployment manifest (`deployment.json`),
its settings (`settings.env`, and `settings.gpu.env` for a GPU mode) and its
Compose files. Scenario and CARLA Simulation also declare
[split-host](https://autowarefoundation.github.io/openadkit/deployments/split-host/)
roles (`--role` over Zenoh, experimental).

`shared/` holds only what runs on Open AD Kit's own images. A service on a
third-party image, such as a simulator or the Zenoh bridge, is defined in the
deployment that uses it, and `openadkit.json` pins its image under
`externalImages`.
