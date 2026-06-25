# Open AD Kit

<div align="center">

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen.svg)](https://autowarefoundation.github.io/openadkit/)
[![Autoware Discord](https://img.shields.io/discord/953808765935816715?logo=discord&logoColor=white&style=flat&label=Autoware)](https://discord.gg/Q94UsPvReQ)
[![Autoware](https://img.shields.io/badge/Linkedin-Autoware-0a66c2?logo=linkedin&logoColor=white&style=flat)](https://www.linkedin.com/company/the-autoware-foundation/)

</div>

Open AD Kit packages [Autoware](https://github.com/autowarefoundation/autoware) as a set of focused, independently deployable container images: Autoware provides the autonomy stack; Open AD Kit makes it deployable. It lowers the threshold for deploying Autoware across cloud and edge with composable images, ready-to-run deployment configurations, and a modernized CI/CD approach.

The Autoware Foundation is a voting member of the [SOAFEE (Scalable Open Architecture For the Embedded Edge)](https://soafee.io/) initiative, and Open AD Kit is the first SOAFEE blueprint for the software-defined vehicle ecosystem.

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

## Repository Layout

See [deployments/README.md](deployments/README.md) for the current deployment directory structure and [`.github/image-inventory.json`](.github/image-inventory.json) for the source-of-truth list of container images.

## Documentation

For complete documentation, operational steps, and troubleshooting:

- **[Getting Started](https://autowarefoundation.github.io/openadkit/getting-started/)**
- **[Documentation](https://autowarefoundation.github.io/openadkit/)**
- **[Supported Platforms](https://autowarefoundation.github.io/openadkit/platforms/)** — Hardware and platform support status
- **[Development](https://autowarefoundation.github.io/openadkit/development/)** — Build from source and contribute

## Release Flow

Maintainers promote an existing build instead of rebuilding during release. See the canonical **[Release Flow](https://autowarefoundation.github.io/openadkit/getting-started/release-flow/)** page for the current step list and validation gates. The build metadata, scan metadata, and `.github/image-inventory.json` are the source of truth for release validation.

## Container Image Tags

Open AD Kit publishes build-specific, release, latest-stable, and CI development image tags to GitHub Container Registry. See the canonical **[Container Image Tags](https://autowarefoundation.github.io/openadkit/getting-started/image-tags/)** page for the full tag taxonomy, examples, and pinning guidance. Use stable release tags for fully pinned deployments; compose files use default ROS distro aliases for convenience. CUDA image aliases are amd64-only.

## Building Images Locally

Open AD Kit images are built with `docker buildx bake`, driven by
[`components/docker-bake.hcl`](components/docker-bake.hcl). The component
images sit on top of upstream Autoware base images published to
`ghcr.io/autowarefoundation/autoware`.

See [Build from Source](https://autowarefoundation.github.io/openadkit/development/build-from-source/)
for the canonical local build workflow, including the Autoware source checkout
that component Dockerfiles bind-mount during `docker buildx bake`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, DCO sign-off requirement, and deployment validation steps.

## Community

- Autoware Discord: [discord.gg/Q94UsPvReQ](https://discord.gg/Q94UsPvReQ)
- Autoware Foundation LinkedIn: [linkedin.com/company/the-autoware-foundation](https://www.linkedin.com/company/the-autoware-foundation/)

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## Security

To report a security vulnerability, please use [GitHub's private security advisory reporting](https://github.com/autowarefoundation/openadkit/security/advisories/new) rather than a public issue.
