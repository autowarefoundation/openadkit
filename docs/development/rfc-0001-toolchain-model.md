# RFC 0001: Evidence-backed Toolchain and Reference Kit

**Status:** proposed project design for working-group review. This RFC records
the selected design; it does not claim working-group or release-team approval.
**Primary v2.0 consumer:** Open AD Kit maintainers and the AWF release team.

## Thesis and audience

Open AD Kit is a toolchain plus a reference kit, not a fork of every workload,
an OTA service, or a new orchestrator. The reference kit exercises the same
extension boundaries an integrator uses. Think of the relationship between
Yocto's tools/layers and its reference distribution, rather than a single
monolithic autonomy image.

The design serves three audiences:

- AWF maintainers consuming build, runtime and upgrade evidence for releases
- ROS/autonomy integrators adding vehicle, sensor, configuration and application
  differences without copying the reference deployment
- Automotive/SDV integrators consuming pinned artifacts and bounded evidence
  through their existing platform and fleet-delivery systems

v2.0 deliberately prioritizes the first audience. `examples/custom-kit` is the
concrete integration acceptance fixture, not a promise to support every possible
external kit, hardware platform or scenario.

## Layers and ownership

```text
Integrator kit: openadkit.json + deployment differences + custom packages
               extends a pinned Open AD Kit release
---------------------- five extension points -----------------------
Reference release: CLI + deployment manifests + Compose + pinned images
---------------------- digest-pinned inputs ------------------------
Workloads: Autoware, simulator artifacts, future upstream applications
```

Build our Autoware component images; consume other upstream projects' published
artifacts by digest. Do not become their build farm. A workload owns its public
runtime interface. In particular, Safety Island and its reference-design group
own its safety boundary; Open AD Kit references it and can produce integration
evidence, not redefine it or inherit an ASIL claim.

## Current v2.0 contracts

### Manifests and pinned CLI

The source and release manifests use `schemaVersion: 2`. `openadkit.json`
identifies the kit or release, deployment catalog, component images, upstream
artifacts and default ROS distro. `deployment.json` identifies requirements,
data resources, shared assets, reset services and optional node views.

An integrator uses `kind: kit` with one level of `extends`, normally an exact
`vX.Y.Z` release; a source path is allowed for development. An integrator kit
cannot extend another integrator kit. The launcher delegates to the pinned
base version's CLI; it does not run an old kit through whichever CLI happens
to be newest. A missing pinned version produces installation guidance.

The kit's deployment declares `base`, and Compose uses native `include` through
`KIT_openadkit`. The CLI resolves metadata and environment; Compose resolves
includes and their relative paths. There is no custom Compose merge language.

Base architecture, ROS distro and GPU requirements are inherited **exactly**;
neither narrowing nor widening is allowed. Additional data resources and reset
services may be declared under the manifest rules. Base evidence exemptions
are inherited, not silently removed. Component-image catalog entries come from
the base; a kit does not duplicate that catalog.

### Five extension points

| Point | Source of the integrator's difference |
|-------|---------------------------------------|
| Public values | Kit `config.env` and host `<deployment>.env` |
| Configuration | Package-relative files under `config/autoware/<package>/` |
| Custom ROS packages | `overlay_ws/install`, built in the matching devel image |
| Extra services | New services alongside the included base Compose graph |
| Artifact replacement | Explicit digest-pinned entries in `artifacts` |

Public variables are derived from base environment/Compose, CLI injections,
artifact definitions and data destinations; there is no unused parallel
`parameters` catalog. The current hook uses Autoware's package-based layout;
there is no separate generic `workloads` metadata layer.

Environment precedence is runtime defaults, base `config.env`, applicable GPU
settings, kit `config.env`, then host/site `.env`. YAML mappings merge
recursively; lists and scalar values replace the base values. Launch substitutions
such as `$(var ...)` survive. Non-YAML files replace the corresponding base file.
The hook starts from a fresh package-share copy under `/tmp/openadkit` for every
container start, so an upgrade keeps untouched base changes.

Unknown base configuration files/keys are warnings recorded in a runtime hook
report. `validate` remains static: it does not pull images to inspect their
parameter files. It warns about replaced base commands/images, mounts over
image-internal paths and undeclared variables. Supported value changes,
inherited mounts and extra services' own commands/images are not violations.

Artifact replacement is mechanically possible, but replacing a base image
does not inherit its conformance claim. It requires the integrator's own
runtime evidence. The signed `overlayConformant` value combines static checks
and every mounted hooked service's report; missing/invalid reports are not clean.
The reference example requires `overlayConformant: true` as well as L0-L2.

Build custom C++ packages in the **same build/release's** distro-specific,
digest-pinned `universe-common-devel` image. ROS package alignment locks cover
the dependencies linked by our tree, not arbitrary packages later added by an
integrator. Pinning is necessary for repeatability, not sufficient to prove ABI
compatibility or behavior of a replacement workload.

### User-owned files and data

Installed releases live side by side under the installation root. Host config
defaults to `~/.config/openadkit`; run output defaults to
`~/.local/state/openadkit/<deployment>/output`. `OPENADKIT_CONFIG_DIR`,
`OPENADKIT_STATE_DIR` and the relevant XDG roots can override them.
Configuration, output, downloads and integrator sources stay outside the base
release, so upgrade/uninstall does not overwrite them.

Downloaded resources carry a `.openadkit-resource.json` ownership marker before
publication. Markerless directories are not adopted, deleted or forcibly
replaced; complete existing data may still be used for a run. This boundary
protects user-owned directories even when a data path is misconfigured.

### Nodes and Compose backend

`nodes` describe host-local views of a deployment, each with a backend and
service selection. v2.0 implements the Compose backend. A node has its own
project/container names, ROS domain and Zenoh endpoint. `--node` selects one
view; omitting it preserves the single-host graph.

CycloneDDS is local to each node; selected host-boundary traffic crosses Zenoh.
The scenario split cell runs both nodes on one hosted runner and checks domain
isolation. This is not evidence of arbitrary LAN/WAN behavior, restart
resilience, two physical hosts, HIL or a vehicle.

### Evidence, releases and upgrade confidence

Use an in-toto Statement v1 with the standard Test Result v0.1 predicate,
signed by GitHub Actions. Subjects bind build image digests, deployment/shared
checksums and example-kit source/config checksums. Colcon products are omitted
from source checksums. Cell annotations bind build tag, source commit, distro,
node, kit, platform, passed levels, conformance and measured runtime metrics.

| Level | Meaning | v2.0 release boundary |
|-------|---------|-----------------------|
| L0 | Render/manifest validity | Required |
| L1 | Processes, ROS interfaces and fresh topics | Required |
| L2 | Golden path, scenario and split-node behavior | Required |
| L3 | Repeated scenario-set statistics | Future evidence |
| L4 | Hardware-in-the-loop | Partner/lab |
| L5 | Field behavior | Partner |

Run every variation on a fresh stack. The runner computes semantic results;
missing expected test cases fail. Retry a failed cell once. CI quarantine is
an investigation annotation, never release permission.

The blocking gate separately verifies signer identity, subject equality, exact
manifest-derived cell coverage and **`PASSED`**. `WARNED`, failed, unknown and
missing evidence block release candidates and stable releases alike. Never
combine incomplete statements into a passing claim. A complete successful
retry is valid evidence; a failed record does not permanently poison that build.

CI-infeasible deployments have reviewed, reasoned manifest exemptions and remain
visible in the CLI, metadata and release notes. An exemption makes no runtime
claim. The current runtime platform is hosted `linux/amd64`; build/scan coverage
for arm64 is a different claim. There are no deployment evidence tiers.

The promoted manifest explicitly chooses the default distro. That choice must
agree with the release input and passing evidence; the gate never silently
chooses another distro or drops failed cells. Stable releases pin a stable
Autoware tag and record the resolved source/lock and upstream image digests.

The immutable plan embeds the selected verified report and BOM. Release notes
derive current metrics from it. Bundle, installer, plan and metadata receive
release-workflow provenance. The minimal upgrade report compares passing-cell
count, readiness/arrival time and memory against the previous stable release,
or an available previous successful `main` run when there is no stable release.
Historical metrics describe change; they are not a safety or performance SLA.

`workflow_call` currently reuses the reference-build verifier in the repository
owning the build, including its example kits. Arbitrary external kit intake is
not implemented. That extension must keep runner/attestation code in a pinned
trusted workflow, explicitly pin caller kit inputs and bind them as subjects;
calling a trusted workflow that executes arbitrary caller code is insufficient.

## Selected delivery design beyond v2.0

These interfaces are specified here but **not delivered by the v2.0 CLI**.

### Simulator boundary and validation ladder

The ladder is SIL, virtual vehicle network, bench HIL, small-scale vehicle,
then full-scale vehicle. Replace the vehicle node between rungs, not the
application topology. A simulator adapter must declare these logical ports:

| Contract | Required behavior |
|----------|-------------------|
| Clock | Wall/simulation time mode, monotonic progress within a run, reset only between fresh runs |
| Ego command/state | Vehicle controls and measured state with documented units, coordinate frames and timestamps |
| Sensors | Declared sensor set, calibration/frame relationships and timestamp domain; explicit unavailable sensors |
| World/map | Pinned world/map identities and consistent origin/frame alignment |
| Scenario | Pinned scenario inputs, variation identity and expected test-case count |
| Readiness | Explicit clock/interface readiness, not merely an alive container |
| Result | Machine-readable case outcomes, failure/timeout/missing-case semantics and diagnostics |

The logical ego boundary must admit both Autoware's vehicle interfaces and
non-ROS applications such as Vision Pilot through adapters; it does not mandate
that every upstream application adopt ROS. v2.0's dummy and Scenario Simulator
checks exercise clock/readiness and behavior portions of this boundary, not a
complete new general-purpose simulator-adapter implementation.

Safety Island's interface remains owned upstream. ODD scenario use-case IDs
should come from the joint ODD work, not a competing private catalog. NCAP-derived
scenarios must not be advertised as an NCAP score or certification.

### Flattening and vehicle backends

Compose remains the source form. Generate a resolved configuration in a staging
root that mirrors vehicle paths; pin every image and required asset by digest.
Never export accidental build-host absolute paths as vehicle mount paths.
Evidence for delivery must bind the actual flattened system, not merely its
unresolved source files.

Quadlet plus BlueChi is the selected first vehicle backend for AutoSD/X5H.
Its initial pod-versus-unit generator spike resolves concrete sharing, GPU and
update constraints. Ankaios is not a required second generator; Kubernetes,
k3s and Helm are outside this design. The vehicle's runtime runs the system.
Open AD Kit does not install its own fleet agent or OTA orchestrator.

### OCI delivery contract

Use the OCI image-layout/index/manifest formats for distribution; GitHub Releases
remain the human-facing channel. The delivery artifact must carry the flattened
system, pinned runtime inputs and a BOM mapping logical components to digests.
All required content must be available for offline mirroring; no moving tag or
unrecorded host path may resolve a delivery dependency.

Attach build provenance, Test Result and later SBOM artifacts through OCI subject
relationships/referrers. Their subjects identify the delivered artifact or
flattened-system digest. Exclude secrets, credentials and mutable vehicle state.
Use standard OCI tooling such as ORAS/skopeo for copying/mirroring. Fleet rollout,
activation and rollback belong to the integrator's delivery system, such as
eSync. OCI packaging, vehicle flattening and Quadlet generation are v2.1 work,
not capabilities of the v2.0 tarball installer.

## Evolution and governance

Change manifest contracts through `schemaVersion` plus migration notes. v1 never
shipped in a stable release and is rejected explicitly. After v2.0, schema
transitions require a migration reader/warning path rather than silently
reinterpreting old data. Removing public variables or extension points is a
breaking change and follows SemVer. Internal paths are not extension contracts.

Release maintainers review exceptions, distro/default changes and upstream pins
as source changes before a new build. The AWF release team and working group
must review how RC evidence and upgrade reports enter their process; this RFC
does not assert that organizational agreement has already happened.

## Roadmap and non-goals

- **v2.0:** pinned/reference kit, user-data boundaries, Compose nodes, L0-L2
  evidence, blocking release policy and minimal upgrade report
- **v2.0.x:** evidence-backed upstream updates, richer scenario/upgrade metrics
  and image SBOM work
- **v2.1:** OCI delivery and the first vehicle backend; upstream application
  integration only with pinned artifacts and concrete evidence
- **Later:** compatibility views generated from evidence and partner-backed
  hardware/field coverage, not hand-maintained certification badges

No custom OTA service, Kubernetes stack, workload fork farm, ASIL/NCAP certification
claim or promise that digest pinning alone makes deployment safe.

For operational detail, see the [Integrator Guide](../deployments/integrator-guide.md),
[Evidence Policy](../releases/evidence.md), [Release Verification](../releases/verification.md)
and [Evidence Workflow](evidence-workflow.md).
