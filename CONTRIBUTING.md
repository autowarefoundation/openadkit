# Contributing to Open AD Kit

Thank you for your interest in contributing to Open AD Kit. This project is part of the [Autoware Foundation](https://www.autoware.org/) ecosystem.

## Quick Links

- [Issues](https://github.com/autowarefoundation/openadkit/issues) — report bugs and request features
- [Discord](https://discord.gg/Q94UsPvReQ) — real-time discussion
- [Discussions](https://github.com/autowarefoundation/openadkit/discussions) — design and Q&A
- [Code of Conduct](CODE_OF_CONDUCT.md)

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
- `release/X.Y` — supported Open AD Kit release line, pinned to an Autoware release
- `feat/...`, `fix/...`, `refactor/...` — active development branches merged into `main` via PR

`main` tracks upstream development, not the last Autoware release. The branch's
`.github/autoware.ref` is the build source of truth: `main` on the development
branch, or an exact Autoware tag such as `1.9.0` on a release branch. PR checks
use the merged checkout's pin; no repository-wide `UPSTREAM_TAG` variable is
needed. Development sources use upstream's regular manifest plus its development
overrides, resolved together into one SHA lock. The upstream core Dockerfile
builds core from that same lock; release builds use official release images.

Create `release/X.Y` only when stabilizing or maintaining that Open AD Kit line,
from a commit verified against the selected Autoware release. Set its pin and
cherry-pick relevant fixes; do not merge upstream-only compatibility changes into
an older release line. Keep one active release line unless broader maintenance
is explicitly needed. Branch creation and backports remain manual.

### Local CI Commands

Run the full lint suite before pushing. These commands mirror (and extend) what CI runs in `.github/workflows/lint.yaml`:

```bash
# Shell scripts
git ls-files '*.sh' | xargs shellcheck --severity=error

# GitHub Actions workflows (no glob — picks up .github/actions/ composites too)
./actionlint

# Dockerfiles
git ls-files '**/Dockerfile*' | xargs hadolint --config .hadolint.yaml

# YAML files
yamllint -c .yamllint.yaml \
  .github/workflows/ .github/actions/ .github/ISSUE_TEMPLATE/ \
  .github/DISCUSSION_TEMPLATE/ .github/dependabot.yaml .github/stale.yml \
  .github/sync-files.yaml deployments/ platforms/ mkdocs.yaml docs/

# Markdown
npx --yes markdownlint-cli --config .markdownlint.yaml '**/*.md' '!site/**' '!.git/**'

# Python tests + shell tests
pytest .github/scripts/
bash .github/actions/combine-multi-arch-images/test-create-manifest.sh
bash .github/scripts/tests/test_report_manifests.sh

# Deployment validation for both supported ROS distros
./openadkit validate planning-simulation --ros-distro humble
./openadkit validate planning-simulation --ros-distro jazzy

# Documentation (local build, from the repository root)
pip install -r docs/requirements.txt
mkdocs build
```

### Testing Deployments

Before merging deployment-related changes, verify the Compose files. Every
deployment carries one complete `config.env` for Compose interpolation. The
shared `deployments/base/runtime.env` is loaded inside containers via
`env_file:` and is not passed on the command line.

```bash
# Validate the manifest and Compose configuration
./openadkit validate planning-simulation

# Test the full deployment flow
./openadkit run planning-simulation
```

The same command surface is included in the release bundle. Use
`deployments/<name>/config.local.env` for local overrides.

For zenoh-bridge split topology testing, follow the [documentation](https://autowarefoundation.github.io/openadkit/deployments/zenoh-bridge/).

### Releasing

Run the scan and release controller workflows from `main` to promote an existing
build. Stable `vX.Y.Z` releases require a build from `release/X.Y` whose Autoware tag matches
that source commit's `.github/autoware.ref`. Development branch builds cannot be
promoted to stable releases. Existing tag/SHA diagnostic builds may still be
used for pre-releases. The `default_ros_distro` input must match the promoted
source commit's `openadkit.json`, not the current development manifest. Images
are promoted by digest and never rebuilt during release.

## DCO Requirement

All commits must include a `Signed-off-by` line. CI enforces this automatically — PRs without sign-off will not be merged.

```bash
git commit -s -m "your commit message"
```
