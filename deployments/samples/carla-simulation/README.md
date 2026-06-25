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

- Docker with NVIDIA Container Toolkit, registered as the `nvidia` runtime
  (`sudo nvidia-ctk runtime configure --runtime=docker`). Run the demo as a
  user in the `docker` group, not via `sudo`: `sudo` resets `HOME` to `/root`,
  so `${MAP_PATH}` (which uses `$HOME`) interpolates to an empty mount and
  localization never initializes.
- Access to `carlasim/carla:0.9.16`
- A working host X display, usually `DISPLAY=:0`
- Host X access for local Docker containers, for example `xhost +SI:localuser:root`
- Host NVIDIA Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`
- Large kernel UDP buffers for DDS (the start script raises them via `sudo sysctl`):

```bash
sudo sysctl -w net.core.rmem_max=2147483647 net.core.wmem_max=2147483647 \
  net.core.rmem_default=134217728 net.core.wmem_default=134217728
```

With the stock 208 KiB limits the kernel drops fragments of the large
PointCloud2 messages exchanged between the host-networked containers:
subscribers receive lidar at ~4 Hz instead of 10 Hz, localization never
initializes, and the drive check fails. Make the values persistent across
reboots with an `/etc/sysctl.d/` entry if you run the demo regularly.

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

The visualizer renders RViz on the GPU via VirtualGL when one is available,
which keeps RViz smooth with dense point clouds and camera images instead of
falling back to slow software rendering. Detection is automatic; force it with
`RVIZ_GPU=on` or disable it with `RVIZ_GPU=off` (the same image still runs on
hosts without a GPU).

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

## Sensor Configuration

The CARLA interface container uses the sample-local `sensor_mapping.yaml`
(mounted and passed via the `sensor_mapping_file` launch argument) instead of
the package default. It enables LiDAR, IMU, and GNSS only.

The 6 cameras defined by the sensor kit are intentionally not enabled:
perception runs in lidar mode with traffic light recognition disabled, so no
node consumes camera images, while each camera adds CARLA render work inside
every synchronous simulation tick plus multi-megabyte reliable image publishes
inside the bridge loop. On hosts without high single-core CPU clocks this slows
the simulation clock until Autoware's data-freshness gates reject autonomous
engagement. To experiment with cameras, uncomment them under `enabled_sensors`
in `sensor_mapping.yaml`.

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
docker compose --env-file carla-simulation.env -f docker-compose.yaml down
```
