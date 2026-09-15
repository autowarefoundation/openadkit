# Scenario Simulation

Runs TIER IV Scenario Simulator workflows. See the
[canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/scenario-simulation/)
for configuration and troubleshooting.

```bash
cd ../..
./openadkit run scenario-simulation
```

The CLI downloads the required Kashiwanoha map. Add `--ros-distro jazzy` to
select Jazzy; Humble is the default.
