# Evidence and Release Policy

A release promotes an existing build. It does not rebuild images or silently
relax its tests. Both stable releases and release candidates require **one
complete, cryptographically verified Test Result with `result: PASSED`**.

## What the gate checks

The release validation job checks these independently before creating a tag:

1. **Identity:** GitHub verifies the signature, the repository, the
   `.github/workflows/evidence.yaml` signer, the `refs/heads/main` source ref,
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
| `examples/custom-kit` | Humble, Jazzy | Custom Planning, including its C++ overlay |

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
and follow-up in the release notes. v2.0's planned pin is **Autoware 1.8.0**;
the evidence-backed 1.9.0 update belongs in a subsequent release.

Stable Open AD Kit builds must originate from an Autoware release tag.
Release candidates may also use a full upstream commit SHA. The build's
`autoware-lock.repos`, resolved SHA and upstream image digests record the input.

`defaultRosDistro` in the promoted `openadkit.json` explicitly selects the ROS
distro. The release input must agree, and its required runtime cells must pass.
The gate does not automatically switch from Humble to Jazzy or remove a failing
distro. To change supported distros, update the manifests in a reviewed source
change and build/test that revision. Humble remains the initial default.

## Metadata and upgrade report

`release-plan.json` seals the validated `evidence` report before packaging.
`release-metadata.json` includes that same report, the BOM, CI exemptions and
`default_ros_distro_decision`. The current release-note metrics come from the
selected signed statement, not an independently downloaded, unsigned summary.
Bundle, installer, plan and metadata receive release-workflow build provenance.

The upgrade table shows passing-cell count, readiness time, arrival time and
peak memory for each cell. Its baseline is the previous stable version below
the target; if none exists, the latest available successful evidence run on
`main` for a different build. Historical metrics are informational, not a
performance-regression or safety gate. Missing baselines/metrics are shown
explicitly, never replaced with zeroes. Positive timing/memory deltas mean an
increase, not automatically a failure.

See [Verify a Release](verification.md) and
[Run the Evidence Workflow](../development/evidence-workflow.md).
