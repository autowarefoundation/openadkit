# Contributing to Open AD Kit

Thank you for your interest in contributing to Open AD Kit. This project is part of the [Autoware Foundation](https://www.autoware.org/) ecosystem.

## Quick Links

- [:material-file-document: Full Contributing Guide](https://autowarefoundation.github.io/openadkit/development/contributing/) — detailed workflow, conventions, and setup instructions
- [:material-github: Issues](https://github.com/autowarefoundation/openadkit/issues) — report bugs and request features
- [:material-chat: Discord](https://discord.gg/Q94UsPvReQ) — real-time discussion

## License

Open AD Kit is licensed under **Apache License 2.0**. All contributions are accepted under the same license. No CLA is required.

## For External Contributors

1. **Fork** the repository and create a feature branch (`feat/`, `fix/`, `docs/`, etc.)
2. **Sign off** your commits (`git commit -s`) to certify DCO compliance
3. **Preview docs** locally with `make serve` (from the repository root)
4. **Open a PR** against `main` with a clear description

See the [full guide](https://autowarefoundation.github.io/openadkit/development/contributing/) for detailed instructions.

## For Internal (Foundation) Contributors

If you are a member of the Autoware Foundation contributing to the `docs-consistency` branch or other internal work:

### Branch Strategy

- `main` — stable, production-ready code
- `docs-consistency` (and similar) — active development branches merged into `main` via PR
- Feature branches — use `feat/`, `fix/`, `refactor/` prefixes

### Local CI Commands

Run the full lint suite before pushing:

```bash
# Shell scripts
shellcheck **/*.sh

# GitHub Actions workflows
actionlint .github/workflows/*.yaml

# Dockerfiles
hadolint **/Dockerfile*

# YAML files
yamllint .github/workflows/ .github/actions/ deployments/ mkdocs.yaml docs/

# Documentation (local build, from the repository root)
pip install -r docs/requirements.txt
python3 docs/scripts/generate_release_notes.py  # optional: populates the Releases page (needs network)
mkdocs build
```

### Testing Deployments

Before merging deployment-related changes, verify the compose files:

```bash
# Validate compose configuration
docker compose -f deployments/samples/planning-simulation/docker-compose.yaml config

# Test the full deployment flow
curl -fsSL https://github.com/autowarefoundation/openadkit/releases/latest/download/planning-simulation.tar.gz | tar xz
cd planning-simulation
./fetch-sample-data.sh planning-simulation
docker compose --env-file planning-simulation.env up -d
```

**Note:** Until the first official release is published, use your local `deployments/samples/planning-simulation/` folder (with `deployments/scripts/fetch-sample-data.sh`) instead of downloading the bundle.

For zenoh-bridge split topology testing, follow the [demo documentation](https://autowarefoundation.github.io/openadkit/deployment/demos/zenoh-bridge/).

### Releasing

Use the `release.yaml` workflow (GitHub Actions) to promote a build to a release. See the workflow input descriptions for details.

## DCO Requirement

All commits must include a `Signed-off-by` line. CI enforces this automatically — PRs without sign-off will not be merged.

```bash
git commit -s -m "your commit message"
```
