# AutoSD + Autoware Open AD Kit

!!! abstract ""
    AutoSD is the upstream binary distribution serving as the public, in-development preview of the **Red Hat In-Vehicle Operating System (RHIVOS)**. It brings cloud-native, container-first principles to automotive edge computing with an emphasis on safety, security, and deterministic behavior.

## What is AutoSD?

AutoSD is built on **CentOS Stream** with an automotive-specific kernel (`kernel-automotive`) and is the functional precursor to the commercial safety-certified **Red Hat In-Vehicle OS**. It is the platform-specific deployment path for Open AD Kit in this repository.

## Key Features for Autonomous Driving

<div class="oak-card-grid" markdown="1">

<div class="oak-card" markdown="1">

:material-shield-check:{ .oak-card-icon }

<h3>Mixed Criticality</h3>
<p>Separates safety-critical containers in the root partition from non-critical workloads in the QM partition using systemd, Eclipse BlueChi, and QM.</p>
</div>

<div class="oak-card" markdown="1">

:material-refresh-auto:{ .oak-card-icon }

<h3>Atomic Updates</h3>
<p>Immutable system images with OSTree and composefs enable A/B updates, rollback, and tamper-proofing. Bootc brings container-native OS lifecycle management.</p>
</div>

<div class="oak-card" markdown="1">

:material-clock-fast:{ .oak-card-icon }

<h3>Real-Time Kernel</h3>
<p>RT-optimized automotive kernel with deterministic scheduling for time-critical autonomous driving functions.</p>
</div>

<div class="oak-card" markdown="1">

:material-docker:{ .oak-card-icon }

<h3>Container-Native</h3>
<p>Built around Podman, Quadlet (systemd container units), and BlueChi orchestration. No Docker daemon required.</p>
</div>

</div>

## Folder Structure

This folder contains a per-use-case structure for deploying and running Open AD Kit on AutoSD. Each folder contains at least:

- **Quadlet files** to define containerized services managed by Podman and systemd
- **Automotive Image Builder files** to build an AutoSD image

Build and running instructions on this page apply to any use-case subfolder.

- [Planning Simulator](planning-simulator/index.md): Run planning and simulator services in containers (pre-built)

## Requirements

### Using the Container Script (Recommended)

- Docker or Podman
- QEMU

### Running Automotive Image Builder on the Host

- RPM-based Linux distribution (Fedora, CentOS, or RHEL)
- Automotive Image Builder
- OSBuild
- QEMU

## Building an AutoSD Image

This section guides you through running `automotive-image-builder` from a container. Commands assume you are inside one of the sub-directories of this folder.

First, download the runner script:

```bash
curl -L -o auto-image-builder.sh \
  "https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/raw/main/auto-image-builder.sh?ref_type=heads"
```

Now build an image (requires sudo/root):

```bash
sudo bash ./auto-image-builder.sh build \
  --distro autosd9 \
  --mode image \
  --target qemu \
  --export qcow2 \
  --define-file aib/vars.yml \
  aib/image.aib.yml \
  disk.qcow2
```

You may want to change the owner of `disk.qcow2`:

```bash
sudo chown $(logname) disk.qcow2
```

You can now use QEMU to run the image from a mounted QEMU disk.

## Running the Image

If you have `automotive-image-runner` available:

```bash
automotive-image-runner --nographic disk.qcow2
```

Otherwise, use the following sample QEMU command:

```bash
/usr/bin/qemu-system-x86_64 \
  -drive file=/usr/share/OVMF/OVMF_CODE.fd,if=pflash,format=raw,unit=0,readonly=on \
  -drive file=/usr/share/OVMF/OVMF_VARS.fd,if=pflash,format=raw,unit=1,snapshot=on,readonly=off \
  -smp 20 \
  -nographic \
  -enable-kvm \
  -m 2G \
  -machine q35 \
  -cpu host \
  -device virtio-net-pci,netdev=n0,mac=FE:00:e2:0d:ba:4d \
  -netdev user,id=n0,net=10.0.2.0/24,hostfwd=tcp::2222-:22 \
  -drive file=disk.qcow2,index=0,media=disk,format=qcow2,if=virtio,id=rootdisk,snapshot=off
```

!!! note "Memory sizing"
    The `-m 2G` value above is only enough to boot and explore the AutoSD OS image. Running the full Open AD Kit stack requires considerably more — see the [hardware requirements](../hardware/index.md) (16 GB minimum, 32 GB recommended) and raise `-m` accordingly.

## Architecture on AutoSD

AutoSD's mixed-criticality architecture maps naturally to Open AD Kit's component model:

<div class="oak-component-grid">

<div class="oak-component-item">
<strong>Root Partition</strong>
<span>Open AD Kit components with higher criticality assumptions (planning, control, vehicle interface) map to the privileged root partition with RT scheduling.</span>
</div>

<div class="oak-component-item">
<strong>QM Partition</strong>
<span>Non-critical components (visualizer, simulator, development tools) are isolated in the QM partition for safety containment.</span>
</div>

<div class="oak-component-item">
<strong>OSTree / Bootc</strong>
<span>Atomic, rollback-capable updates. The entire OS is versioned and updated as a unit, matching Open AD Kit's container-native philosophy.</span>
</div>

<div class="oak-component-item">
<strong>BlueChi + Quadlet</strong>
<span>Container orchestration via systemd units. Each Open AD Kit component maps to a Quadlet service file managed by BlueChi.</span>
</div>

</div>

```mermaid
graph TB
    subgraph Root["Root Partition (Safety-Critical)"]
        R1[Planning]
        R2[Control]
        R3[Vehicle System]
    end

    subgraph QM["QM Partition (Non-Critical)"]
        Q1[Visualizer]
        Q2[Simulator]
    end

    OSTree[OSTree / Bootc<br/>Atomic Updates] --> Root
    OSTree --> QM
```

## Related Documentation

- [CentOS Automotive SIG Documentation](https://sigs.centos.org/automotive/latest/)
- [AutoSD Features and Concepts](https://sigs.centos.org/automotive/latest/features-and-concepts/)
- [Supported Platforms overview](../index.md)
