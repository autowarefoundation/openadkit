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
3. **Preview docs** locally with `make -C docs serve`
4. **Open a PR** against `main` with a clear description

See the [full guide](https://autowarefoundation.github.io/openadkit/development/contributing/) for detailed instructions.

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
hadolint --config .hadolint.yaml **/Dockerfile*

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

# Docker Compose (per-sample, with both env files — base first, last wins)
export REMOTE_PASSWORD="ci-validate"
( cd deployments/planning-simulation && \
  docker compose --env-file ../base/base.env --env-file planning-simulation.env config -q )

# Documentation (local build, from the repository root)
pip install -r docs/requirements.txt
python3 docs/scripts/generate_release_notes.py  # optional: populates the Releases page (needs network)
mkdocs build
```

### Testing Deployments

Before merging deployment-related changes, verify the compose files. Base-backed
deployments (`planning-simulation`, `scenario-simulation`, `logging-simulation`)
declare defaults in `../base/base.env` (relative to the deployment directory) and per-deployment deltas in their own
`<name>.env`. From a cloned repo, pass both, base first, last-wins:

```bash
# Validate compose configuration
docker compose -f deployments/planning-simulation/docker-compose.yaml \
  --env-file deployments/base/base.env \
  --env-file deployments/planning-simulation/planning-simulation.env \
  config

# Test the full deployment flow
curl -fsSL https://github.com/autowarefoundation/openadkit/releases/latest/download/planning-simulation.tar.gz | tar xz
cd planning-simulation
./install.sh sample-data planning-simulation
docker compose --env-file planning-simulation.env up -d
```

**Note:** Until the first official release is published, use your local
`deployments/planning-simulation/` folder (with
`../../install.sh sample-data planning-simulation`) instead of downloading the bundle.
`carla-simulation` runs with both `../base/base.env` and `carla-simulation.env`, the same as the other deployments.

For zenoh-bridge split topology testing, follow the [documentation](https://autowarefoundation.github.io/openadkit/deployment/zenoh-bridge/).

### Releasing

Use the `release.yaml` workflow (GitHub Actions) to promote a build to a release. See the workflow input descriptions for details.

## DCO Requirement

All commits must include a `Signed-off-by` line. CI enforces this automatically — PRs without sign-off will not be merged.

```bash
git commit -s -m "your commit message"
```
