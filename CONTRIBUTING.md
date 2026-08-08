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

- `main` — stable, production-ready code
- `feat/...`, `fix/...`, `refactor/...` — active development branches merged into `main` via PR

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

For zenoh-bridge split topology testing, follow the [documentation](https://autowarefoundation.github.io/openadkit/deployment/zenoh-bridge/).

### Releasing

Use the `release.yaml` workflow (GitHub Actions) to promote a build to a release. See the workflow input descriptions for details.

## DCO Requirement

All commits must include a `Signed-off-by` line. CI enforces this automatically — PRs without sign-off will not be merged.

```bash
git commit -s -m "your commit message"
```
