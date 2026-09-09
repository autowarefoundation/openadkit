# CARLA Simulation

Closed-loop CARLA 0.9.16 end-to-end simulation with modular Open AD Kit
containers and `autoware_carla_interface`. Checkout assets live under
`deployments/carla-simulation/`. Humble, amd64, and an NVIDIA GPU are required.

## Runtime

- CARLA: `carlasim/carla:0.9.16` (default offscreen)
- Interface: `ghcr.io/autowarefoundation/openadkit:carla-interface-amd64-humble`
- Map: `Town01` → `$HOME/autoware_data/maps/Town01`

## Prerequisites

- Host setup via [Getting Started](../../../getting-started/index.md):

```bash
./openadkit setup --gpu --verify
```

- Run as a user in the `docker` group (**not** `sudo` — `sudo` resets `HOME` and
  breaks `MAP_PATH`)
- Sample Town01 map:

```bash
./openadkit fetch carla-simulation
```

Tested on Ubuntu 22.04; other hosts may work if Docker and the NVIDIA runtime are present.

## Run

```bash
./openadkit run carla-simulation --gpu
```

Open the visualizer at `https://localhost:6080/vnc.html` (accept the
self-signed certificate). Use `REMOTE_PASSWORD` from `config.env`. In RViz:
set **2D Goal Pose**, wait for planning, click **Auto**.

## Stop

```bash
./openadkit stop carla-simulation
```

## Notes

- Render is offscreen (`CARLA_RENDER_ARGS=-RenderOffScreen`). No host X display
  is required.
- `carla-map-loader` is force-recreated whenever CARLA is recreated so Town01
  preload cannot be skipped on relaunch.
