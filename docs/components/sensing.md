# Sensing

## Overview

The sensing component collects, preprocesses, and publishes data from the vehicle's sensors. It runs inside the `sensing-perception` image and provides the raw and preprocessed sensor inputs that feed perception, localization, and other downstream components.

## What This Image Contains

- **LiDAR preprocessing** — Point cloud acquisition, distortion correction, ring filtering, and outlier removal
- **Camera preprocessing** — Image capture, distortion correction, and format conversion
- **Radar preprocessing** — Radar target detection and noise filtering
- **Ultrasonic sensing** — Short-range obstacle detection preprocessing
- **GNSS-INS preprocessing** — Global positioning and inertial navigation data fusion
- **Point cloud container** — Shared in-memory point cloud processing pipeline for efficient preprocessing
- **Launch file:** `tier4_sensing_component.launch.xml`

Typical resource usage:

- **CPU**: High — point cloud preprocessing is CPU-intensive without a GPU
- **GPU**: Strongly recommended for point cloud preprocessing (use the `sensing-perception-cuda` variant)
- **Memory**: ~4–8 GB typical

## CUDA Variant

The `sensing-perception-cuda` image is an amd64-only, GPU-accelerated variant that offloads point cloud preprocessing and sensor data operations to NVIDIA GPUs. It requires the NVIDIA Container Toolkit and is strongly recommended for [Logging Simulation](../deployment/logging-simulation/index.md) deployments.

## Used In

- [Logging Simulation](../deployment/logging-simulation/index.md) — Replays recorded sensor data through the full stack
- [CARLA Simulation](../deployment/carla-simulation/index.md) — Live sensor feed from the CARLA simulator

## Related

- [Perception](perception.md) — Shares the same `sensing-perception` image
- [Autoware sensing design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/sensing/)
