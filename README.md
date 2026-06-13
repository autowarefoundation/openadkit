# Open AD Kit

<div align="center">

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Documentation](https://img.shields.io/badge/docs-available-brightgreen.svg)](https://autowarefoundation.github.io/openadkit/)
[![Autoware Discord](https://img.shields.io/discord/953808765935816715?logo=discord&logoColor=white&style=flat&label=Autoware)](https://discord.gg/Q94UsPvReQ)
[![Autoware](https://img.shields.io/badge/Linkedin-Autoware-0a66c2?logo=linkedin&logoColor=white&style=flat)](https://www.linkedin.com/company/the-autoware-foundation/)

</div>

## Containerized Components for Autoware

Open AD Kit is a collaborative project developed by the Autoware Foundation and its member companies and alliance partners. It aims to bring software-defined best practices to the Autoware project and to enhance the Autoware ecosystem and capabilities by partnering with other organizations that share the goal of creating software-defined vehicles.

Open AD Kit packages [Autoware](https://github.com/autowarefoundation/autoware) as a set of focused, independently deployable container images: Autoware provides the autonomy stack; Open AD Kit makes it deployable. It lowers the threshold for deploying Autoware across cloud and edge with composable images, ready-to-run deployment configurations, and a modernized CI/CD approach.

## The First SOAFEE Blueprint

The Autoware Foundation is a voting member of the [SOAFEE (Scalable Open Architecture For the Embedded Edge)](https://soafee.io/) initiative, and the Autoware Open AD Kit is the first SOAFEE blueprint for the software-defined vehicle ecosystem.

### Quick Links

- **[Getting Started](https://autowarefoundation.github.io/openadkit/getting-started/)**
- **[Documentation](https://autowarefoundation.github.io/openadkit/)**
- **[Supported Platforms](https://autowarefoundation.github.io/openadkit/platforms/)** — Hardware and platform support status
- **[Development](https://autowarefoundation.github.io/openadkit/development/)** — Build from source and contribute

## Container Image Tags

Open AD Kit publishes build-specific, release, latest-stable, and CI development image tags to GitHub Container Registry.

- Stable release tags are immutable and use `<target>-<ros_distro>-vX.Y.Z`, for example `ghcr.io/autowarefoundation/openadkit:planning-control-humble-v2.0.0`.
- Latest stable aliases use `<target>-<ros_distro>` and `<target>-<ros_distro>-latest`, for example `ghcr.io/autowarefoundation/openadkit:planning-control-humble` and `ghcr.io/autowarefoundation/openadkit:planning-control-humble-latest`.
- Default ROS distro aliases use `<target>` and `<target>-latest`, for example `ghcr.io/autowarefoundation/openadkit:planning-control` and `ghcr.io/autowarefoundation/openadkit:planning-control-latest`. The current default ROS distro is Humble.
- Immutable build tags use `<target>-<ros_distro>-<build_tag>`, for example `ghcr.io/autowarefoundation/openadkit:planning-control-humble-123456789-1`.
- CI development aliases are mutable per-platform tags and use `<target>-<arch>-<ros_distro>`, for example `ghcr.io/autowarefoundation/openadkit:planning-control-amd64-humble`. Do not use them for pinned deployments.
- Pre-release tags use `<target>-<ros_distro>-vX.Y.Z-prerelease`, for example `ghcr.io/autowarefoundation/openadkit:planning-control-humble-v2.0.0-rc.1`; pre-releases do not update latest aliases.

Use stable release tags for fully pinned deployments. Sample compose files use default ROS distro aliases for convenience. CUDA image aliases are amd64-only.

## Release Flow

Maintainers promote an existing build instead of rebuilding during release:

1. Run `build-all-images` from `main`. Stable Open AD Kit releases must use an Autoware `X.Y.Z` tag; pre-releases may use an Autoware `X.Y.Z` tag or full 40-character SHA.
2. Keep the build summary's `build_tag`, formatted as `RUN_ID-RUN_ATTEMPT`.
3. Ensure `scan-images` completes successfully for that `build_tag`. Scheduled builds request scans automatically; otherwise run `scan-images` manually.
4. Run the `release` workflow with the Open AD Kit `version` and the validated `build_tag`.

The build metadata, scan metadata, and `.github/image-inventory.json` are the source of truth for release validation.

## Key Features

### Modular Components

Open AD Kit is a microservice-based project designed to run on a variety of platforms. Each component is independent and can be deployed independently.

- **Independent images** for sensing, perception, mapping, localization, planning, control, APIs, simulation, and visualization
- **Multi-platform deployment** supporting both amd64 and arm64 architectures
- **Configurable ROS 2 container deployments** with environment-driven composition

![Granular Components](docs/assets/images/granular-components.png)

### Mixed Criticality

Open AD Kit supports mixed-criticality deployment, separating components by criticality assumption. This architecture allows flexible deployment strategies where higher-criticality driving functions can run on safety-qualified hardware while monitoring and development components operate on standard platforms.

- **Flexible deployment** separating components by criticality assumption
- **Configurable criticality** across development, testing, and vehicle deployment scenarios
- **Hardware abstraction** supporting safety-island compute architectures

![Mixed Criticality](docs/assets/images/mixed-criticality.png)

### Cloud Native

Open AD Kit leverages modern cloud-native technologies to deliver a scalable, portable AD stack.

- **Seamless scaling** from development laptops to in-vehicle edge devices
- **Hybrid cloud support** bridging development and deployment environments
- **Containerized runtimes** using Docker Compose, Docker Bake, and platform-specific integrations such as AutoSD

![Cloud Native](docs/assets/images/cloud-native.png)

### Connected and Continuous

Open AD Kit works toward an always-connected deployment lifecycle for autonomous driving — building, deploying, testing, observing, and updating modular Autoware deployments from the cloud to the edge.

- **Automated CI/CD** with GitHub Actions integration
- **Optimized build caching** for faster deployment cycles
- **Continuous testing** in containerized environments

![Connected and Continuous](docs/assets/images/connected-continuous.png)

## Building images locally

Open AD Kit images are built with `docker buildx bake`, driven by
[`components/docker-bake.hcl`](components/docker-bake.hcl). The component
images sit on top of upstream Autoware base images published to
`ghcr.io/autowarefoundation/autoware`.

First prepare the Autoware colcon workspace (the same step CI runs):

```bash
pipx install vcs2l
git clone --depth 1 https://github.com/autowarefoundation/autoware.git
mkdir -p autoware/src
vcs import --shallow autoware/src < autoware/repositories/autoware.repos
```

Then build:

```bash
# Build everything (default group)
docker buildx bake -f components/docker-bake.hcl

# Build a single target
docker buildx bake -f components/docker-bake.hcl simulator

# Build the component images (the component group)
docker buildx bake -f components/docker-bake.hcl component

# Override ROS distro / platform / upstream pin
ROS_DISTRO=humble UPSTREAM_TAG=1.2.3 \
  docker buildx bake -f components/docker-bake.hcl \
  --set "*.platform=linux/arm64" simulator
```

See the [components documentation](https://autowarefoundation.github.io/openadkit/components/)
for the full bake-group structure and CI pipeline details.
