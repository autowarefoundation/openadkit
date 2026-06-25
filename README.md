# Open AD Kit

<div align="center">

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen.svg)](https://autowarefoundation.github.io/openadkit/)
[![Autoware Discord](https://img.shields.io/discord/953808765935816715?logo=discord&logoColor=white&style=flat&label=Autoware)](https://discord.gg/Q94UsPvReQ)
[![Autoware](https://img.shields.io/badge/Linkedin-Autoware-0a66c2?logo=linkedin&logoColor=white&style=flat)](https://www.linkedin.com/company/the-autoware-foundation/)

</div>

Open AD Kit is the first [SOAFEE](https://soafee.io/) blueprint for deploying [Autoware](https://github.com/autowarefoundation/autoware) as containerized, cloud/edge-ready software-defined vehicle components.

This repository provides the component images, deployment configurations, release bundles, and CI metadata needed to run and ship Autoware-based stacks more predictably.

## Quickstart

```bash
git clone https://github.com/autowarefoundation/openadkit.git
cd openadkit

# Install Docker (and NVIDIA Container Toolkit on supported hosts)
./setup.sh

# Start the planning-simulation deployment from the source tree
cd deployments/planning-simulation
docker compose --env-file ../base/base.env --env-file planning-simulation.env up -d
```

Open the noVNC visualizer at `http://localhost:6080/vnc.html` (password: `openadkit`).

For artifact downloads (logging-simulation's perception models), run `./setup.sh --download-artifacts`. For other deployments and the release-bundle workflow, see the [documentation site](https://autowarefoundation.github.io/openadkit/deployment/).

## Deployments

Open AD Kit includes several user-facing deployment configurations, each with its own compose file and environment defaults:

- **[planning-simulation](https://autowarefoundation.github.io/openadkit/deployment/planning-simulation/)** - Run planning with a simulator-backed vehicle interface
- **[logging-simulation](https://autowarefoundation.github.io/openadkit/deployment/logging-simulation/)** - Replay sample data through the logging/perception stack
- **[scenario-simulation](https://autowarefoundation.github.io/openadkit/deployment/scenario-simulation/)** - Run scenario-based simulation workflows
- **[carla-simulation](https://autowarefoundation.github.io/openadkit/deployment/carla-simulation/)** - Connect Autoware to CARLA simulation
- **[zenoh-bridge](https://autowarefoundation.github.io/openadkit/deployment/zenoh-bridge/)** - Bridge Autoware traffic across edge and cloud hosts

## Images and Releases

Open AD Kit publishes build-specific, release, latest-stable, and CI development image tags to GitHub Container Registry. Use stable release tags for fully pinned deployments; compose files use default ROS distro aliases for convenience. CUDA image aliases are amd64-only.

- **[Container Image Tags](https://autowarefoundation.github.io/openadkit/getting-started/image-tags/)** - Tag taxonomy, examples, and pinning guidance
- **[Release Flow](https://autowarefoundation.github.io/openadkit/getting-started/release-flow/)** - How maintainers promote existing builds at release time

## Documentation

For the full docs, platform support, and development guides:

- **[Getting Started](https://autowarefoundation.github.io/openadkit/getting-started/)**
- **[Documentation](https://autowarefoundation.github.io/openadkit/)**
- **[Supported Platforms](https://autowarefoundation.github.io/openadkit/platforms/)** - Hardware and platform support status
- **[Build from Source](https://autowarefoundation.github.io/openadkit/development/build-from-source/)** - Build component images locally with `docker buildx bake`
- **[Contributing](https://autowarefoundation.github.io/openadkit/development/contributing/)** - Development workflow, DCO sign-off, and validation steps

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, DCO sign-off requirement, and deployment validation steps.

Join the community:

- Autoware Discord: [discord.gg/Q94UsPvReQ](https://discord.gg/Q94UsPvReQ)
- Autoware Foundation LinkedIn: [linkedin.com/company/the-autoware-foundation](https://www.linkedin.com/company/the-autoware-foundation/)

## License

Apache License 2.0 - see [LICENSE](LICENSE).
