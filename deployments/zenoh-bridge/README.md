# Open AD Kit Zenoh Bridge

This deployment bridges Autoware data from Edge to Cloud using Zenoh for remote visualization and control.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — Zenoh Bridge](https://autowarefoundation.github.io/openadkit/deployment/zenoh-bridge/)**

## Quick Start

```bash
./install.sh sample-data zenoh-bridge
```

### Split Topology (Recommended)

Set a password in `.env`, then start each side in its own terminal:

```bash
./edge.sh up -d
./cloud.sh up -d
```

Access the visualizer at `http://localhost:6081`.

### Monolithic

```bash
docker compose up -d
```

*Cloned repo: run `../../install.sh` instead; pass `--env-file ../base/base.env` before the deployment env file.*

## Teleoperation

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
