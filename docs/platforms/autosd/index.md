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

## In This Repository

AutoSD assets live under
[`platforms/autosd/`](https://github.com/autowarefoundation/openadkit/tree/main/platforms/autosd).
Each use case contains Quadlet files for its services and Automotive Image
Builder files for its OS image.

- [Planning Simulator](planning-simulator/index.md): Autoware planning and
  Scenario Simulator under Podman and Quadlet
- [R-Car X5H](https://github.com/autowarefoundation/openadkit/tree/main/platforms/autosd/x5h):
  AutoSD 10 image for the R-Car X5H board, tested in QEMU before board bring-up

!!! note "Current scope"
    These are platform demos. They run upstream Autoware images, not the modular
    Open AD Kit component images. Mapping the components onto AutoSD's
    root and QM partitions is on the [roadmap](../../releases/index.md).

## Build an Image {: #building-an-autosd-image }

You need Docker or Podman and QEMU. Run these commands from a use-case directory
such as `platforms/autosd/planning-simulator/`.

Download the Automotive Image Builder runner and build its container:

```bash
curl -fL -o auto-image-builder.sh \
  "https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/raw/main/auto-image-builder.sh?ref_type=heads"
chmod +x auto-image-builder.sh
sudo bash ./auto-image-builder.sh build-builder --distro autosd10-sig
```

Build the image. The arguments are the manifest, the container image name, and
the disk image to write:

```bash
sudo bash ./auto-image-builder.sh build \
  --distro autosd10-sig \
  --target qemu \
  --define-file aib/vars.yml \
  aib/image.aib.yml \
  localhost/awf-oak:latest \
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
heavier workloads. `-m 2G` is enough only to boot and explore the OS.
