# Open AD Kit Logging Simulation

This deployment replays recorded sensor data through the full Autoware sensing, perception, and planning stack.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — Logging Simulation](https://autowarefoundation.github.io/openadkit/deployment/logging-simulation/)**

Before starting this deployment, install the host dependencies and Autoware perception artifacts as described in the canonical documentation.

## Source Checkout

```bash
../../install.sh sample-data logging-simulation
docker compose --env-file ../base/base.env --env-file logging-simulation.env up -d
docker compose --env-file ../base/base.env --env-file logging-simulation.env \
  --profile rosbag up -d rosbag
```

## Release Bundle

From the extracted directory:

```bash
./install.sh sample-data logging-simulation
docker compose --env-file logging-simulation.env up -d
docker compose --env-file logging-simulation.env --profile rosbag up -d rosbag
```

The rosbag service waits for a subscriber on `ROSBAG_READY_TOPIC` before
starting playback and fails after `ROSBAG_READY_TIMEOUT` instead of silently
dropping the beginning of the recording.
