# Open AD Kit — Context

Open AD Kit packages Autoware as independently deployable container images, with
ready-to-run deployment configurations and the CI/CD that builds and releases
them. This file records the project-specific vocabulary so reviews and docs stay
consistent.

## Language

### Deployment

**Sample deployment**:
A ready-to-run Autoware configuration (e.g. planning-simulation) shipped to users
as a self-contained bundle. Each is composed of one **deployment base** plus an
**overlay**.
_Avoid_: example, demo (a **demo** is the separate zenoh-bridge class, not a sample).

**Deployment base**:
The services shared by the base-backed samples (planning/scenario/logging) —
`map`, `system`, `planning`, `vehicle`, `control`, `simulator`, `api`,
`visualizer` — defined once and reused. carla-simulation and zenoh-bridge stay
self-contained and are not on the base.
_Avoid_: common compose, parent compose, template.

**Overlay**:
The per-sample delta layered on the deployment base: the extra services and env a
single sample adds (e.g. `scenario_simulator`, `rosbag`,
`sensing`/`perception`/`localization`), plus overrides of base services.
_Avoid_: variant, profile.

**Bundle**:
The self-contained per-sample artifact (`<sample>.tar.gz`) assembled at release
time and downloaded by users. A bundle is flat — the deployment base and overlay
are merged into one compose + one env before packaging, so the user never sees the
seam.
_Avoid_: package, archive, release asset (use bundle for the deployment tarball
specifically).

**Catalog**:
`.github/image-inventory.json` — the source of truth for the set of component
images, their target names, ROS distros, and platforms.
_Avoid_: manifest, inventory list, registry.
