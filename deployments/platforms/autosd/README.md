# AutoSD + Autoware Open AD Kit

[AutoSD](https://sigs.centos.org/automotive/about/), short for Automotive Stream Distribution, is the upstream binary distribution that serves as the public, in-development preview and functional precursor of the Red Hat In-Vehicle Operating System (OS).

AutoSD is downstream of CentOS Stream, so it retains most of the CentOS Stream code with a few divergences,
such as an optimized automotive-specific kernel rather than CentOS Stream’s kernel package.
Red Hat In-Vehicle OS is based on both AutoSD and RHEL, both of which are downstreams of CentOS Stream.

AutoSD brings different features into the table, such as:

* Mixed Critical Orchestration with Systemd, Eclipse [BlueChi](https://github.com/eclipse-bluechi/bluechi) and [QM](https://github.com/containers/qm)
* Container management and workload definition with [Podman and Quadlet](https://www.redhat.com/en/blog/quadlet-podman)
* A realtime [linux kernel](https://gitlab.com/redhat/centos-stream/src/kernel/centos-stream-9/-/tree/main-automotive?ref_type=heads)
* Immutable system images with [OSTree](https://sigs.centos.org/automotive/features-and-concepts/con_ostree/)

## Folder Structure

This folder contains a per use-case structure on how to deploy/run Open AD Kit in AutoSD, with each folder containing at least:

* quadlet files to define containerized services to  be managed by podman and systemd
* automotive-image-builder files to build an AutoSD image(s)

Build and running instructions in this page applies to any user-case/sub folder.

* [planning-simulator](./planning-simulator/README.md): Run planning and simulator services in containers (pre-built)

## General Instructions

### Requirements

If using the container script (recommended):

* Docker/podman
* QEMU

If running automotive image builder on the host:

* rpm based Linux distro such as Fedora, CentOS or RHEL
* Automotive Image Builder
* OSBuild
* QEMU

### Building

This section will guide how to run automotive-image-builder from a container. Commands assume you are inside one of the
sub-directories of this folder.

First, download the "runner" script:

```
$ curl -L -o auto-image-builder.sh \
"https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/raw/main/auto-image-builder.sh?ref_type=heads"
```

Now build an image (requires sudo/root):

```
$ sudo bash ./auto-image-builder.sh build \
--distro autosd9 \
--mode image \
--target qemu \
--export qcow2 \
--define-file aib/vars.yml \
aib/image.aib.yml \
disk.qcow2
```

You may want to change the owner of `disk.qcow2`:

```
$ sudo chown $(logname) disk.qcow2
```

You can now use qemu to run the image in a mounted qemu disk.

### Running

If you have automotive-image-runner available:

```
$ automotive-image-runner --nographic disk.qcow2
```

Otherwise, use the following sample qemu command:

```
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
