# Custom Deployment

Start your own kit with `openadkit new`. It makes a kit that extends this Open
AD Kit and one of its deployments without copying them, so the kit keeps only
your differences:

```bash
openadkit new my-kit                       # on top of planning-simulation
openadkit new my-kit --base scenario-simulation
```

## One Directory, One Deployment

```text
my-kit/
├── openadkit.json
├── deployment.json
├── docker-compose.yaml
├── config.env
├── config/autoware/
└── overlay_ws/src/
```

- `openadkit.json` selects the base (`extends`), lists extra images you pin
  (`artifacts`), and points the `my-kit` deployment at `"."`, this same
  directory.
- `deployment.json` names the base deployment and the Compose entrypoint.
  Architecture, ROS distro, GPU, downloads and the verify step are inherited.
- `docker-compose.yaml` includes `${OPENADKIT_BASE_DEPLOYMENT}/docker-compose.yaml`;
  add your services below it. `OPENADKIT_BASE_ROOT` names the base root for
  shared assets.
- `config.env` holds only the values you change, such as `VEHICLE_ID`.
- `config/autoware/` holds parameter overrides for Autoware packages.
- `overlay_ws/src/` holds your ROS packages.

The directory name, the deployment key in `openadkit.json` and `name` in
`deployment.json` agree; rename them together. The CLI checks that they agree.

## Pin Your Base

`openadkit new` from an installed release writes its version, such as
`"extends": "v2.0.0"`; the kit then runs with that release's own launcher.
From a source checkout it writes the checkout's path. To move to another
release, install it with `openadkit install --version <tag>` and change
`extends`.

## Build, Validate, Run, Stop

```bash
cd my-kit
openadkit build                 # overlay_ws, in the release's devel image
openadkit validate my-kit
openadkit run my-kit --verify   # start, wait until ready, run the base's end-to-end check
openadkit stop
```

A source checkout pins no devel image: set `DEVEL_IMAGE` to the matching
`universe-common-devel` digest from that build's metadata before `build`. Add
`--ros-distro jazzy` to `build`, `validate` and `run` for Jazzy. Static
validation renders the Compose model; it is not runtime or ABI evidence. CI
makes a kit with `openadkit new` and exercises every extension point on Humble
and Jazzy: a value, a parameter override, a C++ package, a pinned image and a
service with a healthcheck, then the Planning Simulation golden path.

Keep parameter and package changes in `config/` and `overlay_ws/` rather than
mounting over `/opt/autoware` or replacing base service commands. See the
[Integrator Guide](integrator-guide.md) for configuration order, pinned image
replacement and contract warnings.
