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
| **Pre-release** | `planning-control-humble-v2.0.0-rc.1` | Pre-releases | No |
| **CI build** | `planning-control-humble-123456789-1` | Every CI build (`<run_id>-<run_attempt>`) | No |

Releases promote a CI build of `main` (see [Versioning](#versioning)).

Pre-releases never move the latest-per-distro aliases. No alias leaves out the
distro, so an image never switches ROS distro under the same tag.

Examples use **{{ default_distro_title }}**, the default distro. Jazzy images use
the same patterns with `-jazzy` (for example `planning-control-jazzy`).
`sensing-perception-cuda` and `carla-interface` are amd64-only.

## Choosing a Tag

- **Reproducible deployments**: use a release tag (`vX.Y.Z`) or a digest.
- **Latest stable for a distro**: use `<target>-<ros_distro>`.
- **Never** pin per-platform CI tags such as `universe-common-amd64-humble`;
  they move with every build of `main`.

## Versioning

Open AD Kit versions follow [Semantic Versioning](https://semver.org/) on their
own, starting at `v2.0.0`: a backward-incompatible change to the CLI, the
manifests or a deployment raises the major version, and a move to a new
Autoware release raises at least the minor version. The release notes list what
breaks.

Releases come from `main`, which pins one Autoware release in
`.github/autoware.ref`. Every release pairs the two in its
[GitHub Release](https://github.com/autowarefoundation/openadkit/releases) title,
`Open AD Kit v2.0.1 · Autoware 2.0.0`, and so do `openadkit install` and
`openadkit version`. The release also pins the ROS 2 distros and every image
digest, and its images carry `org.opencontainers.image.autoware-base-version`.
A fix that is upstream but not yet in an Autoware release can be
[backported](../releases/evidence.md#backporting-an-autoware-fix); the release
notes list it, and the Autoware version stays the tag's. A `release/X.Y` branch
is created from a release tag only to fix an older version.

## ROS 2 Distro Support

| Distro | Status |
|--------|--------|
| **Humble** | Default |
| **Jazzy** | Published where required builds, scans and runtime evidence pass |

A release bundle carries pinned images for both distros; choose one with
`--ros-distro`. A distro is supported only while it is supported upstream.
Non-exempt runtime cells for each declared distro must also pass the
[release evidence gate](../releases/evidence.md). The initial default is Humble;
changing it requires a reviewed manifest change and passing evidence, not an
automatic release-time fallback. Image builds alone do not prove runtime behavior
on every architecture.

### ROS Package Snapshot

Every image installs its ROS packages from one dated
[ROS snapshot](http://snapshots.ros.org/): the one the upstream Autoware images
of that release were built from. Compiled code and runtime therefore use the
same ROS versions, and the build fails if they would differ. Release notes and
the release BOM name the snapshot per distro; an image carries it as a label:

```bash
docker inspect --format '{{ "{{" }} index .Config.Labels "org.opencontainers.image.ros-snapshot" {{ "}}" }}' \
  {{ registry }}:planning-control-humble
```

The snapshot changes only with the upstream Autoware release. Ubuntu packages
are not pinned, so security updates keep flowing into new builds.

## What "Supported" Means

- **Releases**: the latest stable release is supported. Fixes, including CVE
  remediation, ship in a new release; older releases are not patched.
- **Platforms**: support is tiered (committed, experimental, best-effort,
  unsupported). See [Supported Platforms](../platforms/index.md).
- **No certification claims**: Open AD Kit makes no safety-certification,
   functional-safety, or production-readiness claims.

Community help and version coverage are described in
[SUPPORT.md](https://github.com/autowarefoundation/openadkit/blob/main/.github/SUPPORT.md);
report security vulnerabilities through the
[private reporting policy](https://github.com/autowarefoundation/openadkit/blob/main/.github/SECURITY.md).

Maintainers: see the [Release Process](../development/build-from-source.md#release-process).
