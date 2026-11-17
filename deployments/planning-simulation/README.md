# Planning Simulation

Runs the Autoware planning and control stack on a sample map with the built-in
simulator. See the [canonical documentation](https://autowarefoundation.github.io/openadkit/deployments/planning-simulation/).

```bash
cd ../..
./openadkit run planning-simulation
```

Validate without starting containers with
`./openadkit validate planning-simulation`. Add `--ros-distro jazzy` to either
command to select Jazzy; Humble is the default.
