# Evidence and Release Policy

A release promotes an existing build. It does not rebuild images or silently
relax its tests. Both stable releases and release candidates require **one
complete, cryptographically verified Test Result with `result: PASSED`**.

## What the gate checks

The release validation job checks these independently before creating a tag:

1. **Identity:** GitHub verifies the signature, the repository, the
   `.github/workflows/evidence.yaml` signer, the `release/X.Y` source ref,
   and that the attestation was signed on a hosted runner.
2. **Subject:** all build image digests and the deployment, shared asset and
   example-kit source/config checksums match the exact promoted source tree.
   The dispatch-time scripts and the promoted source are checked out separately.
3. **Coverage:** every required manifest-derived cell appears exactly once in
   the signed configuration and in `passedTests`. Cell build/source identity,
   distro, node, kit and platform must match; L0, L1 and L2 must all be true.
   The example-kit cells must also have `overlayConformant: true`.
4. **Result:** only the exact value `PASSED` is accepted. `WARNED`, `FAILED`,
   unknown/malformed results, failed/warned test lists, and missing evidence block
   publication. Several incomplete statements cannot be combined into a pass.

A complete passing retry may supersede a failed attempt; a failed attempt is
never itself treated as passed. There is no release bypass input.

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

The workflow retries a failed runtime cell once. A short, reasoned, dated CI
quarantine can label a failure `WARNED` for investigation; **it still blocks a
release**. The release gate does not consult quarantine to waive a failed test.
The cells start deployments with `openadkit run --no-visualizer`.

On the 4-vCPU GitHub-hosted runners a scenario-simulation cell occasionally
fails although the change is sound, about one run in five: Autoware main
takes minutes to load its components there, and Scenario Simulator V2
sometimes checks a reused Autoware's state before it has left the previous
scenario. Hosts with 16 vCPUs pass these cells consistently. Rerun the failed
jobs once, and investigate only a failure that repeats or a new error. Such a
failure can turn a run red; it cannot pass a broken change.

## Testing a change without a build

A change that rebuilds no image, such as a deployment setting, the CLI or a
check, runs the cells against an existing build:

- A pull request that touches `deployments/`, `cli/` or the evidence checks
  runs them against its base branch's latest successful build. When it also
  changes an image's inputs, it waits for the build after merge instead.
- A dispatch of `evidence.yaml` with `source_ref` tests that branch or commit;
  `build_tag` defaults to the dispatched branch's latest successful build.

The cells take the deployments, CLI and checks from the tested commit and the
images from the build. Such a run is not release evidence: it is not attested,
its summary names both commits, and its cells carry the tested commit, which
the gate rejects.

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

`defaultRosDistro` in the promoted `openadkit.json` explicitly selects the ROS
distro. The release input must agree, and its required runtime cells must pass.
The gate does not automatically switch from Humble to Jazzy or remove a failing
distro. To change supported distros, update the manifests in a reviewed source
change and build/test that revision. Humble remains the initial default.

## Metadata and verification report

`release-plan.json` seals the validated `evidence` report before packaging.
`release-metadata.json` includes that same report, the BOM, CI exemptions and
`default_ros_distro_decision`. The current release-note metrics come from the
selected signed statement, not an independently downloaded, unsigned summary.
Bundle, installer, plan and metadata receive release-workflow build provenance.

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
