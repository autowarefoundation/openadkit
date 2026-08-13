# Visualizer

The visualizer provides browser-accessible RViz2 through noVNC. Image
architecture lives in the
[component documentation](https://autowarefoundation.github.io/openadkit/components/).

```bash
docker run --rm --name visualizer --network host \
  -e REMOTE_PASSWORD=yourpassword \
  ghcr.io/autowarefoundation/openadkit:visualizer
```

Open `https://localhost:6080/vnc.html`. The self-signed certificate causes an
expected browser warning on first access.

| Variable | Default | Description |
| --- | --- | --- |
| `REMOTE_PASSWORD` | (required) | noVNC password. The container exits if unset. |
| `REMOTE_DISPLAY` | `true` | `true` starts noVNC/VNC. `false` runs local RViz2. |
| `WEBSOCKIFY_BIND` | `127.0.0.1` | noVNC bind address. Use `0.0.0.0` only behind a reverse proxy or Docker port publish. |
| `RVIZ_CONFIG` | `/opt/autoware/autoware_launch/share/autoware_launch/rviz/autoware.rviz` | RViz config path inside the container. |
| `RVIZ_GPU` | `auto` | `auto` uses VirtualGL when an NVIDIA GPU is present. `on` forces it. `off` disables it. |
| `USE_SIM_TIME` | `false` | Forwarded to RViz as `use_sim_time`. |
