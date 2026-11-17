# AutoSD

!!! warning "Experimental"
    Running Open AD Kit on AutoSD with Podman and Quadlet may change in a minor
    release. See [Compatibility](../releases/compatibility.md#experimental).

AutoSD (Automotive Stream Distribution) is the public, in-development preview of
**Red Hat In-Vehicle OS**. It is built on CentOS Stream with an automotive
kernel and provides:

- **Mixed criticality**: safety-critical containers in the root partition,
  non-critical ones in an isolated QM partition
- **Atomic updates**: immutable OSTree images with A/B updates and rollback
- **Real-time kernel** for deterministic scheduling
- **Container-native runtime**: Podman, Quadlet (systemd container units), and
  BlueChi orchestration, with no Docker daemon

## Generate a Deployment

Compose stays the single source. `openadkit config` prints a deployment's resolved
Compose model, and `platforms/autosd/quadlet.py` translates it:

```bash
openadkit fetch planning-simulation
openadkit config planning-simulation \
  | python3 platforms/autosd/quadlet.py --output out --without visualizer \
      --root-password-hash "$(openssl passwd -6 password)"
```

Use the `openadkit` of an installed release, and `platforms/autosd` from a
clone of the repository at the same tag (the release bundle does not include
it): the release's CLI puts the image digests in the model, so the result is
pinned. A source checkout names the tags of a local build instead. Kits work
the same way, such as `openadkit config ./my-kit`.

| Output | Contents |
|--------|----------|
| `out/rootfs/etc/containers/systemd/` | A Quadlet unit per service, named after its container |
| `out/rootfs/usr/share/openadkit/` | The bind-mounted files and data, by mount target |
| `out/image.aib.yml` | Automotive Image Builder manifest that embeds the images and `rootfs/`; written only with `--root-password-hash`, since an image has no default password |

A Compose field or value the script does not translate stops it instead of
being dropped. It covers what Planning Simulation uses; writable mounts, for
example, have no translation. A mount of the login session, such as the
visualizer's X11 cookie, stops it too, so leave the visualizer out.

The units run as root with the deployment's host networking. They use the
component images, and are not mapped onto AutoSD's root and QM partitions.

!!! warning "Evidence scope"
    Evidence runs these units under Podman and systemd on Ubuntu 24.04 and drives
    the ego to its goal. CI does not build or boot the image below. An image
    built from these units was driven once by hand: it booted in QEMU with
    SELinux enforcing and no outside network, and the ego arrived at its goal.

## Build an Image {: #building-an-autosd-image }

You need Podman and QEMU; the runner does not work with Docker. Download the
Automotive Image Builder runner and build its container:

```bash
curl -fL -o auto-image-builder.sh \
  "https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/raw/main/auto-image-builder.sh?ref_type=heads"
chmod +x auto-image-builder.sh
sudo bash ./auto-image-builder.sh build-builder --distro autosd10-sig
```

Build the image from the directory you generated `out` in, because the manifest
names its large files by path. `/var/tmp` goes on disk because the runner's own
is in memory and too small for this image. The arguments are the manifest, the
container image name, and the disk image to write:

```bash
sudo mkdir -p /var/tmp/aib-work
sudo AIB_PODMAN_OPTIONS="-v /var/tmp/aib-work:/var/tmp" bash ./auto-image-builder.sh build \
  --distro autosd10-sig \
  --target qemu \
  --define-file platforms/autosd/vars.yml \
  out/image.aib.yml \
  localhost/openadkit:latest \
  disk.qcow2
sudo chown "$(logname)" disk.qcow2
```

To run Automotive Image Builder directly instead, use an RPM-based host (Fedora,
CentOS, or RHEL) with Automotive Image Builder, OSBuild, and QEMU installed.

## Run the Image

Run it with Automotive Image Builder's runner, `air`:

```bash
air disk.qcow2
```

The Autoware stack needs at least 16 GB of memory in the virtual machine. Log in
as `root` with the password you hashed in
[Generate a Deployment](#generate-a-deployment), here `password`, which is for
this demo only.
