# Planning Simulation

Runs the Autoware planning and control stack with a pre-recorded point cloud
map. See the [canonical documentation](https://autowarefoundation.github.io/openadkit/deployment/planning-simulation/)
for configuration and troubleshooting.

```bash
cd ../..
./openadkit run planning-simulation
```

Validate without starting containers with
`./openadkit validate planning-simulation`. Add `--ros-distro jazzy` to either
command to select Jazzy; Humble is the default.
