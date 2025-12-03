# Zenoh Bridge Demo

This project demonstrates how to bridge Autoware data from Edge to Cloud using Zenoh.

## Project Structure

The project provides different deployment strategies to suit various testing needs:

### 1. Standard Demo
*   Description: The unified local environment supporting both Split Topology (Edge/Cloud separation) and Monolithic deployment.
*   Usage:
    *   Split: `./edge.sh up -d` + `./cloud.sh up -d`
    *   Mono: `docker compose up -d`
*   Best for: General testing, demonstrating Edge-Cloud architecture, and PR verification.

### 2. `net-topo-test` (Advanced Networking)
*   Path: `./net-topo-test`
*   Description: Experimental setups for testing complex network topologies (e.g., multi-network, double-bridge).
*   Status: Under active development.

### 3. `probe_tool` (Monitoring)
*   Path: `./probe_tool`
*   Description: Custom Python tools for monitoring ROS 2 topics and Zenoh sessions.
*   Status: Under active development.

## Quick Start

We recommend using the Split Topology mode in the `local` directory:

```bash
cd local
./edge.sh up -d
./cloud.sh up -d
```

Then access the visualizer at `http://localhost:6081`.

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
