# Zenoh Bridge Demo

This project demonstrates how to bridge Autoware data from Edge to Cloud using Zenoh.

## Demo

[![[openadkit x zenoh-bridge] remote control (cloud/edge) demo](https://img.youtube.com/vi/6yhhxlVQTKI/0.jpg)](https://www.youtube.com/watch?v=6yhhxlVQTKI)

| Time  | Description                  |
| :---- | :--------------------------- |
| 00:00 | Start cloud services         |
| 00:16 | Start edge services          |
| 00:52 | Demo: Stop, planning, resume |
| 01:53 | Stop edge and cloud services |

## Project Structure

The project provides different deployment strategies to suit various testing needs:

### Monolithic Demo
*   Single compose deployment without network separation.
*   Usage: `docker compose up -d`

### Split Topology Demo
*   Simulates Edge/Cloud separation (Unified local environment).
*   Usage: `./edge.sh up -d` + `./cloud.sh up -d`

## Quick Start

We recommend using the Split Topology mode in the `local` directory:

```bash
cd local
./edge.sh up -d
./cloud.sh up -d
```

Then access the visualizer at `http://localhost:6081`.



## Distributed Deployment (Multi-Machine)

To deploy on separate machines (e.g., one Cloud, one Edge):

1.  **Cloud Machine**:
    Run `cloud.sh` to start services. It will automatically detect and display available IP addresses:
    ```bash
    ./cloud.sh
    # [Info] Cloud services started.
    #        To connect from Edge, set CLOUD_IP to one of the following:
    #        [Public/Routable IPs]
    #        - 192.168.1.100
    ```

2.  **Edge Machine**:
    Use the displayed IP to connect:
    ```bash
    export CLOUD_IP=192.168.1.100
    ./edge.sh
    ```

## CLI Reference

Scripts (`cloud.sh`, `edge.sh`) support the following commands:

*   `up [args]` (default): Start services (foreground). To run in background, add `-d` (e.g., `./cloud.sh up -d`).
*   `down`: Stop and remove services.
*   `dry-run`: Preview composition config and connection information without starting containers.
    *   Useful for checking `CLOUD_IP` candidates on the Cloud machine without launching everything.
*   `...`: Any other command (e.g., `logs`, `restart`, `ps`) is passed directly to `docker compose`.

## Shutdown

To stop the containers:

```bash
# Stop Cloud
./cloud.sh down

# Stop Edge
./edge.sh down

# Stop All and remove volumes
docker compose down -v
```
