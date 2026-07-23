# CARLA Simulation

Run the full modular Autoware stack against CARLA 0.9.16 in closed loop.

## Requirements

Host (no ROS install required):

- amd64 and Ubuntu 22.04
- Docker with NVIDIA Container Toolkit
- NVIDIA GPU and Vulkan ICD at `/usr/share/vulkan/icd.d/nvidia_icd.json`
- Host X access only for optional windowed rendering; offscreen mode is default

Container images use ROS 2 Humble (including the default
`sensing-perception-cuda` Autoware image). CARLA 0.9.16 uses Unreal Engine 4.26
and is not validated on Ubuntu 24.04.

## Setup

Install Docker and the NVIDIA toolkit once:

```bash
{{ install_command }}
```

--8<-- "includes/docker-group-activation.md"

Choose one layout. Map assets are downloaded by the launcher (not
`install.sh sample-data`):

=== "Source checkout"

    ```bash
    git clone https://github.com/autowarefoundation/openadkit.git
    cd openadkit/deployments/carla-simulation
    ```

=== "Release bundle"

    ```bash
    curl -fL https://github.com/autowarefoundation/openadkit/releases/latest/download/carla-simulation.tar.gz | tar xz
    cd carla-simulation
    ```

    The CARLA bundle vendors compose and env files but does not ship `install.sh`
    (host Docker/NVIDIA still come from the install command above; Town01 maps
    come from `./start-carla-e2e-demo.sh`).

Set the required host UDP buffers before starting:

```bash
sudo sysctl -w net.core.rmem_max=2147483647 net.core.wmem_max=2147483647 \
  net.core.rmem_default=134217728 net.core.wmem_default=134217728
```

## Run

```bash
./start-carla-e2e-demo.sh
```

The launcher verifies Docker, NVIDIA, Vulkan, and UDP settings; downloads and
checksum-validates the Town01 assets; starts CARLA and the modular stack; and
checks localization, LiDAR, and the ego actor. Failed startup removes only the
services started by that invocation.

`sensor_mapping.yaml` enables LiDAR, IMU, and GNSS by default. Camera entries
are available but commented out.

--8<-- "includes/visualizer-remote-access.md"

Set a goal with **2D Goal Pose** and select **Auto** in RViz2. To automate route
selection, engagement, and movement verification, run:

```bash
./start-carla-e2e-demo.sh --drive
```

## Stop

=== "Source checkout"

    ```bash
    docker compose --env-file ../base/base.env --env-file carla-simulation.env down
    ```

=== "Release bundle"

    ```bash
    docker compose --env-file carla-simulation.env down
    ```

If autonomous mode is unavailable, inspect `/system/command_mode/availability`
and `/diagnostics_graph/status` rather than overriding availability. For common
Docker, GPU, and visualizer issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
