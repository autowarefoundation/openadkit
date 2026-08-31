# CARLA Simulation

Closed-loop Autoware against CARLA 0.9.16. Humble, amd64, and an NVIDIA GPU
are required.

```bash
./openadkit setup --gpu --verify
./openadkit run carla-simulation --gpu
./openadkit stop carla-simulation
```

Optional helpers after the stack is running:

```bash
./start-carla-e2e-demo.sh --drive    # route + engage
./start-carla-e2e-demo.sh --build    # bake carla-interface locally
```
