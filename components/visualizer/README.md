# Visualizer

The visualizer component provides a browser-accessible RViz environment via noVNC, enabling remote inspection of Autoware topics and state without installing ROS 2 locally.

## Documentation

For full visualizer settings and deployment context, see the [Open AD Kit Docs — Visualizer](https://autowarefoundation.github.io/openadkit/components/visualizer/).

## Standalone Run

```bash
docker run --rm --name visualizer --network host \
  -e REMOTE_PASSWORD=yourpassword \
  ghcr.io/autowarefoundation/openadkit:visualizer
```

The visualizer binds websockify to loopback (`127.0.0.1:6080`) by default, so `--network host` is required for standalone runs. Under host networking, `-p` is a no-op and the browser reaches noVNC at `https://localhost:6080/vnc.html`. For bridge networking, set `WEBSOCKIFY_BIND=0.0.0.0` and use `-p 6080:6080`.

## Settings

| Variable | Default | Options | Description |
|----------|---------|---------|-------------|
| `RVIZ_CONFIG` | `/opt/autoware/autoware_launch/share/autoware_launch/rviz/autoware.rviz` | Any valid path | RViz configuration file inside the container |
| `REMOTE_DISPLAY` | `true` | `true`, `false` | Browser-based display (recommended). Set `false` for local RViz2 |
| `REMOTE_PASSWORD` | — (required) | Any string | Password for the remote display; the container exits if unset |
| `WEBSOCKIFY_BIND` | `127.0.0.1` | IP address | Address websockify binds to. Set to `0.0.0.0` under bridge networking so Docker port forwarding can reach it |

## Example with Custom Settings

```bash
docker run --rm --name visualizer \
  --network host \
  -e RVIZ_CONFIG=/opt/autoware/autoware_launch/share/autoware_launch/rviz/custom.rviz \
  -e REMOTE_PASSWORD=mysecurepass \
  ghcr.io/autowarefoundation/openadkit:visualizer
```
