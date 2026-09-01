# Getting Started

## Requirements

- Docker Engine
- NVIDIA Container Toolkit and OpenGL/Vulkan libraries (Optional but highly recommended for sensing, perception, and CARLA)
- Autoware artifacts (Optional in general, but required for sensing and perception deployments such as Logging Simulation)

    > Host dependencies are installed by `./openadkit setup`.

## Installation

1. Clone the repository

    ```bash
    git clone https://github.com/autowarefoundation/openadkit
    cd openadkit
    ```

2. Set up the runtime environment. This requests sudo only for host changes:

    ```bash
    ./openadkit setup --verify
    ```

    GPU hosts:

    ```bash
    ./openadkit setup --gpu --verify
    ```

    Start a new shell with the Docker group before running Docker without sudo:

    ```bash
    newgrp docker
    ```

3. Run a curated deployment. The CLI fetches the maps and data it needs:

    ```bash
    ./openadkit run planning-simulation
    ```

    Logging Simulation GPU mode is `./openadkit run logging-simulation --gpu`.
    Zenoh is a standalone demo: `./openadkit fetch scenario-simulation`, then
    `deployments/zenoh-bridge/cloud.sh` / `edge.sh`.

## Next Steps

- [Running a sample deployment](../deployments/index.md)
- [Learn more about the Open AD Kit components](../components/index.md)
