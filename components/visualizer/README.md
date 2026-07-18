# Visualizer

The visualizer provides browser-accessible RViz2 through noVNC. Configuration
and networking details are maintained in the
[Visualizer documentation](https://autowarefoundation.github.io/openadkit/components/visualizer/).

```bash
docker run --rm --name visualizer --network host \
  -e REMOTE_PASSWORD=yourpassword \
  ghcr.io/autowarefoundation/openadkit:visualizer
```

Open `https://localhost:6080/vnc.html`. The self-signed certificate causes an
expected browser warning on first access.
