# Autoware Open AD Kit AWSIM E2E Simulation

This sample runs closed-loop AWSIM v2 end-to-end simulation with modular OpenADKit containers.

AWSIM publishes Autoware-compatible ROS 2 sensor and vehicle status topics directly, so this sample does not need a simulator bridge container like the CARLA sample.

## Runtime

- AWSIM: `AWSIM-Demo-Lightweight.zip` from `autowarefoundation/AWSIM` `v2.0.1`, built into a local Docker image
- Autoware modules: standard OpenADKit split images
- AWSIM map: West Shinjuku, Tokyo
- Autoware map assets: `$HOME/autoware_data/maps/Shinjuku`
- RViz/noVNC: `ghcr.io/autowarefoundation/openadkit:visualizer`

## Requirements

- Ubuntu 22.04 host with Docker and Docker Compose
- NVIDIA GPU with driver 570 or newer for AWSIM v2 raytracing
- NVIDIA Container Toolkit registered as the Docker `nvidia` runtime
- Host NVIDIA Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`
- `curl` and `unzip` on the host for map download/extraction
- Large kernel UDP buffers for DDS; the start script raises them via `sudo sysctl`

AWSIM runs under `xvfb-run` by default, so a physical X display is not required on a remote GPU VM. The AWSIM Xvfb server uses display `:98` by default to avoid colliding with the visualizer TigerVNC display `:99`.

## Start

```bash
./start-awsim-e2e-demo.sh
```

The helper will:

- Build `openadkit-awsim-demo:v2.0.1` from the sample Dockerfile if missing.
- Download and unpack the official AWSIM Shinjuku map assets if missing.
- Start AWSIM as `awsim-e2e` in host-networked, NVIDIA-enabled Docker.
- Start modular OpenADKit map, system, sensing, perception, localization, planning, vehicle, control, and API containers.
- Start the browser RViz/noVNC visualizer.
- Verify `/clock`, AWSIM LiDAR, and Autoware localization.

Use `--build` to force rebuilding the AWSIM runtime image. Use `--skip-build` when the image already exists and should not be rebuilt. Other options: `--no-visualizer` (skip the RViz/noVNC container), `--skip-verify` (skip topic and localization checks), and `--dry-run` (print the planned commands without running them). Run `./start-awsim-e2e-demo.sh --help` for the full list.

The default behavior is no-drive. Set the route and engage manually in RViz.

## Open RViz

When running on a remote GPU host, forward the noVNC port over SSH:

```bash
ssh -L 6080:localhost:6080 <user>@<gpu-host>
```

Open:

```text
http://localhost:6080/vnc.html
```

Password:

```text
openadkit
```

In RViz:

- Use `2D Goal Pose` to set a route on the Shinjuku map.
- Wait for routing and planning to become available.
- Click `Auto` to engage autonomous driving.

## Optional Drive Check

To attempt an automated route, engage autonomous mode, ask AWSIM to switch to autonomous control mode, and verify movement:

```bash
./start-awsim-e2e-demo.sh --drive
```

By default, `awsim-simulation.e2e.env` includes a lane-valid Shinjuku goal for the deterministic ego start pose in `awsim-config.json`. To use a different route, set another fixed goal:

```text
AWSIM_E2E_GOAL_X=<map x>
AWSIM_E2E_GOAL_Y=<map y>
AWSIM_E2E_GOAL_YAW=<yaw radians>
```

## Stop

```bash
docker compose --env-file awsim-simulation.e2e.env -f docker-compose.yaml down
```

## Configuration

`awsim-config.json` is mounted into the AWSIM container and passed with `--json_path`. It fixes the Shinjuku ego start pose and random traffic seed to keep runs repeatable.

Set `AWSIM_ASSET=AWSIM-Demo.zip` in `awsim-simulation.e2e.env` if you want the full AWSIM demo asset instead of the lightweight asset.

Set `VISUALIZER_IMAGE` if you need to test a locally built visualizer image, for example when validating RViz GPU/VirtualGL changes before they are published to GHCR.
