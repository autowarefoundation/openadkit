# CARLA Simulation

Closed-loop CARLA 0.9.16 end-to-end simulation with modular Open AD Kit
containers and `autoware_carla_interface`. Checkout assets live under
`deployments/carla-simulation/`.

## Runtime

- CARLA: `carlasim/carla:0.9.16` (default offscreen)
- Interface: `ghcr.io/autowarefoundation/openadkit:carla-interface-amd64-humble`
- Map: `Town01` → `$HOME/autoware_data/maps/Town01`

## Prerequisites

- Docker with NVIDIA runtime (`nvidia-ctk runtime configure --runtime=docker`)
- Run as a user in the `docker` group (**not** `sudo` — `sudo` resets `HOME` and
  breaks `MAP_PATH`)
- NVIDIA Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`
- Large kernel UDP buffers for DDS:

```bash
sudo sysctl -w net.core.rmem_max=2147483647 net.core.wmem_max=2147483647 \
  net.core.rmem_default=134217728 net.core.wmem_default=134217728
```

Tested on Ubuntu 22.04; other hosts may work if Docker/NVIDIA/Vulkan are present.

## Start

```bash
cd deployments/carla-simulation
./start-carla-e2e-demo.sh
```

The helper downloads Town01 map assets (checksummed), starts CARLA, preloads
the map via `carla-map-loader`, then brings up Autoware components and (by
default) the visualizer.

Optional:

```bash
./start-carla-e2e-demo.sh --build    # build carla-interface locally
./start-carla-e2e-demo.sh --drive    # auto route + engage smoke check
```

## Visualizer

`https://localhost:6080/vnc.html` — password from `config.env`
(`REMOTE_PASSWORD`). In RViz: set **2D Goal Pose**, wait for planning, click
**Auto**.

## Stop

```bash
cd deployments/carla-simulation
./start-carla-e2e-demo.sh --down
# or: docker compose --env-file config.env down
```

## Notes

- Default render is offscreen (`CARLA_RENDER_ARGS=-RenderOffScreen`). For an
  on-screen window, clear that flag and set `CARLA_DISPLAY` + X11 access.
- `carla-map-loader` is force-recreated whenever CARLA is recreated so Town01
  preload cannot be skipped on relaunch.
