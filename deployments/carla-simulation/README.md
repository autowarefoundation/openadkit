# CARLA Simulation

Closed-loop Autoware against CARLA 0.9.16. Humble, amd64, and an NVIDIA GPU
are required. See the [canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/carla-simulation/).

```bash
cd ../..
./openadkit setup --gpu --verify
./openadkit run carla-simulation --gpu
./openadkit stop carla-simulation
```
