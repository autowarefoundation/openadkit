# Logging Simulation

Replays recorded sensor data through the Autoware sensing, perception, and
planning stack. Install the host dependencies and perception artifacts in the
[canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/logging-simulation/)
before starting.

## Source Checkout

```bash
../../install.sh sample-data logging-simulation
docker compose --env-file ../base/base.env --env-file logging-simulation.env up -d
docker compose --env-file ../base/base.env --env-file logging-simulation.env \
  --profile rosbag up -d rosbag
```

## Release Bundle

```bash
./install.sh sample-data logging-simulation
docker compose --env-file logging-simulation.env up -d
docker compose --env-file logging-simulation.env --profile rosbag up -d rosbag
```
