# Logging Simulation

Runnable assets for rosbag-based logging simulation (CPU or GPU overlay).

**Guide (source of truth):**
[Logging Simulation docs](https://autowarefoundation.github.io/openadkit/deployments/samples/logging-simulation/)

```bash
sudo ../../install.sh --download-artifacts
../../install.sh sample-data logging-simulation
docker compose --env-file config.env up -d
```

GPU:

```bash
docker compose --env-file config.env \
  -f docker-compose.yaml -f docker-compose.gpu.yaml up -d
```
