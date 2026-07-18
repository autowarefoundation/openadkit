# Zenoh Bridge

Bridges Autoware data from edge to cloud for remote visualization and control.
See the [canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/zenoh-bridge/)
for topology, configuration, and teleoperation.

## Setup

```bash
cp .env.example .env
../../install.sh sample-data zenoh-bridge
```

From a release bundle, replace the install command with:

```bash
./install.sh sample-data zenoh-bridge
```

Set `REMOTE_PASSWORD` in `.env` before starting.

## Start

```bash
./cloud.sh up -d
./edge.sh up -d
```

Open `https://localhost:6081/vnc.html` and accept the self-signed certificate.

**Warning:** TCP 7448 has no transport authentication or encryption. For
separate machines, bind it to an exact VPN/private-interface address and
restrict it to trusted peers. `REMOTE_PASSWORD` protects only the noVNC
visualizer.

## Stop

```bash
./edge.sh down
./cloud.sh down
```
