# Visualizer

The visualizer provides RViz in the browser through noVNC. Configuration and
networking details are maintained in the
[Visualizer documentation](https://autowarefoundation.github.io/openadkit/deployments/components/#visualizer).

```bash
docker run --rm --name visualizer --network host \
  -e REMOTE_PASSWORD=yourpassword \
  ghcr.io/autowarefoundation/openadkit:visualizer-humble
```

Open `http://localhost:6080/vnc.html`.
