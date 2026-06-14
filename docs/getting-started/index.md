# Getting Started

This guide walks you through setting up your environment and running your first Open AD Kit deployment.

```mermaid
flowchart LR
    A[Run setup.sh] --> B[Verify Installation] --> C[Download a deployment]
    A -.->|Optional| D["--no-nvidia"]
```

## Prerequisites

Open AD Kit runs on **Ubuntu** with Docker. The v2.0 quickstart is validated on the committed host profile — **Ubuntu 22.04 (Jammy) with ROS 2 Humble**. Install everything with the included [`setup.sh`](https://github.com/autowarefoundation/openadkit/blob/main/setup.sh) script instead of following separate install guides:

| Component | When you need it | How to install |
|-----------|------------------|----------------|
| **Docker Engine** | All deployments | `setup.sh` (below) |
| **NVIDIA Container Toolkit** | GPU-accelerated sensing and perception | Included by default; add `--no-nvidia` to skip |
| **Autoware artifacts** | Sensing and perception samples (for example, [Logging Simulation](../deployment/samples/logging-simulation/index.md)) | `setup.sh --download-artifacts` |

## Set Up Your Environment

`setup.sh` is self-contained — no `git clone` required. Run it directly:

```bash
{{ setup_command }}
```

This installs Docker, the NVIDIA Container Toolkit, and other dependencies (requires sudo).

!!! tip "Skip NVIDIA Toolkit"
    Append `-s -- --no-nvidia` (i.e. `… | sudo bash -s -- --no-nvidia`) if you do not have an NVIDIA GPU. Otherwise the toolkit is **highly recommended** for sensing and perception performance.

!!! info "Autoware artifacts"
    For sensing/perception samples (e.g. [Logging Simulation](../deployment/samples/logging-simulation/index.md)) that mount `${HOME}/autoware_data`, add `-s -- --download-artifacts`. This downloads artifacts and continues with Docker installation. For users who already have Docker and only need artifacts, run `setup.sh --download-artifacts` directly (no `-s` needed).

Each sample/demo is then downloaded as a self-contained bundle — see [Sample Deployments](../deployment/samples/index.md). You do **not** clone the repository to run deployments.

## Verify Your Installation

After running `setup.sh`, confirm your environment is ready:

```bash
# Check Docker
docker --version
docker compose version

# Check NVIDIA toolkit (if installed)
nvidia-ctk --version

# Verify artifacts directory
ls -la ~/autoware_data
```

!!! success "Ready to Deploy"
    If all checks pass, you are ready to run a sample deployment. See [Sample Deployments](../deployment/samples/index.md).

<h2 class="oak-eyebrow" id="reference">Reference</h2>

- [Container Image Tags](image-tags.md) — Understanding the tag schema for choosing the right image
- [Release Flow](release-flow.md) — How Open AD Kit releases are built, scanned, and promoted

<h2 class="oak-eyebrow" id="next-steps">Next Steps</h2>

- [Run your first deployment](../deployment/samples/planning-simulation/index.md) — Start with the Planning Simulation sample
- [Learn about components](../components/index.md) — Understand the Open AD Kit architecture
- [Choose a platform](../platforms/index.md) — Deploy to AutoSD, EWAOL, or your local machine
