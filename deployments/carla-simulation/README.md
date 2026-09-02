# CARLA Simulation

Closed-loop Autoware against CARLA 0.9.16. Humble, amd64, and an NVIDIA GPU
are required.

```bash
./openadkit setup --gpu --verify
./openadkit run carla-simulation --gpu
./openadkit stop carla-simulation
```

Bake a local `carla-interface` image **before** run (then re-run to pick it up):

```bash
./start-carla-e2e-demo.sh --build
```

After the stack is running:

```bash
./start-carla-e2e-demo.sh --drive    # route + engage
```
