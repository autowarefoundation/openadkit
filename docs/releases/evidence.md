# Evidence and Release Policy

A release promotes an existing build. It does not rebuild images or silently
relax its tests. Both stable releases and release candidates require **a
successful evidence run that passed every cell for the promoted build**.

## What the gate checks

Before creating a tag, the release validation job looks for an
`evidence-summary-<build_tag>` artifact and accepts it only when:

1. **The run succeeded:** it is a completed, successful run of
   `.github/workflows/evidence.yaml` on the same `release/X.Y` branch.
2. **It tested this build:** the summary names the promoted build tag, and it
   tested the build's own commit, not another commit against its images.
3. **Every cell passed:** the summary result is `PASSED`. A cell passes only
   when L0, L1 and L2 all pass, and a missing expected cell fails the run.

A passing rerun may supersede a failed run; a failed run never counts. There is
no release bypass input. The release also requires the latest full scan of the
build to pass.

## Cells and levels

Runtime cells are enumerated from the source deployment manifests:

| Deployment | Distros | Topologies |
|------------|---------|------------|
| Planning Simulation | Humble, Jazzy | Single host |
| Scenario Simulation | Humble, Jazzy | Single host; two isolated nodes on one host |
| `deployments/custom-kit` | Humble, Jazzy | Planning Simulation extended with the example's C++ overlay |

All currently run on GitHub-hosted `linux/amd64` runners. Image build and scan
coverage includes the inventory's other architectures; this must not be
presented as arm64 runtime, two-machine LAN, GPU, HIL or vehicle evidence.

- **L0:** manifests and Compose configuration validate.
- **L1:** required processes and ROS interfaces are present; topics are fresh.
- **L2:** the planning golden path arrives, or the scenario and split-node
  checks pass. Each run starts a fresh stack.

The workflow retries a failed runtime cell once. A cell that still fails fails
the run and blocks a release. The cells start deployments with
`openadkit run --no-visualizer`.

A 4-vCPU GitHub-hosted runner cannot run Autoware main in real time: the ego
drives late and the bundled samples take about three times as long as on a
16-vCPU host. The scenario-simulation cells therefore run the simulation at
half speed (`GLOBAL_REAL_TIME_FACTOR=0.5`, with `GLOBAL_TIMEOUT=400` wall-clock
seconds) through the cell's host settings file, so they test the scenarios
rather than the runner's size. Investigate a cell that still fails after the
workflow's retry.

## Testing a change without a build

A change that rebuilds no image, such as a deployment setting, the CLI or a
check, runs the cells against an existing build:

- A pull request that touches `deployments/`, `cli/` or the evidence checks
  runs them against its base branch's latest successful build. When it also
  changes an image's inputs, it waits for the build after merge instead.
- A dispatch of `evidence.yaml` with `source_ref` tests that branch or commit;
  `build_tag` defaults to the dispatched branch's latest successful build.

The cells take the deployments, CLI and checks from the tested commit and the
images from the build. Such a run is not release evidence: its summary names
both commits, which the gate rejects.

## Explicit CI exemptions

CARLA Simulation requires a GPU; Logging Simulation has no hosted runtime
cell. Their deployment manifests contain a reasoned `evidence.exempt` entry.
They remain in the bundle, are listed in release metadata/notes, and the CLI
warns when they run. **An exemption is not runtime evidence.**

Adding an exemption is a reviewed source change, not a release-time override.
Do not use it to hide a known product failure in a normally tested cell.

## Autoware and ROS distro decisions

Pin the latest stable Autoware release at the release cut. If it has a blocking
issue, keep the previous verified stable pin and explain the exception, date
and follow-up in the release notes. v2.0 pins **Autoware 1.9.0**.

Every release, stable or candidate, is built on its `release/X.Y` branch from
the Autoware release tag in `.github/autoware.ref`. A release line keeps one
Autoware minor release: the release gate compares each release with the line's
latest published one and refuses another Autoware minor (v2.0.x is 1.9.x). Builds of `main` use a
weekly snapshot of upstream development and are never released. The build's
`autoware-lock.repos`, resolved SHA and upstream image digests record the input.

### Backporting an Autoware fix

Autoware releases come months apart. A fix that blocks a release line and is
upstream, merged on Autoware's `main` or in an open pull request, can ride on
the line as a patch instead of waiting for the next Autoware release:

1. In the upstream repository, `git format-patch -1 <commit>`, and add a line
   `Upstream: <URL of the commit or pull request>` to its message.
2. Open a pull request into `release/X.Y` that adds it as
   `.github/autoware-patches/<repository>/<NNNN>-<subject>.patch`, where
   `<repository>` is its path under `autoware/src` (a key of
   `autoware-lock.repos`, such as `universe/autoware_universe`). The review is
   the fix's own diff.
3. Every build of the line applies the patches in order right after
   `vcs import`; one that does not apply, or has no `Upstream:` line, fails the
   build. The release lists them under **Backported Autoware fixes**, its
   bundle carries them as `autoware.backports`, and `openadkit version` counts
   them. The Autoware version and the release line stay those of the tag.
4. When the line moves to an Autoware release that contains the fix, delete
   the patch. `main`, which builds upstream development, needs none.

`defaultRosDistro` in the promoted `openadkit.json` explicitly selects the ROS
distro. The release input must agree, and its required runtime cells must pass.
The gate does not automatically switch from Humble to Jazzy or remove a failing
distro. To change supported distros, update the manifests in a reviewed source
change and build/test that revision. Humble remains the initial default.

## Metadata and verification report

`release-plan.json` seals the selected evidence summary (result, build, commit,
run URL and cells) before packaging. `release-metadata.json` includes that same
evidence, the BOM and the CI exemptions. Bundle, installer, plan and metadata
receive release-workflow build provenance.

The verification table shows passing-cell count, readiness time, arrival time
and peak memory for the current build. Release never searches older runs or
releases; its notes depend only on the sealed plan. Missing metrics are shown
as `-`, never replaced with zeroes.

Historical comparison is optional, outside release. With two explicitly chosen
local summaries, run:

```bash
python3 .github/scripts/evidence/report.py \
  --current current.json --previous previous.json --output comparison.md
```

This is a timing/memory comparison, not an `openadkit upgrade` acceptance test,
performance SLA or safety gate.

See [Verify a Release](verification.md) and
[Run the Evidence Workflow](../development/evidence-workflow.md).
