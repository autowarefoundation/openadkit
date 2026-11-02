# CLI & Maintenance

Commands you need after the first run: runtime controls, validation,
configuration, upgrades, and cleanup.

--8<-- "includes/cli-command-context.md"

## Short Name and Tab Completion

`openadkit install` also links `adkit`, a short name for the same launcher:
`adkit run planning-simulation` is `openadkit run planning-simulation`. Tab
completes commands, options and the deployment names of the kit or release in
the current directory, for both names; bash-completion (installed on Ubuntu by
default) loads it from `~/.local/share/bash-completion/completions` in a new
shell. The installer leaves an `adkit` or a completion file that it did not
install alone, and `openadkit uninstall` removes only its own links.

## Runtime Controls

```bash
openadkit status
openadkit logs --follow
openadkit logs map planning        # only these services
openadkit restart                  # services reread config and overlay workspaces
openadkit restart --all            # the whole deployment, with the same settings
openadkit shell                    # a shell in the api service with ROS sourced
openadkit shell planning ros2 node list
openadkit record /tf /localization/kinematic_state
openadkit stop
```

These act on the deployment running on this host, from any directory, so they
take no deployment name. When several nodes of a split deployment run on one
host, pick one with `--node`; `status` and `stop` act on all of them.

`restart` with no service restarts every service that takes Open AD Kit config
or an overlay workspace, so a changed parameter file or a rebuilt workspace
applies without restarting a simulator such as CARLA; it names the services it
left running. `restart --all` restarts the whole deployment in place, one-shot
services included, as a fresh start with the same settings. Changes to Compose
files or `.env` values need `stop` and `run` again. `shell` sources ROS, Autoware and the overlay
workspaces like the services' entrypoint; give it a service and a command to run
one command instead.

Below its services, `status` shows Autoware's state from the AD API:

```text
localization initialized
routing      set
mode         stop (autonomous available)
mrm          normal
```

A line reads `no data` while nothing publishes that state yet, for example
before localization starts.

`record` writes a rosbag of the named topics (or `--all`) to
`~/openadkit-output/<deployment>/recordings/` (`--output` to change) until
Ctrl+C. It runs as a copy of the running api container, so it joins the
deployment's ROS domain and knows the overlay's message types, and the bag stays
on the host when the deployment stops.
One deployment runs at a time, including deployments from other kits, even one
with the same name. `run` refuses conflicting projects; stop them first with
`openadkit stop`. Declared
split nodes of the same deployment can still run together.
After starting, `run` watches the services for 10 seconds and fails if one
crashes.
`openadkit run <deployment> --pull always` refreshes images before starting,
and `openadkit version` prints the installed version. `--no-visualizer`
starts everything except the visualizer, for a host nobody watches; its
software-rendered RViz needs CPU that Autoware lacks on a small host. CI
evidence runs this way.

## Validate Before Running

```bash
openadkit validate planning-simulation --data
```

`validate` checks the manifest and the Compose configuration without starting
anything. `--data` also reports each data resource as `ok`, `missing`, `incomplete`,
or `outdated` and fails on any gap. It follows the same GPU selection as `run`:
use `openadkit validate logging-simulation --gpu --data` to include the
CenterPoint models.

`list`, `version`, and `validate` accept `--json` for scripting.

`validate`, `fetch`, `run` and `clean` also take a deployment's directory
instead of its name, such as `openadkit run ./my-kit`: an argument with a `/` or
a leading `.` is a directory, and the kit around it is used wherever you run the
command.

## Configuration

Each deployment reads its settings from environment files, in this order
(later files win):

1. `deployments/<name>/config.env`: the deployment defaults
2. `deployments/<name>/config.gpu.env`: GPU settings, loaded only with `--gpu`
3. `~/.config/openadkit/<name>.env`: your host settings

Shell exports do not override variables defined in these files. Put host
settings such as `MAP_PATH` or `REMOTE_PASSWORD` in your host settings file.
It lives outside the release, so upgrades keep it. Source checkouts can also
override component images there; release images stay pinned.

| Directory | Default | Override |
| --- | --- | --- |
| Host settings | `~/.config/openadkit` | `OPENADKIT_CONFIG_DIR` (or `XDG_CONFIG_HOME`) |
| Results and recordings | `~/openadkit-output/<name>/{results,recordings}` | `OPENADKIT_OUTPUT_DIR` |

`deployments/<name>/config.local.env` is no longer read; the CLI warns when it
finds one. Move its settings to `~/.config/openadkit/<name>.env`.

## Upgrading

```bash
openadkit upgrade --check   # report whether a newer stable version exists
openadkit upgrade           # install it
```

The new release is verified and installed next to the old one, and the
`openadkit` launcher is repointed. The previous version stays in the install
destination (default `~/.local/share/openadkit/`), so you can roll back:

```bash
openadkit install --version vOLD --force
```

`--force` replaces the kept version directory; omit it to install a version
that is not kept. Source checkouts update with `git pull` instead.

## Uninstall and Cleanup

Stop running deployments first; `uninstall` refuses while any is running,
because it removes the launcher that `openadkit stop` needs.

```bash
openadkit stop
openadkit uninstall          # keep previously installed versions
openadkit uninstall --all    # remove kept versions too
```

`uninstall` is for release installs; remove a source checkout with Git. Host
settings in `~/.config/openadkit` and results and recordings in
`~/openadkit-output` are kept.

Downloaded data (maps, rosbags, and perception models) lives under
`~/autoware_map` and `~/autoware_data` and is kept by `uninstall`. Check and
delete a deployment's data with:

```bash
openadkit validate planning-simulation --data   # report
openadkit clean planning-simulation             # delete
```

`clean` and `fetch --force` refuse while that deployment is running, or
when any live container mounts the data (including another kit or deployment).
If data usage cannot be checked, deletion or replacement is refused. If Scenario
Simulation's Kashiwanoha map is removed, restore it with
`openadkit fetch scenario-simulation --force`.

`run` downloads missing data, but never replaces an existing data directory.
Replace incomplete or outdated managed data explicitly with `fetch --force`;
`run --force` is not supported. Managed data is outdated when the deployment
now declares other content for it, for example a fixed map with a new checksum:
`run`, `fetch` and `validate --data` then stop and ask for `fetch --force`.

The CLI marks the data it installs with a `.openadkit-resource.json` file.
`clean` and `--force` only delete or replace marked data. Data that was
already there, such as a map you copied yourself, is still used when it is
complete, but the CLI never deletes or replaces it; move or remove it yourself.
If a target changes during `fetch --force`, publication fails instead of deleting
the changed directory. A conflict during the atomic swap preserves staging;
the error names its path for inspection rather than automatically removing it.

## Split-host nodes

`validate` and `run` accept `--node` for
[split-host simulation](../deployments/split-host.md). `status`, `logs`, and
`stop` find the live node from its Compose project; pass `--node` only when
several nodes of one deployment run on the same machine.

Each node's declared Compose entrypoint owns its full service graph, including
any bridge. The CLI selects those files and the node's ROS domain; it never
adds a networking service behind the scenes. The printed Compose command shows
the selected files, env files and project name.

## Verify a Release Bundle Manually

To inspect a release before running anything, download the bundle and check it
against the release metadata:

```bash
VERSION=$(curl -fsSL \
  https://api.github.com/repos/autowarefoundation/openadkit/releases/latest \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')
curl -fLO "https://github.com/autowarefoundation/openadkit/releases/download/${VERSION}/openadkit-${VERSION}.tar.gz"
curl -fLO "https://github.com/autowarefoundation/openadkit/releases/download/${VERSION}/release-metadata.json"
EXPECTED=$(python3 -c 'import json; print(json.load(open("release-metadata.json"))["bundles"][0]["sha256"])')
printf '%s  %s\n' "$EXPECTED" "openadkit-${VERSION}.tar.gz" | sha256sum --check -
tar -xzf "openadkit-${VERSION}.tar.gz"
cd "openadkit-${VERSION}"
```

The extracted directory is a complete runtime; run it with `./openadkit`.
