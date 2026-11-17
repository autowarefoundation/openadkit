# Supported Platforms

[Deployments](../deployments/index.md) run on Ubuntu with Docker Compose, for
development and simulation. **Platforms** are edge targets on automotive
operating systems such as AutoSD.

- [AutoSD](autosd.md) — the upstream preview of Red Hat In-Vehicle OS:
  Quadlet units for Podman and systemd, generated from Compose (experimental)

## Support Matrix

A **supported** path is built and shipped by every release and covered by
[Compatibility](../releases/compatibility.md); the notes say where CI evidence
does not reach it. An **experimental** one works but may change in a minor
release. An **unsupported** one is not built or tested here.

A path that fails its build or validation gate is dropped or marked here, not
documented as if it worked.

| Path | Tier | Notes |
|------|------|-------|
| Ubuntu 22.04 and 24.04 + Docker Compose deployments | **Supported** | Compose validated in CI |
| Component images, amd64 + arm64 | **Supported** | Built, scanned and run in the evidence cells for both. `sensing-perception-cuda` and `planning-cuda` are amd64-only; only the amd64 `simulator` carries the CARLA client |
| Jazzy images | **Supported** | A release needs the Humble and the Jazzy evidence cells to pass; Humble is the default |
| CARLA Simulation | **Supported** | Humble, amd64, NVIDIA GPU; exempt from CI evidence, checked by hand |
| [AutoSD](autosd.md) with Podman and Quadlet | **Experimental** | Component images, generated from Compose; Planning Simulation only |
| [EWAOL](https://ewaol.docs.arm.com/en/latest/) | **Unsupported** | Arm's Yocto framework; no assets in this repository |

Other Linux distributions may work but are not tested.

## Host Requirements

For deployments, simulation and development:

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 8 cores | 16 cores |
| RAM | 16 GB | 32 GB |
| GPU | None | NVIDIA with 2 GB+ VRAM for Planning Simulation's GPU mode, 4 GB+ for Logging Simulation's; 8 GB+ for CARLA Simulation, 16 GB recommended |
| Storage | 50 GB | 100 GB+ SSD |

Images are published for **amd64** and **arm64**. The GPU modes and CARLA
Simulation are amd64-only: the CUDA images do not fall back to CPU, so hosts
without an NVIDIA GPU, and all arm64 hosts, run the CPU images.

On a host below the recommended size Autoware may not keep up in real time;
Scenario Simulation can then run slower than real time with
[`GLOBAL_REAL_TIME_FACTOR`](../deployments/scenario-simulation.md#settings).

## Boards

| Board | Architecture | Support |
|-------|--------------|---------|
| R-Car X5H | arm64 | AutoSD 10 image in [openadkit-rcar-x5h](https://github.com/autowarefoundation/openadkit-rcar-x5h), its own repository; board tests are manual |

No board is part of the release evidence: the
[evidence cells](../releases/evidence.md) run on hosted amd64 and arm64
runners.
