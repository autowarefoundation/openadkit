# Versioning & Support Policy

This page defines how Open AD Kit is versioned, how releases map to Autoware, and what "supported" means. It is the canonical reference for the project's versioning and support commitments.

## Version Scheme

Open AD Kit releases use [Semantic Versioning](https://semver.org/): `vMAJOR.MINOR.PATCH` (for example, `v2.0.0`).

| Component | Increments when |
|-----------|-----------------|
| **MAJOR** | A backward-incompatible change to the public deployment surface — image taxonomy, documented compose/deployment layout, or removal of a supported platform/variant. |
| **MINOR** | New backward-compatible capability — additional components, platforms, deployments, or CI/release machinery. |
| **PATCH** | Backward-compatible fixes — bug fixes, security/CVE remediation, image refreshes, and documentation corrections within the same release surface. |

The Open AD Kit version is **independent of the Autoware version** it packages: a single Open AD Kit release pins a specific upstream Autoware release (see below), and a new Autoware release does not automatically change the Open AD Kit version.

## Relationship to Autoware

Each Open AD Kit release pins a specific upstream **Autoware semver meta-release** and records it in the release:

- Stable Open AD Kit releases pin an Autoware `X.Y.Z` meta-release tag.
- `v2.0.0` pins Autoware **1.8.0**.

A release pins, at minimum: the Open AD Kit version, the Autoware meta-release, the ROS 2 distro(s), and the published image tags and digests. The full per-release detail lives in the [Release Flow](release-flow.md) and the published image inventory; how to consume the tags is in [Container Image Tags](image-tags.md).

## ROS 2 Distro Support

| Distro | Status at v2.0 |
|--------|----------------|
| **Humble** | Default, documented path. The default-distro image aliases (`<target>`) resolve to {{ default_distro_title }}. |
| **Jazzy** | Built and published **in parallel** (`<target>-jazzy`) wherever the `amd64`+`arm64` matrix is green. |

Each release pins its ROS distro(s), and Humble and Jazzy are built while both matrices are green. Jazzy is promoted to the primary documented path at the first release with a sustained green Jazzy `amd64`+`arm64` matrix. Distro support tracks the upstream ROS 2 lifecycle — a distro is supported by Open AD Kit only while it is supported upstream.

## What "Supported" Means

- **Releases** — The latest stable release is supported. Fixes (including security/CVE remediation) land in a new patch or minor release rather than being backported to older tags. Stable release tags are immutable; pin to a fully qualified `<target>-<ros_distro>-vX.Y.Z` tag for reproducible deployments.
- **Platforms** — Support is tiered (committed / experimental / best-effort / unsupported). A variant that does not pass its build/validation gate is dropped from the support matrix rather than shipped as if it worked. See [Supported Platforms](../platforms/index.md) for the current, honest matrix.
- **No certification claims** — "Supported" refers to build, deployment, and validation in a non-certified environment. Open AD Kit makes no safety-certification, functional-safety, or production-readiness claims.

## Getting Help

- Questions and bug reports: [GitHub Issues](https://github.com/autowarefoundation/openadkit/issues).
- See also [Troubleshooting](troubleshooting.md).
