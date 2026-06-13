# Visualizer

The visualizer component provides a browser-accessible RViz environment via noVNC, enabling remote inspection of Autoware topics and state without installing ROS 2 locally.

## Documentation

For full visualizer settings and deployment context, see the [Open AD Kit Docs — Visualizer](https://autowarefoundation.github.io/openadkit/components/visualizer/).

## Standalone Run

```bash
docker run --rm --name visualizer -p 6080:6080 \
  -e REMOTE_PASSWORD=yourpassword \
  ghcr.io/autowarefoundation/openadkit:visualizer
```

## Settings

| Variable | Default | Options | Description |
|----------|---------|---------|-------------|
| `RVIZ_CONFIG` | `/opt/autoware/share/autoware_launch/rviz/autoware.rviz` | Any valid path | RViz configuration file inside the container |
| `REMOTE_DISPLAY` | `true` | `true`, `false` | Browser-based display (recommended). Set `false` for local RViz2 |
| `REMOTE_PASSWORD` | — (required) | Any string | Password for the remote display; the container exits if unset |

## Example with Custom Settings

```bash
docker run --rm --name visualizer \
  -p 6080:6080 \
  -e RVIZ_CONFIG=/opt/autoware/share/autoware_launch/rviz/custom.rviz \
  -e REMOTE_PASSWORD=mysecurepass \
  ghcr.io/autowarefoundation/openadkit:visualizer
```
