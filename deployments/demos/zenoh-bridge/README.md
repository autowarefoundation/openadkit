# Zenoh Bridge Demo

This project demonstrates how to bridge Autoware data from Edge to Cloud using Zenoh.

## Project Structure

The project provides different deployment strategies to suit various testing needs:

### 1. `local-cloud-edge` (Recommended for PR/Demo)
*   **Path**: `./local-cloud-edge`
*   **Description**: A clean, simplified setup that splits services into **Edge** and **Cloud** groups.
*   **Usage**: Uses `edge.sh` and `cloud.sh` to manage services independently (though they share a network).
*   **Best for**: Demonstrating the Edge-Cloud architecture and verifying connectivity.

### 2. `local-mono-compose` (Monolithic)
*   **Path**: `./local-mono-compose`
*   **Description**: A traditional setup where all services are defined in a single `docker-compose.yaml`.
*   **Usage**: Uses `docker compose up` to launch everything at once.
*   **Best for**: Quick local testing without script complexity.

### 3. `net-topo-test` (Advanced Networking)
*   **Path**: `./net-topo-test`
*   **Description**: Experimental setups for testing complex network topologies (e.g., multi-network, double-bridge).
*   **Status**: Under active development.

### 4. `probe_tool` (Monitoring)
*   **Path**: `./probe_tool`
*   **Description**: Custom Python tools for monitoring ROS 2 topics and Zenoh sessions.

## Quick Start (Standard Demo)

We recommend starting with `local-cloud-edge`:

```bash
cd local-cloud-edge
./edge.sh up -d
./cloud.sh up -d
```

Then access the visualizer at `http://localhost:6081`.
