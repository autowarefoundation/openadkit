# Sensing & Perception

## Overview

The `sensing-perception` image packages the first two stages of the AD pipeline into a single build target. Sensing collects, preprocesses, and publishes data from the vehicle's sensors; perception processes that data to build an understanding of the driving environment — detecting, tracking, and classifying objects and producing occupancy maps.

## Sensing

- **LiDAR preprocessing** — Point cloud acquisition, distortion correction, ring filtering, and outlier removal
- **Camera preprocessing** — Image capture, distortion correction, and format conversion
- **Radar preprocessing** — Radar target detection and noise filtering
- **Ultrasonic sensing** — Short-range obstacle detection preprocessing
- **GNSS-INS preprocessing** — Global positioning and inertial navigation data fusion
- **Point cloud container** — Shared in-memory point cloud processing pipeline for efficient preprocessing
- **Launch file:** `tier4_sensing_component.launch.xml`

## Perception

- **Multi-sensor object detection** — Fusion of camera, LiDAR, and radar for multi-class object detection
- **Multi-object tracking (MOT v2)** — Temporal consistency and trajectory prediction for detected objects
- **Priority object merger** — Resolution of overlapping detections from multiple sensors
- **Camera-only 3D detection** — Monocular depth estimation and 3D bounding box generation
- **Radar-only 3D detection** — Radar-based object localization and velocity estimation
- **Cluster-based 3D detection** — Unsupervised LiDAR clustering for object detection
- **Occupancy grid mapping** — 2D grid-based environment representation for navigation
- **Traffic light recognition** — Camera-based traffic signal state detection
- **Launch file:** `tier4_perception_component.launch.xml`

## Resource Usage

- **CPU**: High — point cloud preprocessing and CPU-fallback inference are expensive without a GPU
- **GPU**: Strongly recommended — neural network inference needs 4 GB+ VRAM (use the CUDA variant below)
- **Memory**: ~4–8 GB typical; scales with active detection models

## CUDA Variant

The `sensing-perception-cuda` image is an amd64-only, GPU-accelerated variant that offloads point cloud preprocessing and CUDA-based neural network inference (object detection, traffic light recognition) to NVIDIA GPUs. It requires the NVIDIA Container Toolkit and is enabled opt-in via the GPU overlay in [Logging Simulation](../deployment/logging-simulation/index.md).

## Used In

- [Logging Simulation](../deployment/logging-simulation/index.md) — Replays recorded sensor data through the full stack
- [CARLA Simulation](../deployment/carla-simulation/index.md) — Live sensor feed from the CARLA simulator

## Related

- [Autoware sensing design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/sensing/)
- [Autoware perception design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/perception/)
