# CARLA Interface

This image packages Autoware's CARLA interface with the CARLA 0.9.16 Python API for the CARLA e2e sample.

The image has no default launch command. From the Open AD Kit repository root,
run it through the [CARLA Simulation deployment](https://autowarefoundation.github.io/openadkit/deployment/carla-simulation/) launcher, which prepares the map and supplies the complete Compose configuration:

```bash
cd deployments/carla-simulation
./start-carla-e2e-demo.sh
```

The image is built by GitHub Actions as part of the component pipeline from `components/docker-bake.hcl`.

After preparing `autoware/src` as described in the build-from-source guide, run
the following from the repository root:

```bash
docker buildx bake -f components/docker-bake.hcl \
  --set carla-interface.tags=openadkit:carla-interface \
  --load \
  carla-interface
```
