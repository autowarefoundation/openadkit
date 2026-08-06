# Zenoh Bridge

Edge/cloud bridge for remote visualization and teleoperation.

**Guide (source of truth):**
[Zenoh Bridge docs](https://autowarefoundation.github.io/openadkit/deployments/demos/zenoh-bridge/)

Set `REMOTE_PASSWORD` in `config.env`, then download the sample map:

```bash
../../install.sh sample-data zenoh-bridge
./cloud.sh up -d
./edge.sh up -d
```

Visualizer: `https://localhost:6081/vnc.html`

Zenoh transport stays inside the Compose project and is not published to the host.
