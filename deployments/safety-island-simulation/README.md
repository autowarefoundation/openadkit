# Safety Island Simulation

Planning Simulation driven by the
[Autoware Safety Island](https://github.com/autowarefoundation/autoware-safety-island)
instead of Autoware's own trajectory follower. Autoware runs on DDS domain 1,
the Safety Island on domain 2, and
[`domain_bridge`](https://github.com/ros2/domain_bridge) connects them.

| File | What it does |
| --- | --- |
| `deployment.json` | Pins the Safety Island release by SHA-256: its FreeRTOS POSIX binary, its `bridge-config.yaml` topic contract and its `cyclonedds-domain2.xml` DDS setting |
| `docker-compose.yaml` | Adds the `safety-island` and `safety-island-bridge` services to Planning Simulation |
| `config.env` | Where the release is fetched, and the diagnostics graph below |
| `config/autoware/autoware_control_config/.../default_preset.yaml` | The default control preset with `trajectory_follower_mode: none` |
| `config/autoware/autoware_launch/.../autoware-safety-island.yaml` | Autoware's main diagnostics graph without the follower's `control_state`, which nothing publishes any more |

The deployment uses the release's files as they are. The bridge carries the topics of
`bridge-config.yaml`, and `cyclonedds-domain2.xml` keeps its domain-2 datagrams
within what the Safety Island receives. Both containers use the DDS interface of
the rest of the stack (`lo` unless the host settings set
`CYCLONEDDS_NETWORK_INTERFACE`).

## Run

```bash
openadkit run safety-island-simulation
```

`run` fetches the release on first use. Set the initial pose and a goal in RViz
(or through the AD API) and engage: the vehicle follows the Safety Island's
control command. The `safety-island` container logs `Waiting for ... data`
until localization is initialized.

`run` warns that the override adds `autoware-safety-island.yaml`, which
`autoware_launch` does not have. That is expected: the file is new.

The released binary is linux/amd64 only. The deployment inherits Planning
Simulation's requirements, so `validate` accepts arm64, but the Safety Island
container does not start there.

## Evidence

`run` waits for the bridge's healthcheck (`checks/safety_island.py`): the
control command's only publisher is the Safety Island's bridge, and Autoware's
follower is not running. `run --verify` then runs Planning Simulation's golden
path, as the evidence cell does.

## Upgrade

Update the release tag in the three URLs and the three checksums in
`deployment.json` (from the release's `sha256sums.txt`), and the tag in
`SAFETY_ISLAND_PATH`.
