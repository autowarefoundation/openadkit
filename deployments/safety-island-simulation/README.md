# Safety Island Simulation

Planning Simulation driven by the
[Autoware Safety Island](https://github.com/autowarefoundation/autoware-safety-island)
instead of Autoware's own trajectory follower. See the
[canonical documentation](https://autowarefoundation.github.io/openadkit/deployments/safety-island-simulation/)
for requirements and what to expect.

```bash
cd ../..
./openadkit run safety-island-simulation
```

## Files

| File | What it does |
| --- | --- |
| `deployment.json` | Pins the Safety Island release by SHA-256: its FreeRTOS POSIX binary, its `bridge-config.yaml` topic contract and its `cyclonedds-domain2.xml` DDS setting. Requires amd64 and has no GPU mode |
| `compose.yaml` | Planning Simulation's services, plus the `safety-island` and `safety-island-bridge` services |
| `settings.env` | Planning Simulation's settings, then where the release is fetched and the diagnostics graph below |
| `config/autoware/autoware_control_config/.../default_preset.yaml` | The default control preset with `trajectory_follower_mode: none` |
| `config/autoware/autoware_launch/.../autoware-safety-island.yaml` | Autoware's main diagnostics graph without the follower's `control_state`, which nothing publishes with the follower off |
| `checks/safety_island.py` | The bridge's healthcheck: the control command's only publisher is the Safety Island's bridge, and Autoware's follower is not running |

The deployment uses the release's files as they are. The bridge carries the
topics of `bridge-config.yaml`, and `cyclonedds-domain2.xml` keeps its domain-2
datagrams within what the Safety Island receives. Both containers use the DDS
interface of the rest of the stack (`lo` unless the host settings file sets
`CYCLONEDDS_NETWORK_INTERFACE`).

## Upgrade

Update the release tag in the three URLs and the three checksums in
`deployment.json` (from the release's `sha256sums.txt`), and the tag in
`SAFETY_ISLAND_PATH`.
