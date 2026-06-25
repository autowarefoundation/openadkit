# AutoSD + Autoware Open AD Kit

[AutoSD](https://sigs.centos.org/automotive/about/), short for Automotive Stream Distribution, is the upstream binary distribution that serves as the public, in-development preview and functional precursor of the Red Hat In-Vehicle Operating System (OS).

AutoSD is downstream of CentOS Stream, so it retains most of the CentOS Stream code with a few divergences,
such as an optimized automotive-specific kernel rather than CentOS Stream's kernel package.
Red Hat In-Vehicle OS is based on both AutoSD and RHEL, both of which are downstreams of CentOS Stream.

AutoSD brings different features into the table, such as:

* Mixed Critical Orchestration with Systemd, Eclipse [BlueChi](https://github.com/eclipse-bluechi/bluechi) and [QM](https://github.com/containers/qm)
* Container management and component definition with [Podman and Quadlet](https://www.redhat.com/en/blog/quadlet-podman)
* A realtime [linux kernel](https://gitlab.com/redhat/centos-stream/src/kernel/centos-stream-9/-/tree/main-automotive?ref_type=heads)
* Immutable system images with [OSTree](https://sigs.centos.org/automotive/features-and-concepts/con_ostree/)

## Folder Structure

This folder contains a per use-case structure on how to deploy/run Open AD Kit in AutoSD, with each folder containing at least:

* quadlet files to define containerized services to  be managed by podman and systemd
* automotive-image-builder files to build an AutoSD image(s)

* [planning-simulator](./planning-simulator/README.md): Run planning and simulator services in containers (pre-built)

## Documentation

Canonical build, run, and QEMU instructions live in the docs site:

**https://autowarefoundation.github.io/openadkit/platforms/autosd/**

See that page for current steps; this README only summarizes the folder layout.

