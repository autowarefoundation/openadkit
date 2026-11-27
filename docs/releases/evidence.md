# Evidence Policy

A release promotes an existing build. It does not rebuild images or relax its
tests: stable releases and release candidates both require **a successful
evidence run that passed every cell for the promoted build**. The
[Release Process](../development/release-process.md#what-the-gate-checks) says
how the release gate checks it.

## Cells and Levels

Evidence cells are enumerated from the deployment manifests, one per ROS
distro, architecture and topology:

| Deployment | Distros | Architectures | Topologies |
|------------|---------|---------------|------------|
| Planning Simulation | Humble, Jazzy | amd64, arm64 | Single host; also under Podman and systemd with the [AutoSD](../platforms/autosd.md) units |
| Scenario Simulation | Humble, Jazzy | amd64, arm64 | Single host; two isolated roles on one host |
| Logging Simulation | Humble, Jazzy | amd64, arm64 | Single host, in CPU mode |
| Safety Island Simulation | Humble, Jazzy | amd64, arm64 | Single host, with the pinned Safety Island release over `domain_bridge` |
| `example-kit-planning-simulation` | Humble, Jazzy | amd64, arm64 | Single host: a kit made with `openadkit new` on Planning Simulation, plus a fixture that uses every extension point and its own vehicle and sensor kit packages |

A cell runs on a hosted runner of its own architecture.

Each cell runs these levels on a fresh stack, started with
`openadkit run --no-visualizer`; the AutoSD cells start the generated systemd
units instead:

- **L0:** manifests and Compose configuration validate; the example kit's cell
  validates each of the kit's deployments, of which it runs the first. One cell
  per distro
  also checks that the images' launch files read every launch argument the
  deployments pass, the exempt deployments included: `ros2 launch` ignores an
  argument it does not know, so a renamed Autoware argument would otherwise do
  nothing without any error.
- **L1:** `openadkit run` returns: the deployment's healthchecks pass, so its
  ROS interfaces are present and its topics publish. After the other checks,
  no service has turned unhealthy, so no node died during them. The cell then
  kills one node of the map service and checks that the service turns
  unhealthy while it keeps running.
- **L2:** the deployment's verify step passes (`openadkit run --verify`): the
  Planning Simulation ego arrives at its goal, the scenarios pass, or
  localization and tracking follow the replayed rosbag, plus the split-role
  checks.
- **L3:** the example kit only: the development loop on the running stack. Its
  C++ package changes, `openadkit build` builds it, `openadkit restart` from
  another directory recreates the services, and the stack publishes the change.

The example kit gates a release like every other cell: it shows that each kit
extension point works on the build. It does not verify integrators' own kits.

The workflow retries a failed cell once. A cell that still fails fails the run
and blocks the release.

## What Evidence Does Not Cover

- **Other platforms.** Every cell runs on a hosted `linux/amd64` or
  `linux/arm64` runner. That is not two-machine LAN, GPU, board, HIL or vehicle
  evidence.
- **GPU modes.** The cells of Planning and Logging Simulation run their CPU
  modes. The GPU modes (`--gpu`: the Diffusion Planner on `planning-cuda`,
  CenterPoint on `sensing-perception-cuda`) validate in lint and in release
  packaging, not in an evidence cell, and are checked by hand on a GPU host.
- **Real-time behavior.** A 4-vCPU hosted runner cannot run Autoware in real
  time: the ego drives late, and the bundled samples take about three times as
  long as on a 16-vCPU host. The Scenario Simulation cells therefore run at
  half speed (`GLOBAL_REAL_TIME_FACTOR=0.5`, with `GLOBAL_TIMEOUT=400`
  wall-clock seconds) through the cell's host settings file, so they test the
  scenarios rather than the runner's size. The Logging Simulation cells replay
  the rosbag at a tenth of its speed (`ROSBAG_RATE=0.1`) for the same reason.

## CI Exemptions

CARLA Simulation requires a GPU, which the hosted runners do not have. Its
deployment manifest carries a reasoned `evidence.exempt` entry. It remains in
the bundle, is listed in the release metadata and notes, and the CLI warns when
it runs. **An exemption is not runtime evidence.**

Adding an exemption is a reviewed source change, not a release-time override.
Do not use it to hide a known failure in a normally tested cell.

See [Verify a Release](verification.md) to check a release yourself.
