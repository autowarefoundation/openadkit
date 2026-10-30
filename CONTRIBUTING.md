# Contributing to Open AD Kit

Thank you for your interest in contributing to Open AD Kit. This project is part of the [Autoware Foundation](https://www.autoware.org/) ecosystem.

## Quick Links

- [Issues](https://github.com/autowarefoundation/openadkit/issues) — report bugs and plan tasks
- [Discord](https://discord.gg/Q94UsPvReQ) — questions, ideas, and design discussion
- [Code of Conduct](.github/CODE_OF_CONDUCT.md)
- [Support](.github/SUPPORT.md) — community help and version coverage
- [Security policy](.github/SECURITY.md) — private vulnerability reporting

## License

Open AD Kit is licensed under **Apache License 2.0**. All contributions are accepted under the same license. No CLA is required.

## For External Contributors

1. **Fork** the repository and create a feature branch (`feat/`, `fix/`, `docs/`, etc.)
2. **Sign off** your commits (`git commit -s`) to certify DCO compliance
3. **Preview docs** locally with `make -C docs serve`
4. **Open a PR** against `main` with a clear description

## For Internal (Foundation) Contributors

If you are a member of the Autoware Foundation contributing to active development branches or other internal work:

### Branch Strategy

- `main` — integration with upstream Autoware development
- `release/X.Y` — an Open AD Kit release line, pinned to one Autoware release
- `feat/...`, `fix/...`, `refactor/...` — active development branches merged into `main` via PR

`.github/autoware.ref` pins the Autoware sources a branch builds: an exact
release such as `1.9.0` on `release/X.Y`, and a commit of upstream `main` on
`main`, with every dependency pinned next to it in `.github/autoware-lock.repos`
and the upstream base images it builds on in `.github/autoware-base-images.json`.
A change that only upstream development needs, such as a moved package, lands
on `main` without breaking the release line. Create `release/X.Y` from `main`
when stabilizing a release, set its pin to the release tag, remove
`.github/autoware-lock.repos` and `.github/autoware-base-images.json`, and
cherry-pick fixes into it.

`main` moves to upstream development once a week: `bump-autoware.yaml` opens a
`chore(autoware): bump development snapshot` pull request from
`ci/bump-autoware`, builds every image on it and runs the evidence cells,
reported as its `bump-autoware / build` and `bump-autoware / evidence` statuses. When
upstream breaks a deployment, only that pull request fails; push the
adaptation to its branch, and merge it once its checks pass. Run the workflow
by hand to move sooner.

### Local CI Commands

Run these before pushing. They cover most of what `.github/workflows/lint.yaml` runs; CI also validates every deployment cell from `validation_matrix.py` and checks the Bake file.

```bash
# Shell scripts (and the extensionless launcher)
{ git ls-files '*.sh'; echo openadkit; } | xargs shellcheck --severity=error

# GitHub Actions workflows (no glob — picks up .github/actions/ composites too)
./actionlint

# Dockerfiles
git ls-files '**/Dockerfile*' | xargs hadolint --config .hadolint.yaml

# YAML files
yamllint -c .yamllint.yaml \
  .github/workflows/ .github/actions/ .github/ISSUE_TEMPLATE/ \
  .github/dependabot.yaml .github/stale.yml \
  deployments/ platforms/ mkdocs.yaml docs/

# Markdown
npx --yes markdownlint-cli --config .markdownlint.yaml '**/*.md' '!site/**' '!.git/**'

# Python tests + shell tests
pytest .github/scripts/
bash .github/actions/combine-multi-arch-images/test-create-manifest.sh
bash .github/scripts/tests/test_report_manifests.sh
bash .github/scripts/tests/test_setup_helpers.sh

# Deployment validation for both supported ROS distros
./openadkit validate planning-simulation --ros-distro humble
./openadkit validate planning-simulation --ros-distro jazzy

# Documentation (local build, from the repository root)
pip install -r docs/requirements.txt
mkdocs build
```

### Test Scope

The `.github/scripts/tests/` suite is risk-focused, not exhaustive. Keep regression
coverage for managed-data deletion/replacement, checksums and unsafe archives,
failed install/upgrade recovery, immutable image pins, split-node isolation, and
the complete signed `PASSED` release gate. Share release inputs through
`release_fixtures.py`; do not import one test module from another.

Help wording, exhaustive schema-error and option combinations, terminal signals,
upgrade-check/rollback UX, one-shot resets, bind-mount preparation, post-start
crash/timeout diagnostics, and all GPU/node data combinations are deliberately
not covered. Release draft recreation, alternate packager sources, and every
alias/retry variant are also outside this focused suite. Data-transfer tests use
local files rather than a network server. Docker lifecycle calls use stubs; real
Compose checks render models but do not run containers. These tests do not
replace hosted build/scan/evidence or real two-host SIL acceptance.

### Testing Deployments

Before merging deployment-related changes, verify the Compose files. Every
deployment carries one complete `config.env` for Compose interpolation. A
deployment that declares `gpuFiles` also carries `config.gpu.env`, loaded
after `config.env` when `--gpu` is set. The shared
`deployments/shared/runtime.env` is loaded inside containers via `env_file:`
and is not passed on the command line.

```bash
# Validate the manifest and Compose configuration
./openadkit validate planning-simulation

# Test the full deployment flow
./openadkit run planning-simulation
```

The same command surface is included in the release bundle. Use
`~/.config/openadkit/<name>.env` for local overrides.

For split-host (`--node`) topology testing, follow the [documentation](https://autowarefoundation.github.io/openadkit/deployments/split-host/).

### Releasing

Run the `scan-images`, `evidence` and `release.yaml` workflows (GitHub Actions) on a `release/X.Y` branch to promote its build to a `vX.Y.Z` release or pre-release. `release-pipeline.yaml` runs the build and these three in order. See the workflow input descriptions for details. The `default_ros_distro` input must match `openadkit.json` `defaultRosDistro`: to change the default, update the manifest (and its docs) in a commit before releasing.

Both release candidates and stable releases require complete signed `PASSED`
runtime evidence for the promoted build. CI quarantine does not bypass the gate;
reviewed manifest exemptions remain explicitly unverified. Read the
[evidence policy](https://autowarefoundation.github.io/openadkit/releases/evidence/),
[verification guide](https://autowarefoundation.github.io/openadkit/releases/verification/)
and [toolchain RFC](https://autowarefoundation.github.io/openadkit/development/rfc-0001-toolchain-model/).

## DCO Requirement

All commits must include a `Signed-off-by` line. CI enforces this automatically — PRs without sign-off will not be merged.

```bash
git commit -s -m "your commit message"
```
