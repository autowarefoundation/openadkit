# CLI & Maintenance

Commands you need after the first run: runtime controls, validation,
configuration, upgrades, and cleanup.

--8<-- "includes/cli-command-context.md"

## Runtime Controls

```bash
openadkit status planning-simulation
openadkit logs planning-simulation --follow
openadkit stop planning-simulation
```

Pass the deployment name. Without it, these commands only list what is running.
`openadkit run <deployment> --pull always` refreshes images before starting,
and `openadkit --version` prints the installed version.

## Validate Before Running

```bash
openadkit validate planning-simulation --data
```

`validate` checks the manifest and the Compose configuration without starting
anything. `--data` also reports each data resource as `ok`, `missing`, or
`incomplete` and fails on any gap. It follows the same GPU selection as `run`:
use `openadkit validate logging-simulation --gpu --data` to include the
CenterPoint models.

`list`, `version`, and `validate` accept `--json` for scripting.

## Configuration

Each deployment reads its settings from environment files in
`deployments/<name>/`, in this order (later files win):

1. `config.env`: the deployment defaults
2. `config.gpu.env`: GPU settings, loaded only with `--gpu`
3. `config.local.env`: your local overrides, ignored by Git

Shell exports do not override variables defined in these files. Put host
settings such as `MAP_PATH` or `REMOTE_PASSWORD` in `config.local.env`. Source
checkouts can also override component images there; release images stay pinned.

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
openadkit stop planning-simulation
openadkit uninstall          # keep previously installed versions
openadkit uninstall --all    # remove kept versions too
```

`uninstall` is for release installs; remove a source checkout with Git. It also
removes any `config.local.env` inside the version directory.

Downloaded data (maps, rosbags, and perception models) lives under
`~/autoware_map` and `~/autoware_data` and is kept by `uninstall`. Inspect and
delete a deployment's data with:

```bash
openadkit clean planning-simulation            # report only
openadkit clean planning-simulation --data     # delete
```

`clean --data` refuses while that deployment is running. Scenario Simulation's
Kashiwanoha map is shared with the Zenoh bridge; restore it with
`openadkit fetch scenario-simulation --force`.

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
