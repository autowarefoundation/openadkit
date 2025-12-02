# Zenoh Bridge Demo (Local Environment)

This directory contains the local deployment setup for the Zenoh Bridge demo.
It supports two modes of operation: **Split Topology** (recommended for simulating Edge-Cloud interaction) and **Monolithic** (for quick testing).

## Architecture

*   **Edge Side**: Autoware, Scenario Simulator, Edge Zenoh Bridge.
*   **Cloud Side**: Cloud Zenoh Bridge, Visualizer.
*   **Network**: All services run on a single Docker Bridge network (`local_net`), but are logically separated by the bridge.

## Mode 1: Split Topology (Recommended)

This mode uses separate scripts to manage Edge and Cloud services, simulating a distributed environment.

### 1. Start Edge Services
```bash
./edge.sh up -d
```

### 2. Start Cloud Services
```bash
./cloud.sh up -d
```

### 3. Access Visualizer
*   **URL**: `http://localhost:6081`
*   **Password**: `o`

## Mode 2: Monolithic

This mode starts all services at once using standard Docker Compose.

```bash
docker compose up -d
```

## Configuration

*   **Config File**: `./config/zenoh-bridge-ros2dds.json5`
*   **Ports**:
    *   Visualizer: 6081 (Host) -> 6080 (Container)
    *   Zenoh Bridges: 7447 (Edge), 7448 (Cloud)
