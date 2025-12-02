# Zenoh Bridge Demo (Local Mono-Compose)

This directory contains a **Monolithic** deployment setup for the Zenoh Bridge demo.
Unlike `local-cloud-edge` which splits services into Edge and Cloud groups, this setup uses a single `docker-compose.yaml` to launch the entire stack at once.

## Purpose

*   **Simplicity**: Easiest way to bring up the full environment for quick testing.
*   **Legacy Compatibility**: Maintains the original deployment style where all services run together.

## Quick Start

### 1. Start All Services
```bash
docker compose up -d
```
This command starts Autoware, Scenario Simulator, Edge Bridge, Cloud Bridge, and Visualizer simultaneously.

### 2. Access Visualizer
Open your browser and visit:
*   **URL**: `http://localhost:6080` (or `6081` depending on configuration)
*   **Password**: `o` (if prompted)

## Components

*   **Edge**: Autoware, Scenario Simulator, Edge Zenoh Bridge.
*   **Cloud**: Cloud Zenoh Bridge, Visualizer.
*   **Network**: All services share the same `local_net` bridge network.
