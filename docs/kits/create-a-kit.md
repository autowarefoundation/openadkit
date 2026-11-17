# Create a Kit

`openadkit new` makes a kit: your own project, which extends this release
without copying it. A kit holds one or more deployments. Each runs a deployment
of the release, its base, with the kit's files on top, so the kit holds only
your differences. Every base is a simulation: a kit shows your vehicle's
software in simulation, not on the vehicle.

```bash
openadkit new my-kit                       # on top of planning-simulation
openadkit new my-kit --base scenario-simulation
```

--8<-- "includes/cli-command-context.md"

## One Kit, One or More Deployments

```text
my-kit/
├── openadkit.json
├── settings.env                          # every deployment
├── config/autoware/                      # every deployment
├── overlay_ws/src/                       # every deployment
└── deployments/
    └── my-kit-planning-simulation/
        └── settings.env                  # this deployment only
```

`openadkit.json` is the kit's one manifest. It pins the release (`extends`) and
lists the kit's deployments, each with its `base`:

```json
{
  "schemaVersion": 2,
  "kind": "kit",
  "extends": "v2.0.0",
  "deployments": {
    "my-kit-planning-simulation": { "base": "planning-simulation" }
  },
  "externalImages": {}
}
```

- **The kit root** holds what belongs to your vehicle, whichever deployment
  runs it: settings, config overrides and ROS packages.
- **`deployments/<name>/`** holds what one deployment alone needs: its own
  settings and config overrides, and a `compose.yaml` when it adds or changes
  services. The directory is optional.
- **A deployment** inherits its base's architectures, ROS distros, GPU mode,
  downloads and verify step; `requirements` in its manifest entry may narrow
  the first three. Without a `compose.yaml` it runs its base's services.

`new` names the first deployment after the kit and its base. The name is yours
to change: it is the key in `openadkit.json`, and its directory follows it. It
cannot be the name of a deployment of the release, such as
`planning-simulation`.

### Another Deployment of the Same Kit

To run the same vehicle on another base, add one entry:

```json
"deployments": {
  "my-kit-planning-simulation": { "base": "planning-simulation" },
  "my-kit-logging-simulation": { "base": "logging-simulation" }
}
```

It gets the kit's settings, config overrides and packages. Make
`deployments/my-kit-logging-simulation/` only when it needs files of its own.
What you wrote at the kit root now applies to both, so move what only one of
them needs into its directory.

## Build, Validate, Run, Stop

```bash
cd my-kit
openadkit build                 # overlay_ws, in the release's devel image
openadkit validate
openadkit run --verify          # start, wait until ready, run the base's verify step
openadkit stop
```

Inside a kit with one deployment the commands need no name; from elsewhere,
name the kit by its directory: `openadkit run ./my-kit`. With several
deployments, `run` takes the name of one, while `validate` and `fetch` without
a name act on each of them. From elsewhere, one of them is
`./my-kit/deployments/<name>`, also while it has no directory of its own. A kit on a source checkout
runs that checkout's local build, or the CI build `OPENADKIT_BUILD` names; see
[Overlay Workspace](kit-guide.md#3-overlay-workspace).

Add `--ros-distro jazzy` to `build`, `validate` and `run` for Jazzy.
`validate` renders the Compose model without starting anything; it is not
runtime or ABI evidence, so finish with `run --verify`.

Every release tests a kit made this way: the
[example kit](https://github.com/autowarefoundation/openadkit/tree/main/.github/scripts/evidence/example-kit) exercises each
extension point on Humble and Jazzy.

## Make a Change

A config override changes a parameter without a build. Put the file with only
the keys you change under `config/autoware/`, at the path it has in its
package's share directory, then recreate the services that use it:

```bash
mkdir -p config/autoware/autoware_planning_config/config/scenario_planning/common
$EDITOR config/autoware/autoware_planning_config/config/scenario_planning/common/common.param.yaml
openadkit restart               # the services with config overrides or settings that changed
```

A package change needs a build and a restart of the service that runs it:

```bash
openadkit build
openadkit restart <service>
```

[Develop and Debug](develop-and-debug.md) times that loop and shows how to look
into the running services.

## Where Changes Go

Keep parameter changes in `config/autoware/` and packages in `overlay_ws/`
rather than mounting over `/opt/autoware` or replacing a base service's
command.

- [A New Vehicle](new-vehicle.md): your vehicle and sensor packages, and your
  map.
- [Kit Guide](kit-guide.md): the settings order, config overrides, the overlay
  workspace, extra services and image replacement.
- [Manifest and Output Reference](reference.md): every field of
  `openadkit.json`.
