# Container Images & Versioning

Open AD Kit publishes images to the GitHub Container Registry (`{{ registry }}`).
This page is the reference for image tags, versions, and what "supported" means.

## Tag Reference

Releases are promoted from existing CI builds rather than rebuilt, so the images
tested in CI are the images that ship. Every tag below points at a promoted
image digest.

| Tag | Example | Created | Moves? |
|-----|---------|---------|--------|
| **Release** | `planning-control-humble-v2.0.0` | Every release | No |
| **Latest per distro** | `planning-control-humble` | Stable releases | Yes |
| **Default distro** | `planning-control` | Stable releases, default distro only | Yes |
| **Pre-release** | `planning-control-humble-v2.0.0-rc.1` | Pre-releases | No |
| **CI build** | `planning-control-humble-123456789-1` | Every CI build (`<run_id>-<run_attempt>`) | No |

The moving aliases also exist with a `-latest` suffix
(`planning-control-humble-latest`, `planning-control-latest`). Pre-releases
never update them.

Examples use **{{ default_distro_title }}**, the default distro. Jazzy images use
the same patterns with `-jazzy` (for example `planning-control-jazzy`).
`sensing-perception-cuda` and `carla-interface` are amd64-only.

## Choosing a Tag

- **Reproducible deployments**: use a release tag (`vX.Y.Z`) or a digest.
- **Latest stable for a distro**: use `<target>-<ros_distro>`.
- **Quick experiments**: use the default alias `<target>`.
- **Never** pin per-platform CI tags such as `planning-control-amd64-humble`;
  they move with every build.

## Versioning

Open AD Kit uses [Semantic Versioning](https://semver.org/)
(`vMAJOR.MINOR.PATCH`):

| Part | Increments when |
|------|-----------------|
| **MAJOR** | A backward-incompatible change to the image set, the documented deployment layout, or a supported platform is removed. |
| **MINOR** | New backward-compatible capability: components, platforms, deployments, or tooling. |
| **PATCH** | Backward-compatible fixes: bugs, CVE remediation, image refreshes, and documentation. |

The Open AD Kit version is **independent of the Autoware version**. Each release
pins one upstream Autoware release, the ROS 2 distros, and every image digest,
and lists them in its
[GitHub Release](https://github.com/autowarefoundation/openadkit/releases)
notes.

## ROS 2 Distro Support

| Distro | Status |
|--------|--------|
| **Humble** | Default |
| **Jazzy** | Published in parallel where the amd64 and arm64 builds pass |

A release bundle carries pinned images for both distros; choose one with
`--ros-distro`. A distro is supported only while it is supported upstream.

## What "Supported" Means

- **Releases**: the latest stable release is supported. Fixes, including CVE
  remediation, ship in a new release; older releases are not patched.
- **Platforms**: support is tiered (committed, experimental, best-effort,
  unsupported). See [Supported Platforms](../platforms/index.md).
- **No certification claims**: Open AD Kit makes no safety-certification,
  functional-safety, or production-readiness claims.

Maintainers: see the [Release Process](../development/build-from-source.md#release-process).
