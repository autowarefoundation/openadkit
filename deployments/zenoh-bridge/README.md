# Zenoh Bridge

Bridges Autoware data from edge to cloud for remote visualization and control.
See the [canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/zenoh-bridge/)
for topology, configuration, and teleoperation.

From the source root, prepare the Kashiwanoha map, then start the standalone
helpers:

```bash
cd ../..
./openadkit fetch scenario-simulation
cd deployments/zenoh-bridge
./cloud.sh up -d
./edge.sh up -d
```

Visualizer: `https://localhost:6081/vnc.html`

Zenoh transport stays inside the Compose project and is not published to the host.
This deployment is not included in the unified release bundle or
manifest-driven CLI.
