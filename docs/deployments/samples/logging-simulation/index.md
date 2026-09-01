# Logging Simulation

Runs sensing, perception, and localization against a sample rosbag. Checkout
assets live under `deployments/logging-simulation/`.

## Prerequisites

- Host setup via [Getting Started](../../../getting-started/index.md)
- Sample map, rosbag, and GPU models:

```bash
./openadkit fetch logging-simulation
```

## Run (CPU)

```bash
./openadkit run logging-simulation
```

## Run (GPU)

Requires the NVIDIA Container Toolkit.

```bash
./openadkit run logging-simulation --gpu
```

## Visualizer

Open `https://localhost:6080/vnc.html` and use `REMOTE_PASSWORD` from
`config.env`.

## Stop

```bash
./openadkit stop logging-simulation
```

## Notes

- The sample rosbag has no camera images (privacy); traffic-light recognition
  and full object detection accuracy are limited.
- `config.env` is the complete Compose configuration for this deployment.
