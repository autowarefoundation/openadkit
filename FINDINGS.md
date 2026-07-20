# Remaining Review Findings

This document records findings independently validated for PR #90 at commit
`c55be7760285c72fb19afa1ad3785bfa0c84d2e4`. Severity reflects demonstrated
impact, not the amount of code involved.

## Current PR Status

- The PR is open, approved, and reported as mergeable by GitHub.
- DCO is currently failing because six older commits still lack sign-off; the
  latest commit is signed off.
- Lint, preview, semantic PR, and host-install checks pass.
- Image builds, including `planning-control` with its new timeout, are running.

## Resolved In The Current Worktree

The first five highest-ROI findings were committed and pushed; image CI is still
running:

- The PR image-build timeout now leaves enough time for the bounded Trivy scan.
- A Compose-level dependency guard blocks wildcard Zenoh router binds for normal
  helper and direct `docker compose up` startup paths.
- Artifact prerequisites are chained so a failed `ansible-galaxy` command
  cannot be hidden by a later successful playbook.
- Draft release asset names and SHA-256 contents are revalidated immediately
  before publication.
- Release bundles bind Open AD Kit version tags to validated image digests.

## Merge Decision

There are 28 remaining verified findings: 1 high, 19 medium, and 8 low. The two
defense-in-depth notes are not included in that count.

Eight findings should be resolved before merge because they affect host safety,
release integrity, supply-chain integrity, or a primary runtime service:

| Priority | Finding | Reason to block merge |
|----------|---------|-----------------------|
| 1 | Failed NVIDIA runtime configuration can leave Docker unavailable | Can stop Docker and all host containers |
| 2 | Stable alias promotion can leave a mixed release | Can expose a partially promoted public release |
| 3 | Manual builds can overwrite stable architecture tags | Can publish alternate inputs under stable tags |
| 4 | Release inputs and build tooling are not fully locked | Weakens release reproducibility and privileged CI integrity |
| 5 | NVIDIA repository replacement is non-transactional | A failed install can break a working package source |
| 6 | VirtualGL is installed without cryptographic verification | Installs an unverified package as root |
| 7 | Visualizer does not supervise VNC and websockify | Container can appear healthy after its service dies |
| 8 | Publishing an older or prerelease tag can replace current documentation | Can roll the canonical documentation site backward |

The other 20 findings are valid but may be moved to tracked follow-up issues.
They concern default-off or narrower deployment edge cases, lifecycle and
recovery improvements, locally trusted configuration inputs, test coverage, and
documentation or developer ergonomics.

DCO remediation and successful completion of all required CI checks are process
gates in addition to these eight code findings.

## High Severity

### Failed NVIDIA runtime configuration can leave Docker unavailable

The installer modifies Docker's persistent configuration and then restarts the
daemon without backing up or validating the resulting configuration. Failure
under `set -e` has no rollback path.

**Evidence:** `install.sh:170-175`.

**Impact:** A failed NVIDIA setup can interrupt every container on the host and
leave Docker stopped after the installer exits.

**Recommendation:** Back up the Docker configuration, validate the generated
configuration before restart, and restore the previous configuration and daemon
state on failure. Warn before restarting a daemon that may host active work.

## Medium Severity

### Stable alias promotion can leave a mixed release

Aliases are updated sequentially with no retry around the mutating operation and
no final all-alias convergence check.

**Evidence:** `.github/scripts/promote_release_images.sh:52-77` and
`.github/workflows/release.yaml:172-215`.

**Impact:** A timeout, rate limit, network failure, or runner loss can leave some
public aliases on the new release and others on the previous release.

**Recommendation:** Add bounded retries, verify every resulting digest, and run
a final convergence check that reports changed and pending aliases.

### Manual builds can overwrite stable architecture tags

Manual runs accept an arbitrary Autoware ref while unversioned per-architecture
tags are enabled according to the default branch rather than the event type.

**Evidence:** `.github/workflows/build-all-images.yaml:19-29` and lines 173, 185,
291, and 386.

**Impact:** A manual run from `main` can publish alternate upstream inputs under
tags consumed as stable main-branch contexts.

**Recommendation:** Publish unversioned architecture tags only for successful
`push` events on `main`. Use run-specific tags for manual and scheduled builds.

### Release inputs and build tooling are not fully locked

Release packaging resolves mutable third-party tags at execution time, Compose
is downloaded from the latest release, and `vcs2l` is installed without a fixed
version. Several official GitHub Actions also use moving major-version tags.

**Evidence:**

- `.github/scripts/package_release_bundles.sh:90-109`
- `.github/scripts/install-compose.sh:14-40`
- `.github/actions/setup-build-env/action.yaml:59-65`
- privileged workflow references such as `actions/checkout@v6`

**Impact:** Identical source and release inputs can use different dependencies
or tooling over time, and privileged action code is not immutable.

**Recommendation:** Commit dependency locks and expected checksums; pin Compose,
`vcs2l`, lint tools, and all external actions to reviewed immutable versions or
commit SHAs.

### NVIDIA repository replacement is non-transactional

Existing NVIDIA source-list files and the keyring are removed before replacement
downloads and validation succeed.

**Evidence:** `install.sh:145-159`.

**Impact:** A transient network, TLS, disk, or GPG failure can disable a
previously working NVIDIA package repository.

**Recommendation:** Download and validate temporary replacements first, then
install atomically while preserving rollback state.

### Visualizer does not supervise VNC and websockify

The entrypoint checks both child processes only immediately after startup. With
no explicit command, PID 1 then executes `sleep infinity` and never observes a
later child failure.

**Evidence:**
`components/visualizer/etc/visualizer_entrypoint.sh:106-151` and lines 168-184.

**Impact:** Docker sees a running container even when the browser endpoint or
VNC display has died, so restart policy cannot recover it.

**Recommendation:** Supervise child PIDs with `wait -n`, terminate the sibling
on failure, propagate the exit status, and add an endpoint/process healthcheck.

### VirtualGL is installed without cryptographic verification

The visualizer downloads an architecture-selected `.deb` from a GitHub release
and installs it as root without checking a repository-owned digest or signature.

**Evidence:** `components/visualizer/Dockerfile:93-98`.

**Impact:** Asset replacement or corruption can inject binaries and package
maintainer scripts into the image.

**Recommendation:** Record and verify reviewed SHA-256 values for amd64 and
arm64, or consume a signed repository with a pinned signing key.

### CARLA map preparation and runtime mount can diverge

The launcher downloads assets under `CARLA_E2E_MAP_PATH`, while the base Compose
model mounts `MAP_PATH`. Filenames used for downloaded assets are also hardcoded,
while runtime filenames remain configurable.

**Evidence:**

- `deployments/carla-simulation/carla-simulation.env:33-40`
- `deployments/carla-simulation/start-carla-e2e-demo.sh:282-292`
- `deployments/carla-simulation/start-carla-e2e-demo.sh:344-352`

**Impact:** An override can prepare one directory and mount another. A stale
pointcloud can pass the sole check while Lanelet or projector data is absent.

**Recommendation:** Use one map path, write configured filenames, and verify the
pointcloud, Lanelet map, and projector metadata in the mounted directory.

### CARLA rollback does not restore pre-existing services

The launcher records only services that were not already running, but recreates
every selected service with `--force-recreate`. Failure rollback removes only
the recorded services.

**Evidence:** `start-carla-e2e-demo.sh:92-99` and lines 333-342.

**Impact:** A failed retry can leave replaced containers running in a mixed or
degraded state; the original containers cannot be restored.

**Recommendation:** Do not recreate pre-existing services, or make startup
explicitly destructive and document that rollback cannot restore prior state.

### CARLA's forward route ignores vehicle heading

The helper adds distance to map-frame X and leaves Y unchanged while copying the
current orientation.

**Evidence:** `deployments/carla-simulation/carla_e2e_helper.py:141-148`.

**Impact:** A vehicle not facing global +X can receive a sideways, backward, or
off-lane goal.

**Recommendation:** Rotate displacement by current yaw and preferably select a
valid forward Lanelet or CARLA waypoint.

### CARLA map-loader timeout is not an overall deadline

Individual RPC calls use fixed ten-second timeouts, and the load call forces at
least ten more seconds even when the configured deadline has expired.

**Evidence:** `deployments/carla-simulation/load-carla-map.py:14-52`.

**Impact:** The operation can exceed `CARLA_LOAD_TIMEOUT`, and a successful late
load can still be reported as failure because confirmation no longer runs.

**Recommendation:** Recalculate remaining time before every blocking call and
cap each client timeout to that positive remaining duration.

### Zenoh recovery commands require valid startup configuration

`cloud.sh` resolves and validates the router address for every command, while
the Compose model requires `REMOTE_PASSWORD` during interpolation.

**Evidence:** `deployments/zenoh-bridge/cloud.sh:63-81` and
`deployments/zenoh-bridge/docker-compose.yaml:127`.

**Impact:** A stale hostname or missing startup secret can block `down`, `ps`,
and `logs` during incident recovery.

**Recommendation:** Restrict startup-only validation to startup and dry-run
commands. Keep teardown and diagnostics available with broken configuration.

### Zenoh readiness proves only TCP listener availability

One-shot helper containers check ports 7447 and 7448, not Zenoh session state or
ROS traffic. The bridge services have no sustained healthcheck or restart
policy.

**Evidence:** `deployments/zenoh-bridge/docker-compose.yaml:94-113` and lines
153-198.

**Impact:** Any process listening on the expected port can satisfy readiness,
and readiness remains successful after a bridge later dies.

**Recommendation:** Probe Zenoh route/session state, add a small end-to-end ROS
check, and monitor or restart long-running bridge processes.

### Zenoh teardown can leave owned containers behind

`down` stops and removes only the option-dependent target list. Readiness
helpers are absent from those lists, and prior optional services such as
`teleop` or `scenario_simulator` can be omitted.

**Evidence:**

- `deployments/zenoh-bridge/common.sh:101-107`
- `deployments/zenoh-bridge/cloud.sh:29-45`
- `deployments/zenoh-bridge/edge.sh:25-43`

**Impact:** A documented shutdown can leave running or exited project resources
that interfere with later starts.

**Recommendation:** Use a fixed side-specific ownership list for teardown or
Compose profiles/projects that permit a complete `down --remove-orphans`.

### Compose environment values are interpolated into shell programs

Logging and scenario Compose models place configurable values directly into
`bash -lc` source rather than passing them as runtime environment data.

**Evidence:**

- `deployments/logging-simulation/docker-compose.yaml:116-131`
- `deployments/scenario-simulation/docker-compose.yaml:85-104`

**Impact:** Whitespace or shell metacharacters can alter the command program,
causing startup failures or command execution inside the container. These are
locally trusted inputs, so this is a correctness and containment issue rather
than a remote injection vulnerability.

**Recommendation:** Pass values through `environment:`, reference them as
`"$${VARIABLE}"` at runtime, and validate numeric and enum inputs.

**Validation:** Safe Compose renders inserted `echo INJECTED` as a shell
statement for crafted `ROSBAG_READY_TOPIC` and `SCENARIO` values.

### Source deployments use mutable third-party image tags

Release bundles pin third-party images, but source-checkout defaults still use
`universe` and `latest` references.

**Evidence:**

- `deployments/zenoh-bridge/docker-compose.yaml:19,74,154,201`
- `deployments/logging-simulation/docker-compose.yaml:95`

**Impact:** Two starts from the same source commit can pull incompatible or
otherwise different software.

**Recommendation:** Use reviewed tags plus digests in source defaults while
retaining explicit overrides for intentional upgrades.

### Publishing an older or prerelease tag can replace current documentation

Every published release builds docs from that release tag and deploys them to
the same root site used by `main`.

**Evidence:** `.github/workflows/deploy-docs.yaml:22-24`, lines 43-49, and lines
81-87.

**Impact:** Publishing an older delayed release or prerelease can replace newer
canonical documentation with an older snapshot.

**Recommendation:** Keep the root site sourced from `main`; publish release
snapshots under versioned paths, or gate root replacement to the latest stable
release.

## Test Coverage Findings

### Critical release validation has no direct regression suite

The fail-closed metadata, inventory, scan, tag, and registry-integrity gates are
implemented in `validate_release.sh`, but no test under `.github/scripts/tests/`
invokes that script or its named gate functions.

**Severity:** Medium

**Evidence:** `.github/scripts/validate_release.sh:194-454` and no matching
references under `.github/scripts/tests/`.

**Recommendation:** Add fixture-driven rejection tests for malformed metadata,
missing or extra inventory/scan coverage, policy-SHA mismatch, tag conflicts,
source-digest mismatch, and registry authorization/transient errors.

### Bundle tests stub away final Compose validation

The test replaces Docker with a process that always exits successfully. Digest
pinning and reproducibility are now asserted for all five bundles, but the unit
test still cannot detect an invalid generated Compose model.

**Severity:** Medium

**Evidence:** `.github/scripts/tests/test_release_pipeline.py:286-349`.

**Recommendation:** Add a CI integration test that runs real
`docker compose config -q` against all staged bundles. Keep the current unit
assertions for Open AD Kit digest pinning and reproducible archive bytes.

### Sample-data tests cover only part of the installer contract

Successful planning installation and CARLA rejection are covered, but logging,
scenario, and Zenoh success and preservation paths are not.

**Severity:** Medium

**Evidence:** `.github/scripts/tests/test_install_sample_data.py`.

**Recommendation:** Parameterize success, checksum failure, unsafe archive,
existing-data preservation, and `--force` cases across supported deployments.

## Low Severity

### Planning smoke-test naming and help text are misleading

`deployments/planning-simulation/start-planning-e2e-demo.sh:19-83` says it starts
the deployment but only validates Compose configuration and prints commands.
Rename it or implement startup, readiness, and rollback.

### Release gate count is inconsistent

`docs/development/build-from-source.md:171-199` says both 12 and 14 validation
gates. Make the summary agree with the 14-entry table and implementation.

### Documented local Hadolint glob misses nested Dockerfiles

`CONTRIBUTING.md:41-42` uses `**/Dockerfile*`, but normal Bash does not recurse
without `globstar`. Use a tracked-file list or explicitly enable `globstar`.

### Lint path filters omit docs-build inputs

`.github/workflows/lint.yaml:6-30` omits `docs/macros.py`,
`docs/requirements.txt`, assets, and overrides even though the workflow's docs
smoke test consumes them. Align the filter with the preview/docs build inputs.

### Zenoh config mounts are writable

`deployments/zenoh-bridge/docker-compose.yaml:87-92` and lines 174-178 mount
`./config` read-write even though it is consumed as configuration. Mount it
read-only.

### Zenoh scenario results are ephemeral

`deployments/zenoh-bridge/docker-compose.yaml:52-66` writes scenario results
inside the container without a persistent mount. Bind a documented result path
or explicitly document that output is disposable.

### CARLA local requirements omit enforced platform constraints

`deployments/carla-simulation/README.md:7-17` omits the amd64 and Ubuntu 22.04
requirements enforced by `start-carla-e2e-demo.sh:181-205`, and does not state a
minimum Compose feature/version. Align the local README with launcher checks.

### Production docs workflow changes do not trigger that workflow

`.github/workflows/deploy-docs.yaml:7-21` does not include its own path in the
push filter. Add `.github/workflows/deploy-docs.yaml` so a standalone workflow
fix is exercised after merge.

## Evaluated Hardening Notes

The following observations are valid defense-in-depth improvements but are not
tracked above as behavioral findings at the current permission boundary:

- Untrusted PR jobs retain checkout credentials, but their explicit token is
  read-only. Set `persist-credentials: false` before any future permission
  expansion.
- The scan metadata job grants `actions: write` although its current operations
  appear to require only read access plus the artifact runtime token. Reduce it
  after confirming artifact upload behavior.

## Verification Performed

The following checks passed against the current worktree:

- 34 Python tests under `.github/scripts/`
- Multi-architecture manifest shell tests
- Actionlint
- `git diff --check`
- MkDocs container build
- Source Compose validation for all five deployments
- Release bundle creation and real Compose validation for all five bundles

Additional safe render/reproducer checks confirmed:

- the cloud bridge now depends on the successful wildcard-bind guard;
- shell-program injection from logging and scenario environment values;
- artifact prerequisite commands now use fail-fast `&&` chaining;
- all five generated release bundles contain digest-bound Open AD Kit refs and
  pass real Compose validation;
- changed draft release asset content is rejected before publication.

CARLA, ROS, Zenoh, NVIDIA, and GPU end-to-end runtime tests were not executed
because they require corresponding hardware or a disposable runtime host.

## Previously Closed Context

The release pipeline resolves and records immutable upstream image inputs,
release promotion requires an exact Autoware release tag, runtime images retain
package-manager integrity, and the visualizer runs as the unprivileged `aw`
user. Release bundles pin third-party images, CARLA assets are checksum-verified,
and rosbag and Zenoh waits are bounded.

The previous `diagnostic_graph_aggregator` entry was removed because the pinned
Autoware source implements the availability publisher. An unavailable RViz Auto
button must be diagnosed from the published availability and diagnostic graph
state rather than bypassed with a fabricated availability message.
