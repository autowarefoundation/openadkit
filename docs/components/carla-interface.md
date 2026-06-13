# CARLA Interface

## Overview

The `carla-interface` image packages the `autoware_carla_interface` bridge, enabling **closed-loop end-to-end simulation** with the [CARLA](https://carla.org/) simulator. It is built on top of the `simulator` image and published as `ghcr.io/autowarefoundation/openadkit:carla-interface`. It acts as a bidirectional gateway between Autoware and CARLA: translating Autoware control outputs into CARLA ego vehicle commands, and converting CARLA sensor data into Autoware-compatible ROS 2 messages. This allows the full Autoware stack to drive and perceive within a photorealistic CARLA world.

## What This Image Contains

The `carla-interface` image bundles the following capabilities:

- **CARLA world initialization** — Connects to a running CARLA server, loads the specified map (e.g., `Town01`), and configures synchronous simulation mode
- **Ego vehicle spawning** — Spawns the ego vehicle with a configurable blueprint (e.g., `vehicle.toyota.prius`) and optional spawn coordinates
- **Sensor kit configuration** — Dynamically configures the `carla_sensor_kit` with:
  - 6 cameras for 360-degree coverage (or a single lightweight front camera)
  - LiDAR sensor
  - IMU and GNSS sensors
- **Sensor data translation** — Publishes CARLA sensor outputs as standard Autoware/ROS 2 messages at configurable frequencies
- **Control command calibration** — Uses `autoware_raw_vehicle_cmd_converter` to calibrate Autoware control commands (acceleration, steering) for CARLA-specific vehicle dynamics
- **Traffic light recognition support** — Publishes traffic light state data from CARLA to Autoware perception
- **Lightweight sensor mapping option** — Reduces sensor load (single camera, lower frequencies) for machines with limited GPU/CPU resources
- **Synchronous mode support** — Runs CARLA in lock-step with Autoware for deterministic, reproducible simulation
- **Launch file:** `autoware_carla_interface.launch.xml`

Typical resource usage:

- **CPU**: Moderate (bridge logic + Python-based CARLA client)
- **GPU**: Recommended (CARLA server itself requires GPU; the bridge container does not, but CARLA rendering is GPU-intensive)
- **Memory**: ~2–4 GB

## Used In

- [CARLA Simulation](../deployment/samples/carla-simulation/index.md) — Connects the full Autoware stack to the CARLA simulator for end-to-end autonomous driving simulation

## Related

- [autoware_carla_interface package documentation](https://autowarefoundation.github.io/autoware_universe/main/simulator/autoware_carla_interface/) — Detailed design, parameters, and sensor configuration
- [CARLA simulator tutorial](https://autowarefoundation.github.io/autoware-documentation/main/demos/digital-twin-demos/carla-tutorial/) — Official Autoware CARLA integration guide
- [Deployments](../deployment/index.md) — How the CARLA interface container is composed with other components
