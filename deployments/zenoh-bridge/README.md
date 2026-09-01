# Zenoh Bridge

Edge/cloud bridge for remote visualization and teleoperation.

**Guide (source of truth):**
[Zenoh Bridge docs](https://autowarefoundation.github.io/openadkit/deployments/demos/zenoh-bridge/)

This standalone demo is not in the CLI inventory. Fetch the shared
Kashiwanoha map, then start the helpers:

```bash
cd ../..
./openadkit fetch scenario-simulation
cd deployments/zenoh-bridge
./cloud.sh up -d
./edge.sh up -d
```

Visualizer: `https://localhost:6081/vnc.html`

Zenoh transport stays inside the Compose project and is not published to the host.
