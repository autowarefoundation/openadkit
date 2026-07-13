# Open AD Kit Zenoh Bridge

This deployment bridges Autoware data from Edge to Cloud using Zenoh for remote visualization and control.

## Documentation

For complete operational instructions, see the canonical documentation:

**[Open AD Kit Docs — Zenoh Bridge](https://autowarefoundation.github.io/openadkit/deployment/zenoh-bridge/)**

## Quick Start

```bash
cp .env.example .env
./install.sh sample-data zenoh-bridge
```

Set `REMOTE_PASSWORD` in `.env` before starting. Docker Compose reads this file
without sourcing it; exported shell variables take precedence.

### Split Topology (Recommended)

Start each side in its own terminal:

```bash
./edge.sh up -d
./cloud.sh up -d
```

Access the visualizer at `https://localhost:6081/vnc.html` (accept the self-signed certificate warning).

For separate machines, expose TCP 7448 only on an exact VPN/private-interface
address and restrict it to trusted peers. Zenoh transport is not authenticated
or encrypted; `REMOTE_PASSWORD` protects only the noVNC visualizer.

### Monolithic

```bash
docker compose up -d
```

*Cloned repo: run `../../install.sh` instead.*

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
