# Getting Started

## Requirements

- Docker Engine
- NVIDIA Container Toolkit and OpenGL/Vulkan libraries (Optional but highly recommended for sensing, perception, and CARLA)
- Autoware artifacts (Optional in general, but required for sensing and perception deployments such as Logging Simulation)

    > All the above requirements can be installed by running the **install.sh** script.

## Installation

1. Clone the repository

    ```bash
    git clone https://github.com/autowarefoundation/openadkit
    cd openadkit
    ```

2. Set up the runtime environment by running the `install.sh` script located at the root of the repository. This requires sudo privileges (skip if you already have the environment set up on your platform):

    ```bash
    sudo ./install.sh
    ```

    Start a new shell with the Docker group before running Docker without sudo:

    ```bash
    newgrp docker
    ```

    > You can use the `--no-nvidia` flag to skip the NVIDIA Container Toolkit and OpenGL/Vulkan libraries if you don't have a **NVIDIA GPU**. Otherwise, it's **highly recommended** to install them for CUDA and GPU rendering.

3. Download the Autoware artifacts by running the following command, requires sudo privileges:

    ```bash
    sudo ./install.sh --download-artifacts
    ```

    > This still runs host Docker setup (idempotent if Docker is already
    > installed). It is **not** a data-only mode like the old `setup.sh
    > --download-artifacts`. Required for deployments that mount
    > `${HOME}/autoware_data`, including Logging Simulation.

4. Download sample maps/rosbags for the deployment you want to run (no sudo):

    ```bash
    ./install.sh sample-data planning-simulation
    # or: logging-simulation | scenario-simulation | zenoh-bridge | all
    ```

    > CARLA maps are fetched by `deployments/carla-simulation/start-carla-e2e-demo.sh`, not `sample-data`.

## Next Steps

- [Running a sample deployment](../deployments/index.md)
- [Learn more about the Open AD Kit components](../components/index.md)
