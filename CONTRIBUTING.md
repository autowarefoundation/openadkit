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

## Submitting a Change

1. **Fork** the repository and create a branch (`feat/`, `fix/`, `docs/`, etc.)
2. **Sign off** every commit (`git commit -s`). The `Signed-off-by` line
   certifies the [Developer Certificate of Origin](https://developercertificate.org/);
   a PR without it is not merged
3. **Run the [local checks](#local-checks)** that match your change, and
   preview docs with `pip install -r docs/requirements.txt && mkdocs serve`. The docs site documents the latest
   stable release, so a docs change reaches it with the next one
4. **Open a PR** against `main` with a clear description. Its title follows
   [Conventional Commits](https://www.conventionalcommits.org/) (`feat(cli): ...`,
   with `!` for a breaking change): PRs are squash-merged, so the title becomes
   the commit and its line in the release notes

Maintainers can branch in this repository instead of a fork. Such a PR also
runs the evidence cells on its own images before merge; see
[Testing a Pull Request](https://autowarefoundation.github.io/openadkit/development/build-from-source/#testing-a-pull-request).

## Branches

- `main` — Open AD Kit development; releases come from it
- `release/X.Y` — created from a release tag only when an older line needs a fix
- `feat/...`, `fix/...`, `refactor/...` — development branches merged into `main` via PR

`.github/autoware.ref` pins the Autoware release a branch builds on, such as
`2.0.0`. Moving `main` to a new Autoware release is a pull request that changes
the pin and adapts the deployments to it.

## Local Checks

Run these before pushing. They cover most of what `.github/workflows/lint.yaml` runs; CI also validates every deployment cell from `validation_matrix.py` and checks the Bake file.

```bash
# Shell scripts (and the extensionless launcher)
{ git ls-files '*.sh'; echo openadkit; } | xargs shellcheck --severity=error

# GitHub Actions workflows (no glob — picks up .github/actions/ composites too).
# Download the binary once:
#   bash <(curl -sSL https://raw.githubusercontent.com/rhysd/actionlint/main/scripts/download-actionlint.bash)
./actionlint

# Python lint and types
ruff check cli .github/scripts components/shared/entrypoint
mypy

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
bash .github/scripts/tests/test_setup_helpers.sh

# Deployment validation for both supported ROS distros
./openadkit validate planning-simulation --ros-distro humble
./openadkit validate planning-simulation --ros-distro jazzy

# Documentation (local build, from the repository root), then the links
# READMEs make to the docs site
pip install -r docs/requirements.txt
mkdocs build
python3 .github/scripts/check_site_links.py
```

## Test Scope

The `.github/scripts/tests/` suite is risk-focused, not exhaustive. Keep regression
coverage for managed-data deletion/replacement, checksums and unsafe archives,
failed install/upgrade recovery, immutable image pins, split-role isolation, and
the `PASSED` evidence release gate. Share release inputs through
`release_fixtures.py`; do not import one test module from another.

Help wording, exhaustive schema-error and option combinations, terminal signals,
upgrade-check/rollback UX, one-shot services, bind-mount preparation, post-start
crash/timeout diagnostics, and all GPU/role data combinations are deliberately
not covered. Release draft recreation and every alias/retry variant are also
outside this focused suite. Data-transfer tests use
local files rather than a network server. Docker lifecycle calls use stubs; real
Compose checks render models but do not run containers. These tests do not
replace hosted build/scan/evidence or real two-host SIL acceptance.

## Testing Deployments

Before merging deployment-related changes, verify the Compose files. A
deployment carries one complete `settings.env` for Compose interpolation (a kit
deployment carries only its differences). A deployment with a
`compose.gpu.yaml` also carries `settings.gpu.env`, loaded after `settings.env`
when `--gpu` is set. The shared `deployments/shared/runtime.env` is loaded inside
containers via `env_file:` and is not passed on the command line.

```bash
# Validate the manifest and Compose configuration
./openadkit validate planning-simulation

# Test the full deployment flow
./openadkit run planning-simulation
```

Put local overrides in the host settings file,
`~/.config/openadkit/<deployment>.env`.

To test a split-host (`--role`) topology, follow [Split-host Simulation](https://autowarefoundation.github.io/openadkit/deployments/split-host/).

## Releasing

Every build of `main` (or of a `release/X.Y` branch) is scanned and runs the
evidence cells. A release promotes one of those builds: run `release.yaml` on
the same branch with a version and the `build_tag` of a build whose scan and
evidence passed. The
[Release Process](https://autowarefoundation.github.io/openadkit/development/release-process/)
lists what must be in place, and the
[Evidence Policy](https://autowarefoundation.github.io/openadkit/releases/evidence/)
what the gate accepts.

## Breaking Changes

[Compatibility](https://autowarefoundation.github.io/openadkit/releases/compatibility/)
lists what a major version keeps working. Removing or changing one of those
items, such as a command, a manifest field, a covered setting or an extension
point, is a breaking change: mark the pull request title with `!`, say what
breaks and how to migrate, and expect it to wait for the next major version. A
manifest contract change also bumps `schemaVersion`.
