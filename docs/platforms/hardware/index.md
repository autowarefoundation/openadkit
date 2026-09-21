# Hardware

Requirements and tested platforms for Open AD Kit deployments.

## Requirements

Open AD Kit supports **amd64** and **arm64**. Requirements differ between local
development and a verified edge deployment.

### Local Development & Simulation

For deployments, simulations, and development workloads on a workstation or
cloud instance:

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 8 cores | 16 cores |
| RAM | 16 GB | 32 GB |
| GPU | — | NVIDIA with 4 GB+ VRAM (for sensing/perception) |
| Storage | 50 GB | 100 GB+ SSD |

!!! tip "GPU Recommendation"
    An NVIDIA GPU is strongly recommended for sensing and perception. CUDA images
    need a working NVIDIA runtime and do not fall back to CPU; on hosts without a
    GPU, use the standard CPU image or deployment configuration.

### Verified Edge Deployment

For running a full Autoware stack on a verified edge platform, the requirements are higher:

| Resource | Specification |
|----------|---------------|
| CPU | 40-core Arm Neoverse N1 equivalent (or better) |
| RAM | 32 GB |
| GPU | NVIDIA with CUDA support (hardware capability; see the ARM64 image note below) |
| Architecture | arm64 |

!!! warning "ARM64 sensing and perception"
    ARM64 edge hardware may include a CUDA-capable NVIDIA GPU, but the published
    `sensing-perception-cuda` image currently supports `linux/amd64` only. On
    ARM64, use the standard `sensing-perception` image; sensing and perception
    run on CPU and do not use the available GPU.

!!! info "Why the difference?"
    The 40-core Neoverse N1 requirement comes from the verified ADLINK AADP-AVA
    platform, which runs the full Autoware stack under real-time constraints.
    Demo simulations on a workstation need far less.

## Tested Hardware

| Platform | Architecture | Status | Notes |
|----------|--------------|--------|-------|
| ADLINK AADP-AVA | arm64 (Ampere Altra, Neoverse N1) | <span class="oak-badge oak-badge--verified">Verified</span> | Primary verified platform for edge deployment |
| AWS EC2 G5.4XLarge | amd64 | <span class="oak-badge oak-badge--verified">Verified</span> | GPU-enabled cloud instance for simulation workloads |

## Tests Ongoing

| Platform | Architecture | Status | Notes |
|----------|--------------|--------|-------|
| NVIDIA Jetson Orin | arm64 | <span class="oak-badge oak-badge--testing">Tests Ongoing</span> | JetPack 6 validation in progress. Not yet fully verified for production use. |
| R-Car X5H (r8a78000 / ironhide) | arm64 | <span class="oak-badge oak-badge--testing">Tests Ongoing</span> | AutoSD 10 board bring-up; QEMU-gated off-board, board smoke remains manual |
| ADLINK ADM-AL30 | arm64 | <span class="oak-badge oak-badge--testing">Tests Ongoing</span> | Arm64 edge platform; no validation evidence recorded in this repository |
