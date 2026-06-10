# Autoware Open AD Kit CARLA E2E Simulation

This sample runs closed-loop CARLA 0.9.16 end-to-end simulation with modular OpenADKit containers and Autoware's `autoware_carla_interface`.

The default runtime uses the official CARLA Ubuntu 22 container image. It does not use the CARLA ROS bridge, dummy vehicle, dummy perception, a monolithic Autoware container, or a host-installed CARLA runtime.

## Runtime

- CARLA: `carlasim/carla:0.9.16`
- CARLA interface image: `ghcr.io/autowarefoundation/openadkit:carla-interface`
- Autoware modules: standard OpenADKit split images
- CARLA map: `Town01`
- Autoware map assets: `$HOME/autoware_data/maps/Town01`
- RViz/noVNC: `ghcr.io/autowarefoundation/openadkit:visualizer`

## Requirements

- Docker with NVIDIA Container Toolkit
- Access to `carlasim/carla:0.9.16`
- A working host X display, usually `DISPLAY=:0`
- Host X access for local Docker containers, for example `xhost +SI:localuser:root`
- Host NVIDIA Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`

## Start

```bash
./start-carla-e2e-demo.sh
```

The helper will:

- Use the CI-built `ghcr.io/autowarefoundation/openadkit:carla-interface` image.
- Download the official CARLA Autoware Town01 map assets if missing.
- Start `carlasim/carla:0.9.16` as `carla-e2e` on `DISPLAY=:0`.
- Preload `Town01`.
- Start modular OpenADKit map, system, CARLA interface, sensing, perception, localization, planning, vehicle, control, and API containers.
- Start the browser RViz/noVNC visualizer.
- Verify localization, CARLA LiDAR, and the CARLA ego actor.

Use `--build` to build the CARLA interface image locally from `components/carla-interface` before starting the stack.

The default behavior is no-drive. Set the route and engage manually in RViz.

## Open RViz

If running remotely, forward noVNC from the machine running the sample:

```bash
ssh -L 8080:localhost:6080 <user>@<host>
```

Open:

```text
http://localhost:8080/vnc.html
```

Password:

```text
openadkit
```

In RViz:

- Use `2D Goal Pose` to set a route.
- Wait for routing and planning to become available.
- Click `Auto` to engage autonomous driving.

## Optional Drive Check

To automatically set a short forward route, engage autonomous mode, and verify movement:

```bash
./start-carla-e2e-demo.sh --drive
```

Expected success output includes:

```text
Route set: start=(..., ...) goal=(..., ...)
Autonomous mode active
Moved ... m: start=(..., ...) current=(..., ...)
```

## Faster Relaunch

The helper does not build the CARLA interface image unless `--build` is passed, so relaunching uses the configured image directly:

```bash
./start-carla-e2e-demo.sh
```

For start-only behavior with an explicit no-drive flag:

```bash
./start-carla-e2e-demo.sh --no-drive
```

## Command Path

Closed-loop control uses this path:

```text
/control/command/control_cmd
  -> autoware_raw_vehicle_cmd_converter
  -> /control/command/actuation_cmd
  -> autoware_carla_interface
  -> CARLA ego vehicle
```

## Stop

```bash
docker compose --env-file carla-simulation.e2e.env -f docker-compose.yaml down
```
