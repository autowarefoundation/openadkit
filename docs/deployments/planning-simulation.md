# Planning Simulation

Run the Autoware planning and control stack on a sample map with the built-in
simulator, then set a route in RViz in your browser. No GPU is required; with
an NVIDIA GPU, `--gpu` plans with Autoware 2.0's Diffusion Planner.

## Run

```bash
openadkit run planning-simulation         # CPU: the rule-based planner
openadkit run planning-simulation --gpu   # GPU: the Diffusion Planner (amd64 only)
```

`run` downloads the sample map, pulls the images and starts the stack. The
sample map is Copyright 2020 TIER IV, Inc. and is provided for demonstration
only.

### GPU Mode {: #gpu-mode }

!!! warning "Experimental"
    The GPU mode may change in a minor release. See
    [Compatibility](../releases/compatibility.md#experimental).

With `--gpu`, the planning service runs the `planning-cuda` image with
`planning_setting:=diffusion_planner`, and `run` also downloads the Diffusion
Planner v5.0 model from Hugging Face to
`~/autoware_data/ml_models/diffusion_planner/v5.0`. The first start builds a
TensorRT engine from the model there, so it takes longer than later starts.
The planner used about 0.8 GB of GPU memory in a measured run, engine build
included; RViz renders on the CPU.

Control and the rest of the stack are the same in both modes: control follows
`/planning/trajectory`, whichever planner makes it. See
[Autoware Architecture 2.0](https://autowarefoundation.github.io/autoware-documentation/main/design/autoware-architecture-v2/)
for the planner. CI evidence runs the CPU mode; the GPU mode is checked by
hand on a GPU host.

!!! warning "Known limitation"
    Autoware 2.0.0's Diffusion Planner can stop the
    ego up to about 2 m before the goal, so the route does not become `ARRIVED`
    and `run --gpu --verify` fails on the sample route. This is the planner's own
    output, reproduced with upstream's image
    ([autoware_universe#13603](https://github.com/autowarefoundation/autoware_universe/issues/13603)).

## Drive

Open the [visualizer](index.md#open-the-visualizer). In RViz, set an initial pose and a goal pose, then press **AUTO** in the
**OperationMode** section of the AutowareStatePanel to drive the route. See the
[Autoware planning simulation guide](https://docs.autoware.org/main/simulation/planning-simulation/lane-driving/#2-set-an-initial-pose-for-the-ego-vehicle)
for details.
