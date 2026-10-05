# Hardware

Requirements and tested hardware for Open AD Kit. Both **amd64** and **arm64**
are supported.

## Workstation or Cloud Instance

For deployments, simulation, and development:

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 8 cores | 16 cores |
| RAM | 16 GB | 32 GB |
| GPU | None | NVIDIA with 4 GB+ VRAM (for perception) |
| Storage | 50 GB | 100 GB+ SSD |

The CUDA perception image is amd64-only and does not fall back to CPU. Hosts
without an NVIDIA GPU, and all arm64 hosts, use the CPU perception image.

## Edge Deployment

Running the full Autoware stack in real time on a vehicle computer needs more.
These figures come from the verified ADLINK AADP-AVA platform:

| Resource | Specification |
|----------|---------------|
| CPU | 40-core Arm Neoverse N1 or equivalent |
| RAM | 32 GB |
| Architecture | arm64 |

## Tested Hardware

| Platform | Architecture | Status | Notes |
|----------|--------------|--------|-------|
| ADLINK AADP-AVA | arm64 (Ampere Altra) | <span class="oak-badge oak-badge--verified">Verified</span> | Primary edge platform |
| AWS EC2 G5.4XLarge | amd64 | <span class="oak-badge oak-badge--verified">Verified</span> | GPU cloud instance for simulation |
| NVIDIA Jetson Orin | arm64 | <span class="oak-badge oak-badge--testing">Tests Ongoing</span> | JetPack 6 validation in progress |
| R-Car X5H | arm64 | <span class="oak-badge oak-badge--testing">Tests Ongoing</span> | AutoSD 10 bring-up; QEMU-tested, board tests manual |
| ADLINK ADM-AL30 | arm64 | <span class="oak-badge oak-badge--testing">Tests Ongoing</span> | No validation results recorded yet |
