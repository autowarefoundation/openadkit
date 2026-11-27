# Safety Island HIL Simulation

Planning Simulation driven by an
[Autoware Safety Island](https://github.com/autowarefoundation/autoware-safety-island)
that runs outside Open AD Kit: on Arm Virtual Hardware, an FVP or a board. See
the [canonical documentation](https://autowarefoundation.github.io/openadkit/deployments/safety-island-hil-simulation/)
for requirements and what to expect.

```bash
cd ../..
./openadkit run safety-island-hil-simulation
```

## Files

| File | What it does |
| --- | --- |
| `deployment.json` | Pins the Safety Island release's `bridge-config.yaml` topic contract and `cyclonedds-domain2.xml` DDS setting by SHA-256, without its binary. Has no GPU mode and no CI evidence: the runners have no Safety Island |
| `compose.yaml` | Safety Island Simulation's services without the `safety-island` binary: Planning Simulation's, plus `safety-island-bridge` |
| `settings.env` | Safety Island Simulation's settings, with the contract download and `SAFETY_ISLAND_DDS_INTERFACE`, the interface that reaches the Safety Island |
| `cyclonedds.xml` | The bridge's DDS configuration: domain 1 on the stack's interface, domain 2 only on `SAFETY_ISLAND_DDS_INTERFACE` |
| `config/autoware/...` | The same control preset and diagnostics graph as Safety Island Simulation |
| `../shared/checks/safety_island.py` | The bridge's healthcheck: the control command's only publisher is the Safety Island's bridge, and Autoware's follower is not running |

The files Safety Island Simulation also has must stay the same as there; a
test in `.github/scripts/tests/` compares them.

## Upgrade

Update the release tag in the two URLs and the two checksums in
`deployment.json` (from the release's `sha256sums.txt`), and the tag in
`SAFETY_ISLAND_PATH`, as in Safety Island Simulation.
