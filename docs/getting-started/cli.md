# CLI & Maintenance

The commands you need after the first run. `openadkit --help` and
`openadkit <command> --help` list every option.

--8<-- "includes/cli-command-context.md"

| Command | What it does |
|---------|--------------|
| [`list`, `run`](#run-a-deployment) | List the deployments, and start one and wait until it is ready |
| [`status`, `logs`, `shell`, `record`](#runtime-controls) | Inspect the running deployment and record its topics |
| [`restart`](#restart) | Apply changed settings, config overrides and overlay workspaces |
| [`stop`](#runtime-controls) | Stop and remove the running deployment |
| [`validate`, `config`](#validate-before-running) | Check a deployment, or print its Compose model, without starting it |
| [`fetch`, `clean`](#downloaded-data) | Download or delete a deployment's data |
| [`new`, `build`](../kits/create-a-kit.md) | Create a kit and build its overlay workspace |
| [`setup`](index.md#set-up-the-host) | Install the host dependencies |
| [`install`, `upgrade`](#upgrading), [`uninstall`](#uninstall) | Install, move between and remove releases |
| [`version`](#names-directories-and-output) | Show the installed release and its Autoware release |

## Run a Deployment

```bash
openadkit list                                    # the deployments you can run
openadkit run planning-simulation
openadkit run planning-simulation --verify        # then run its verify step
openadkit run planning-simulation --no-visualizer
```

`run` downloads missing data, pulls missing images, starts the services and
returns once the deployment is ready.

- **Ready** means the services' healthchecks pass, for example once the AD API
  is up (`READINESS_CHECKS` in the deployment's `settings.env`). `run` then
  watches the services for 10 seconds and fails if one crashes, restarts, exits
  or turns unhealthy; a one-shot service may finish but not fail.
- **`--verify`** then runs the deployment's verify step, the check CI runs on
  it: Planning Simulation drives the ego from its start to its goal, Scenario
  Simulation waits for the scenarios' result. `run` exits with the step's
  result; the deployment keeps running.
- **`--no-visualizer`** starts everything except the visualizer, for a host
  nobody watches: its software-rendered RViz needs CPU that Autoware lacks on a
  small host. CI evidence runs this way.
- **One deployment runs at a time**, including deployments from other kits,
  even one with the same name. `run` refuses while another is running, or
  while another has left stopped containers; remove either with
  `openadkit stop`. The roles of one
  [split-host](../deployments/split-host.md) deployment can run together.

Every run writes `results/run.json` in the deployment's output directory: what
it started, how long it took to be ready and, with `--verify`, the step's
result ([fields](../kits/reference.md#resultsrunjson)).

Without `--ros-distro`, a deployment command uses the release's default distro,
or the deployment's first one when it does not run on that.

## Runtime Controls

```bash
openadkit status
openadkit logs --follow           # stream, from each service's last 100 lines
openadkit logs map planning        # only these services
openadkit restart                  # apply changed settings, config overrides and overlay workspaces
openadkit restart --all            # recreate the whole deployment
openadkit shell                    # a shell in the api service with ROS sourced
openadkit shell planning ros2 node list
openadkit record /tf /localization/kinematic_state
openadkit stop
```

These act on the deployment running on this host, from any directory, so they
take no deployment name. With several roles of a split-host deployment on one
host, see [Lifecycle Notes](../deployments/split-host.md#lifecycle-notes).

`status` and `stop` also see a deployment whose containers have all stopped,
after a failed start or a restart of Docker. Its containers stay, with their
logs, until `stop` removes them.

### Status

`status` lists each service beside its container:

```text
SERVICE   CONTAINER          STATUS
map       autoware-map       Up 2 minutes (healthy)
planning  autoware-planning  Up 2 minutes (healthy)
```

A service that stopped stays in the list with how it ended, such as
`Exited (0)` for a one-shot service that finished.

`logs`, `restart` and `shell` take a service by either name: `planning`, as
the Compose files call it, or `autoware-planning`, as `docker ps` and the log
lines show it.

Below the services, `status` shows Autoware's state from the AD API and the
visualizer address:

```text
localization initialized
routing      set
mode         stop (autonomous available)
mrm          normal
```

A line reads `no data` while nothing publishes that state yet, for example
before localization starts.

When a node of an Autoware service dies, the service turns `unhealthy` and
`status` names the process; see
[A Service Is Unhealthy](troubleshooting.md#a-service-is-unhealthy).

### Restart

`restart` recreates services as `run` started them, with the current settings,
config overrides and overlay workspace, and keeps to the same readiness checks.

- With no service, it recreates every service that takes config overrides or
  an overlay workspace, and every service whose settings changed. A changed
  parameter file, a rebuilt workspace or a new `settings.env` value applies
  without restarting a simulator such as CARLA; `restart` names the services it
  left running.
- A running service that shares the process namespace of a recreated one is
  recreated with it, since it cannot outlive that namespace: a rosbag that is
  still playing or a scenario that is still running, which then start over.
- `restart <service>...` recreates only those services.
- `restart --all` recreates the whole deployment, one-shot services included.

### Shell

`shell` sources ROS, Autoware and the overlay workspace, as the services'
entrypoint does. Give it a service and a command to run one command instead of
an interactive shell; `shell` then exits with the command's status.

Unlike the service itself, the shell runs as root and without the config
overrides: a launch file you start there reads Autoware's own parameter files.
The running nodes have the overrides, so `ros2 param get` shows them.

### Record

`record` writes a rosbag of the named topics (or `--all`) to
`~/openadkit-output/<deployment>/recordings/` (`--output` to change) until
Ctrl+C. It runs as a copy of the running `api` container, so it joins the
deployment's ROS domain and knows the overlay's message types, and the bag
stays on the host when the deployment stops.

## Validate Before Running

```bash
openadkit validate planning-simulation --data
```

`validate` checks the manifest and the Compose configuration without starting
anything. `--data` also reports each data resource as `ok`, `missing`,
`incomplete` or `outdated` and fails on any gap; a directory of your own shows
as `own`. It follows the same GPU
selection as `run`: `openadkit validate logging-simulation --gpu --data`
includes the CenterPoint models.

`config` prints a deployment's resolved Compose model as JSON, with `validate`'s
`--ros-distro`, `--gpu`, `--role` and `--ws`;
[AutoSD](../platforms/autosd.md) builds on it.

## Settings

A deployment reads its settings from environment files, in this order (later
files win):

1. `deployments/<name>/settings.env`: the deployment defaults
2. `deployments/<name>/settings.gpu.env`: GPU settings, loaded with `--gpu` and for a deployment that requires a GPU
3. `~/.config/openadkit/<deployment>.env`: your host settings file

Shell exports do not override variables defined in these files. Put host
settings such as `MAP_PATH` or `REMOTE_PASSWORD` in your host settings file: it
lives outside the release, so upgrades keep it. A source checkout can also
override component images there; release images stay pinned. A kit adds its
own files to this order; see the
[Kit Guide](../kits/kit-guide.md#1-settings).

Most settings are arguments of Autoware's launch files, such as
`VEHICLE_MODEL`; the rest are host paths and options of Open AD Kit's own
services. To change a node parameter instead, use a
[config override](../kits/kit-guide.md#2-config-overrides).

| Directory | Default | With `OPENADKIT_HOME` |
| --- | --- | --- |
| Host settings | `~/.config/openadkit` (or under `XDG_CONFIG_HOME`) | `settings/` |
| Run records, which `restart` reads | `~/.local/state/openadkit` (or under `XDG_STATE_HOME`) | `state/` |
| Installed releases | `~/.local/share/openadkit` (or under `XDG_DATA_HOME`) | `releases/` |
| Results and recordings | `~/openadkit-output/<deployment>/{results,recordings}` | `output/` |
| Downloaded data | `~/autoware_data` | `data/` |

Set `OPENADKIT_HOME` to an absolute path to keep everything Open AD Kit writes
under that one directory, for example to keep a test run apart from your own
files. Outside it stay the `openadkit` launcher in `~/.local/bin` and its Tab
completion, which `install`, `upgrade` and `uninstall` change, and the system
files `setup` changes.

## Downloaded Data

Maps, rosbags and models live under one data directory, `~/autoware_data` (see
the table above): maps in `maps/`, rosbags in `rosbags/`, models and the Safety
Island beside them. To move one of them only, set its path in the host settings
file, such as `MAP_PATH`.

```bash
openadkit validate planning-simulation --data   # report
openadkit fetch planning-simulation --force     # replace
openadkit clean planning-simulation             # delete, after asking
```

- **`run`** and **`fetch`** download missing data and update outdated data.
  Data is outdated when the deployment now declares other content for it, for
  example a map with a new checksum. They update only data the CLI installed,
  and not while a running container uses it. `fetch` always includes the GPU
  data.
- **`fetch --force`** replaces the data even when it is complete, and is the
  way to repair incomplete data.
- **`clean`** lists what it deletes and asks first; `--yes` skips the question,
  as scripts need. Answering no deletes nothing and is not an error. It
  deletes all the data the deployment uses, including data that other
  deployments share, such as a kit deployment's base; the list names them. The
  next `run` or `fetch` downloads it again.

The CLI marks the data it installs with a `.openadkit-resource.json` file, and
checks, updates and deletes only marked data. A directory that holds files and
no marker is yours, such as your own map at `MAP_PATH`, and so is a link you
made to a directory with files, such as data moved to another disk: the deployment uses it
as it is, whatever its files are called, and `fetch`, `--force` and `clean`
leave it alone. Name its files in the settings where the deployment has them,
such as `LANELET2_MAP_FILE` and `POINTCLOUD_MAP_FILE`.

A path that does not exist, or an empty directory, counts as missing: the CLI
downloads the sample data there, and says so first when the path is outside
the data directory. Copy your own data in before the first `run`, and check
the path for a typo when you see that line.

`clean` and `fetch --force` refuse while that deployment is running, or while
any live container mounts the data (including another kit or deployment). If
data usage cannot be checked, they refuse as well.

## Upgrading

```bash
openadkit upgrade --check   # report whether a newer stable version exists
openadkit upgrade           # install it
```

The new release is verified and installed next to the old one, and the
`openadkit` launcher is repointed. `upgrade` moves to the latest stable
release, also across a major version, and says so when it does: read that
release's breaking changes first. A kit keeps running the release it pins. The
previous version stays in the install directory, so you can roll back:

```bash
openadkit install --version vOLD
```

A version that is already installed becomes the active one as it is, without a
download, so this works offline; `--force` downloads and replaces it. Images of
a version you no longer use stay in Docker until you remove them with
`docker image rm`; `docker image ls ghcr.io/autowarefoundation/openadkit` lists
them. A source checkout updates with `git pull`
instead.

## Uninstall

Stop running deployments first; `uninstall` refuses while any is running,
because it removes the launcher that `openadkit stop` needs.

```bash
openadkit stop
openadkit uninstall          # keep previously installed versions
openadkit uninstall --all    # remove kept versions too
```

`uninstall` is for release installs; remove a source checkout with Git. It
keeps your host settings, run records, results, recordings and downloaded data
(see [Settings](#settings) for where they are), and the Docker images, several
GB each. To delete a deployment's data, run `openadkit clean <deployment>`
before uninstalling, since it needs the CLI. Afterwards,
`docker image ls ghcr.io/autowarefoundation/openadkit` lists the images and
`docker image rm` removes them. The host changes `openadkit setup` made stay
too: Docker and its apt source, your `docker` group membership and
`/etc/sysctl.d/99-openadkit-dds.conf`.

## Names, Directories and Output

- **A directory instead of a name:** `validate`, `config`, `fetch`, `run` and
  `clean` also take a deployment's directory, such as `openadkit run ./my-kit`.
  An argument with a `/` or a leading `.` is a directory, and the kit around it
  is used wherever you run the command. A kit's own directory stands for the
  kit, as when you run the command inside it; from outside, one of several
  deployments is named as `./my-kit/deployments/<name>`.
- **Version:** `openadkit version` prints the installed release and the
  Autoware release it pins; in a source checkout, the commit.
- **Scripting:** `list`, `version` and `validate` accept `--json`.
  `validate --json` prints one JSON document also when the deployment is
  invalid (`"valid": false` with the `"error"`), and covers one deployment: in
  a kit with several, name one. The [reference](../kits/reference.md#json-output)
  lists the fields.
- **Docker commands:** commands print what they do in plain terms; add
  `--verbose` (or set `OPENADKIT_VERBOSE=1`) to also see the docker commands
  they run, status queries aside.
- **Tab completion:** Tab completes commands, options and deployment names,
  from the kit around the current directory or else the active release;
  bash-completion (installed on Ubuntu by default) loads it in a new shell.
