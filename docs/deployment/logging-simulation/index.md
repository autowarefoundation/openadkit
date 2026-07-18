# Logging Simulation

Replay a demo rosbag through sensing, perception, localization, planning, and
control. An NVIDIA GPU with at least 4 GB VRAM is strongly recommended; CPU
operation is supported but substantially slower.

## Setup

Install Docker, NVIDIA support, and Autoware perception artifacts:

```bash
{{ install_command }} --download-artifacts
```

--8<-- "includes/docker-group-activation.md"

=== "Source checkout"

    ```bash
    git clone https://github.com/autowarefoundation/openadkit.git
    cd openadkit/deployments/logging-simulation
    ../../install.sh sample-data logging-simulation
    ```

=== "Release bundle"

    ```bash
    curl -fL https://github.com/autowarefoundation/openadkit/releases/latest/download/logging-simulation.tar.gz | tar xz
    cd logging-simulation
    ./install.sh sample-data logging-simulation
    ```

The demo rosbag is Copyright 2020 TIER IV, Inc. It contains no camera images,
so traffic-light recognition is unavailable and object detection is less
complete than with a full recording.

## Start the Stack

=== "Source checkout"

    ```bash
    docker compose --env-file ../base/base.env --env-file logging-simulation.env up -d
    ```

=== "Release bundle"

    ```bash
    docker compose --env-file logging-simulation.env up -d
    ```

For NVIDIA acceleration, add the GPU overlay:

=== "Source checkout"

    ```bash
    docker compose -f docker-compose.yaml -f docker-compose.gpu.yaml \
      --env-file ../base/base.env --env-file logging-simulation.env \
      --env-file logging-simulation.gpu.env up -d
    ```

=== "Release bundle"

    ```bash
    docker compose -f docker-compose.yaml -f docker-compose.gpu.yaml \
      --env-file logging-simulation.env --env-file logging-simulation.gpu.env up -d
    ```

The CUDA image is amd64-only.

--8<-- "includes/visualizer-remote-access.md"

## Play the Rosbag

=== "Source checkout"

    ```bash
    docker compose --env-file ../base/base.env --env-file logging-simulation.env \
      --profile rosbag up -d rosbag
    ```

=== "Release bundle"

    ```bash
    docker compose --env-file logging-simulation.env --profile rosbag up -d rosbag
    ```

Playback waits for `ROSBAG_READY_TOPIC` for up to `ROSBAG_READY_TIMEOUT` seconds
before starting.

## Stop and Recover

=== "Source checkout"

    ```bash
    docker compose --env-file ../base/base.env --env-file logging-simulation.env --profile rosbag down
    ```

=== "Release bundle"

    ```bash
    docker compose --env-file logging-simulation.env --profile rosbag down
    ```

The rosbag service currently uses the upstream `autoware:universe` image;
release bundles pin its manifest digest. To replace missing sample data, run
`../../install.sh sample-data logging-simulation --force` from a source checkout
or `./install.sh sample-data logging-simulation --force` from a bundle. For
common issues, see
[Troubleshooting](../../getting-started/troubleshooting.md).
