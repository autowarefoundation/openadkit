# Open AD Kit

<div align="center">

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen.svg)](https://autowarefoundation.github.io/openadkit/)
[![Autoware Discord](https://img.shields.io/discord/953808765935816715?logo=discord&logoColor=white&style=flat&label=Autoware)](https://discord.gg/Q94UsPvReQ)
[![Autoware](https://img.shields.io/badge/Linkedin-Autoware-0a66c2?logo=linkedin&logoColor=white&style=flat)](https://www.linkedin.com/company/the-autoware-foundation/)

</div>

> A modular, container-based distribution of [Autoware](https://github.com/autowarefoundation/autoware) for simulation, development, and in-vehicle deployment.

Open AD Kit packages Autoware into focused container images and ready-to-run Docker Compose deployments. It includes a CLI, deployment assets, and build and release automation for running the stack consistently across development and vehicle-edge systems.

Open AD Kit is the first [SOAFEE](https://www.soafee.io/) blueprint for the software-defined vehicle.

## Quick Start

Run the CPU-based planning simulation on Ubuntu 22.04 or 24.04. No GPU is required.

```bash
git clone https://github.com/autowarefoundation/openadkit.git
cd openadkit
./openadkit setup --verify
```

If setup adds you to the Docker group, start a new login session or run `newgrp docker` before continuing.

```bash
./openadkit run planning-simulation
```

When the stack is ready, open [the noVNC visualizer](https://localhost:6080/vnc.html), accept the self-signed certificate, and sign in with the password `openadkit`.

The CLI downloads required data, pulls missing images, starts the services, and verifies readiness. See the [guided quick start](https://autowarefoundation.github.io/openadkit/getting-started/) for installation options, runtime controls, and troubleshooting.

## Deployments

| Deployment | Purpose | GPU |
|---|---|---|
| [`planning-simulation`](https://autowarefoundation.github.io/openadkit/deployments/planning-simulation/) | Plan and follow a route with the built-in simulator | No |
| [`scenario-simulation`](https://autowarefoundation.github.io/openadkit/deployments/scenario-simulation/) | Run predefined traffic scenarios | No |
| [`logging-simulation`](https://autowarefoundation.github.io/openadkit/deployments/logging-simulation/) | Replay recorded sensor data through sensing and perception | Optional |
| [`carla-simulation`](https://autowarefoundation.github.io/openadkit/deployments/carla-simulation/) | Run Autoware in closed loop with CARLA | Required |

Use `./openadkit list` to inspect the deployment catalog. CARLA requires Humble, amd64, and an NVIDIA GPU. The [Zenoh bridge](https://autowarefoundation.github.io/openadkit/deployments/zenoh-bridge/) is available as a standalone source-checkout workflow.

## Documentation

The [documentation site](https://autowarefoundation.github.io/openadkit/) covers:

- [Architecture and components](https://autowarefoundation.github.io/openadkit/overview/)
- [Deployments and custom stacks](https://autowarefoundation.github.io/openadkit/deployments/)
- [Supported platforms](https://autowarefoundation.github.io/openadkit/platforms/)
- [Container images and versioning](https://autowarefoundation.github.io/openadkit/getting-started/container-images/)
- [Building from source](https://autowarefoundation.github.io/openadkit/development/build-from-source/)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and validation steps.

The [Open AD Kit Working Group](https://github.com/autowarefoundation/autoware-projects/wiki/Open-AD-Kit-Working-Group) is open to everyone and meets every Thursday at 13:00 UTC (16:00 TRT). [Add the meeting to Google Calendar](https://www.google.com/calendar/event?eid=YnY4dmJxZTVsM2h2cWE1cTJ2NmhtOWdwMzZfMjAyNjA5MjRUMTMwMDAwWiBhdXRvd2FyZS5vcmdfNmxvbDBobzVmdDAyMTdoOGM2MHBpMWZtMzBAZw) for joining details, and browse the [meeting archive](https://github.com/orgs/autowarefoundation/discussions?discussions_q=label%3Ameeting%3Aopenadkit-wg) for agendas and notes.

For questions and design discussions, join the [Autoware Discord](https://discord.gg/Q94UsPvReQ).

## License

Apache License 2.0 - see [LICENSE](LICENSE).
