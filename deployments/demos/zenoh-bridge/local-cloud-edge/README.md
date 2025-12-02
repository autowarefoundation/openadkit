# Zenoh Bridge Demo (Local Cloud-Edge)

This is a simplified Zenoh Bridge deployment example, demonstrating how to bridge Edge Autoware data to the Cloud for visualization using the Zenoh protocol.
This version (`local-cloud-edge`) is to provide the simplest cloud-edge demo, removing redundant test containers to provide a clean experience.

## Architecture Overview

This demo simulates Edge and Cloud interaction within a single Docker Network (`local_net`):

*   **Edge Side**:
    *   `autoware`: Runs Autoware Universe (Planning Simulator).
    *   `scenario_simulator`: Generates virtual scenarios and sensor data.
    *   `edge_zenoh_bridge`: Responsible for forwarding ROS 2 data to the Cloud.
*   **Cloud Side**:
    *   `cloud_zenoh_bridge`: Receives data from the Edge.
    *   `visualizer`: Cloud visualization tool (NoVNC), accessible via browser.

## Quick Start

### 1. Start Edge Services
```bash
./edge.sh up -d
```
This command starts Autoware, the Simulator, and the Edge Bridge.

### 2. Start Cloud Services
```bash
./cloud.sh up -d
```
This command starts the Cloud Bridge and the Visualizer.

### 3. Access Visualizer
Open your browser and visit:
*   **URL**: `http://localhost:6081` (Note: Port mapped to 6081 to avoid conflicts with other local services)
*   **Password**: `o` (if prompted)

## Current Status & Known Issues

### Stability
*   **Single Topology**: Currently uses a single Docker Network with a 100% connection success rate.
*   **Visualizer**: Configured to listen on `0.0.0.0`, supporting remote access (requires SSH Tunnel or firewall configuration).

### Known Issues
*   **Disconnection after Scenario Ends**: It has been observed that when the Scenario Simulator finishes a scenario (approx. 30 seconds), the Cloud Visualizer may show a "Global Warning" or lose connection. This might be related to `/clock` stopping or topics becoming inactive.

## Development Progress
- [x] Simplified Docker Compose configuration (removed redundant test nodes).
- [x] Fixed startup scripts (`common.sh`) ignoring arguments bug.
- [x] Supported remote access (Port Bind `0.0.0.0`).
- [ ] Integration of multi-domain test results from `net-topo-test`.
