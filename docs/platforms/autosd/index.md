# AutoSD

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

Use the `openadkit` of an installed release and `platforms/autosd` from the same
tag: the release's CLI puts the image digests in the model, so the result is
pinned. From a source checkout the images are moving aliases. Kits work the same
way, such as `openadkit config ./my-kit`.

| Output | Contents |
|--------|----------|
| `out/rootfs/etc/containers/systemd/` | A Quadlet unit per service, named after its container |
| `out/rootfs/usr/share/openadkit/` | The bind-mounted files and data, by mount target |
| `out/image.aib.yml` | Automotive Image Builder manifest that embeds the images and `rootfs/`; written only with `--root-password-hash`, since an image has no default password |

A Compose field the script does not translate stops it instead of being dropped.
It covers what Planning Simulation uses; writable mounts, for example, have no
translation yet.

The units run as root with the deployment's host networking. They use the
component images, and mapping them onto AutoSD's root and QM partitions is not
done yet.

!!! warning "Evidence scope"
    Evidence runs these units under Podman and systemd on Ubuntu 24.04 and drives
    the golden path. CI does not build or boot the image below. An image built from
    these units was driven once by hand: it booted in QEMU with SELinux enforcing
    and no outside network, and the golden path arrived.

## Run on a Podman Host

The tree is what an image would contain, so a host with Podman 4.9 or newer,
`catatonit` and systemd can run it:

```bash
sudo cp -a out/rootfs/. /
sudo systemctl daemon-reload
sudo systemctl start autoware-api autoware-control autoware-perception-simulation \
  autoware-planning autoware-simulator autoware-system autoware-vehicle
systemctl status 'autoware-*'
journalctl -u autoware-control -f
```

Quadlet registers each `.container` file as a `.service` unit. The units pull
their images on first start, which takes a while.

## Build an Image {: #building-an-autosd-image }

You need Podman and QEMU; the runner does not work with Docker. Download the Automotive Image Builder runner
and build its container:

```bash
curl -fL -o auto-image-builder.sh \
  "https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/raw/main/auto-image-builder.sh?ref_type=heads"
chmod +x auto-image-builder.sh
sudo bash ./auto-image-builder.sh build-builder --distro autosd10-sig
```

Build the image from the directory you generated `out` in, because the manifest
names its large files by path. `/var/tmp` goes on disk because the runner's own
is in memory and too small for this image. The arguments are the manifest, the container
image name, and the disk image to write:

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

With `air` installed:

```bash
air disk.qcow2
```

Or with QEMU directly:

```bash
/usr/bin/qemu-system-x86_64 \
  -drive file=/usr/share/OVMF/OVMF_CODE.fd,if=pflash,format=raw,unit=0,readonly=on \
  -drive file=/usr/share/OVMF/OVMF_VARS.fd,if=pflash,format=raw,unit=1,snapshot=on,readonly=off \
  -smp 20 \
  -nographic \
  -enable-kvm \
  -m 16384 \
  -machine q35 \
  -cpu host \
  -device virtio-net-pci,netdev=n0,mac=FE:00:e2:0d:ba:4d \
  -netdev user,id=n0,net=10.0.2.0/24,hostfwd=tcp::2222-:22 \
  -drive file=disk.qcow2,index=0,media=disk,format=qcow2,if=virtio,id=rootdisk,snapshot=off
```

`-m 16384` (16 GB) is the minimum for the Autoware stack; use `-m 32768` for
heavier workloads. `-m 2G` is enough only to boot and explore the OS. Log in as
`root` with the password `password` from the command above, which is for this demo only.

## Boards

- [R-Car X5H](https://github.com/oguzkaganozt/rcar-x5h-autosd): AutoSD 10 image for the R-Car X5H board, kept in its own repository.
