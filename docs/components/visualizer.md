# Visualizer

The `visualizer` image provides browser-accessible RViz2 through noVNC. It
combines RViz2 and Autoware plugins with Openbox, TigerVNC, and a TLS-enabled
noVNC server. The VNC backend remains loopback-only, and each container creates
its own self-signed certificate at startup.

## Settings

| Variable | Default | Values | Description |
|----------|---------|--------|-------------|
| `RVIZ_CONFIG` | `/opt/autoware/autoware_launch/share/autoware_launch/rviz/autoware.rviz` | Path | RViz2 configuration inside the container |
| `REMOTE_DISPLAY` | `true` | `true`, `false` | Use browser-based RViz2; `false` launches a local display |
| `REMOTE_PASSWORD` | — | String | Required when `REMOTE_DISPLAY=true` |
| `WEBSOCKIFY_BIND` | `127.0.0.1` | IP address | noVNC bind address; bridge networking uses `0.0.0.0` with a host loopback port mapping |
| `USE_SIM_TIME` | `false` | `true`, `false` | Use the ROS simulation clock |
| `RVIZ_GPU` | `auto` | `auto`, `on`, `off` | Select automatic, forced, or disabled VirtualGL acceleration |

Under host networking, open `https://localhost:6080/vnc.html`. For remote
access, use SSH forwarding or an authenticated reverse proxy rather than
exposing noVNC directly.
