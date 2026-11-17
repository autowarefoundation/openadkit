# Scenario Simulation

Runs predefined traffic scenarios in TIER IV Scenario Simulator. See the
[canonical documentation](https://autowarefoundation.github.io/openadkit/deployments/scenario-simulation/)
for settings.

```bash
cd ../..
./openadkit run scenario-simulation
```

The CLI downloads the required Kashiwanoha map. Add `--ros-distro jazzy` to
select Jazzy; Humble is the default.
