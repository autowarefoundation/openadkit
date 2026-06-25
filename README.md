# Open AD Kit

<div align="center">

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen.svg)](https://autowarefoundation.github.io/openadkit/)
[![Autoware Discord](https://img.shields.io/discord/953808765935816715?logo=discord&logoColor=white&style=flat&label=Autoware)](https://discord.gg/Q94UsPvReQ)
[![Autoware](https://img.shields.io/badge/Linkedin-Autoware-0a66c2?logo=linkedin&logoColor=white&style=flat)](https://www.linkedin.com/company/the-autoware-foundation/)
[![SOAFEE](https://img.shields.io/badge/SOAFEE-first%20blueprint-orange)](https://soafee.io/)

**First [SOAFEE](https://soafee.io/) blueprint for software-defined vehicles.**

</div>

Open AD Kit packages [Autoware](https://github.com/autowarefoundation/autoware) as a set of focused, independently deployable container images: Autoware provides the autonomy stack; Open AD Kit makes it deployable. It lowers the threshold for deploying Autoware across cloud and edge with composable images, ready-to-run deployment configurations, and a modernized CI/CD approach.

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

## Documentation

For complete documentation, operational steps, and troubleshooting:

- **[Getting Started](https://autowarefoundation.github.io/openadkit/getting-started/)**
- **[Documentation](https://autowarefoundation.github.io/openadkit/)**
- **[Release Flow](https://autowarefoundation.github.io/openadkit/getting-started/release-flow/)** — Promote existing builds instead of rebuilding at release time
- **[Supported Platforms](https://autowarefoundation.github.io/openadkit/platforms/)** — Hardware and platform support status
- **[Build from Source](https://autowarefoundation.github.io/openadkit/development/build-from-source/)** — Build component images locally with `docker buildx bake`

## Container Image Tags

Open AD Kit publishes build-specific, release, latest-stable, and CI development image tags to GitHub Container Registry. See the canonical **[Container Image Tags](https://autowarefoundation.github.io/openadkit/getting-started/image-tags/)** page for the full tag taxonomy, examples, and pinning guidance. Use stable release tags for fully pinned deployments; compose files use default ROS distro aliases for convenience. CUDA image aliases are amd64-only.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, DCO sign-off requirement, and deployment validation steps.

Join the community:

- Autoware Discord: [discord.gg/Q94UsPvReQ](https://discord.gg/Q94UsPvReQ)
- Autoware Foundation LinkedIn: [linkedin.com/company/the-autoware-foundation](https://www.linkedin.com/company/the-autoware-foundation/)

## License

Apache License 2.0 — see [LICENSE](LICENSE).
