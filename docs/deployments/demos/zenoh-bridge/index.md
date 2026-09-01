# Zenoh Bridge

Splits Autoware and visualization into edge/cloud networks connected through
Zenoh inside one Compose project. Checkout assets live under
`deployments/zenoh-bridge/`.

## Security

- noVNC is loopback-bound; set `REMOTE_PASSWORD` in `config.env` (required).
- Zenoh TCP 7448 stays on the internal Compose network and is not published to
  the host.
- Control topics (engage, emergency, teleop cmd) are on the allow-list — treat
  7448 as a vehicle-control plane.

## Setup

```bash
./openadkit fetch scenario-simulation
cd deployments/zenoh-bridge
```

## Run

```bash
./cloud.sh up -d
./edge.sh up -d
```

Visualizer: `https://localhost:6081/vnc.html`

## Teleoperation

```bash
./cloud.sh up --with-teleop -d
./edge.sh --no-sim -d   # or default with sim
./run_teleop.sh
```

| Key | Function |
| --- | --- |
| W/S | Throttle / Brake |
| A/D | Steer left / right |
| Z | Toggle Auto/Local control mode |
| M | Cycle STOP → PHYSICS → CRUISE |
| X/C/V | Gear D / R / P |
| Space | Emergency stop / resume |
| R | Reset pose |
| Q | Quit |

## Stop

```bash
./edge.sh down
./cloud.sh down
```

## Notes

- Prefer `./cloud.sh` / `./edge.sh` over raw `docker compose up`.
- Map files must exist under `MAP_PATH` before `edge.sh` starts.
