# Visualizer

The visualizer provides browser-accessible RViz2 through noVNC. Configuration
and networking details are maintained in the
[Visualizer documentation](https://autowarefoundation.github.io/openadkit/components/visualizer/).

```bash
docker run --rm --name visualizer --network host \
  -e REMOTE_PASSWORD=yourpassword \
  ghcr.io/autowarefoundation/openadkit:visualizer
```

Open `http://localhost:6080/vnc.html`. noVNC is served over plain HTTP on
loopback; to serve HTTPS, mount a certificate and set `NOVNC_CERT` and
`NOVNC_KEY`.

| Variable | Default | Description |
| --- | --- | --- |
| `REMOTE_PASSWORD` | (required) | noVNC password. The container exits if unset. |
| `REMOTE_DISPLAY` | `true` | `true` starts noVNC/VNC. `false` runs local RViz2. |
| `WEBSOCKIFY_BIND` | `127.0.0.1` | noVNC bind address. Use `0.0.0.0` only behind a reverse proxy or Docker port publish. |
| `RVIZ_CONFIG` | `/tmp/openadkit/autoware_launch/share/autoware_launch/rviz/autoware.rviz` | RViz config path inside the container. The default is the copy with config overrides applied. |
| `RVIZ_GPU` | `auto` | `auto` uses VirtualGL when an NVIDIA GPU is present. `on` forces it. `off` disables it. |
| `NOVNC_CERT`, `NOVNC_KEY` | unset | Certificate and key inside the container. Set both to serve HTTPS only. |
| `USE_SIM_TIME` | `false` | Forwarded to RViz as `use_sim_time`. |
