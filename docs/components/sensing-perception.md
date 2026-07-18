# Sensing & Perception

The `sensing-perception` image packages sensor preprocessing and environment
understanding into one build target.

## Sensing

- LiDAR distortion correction, filtering, and point cloud preprocessing
- Camera and radar preprocessing
- GNSS/INS preprocessing
- Shared point cloud container
- Launch file: `tier4_sensing_component.launch.xml`

## Perception

- Camera, LiDAR, and radar object detection and fusion
- Multi-object tracking and trajectory prediction
- Traffic light recognition
- Occupancy grid mapping
- Launch file: `tier4_perception_component.launch.xml`

## CUDA Variant

`sensing-perception-cuda` accelerates point cloud processing and neural network
inference on NVIDIA GPUs. It is published for amd64 only, requires NVIDIA
Container Toolkit, and is enabled through the
[Logging Simulation GPU overlay](../deployment/logging-simulation/index.md).
