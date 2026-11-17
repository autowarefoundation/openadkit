# Open AD Kit

[![Build](https://img.shields.io/github/actions/workflow/status/autowarefoundation/openadkit/build-all-images.yaml?branch=main&label=build)](https://github.com/autowarefoundation/openadkit/actions/workflows/build-all-images.yaml)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen.svg)](https://autowarefoundation.github.io/openadkit/)
[![Release](https://img.shields.io/github/v/release/autowarefoundation/openadkit?label=release)](https://github.com/autowarefoundation/openadkit/releases)
[![ROS 2](https://img.shields.io/badge/ROS%202-Humble%20%7C%20Jazzy-22314E?logo=ros&logoColor=white)](https://autowarefoundation.github.io/openadkit/platforms/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**The deployment layer for the Autoware ecosystem.**

[Autoware](https://github.com/autowarefoundation/autoware) provides the autonomy stack; Open AD Kit makes it deployable. It packages the stack into focused container images and ready-to-run deployments, with [Autoware Safety Island](https://autowarefoundation.github.io/autoware-safety-island/) alongside. One CLI runs them the same way on every host.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/images/readme-hero-dark.svg">
  <img src="docs/assets/images/readme-hero-light.svg" width="100%" alt="One command, openadkit run planning-simulation, starts Autoware as separate containers that talk over ROS 2: localization-mapping, planning, control, vehicle-system, simulator, visualizer and api. One reproducible path from simulation to in-vehicle systems.">
</picture>

## Quickstart

From nothing to a driving Autoware on Ubuntu. No GPU needed. The [full Quickstart](https://autowarefoundation.github.io/openadkit/getting-started/) has the details.

```bash
# 1. Install the CLI
curl -fsSL https://github.com/autowarefoundation/openadkit/releases/latest/download/openadkit \
  | bash -s -- install

# 2. Prepare the host, then start a shell in the docker group it adds you to
openadkit setup
newgrp docker

# 3. Start Autoware
openadkit run planning-simulation

# 4. Drive: open http://localhost:6080/vnc.html (password: openadkit). In RViz,
#    set an initial pose and a goal, then press AUTO in the OperationMode panel.

# 5. Stop
openadkit stop
```

## Deployments

A deployment is a ready-to-run Autoware stack for one task. `openadkit list` prints them in your terminal.

| Deployment | What it runs | Requires |
|---|---|---|
| [`planning-simulation`](https://autowarefoundation.github.io/openadkit/deployments/planning-simulation/) | Plan and follow a route on a sample map<br>`--gpu` plans with the Diffusion Planner (experimental) | |
| [`scenario-simulation`](https://autowarefoundation.github.io/openadkit/deployments/scenario-simulation/) | Predefined traffic scenarios in Scenario Simulator<br>`--role` [splits it across two hosts](https://autowarefoundation.github.io/openadkit/deployments/split-host/) (experimental) | |
| [`logging-simulation`](https://autowarefoundation.github.io/openadkit/deployments/logging-simulation/) | Replay recorded sensor data, sensing to localization<br>`--gpu` runs CenterPoint on CUDA | |
| [`carla-simulation`](https://autowarefoundation.github.io/openadkit/deployments/carla-simulation/) | Closed-loop driving in the CARLA simulator<br>`--role` [splits it across two hosts](https://autowarefoundation.github.io/openadkit/deployments/split-host/) (experimental) | NVIDIA GPU<br>amd64, Humble |
| [`safety-island-simulation`](https://autowarefoundation.github.io/openadkit/deployments/safety-island-simulation/) | Planning Simulation controlled by the Safety Island | amd64 |

## Create a Kit

A kit holds only your differences from a deployment: your ROS packages, config overrides and extra services. [Create a Kit](https://autowarefoundation.github.io/openadkit/kits/create-a-kit/) covers the layout and each extension point.

```bash
openadkit new my-kit        # on top of planning-simulation
cd my-kit
openadkit build             # your overlay workspace
openadkit run --verify      # start, wait until ready, run the verify step
```

## Documentation

- [**Overview**](https://autowarefoundation.github.io/openadkit/) — what Open AD Kit is and how it is put together
- [**CLI & Maintenance**](https://autowarefoundation.github.io/openadkit/getting-started/cli/) — every command, settings, upgrades and cleanup
- [**Troubleshooting**](https://autowarefoundation.github.io/openadkit/getting-started/troubleshooting/) — Docker, data, GPU, visualizer and network
- [**Components**](https://autowarefoundation.github.io/openadkit/deployments/components/) — the container images and what each one runs
- [**Platforms**](https://autowarefoundation.github.io/openadkit/platforms/) — support tiers, AutoSD and host requirements
- [**Releases**](https://autowarefoundation.github.io/openadkit/releases/) — what a release ships, promises and proves
- [**Build from Source**](https://autowarefoundation.github.io/openadkit/development/build-from-source/) — build the images yourself

## Community

- **Working Group** — Thursdays at 13:00 UTC, open to everyone: [calendar](https://www.google.com/calendar/event?eid=YnY4dmJxZTVsM2h2cWE1cTJ2NmhtOWdwMzZfMjAyNjA5MjRUMTMwMDAwWiBhdXRvd2FyZS5vcmdfNmxvbDBobzVmdDAyMTdoOGM2MHBpMWZtMzBAZw) · [agendas](https://github.com/orgs/autowarefoundation/discussions?discussions_q=label%3Ameeting%3Aopenadkit-wg)
- **Chat** — questions and design discussions on the [Autoware Discord](https://discord.gg/Q94UsPvReQ)
- **Contribute** — [CONTRIBUTING.md](CONTRIBUTING.md) has the development workflow and validation steps

## License

Apache License 2.0. See [LICENSE](LICENSE).
