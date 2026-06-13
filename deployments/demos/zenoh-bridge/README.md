# Zenoh Bridge Demo

This project demonstrates how to bridge Autoware data from Edge to Cloud using Zenoh.

## Documentation

For **complete architecture documentation**, setup instructions, troubleshooting, and multi-machine deployment details, see the canonical documentation:

**[Open AD Kit Docs — Zenoh Bridge Demo](https://autowarefoundation.github.io/openadkit/deployment/demos/zenoh-bridge/)**

## Demo Video

[![[openadkit x zenoh-bridge] remote control (cloud/edge) demo](https://img.youtube.com/vi/6yhhxlVQTKI/0.jpg)](https://www.youtube.com/watch?v=6yhhxlVQTKI)

## Quick Start

First download the sample map (mounted by the Autoware service). From a cloned repo, use `../../scripts/fetch-sample-data.sh` instead:

```bash
./fetch-sample-data.sh zenoh-bridge
```

### Split Topology (Recommended)

Before starting, set a password for the visualizer in `.env`:

```bash
# Edit .env and set REMOTE_PASSWORD to a secure value
```

```bash
./edge.sh up -d
./cloud.sh up -d
```

Access the visualizer at `http://localhost:6081` (use the `REMOTE_PASSWORD` set in `.env`).

### Monolithic

```bash
# Make sure to set REMOTE_PASSWORD in .env first
docker compose up -d
```

## Teleoperation Controls

The teleop backend only runs when the cloud side is started with `--with-teleop`:

```bash
./cloud.sh up --with-teleop -d
./run_teleop.sh
```

| Key | Function |
|-----|----------|
| **W/S** | Throttle / Brake |
| **A/D** | Turn Left / Right |
| **Z** | Toggle Auto/Local Control |
| **Space** | Emergency Stop / Resume |
| **Q** | Quit |

## CLI Reference

| Command | Description |
|---------|-------------|
| `up -d` | Start services in background |
| `down` | Stop and remove services |
| `dry-run` | Preview config without starting |

## Shutdown

```bash
./cloud.sh down
./edge.sh down
```
