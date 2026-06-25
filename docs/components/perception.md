# Perception

## Overview

The perception component processes preprocessed sensor data to build an understanding of the driving environment. It detects, tracks, and classifies objects and produces occupancy maps. It runs inside the `sensing-perception` image, which is the same image that hosts sensing.

## What This Image Contains

- **Multi-sensor object detection** — Fusion of camera, LiDAR, and radar for multi-class object detection
- **Multi-object tracking (MOT v2)** — Temporal consistency and trajectory prediction for detected objects
- **Priority object merger** — Resolution of overlapping detections from multiple sensors
- **Camera-only 3D detection** — Monocular depth estimation and 3D bounding box generation
- **Radar-only 3D detection** — Radar-based object localization and velocity estimation
- **Cluster-based 3D detection** — Unsupervised LiDAR clustering for object detection
- **Occupancy grid mapping** — 2D grid-based environment representation for navigation
- **Traffic light recognition** — Camera-based traffic signal state detection
- **Launch file:** `tier4_perception_component.launch.xml`

Typical resource usage:

- **CPU**: Moderate — used as a fallback when no GPU is available, with significantly degraded performance
- **GPU**: Heavy — neural network inference; 4 GB+ VRAM strongly recommended (use the `sensing-perception-cuda` variant)
- **Memory**: Scales with active detection models

## CUDA Variant

The `sensing-perception-cuda` image is an amd64-only, GPU-accelerated variant that enables CUDA-based neural network inference for object detection and traffic light recognition. It requires the NVIDIA Container Toolkit and is the default choice for [Logging Simulation](../deployment/logging-simulation/index.md) deployments.

## Used In

- [Logging Simulation](../deployment/logging-simulation/index.md) — Processes real recorded sensor data

## Related

- [Sensing](sensing.md) — Shares the same `sensing-perception` image
- [Autoware perception design document](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v1/components/perception/)
