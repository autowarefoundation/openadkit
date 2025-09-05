# Supported Platforms

As the Autoware Open AD Kit is the first [SOAFEE](https://www.soafee.io/blog/2025/the-benefits-of-open-standards-in-automotive-development/) blueprint for the software defined vehicle ecosystem, it supports a variety of platforms as core SOAFEE platforms.

## Core platforms

### EWAOL

The Edge Workload Abstraction and Orchestration Layer (EWAOL) is a standards-based, container-centric framework for deploying and orchestrating applications on edge platforms, delivered via the `meta-ewaol` Yocto layer to build distribution images. It organizes the stack into user-defined containerized application workloads (deployed by end users), an EWAOL Linux filesystem that provides core services such as Docker, K3s, and Xen along with validation and development tooling, and platform-specific system software (firmware, bootloader, OS, and optional Xen) integrated from `meta-arm`, `meta-arm-bsp`, and `meta-virtualization`. EWAOL is the reference implementation for SOAFEE, extending cloud-native methods to automotive with an emphasis on real-time and functional safety (`https://soafee.io`).

### AutoSD

AutoSD is the upstream binary distribution that serves as the public, in-development preview of Red Hat In-Vehicle Operating System (OS). AutoSD is downstream of CentOS Stream, so it retains most of the CentOS Stream code with a few divergences, such as an optimized automotive-specific kernel rather than CentOS Stream's kernel package. Red Hat In-Vehicle OS is based on both AutoSD and RHEL, both of which are downstreams of CentOS Stream.
