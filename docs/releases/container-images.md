# Container Images

Open AD Kit publishes images to the GitHub Container Registry (`{{ registry }}`).
This page is the reference for image tags, versions, and what "supported" means.

## Tag Reference

A release promotes an existing CI build instead of rebuilding it, so the
images tested in CI are the images that ship.

| Tag | Example | Created | Moves? |
|-----|---------|---------|--------|
| **Release** | `planning-humble-v2.0.0` | Every release | No |
| **Latest alias** | `planning-humble` | Stable releases | Yes |
| **Pre-release** | `planning-humble-v2.0.0-rc.1` | Pre-releases | No |
| **CI build** | `planning-humble-123456789-1` | Every CI build (`<run_id>-<run_attempt>`) | No |

Pre-releases never move the latest aliases. No alias leaves out the
distro, so an image never switches ROS distro under the same tag.

Examples use **{{ default_distro_title }}**, the default distro. Jazzy images use
the same patterns with `-jazzy` (for example `planning-jazzy`).
`sensing-perception-cuda` and `planning-cuda` are amd64-only, and only the amd64
`simulator` carries the CARLA client.

## Choosing a Tag

- **Reproducible deployments**: use a release tag (`vX.Y.Z`) or a digest.
- **Latest stable for a distro**: use `<target>-<ros_distro>`.
- **Never** pin per-architecture tags such as `universe-common-amd64-humble`:
  CI moves them with every build of `main`, and pushes them only for the
  common images its own builds start from. `universe-common`, the runtime base
  of the component images, is not released; `universe-common-devel` is.
- **Source checkout**: `./openadkit` runs `<target>-<arch>-<ros_distro>`, the
  tags of a [local build](../development/build-from-source.md), not published
  images.

## ROS Distro Support

| Distro | Status |
|--------|--------|
| **Humble** | Default |
| **Jazzy** | Supported |

A release bundle pins images for both distros; choose one with `--ros-distro`.
A release needs the evidence cells of both distros to pass its
[gate](evidence.md), and a distro is supported only while it is
supported upstream. Changing the default takes a reviewed manifest change and
passing evidence; a release never falls back to another distro by itself.
Evidence runs on amd64 and arm64 hosts; the CUDA images, which are amd64-only,
are checked by hand.

### ROS Package Snapshot

Every image installs its ROS packages from one dated
[ROS snapshot](http://snapshots.ros.org/): the one the upstream Autoware images
of that release were built from. Compiled code and runtime therefore use the
same ROS versions, and the build fails if they would differ. The release BOM
names the snapshot per distro; an image carries it as a label:

```bash
docker inspect --format '{{ "{{" }} index .Config.Labels "org.autoware.openadkit.ros-snapshot" {{ "}}" }}' \
  {{ registry }}:planning-humble
```

The snapshot changes only with the upstream Autoware release. Ubuntu packages
are not pinned, so security updates keep flowing into new builds.

## Image Reference

Generated from the image inventory (`.github/image-inventory.json`), so it always
matches what CI builds. The [Tag Reference](#tag-reference) explains the tag names.

{{ component_table() }}
