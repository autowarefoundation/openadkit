# CLI & Maintenance

Commands you need after the first run: runtime controls, validation, upgrades,
and cleanup.

--8<-- "includes/cli-command-context.md"

## Runtime Controls

```bash
openadkit status planning-simulation
openadkit logs planning-simulation --follow
openadkit stop planning-simulation
```

Without a deployment name, `status`, `logs`, and `stop` list the running
deployments. `openadkit run --pull always` refreshes images before starting, and
`openadkit --version` prints the CLI version.

## Validate Before Running

```bash
openadkit validate planning-simulation --data
```

`--data` reports each data resource as `ok`, `missing`, or `incomplete`, and
fails when any resource is missing or incomplete. Without it, `validate` checks
the manifest, the declared data destinations, and the Compose configuration.
`list`, `version`, and `validate` also accept `--json` for scripting.

## Local Overrides

Use `deployments/<name>/config.local.env` for host-specific settings. Source
checkouts also accept component image overrides there; release component refs
stay pinned by the release context. The file is ignored by Git.

## Upgrading

Check whether a newer stable version exists:

```bash
openadkit upgrade --check
```

Then upgrade to the latest stable version:

```bash
openadkit upgrade
```

The new release is verified, installed alongside the old one, and the `openadkit`
launcher is repointed. The previous version is kept in the install destination
(by default `~/.local/share/openadkit/`; change it with
`openadkit install --destination DIRECTORY`), so you can roll back:

```bash
openadkit install --version vOLD --force
```

`--force` replaces the kept version directory. To switch to a version that is not
installed, omit `--force`. Source checkouts update with `git pull` or
`git checkout` instead.

## Uninstall and Cleanup

Remove the installed release and its launcher (release installs only; remove a
source checkout with Git):

```bash
openadkit uninstall          # keep previously installed versions
openadkit uninstall --all    # remove kept versions too
```

Any `config.local.env` overrides inside the version directory are removed with
it; downloaded data is kept.

Downloaded data (maps, rosbag samples, and perception models) lives under
`~/autoware_map` and `~/autoware_data` and is not removed by `uninstall`. Inspect
what a deployment has installed and delete it with:

```bash
openadkit clean planning-simulation            # report only
openadkit clean planning-simulation --data     # delete
```

Stop the deployment first. The Kashiwanoha map used by Scenario Simulation is
shared with the standalone Zenoh bridge; if it is removed, restore it with
`openadkit fetch scenario-simulation --force`.

## Related

- [Quickstart](index.md) - First run in about 10 minutes
- [Deployments](../deployments/index.md) - Per-deployment commands and configuration
- [Troubleshooting](troubleshooting.md) - Common issues and fixes
