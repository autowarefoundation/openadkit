# Getting Started

## Requirements

- Docker Engine
- NVIDIA Container Toolkit (Optional but highly recommended for sensing and perception tasks)
- Autoware artifacts (Optional in general, but required for sensing and perception deployments such as Logging Simulation)

    > All the above requirements can be installed by running the **setup.sh** script.

## Installation

1. Clone the repository

    ```bash
    git clone https://github.com/autowarefoundation/openadkit
    cd openadkit
    ```

2. Setup the runtime environment by running the `setup.sh` script located at the root of the repository. This requires sudo privileges (skip if you already have the environment setup on your platform):

    ```bash
    sudo ./setup.sh
    ```

    > You can use the `--no-nvidia` flag to skip the installation of the NVIDIA Container Toolkit if you don't have a **NVIDIA GPU**. Otherwise, it's **highly recommended** to install it to utilize CUDA for better performance for sensing and perception tasks.

3. Download the Autoware artifacts by running the following command, requires sudo privileges:

    ```bash
    sudo ./setup.sh --download-artifacts
    ```

    > This step is required for deployments that mount `${HOME}/autoware_data`, including the Logging Simulation sample.

## Next Steps

- [Running a sample deployment](../deployments/index.md)
- [Learn more about the Open AD Kit components](../components/index.md)
