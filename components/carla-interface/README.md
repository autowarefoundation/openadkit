# CARLA Interface

This image packages Autoware's CARLA interface with the CARLA 0.9.16 Python API
for the CARLA e2e deployment (`deployments/carla-simulation/`).

The image has no default launch command. Start the CARLA deployment with:

```bash
./openadkit setup --gpu --verify
./openadkit run carla-simulation --gpu
```

Guide: [CARLA Simulation docs](https://autowarefoundation.github.io/openadkit/deployment/carla-simulation/)

The image is built by GitHub Actions as part of the component pipeline from `components/docker-bake.hcl`.

After preparing `autoware/src` as described in the build-from-source guide, run
the following from the repository root:

```bash
docker buildx bake -f components/docker-bake.hcl \
  --set carla-interface.tags=openadkit:carla-interface \
  --load \
  carla-interface
```
