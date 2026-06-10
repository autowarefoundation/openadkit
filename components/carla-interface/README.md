# CARLA Interface

This image packages Autoware's CARLA interface with the CARLA 0.9.16 Python API for the CARLA e2e sample.

```bash
docker run --rm --network host ghcr.io/autowarefoundation/openadkit:carla-interface
```

The image is built by GitHub Actions as part of the component pipeline from `components/docker-bake.hcl`.

To build it locally:

```bash
docker buildx bake -f components/docker-bake.hcl \
  --set carla-interface.tags=openadkit:carla-interface \
  --load \
  carla-interface
```
