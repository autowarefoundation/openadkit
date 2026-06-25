# Open AD Kit 2026–2027 Roadmap

*Published June 2026. Canonical copy: `roadmap.md`; issue #91 mirrors it.*

---

## 1. Executive Summary

Open AD Kit is the **modular deployment and validation layer for Autoware** — turning it into a reproducible, evidence-backed workload for software-defined-vehicle (SDV) development.

**Mid-2027 goal:** from documented commands, a user runs the full loop on a pinned modular Autoware deployment — deploy → validate → observe → update one component → roll back to a known-good set — in a non-certified validation environment.

### Release ladder

| Release | Target | Theme |
| :--- | :--- | :--- |
| [v2.0.0](#v200--first-trustworthy-release--jul-2026) | Jul 2026 | First trustworthy release |
| [v2.1.0](#v210--compatibility-set-mvp--sep-2026) | Sep 2026 | Compatibility-set MVP |
| [v2.2.0](#v220--readiness-and-test-gating--oct-2026) | Oct 2026 | Readiness + test gating |
| [v2.3.0](#v230--release-trust--nov-2026) | Nov 2026 | Release trust |
| [CES 2027](#ces-2027--flagship-event--jan-69-2027) | Jan 6–9, 2027 | Flagship event (not a gate) |
| [v2.4.0](#v240--platform-profiles--ecosystem--late-janfeb-2027) | Late Jan–Feb 2027 | Platform profiles + ecosystem |
| [v2.5.0](#v250--updaterollback-beta--mar-2027) | Mar 2027 | Update/rollback beta |
| [v3.0.0](#v300--closed-loop-release--may-2027) | May 2027 | Closed-loop release |

### Status labels

- **`COMMITTED`** — owned and scheduled. Ships executable evidence, or a dated blocker list when blocked by external lab/partner/upstream/hardware access.
- **`CONDITIONAL`** — intended but dependent on validation/access/upstream/hardware/proof. Droppable without blocking core releases.
- **`FUTURE`** — named direction, not scheduled this window.

In §5, every deliverable is `COMMITTED` unless tagged.

### Baseline (already in-tree, reframed not greenfield)

Scenario Simulator V2 (#78), CARLA 0.9.16 (#73), arm64 + Jazzy builds, digest-based promotion, `autoware-lock.repos`, Trivy scans, AutoSD Quadlet/systemd profile. Remaining work is CI gating, validation evidence, and contracts.

> **Versioning lineage.** `v2.x` continues earlier Open AD Kit releases published outside this repo's tag history. This repo has no Git tags, so v2.0.0 is the first cut here; "first trustworthy" means first with the full evidence surface, not first ever.

**Directional goals** (not release-gated, tracked offline): ≥1 OEM evaluation by v3.0; ≥2 maintainers from ≥2 orgs; quarterly contributor pulse (<7d first response); blueprint/flavor + partner-showcase count. Baselines set at the v2.0 cut, reported in release notes.

---

## 2. Scope and Positioning

**Opinionated spine, swappable edges.** Open AD Kit is not a neutral toolkit — the substrate (plain Autoware + Docker + bring-your-own-orchestrator) already exists, and that assembly problem is exactly what this project removes. Its value *is* the opinion: a pinned, validated, evidence-backed golden path. The spine is fixed; flexibility lives only at documented contract boundaries, where it stays cheap to validate.

| Layer | Commitment |
| :--- | :--- |
| **Spine** (load-bearing) | Containerized modular Autoware on ROS 2; compatibility sets + lockfile; golden-path-first validation; evidence-gated releases; Docker Compose as default runtime; SOAFEE alignment. |
| **Edges** (swappable behind a contract + validation evidence) | Orchestrator (Compose → Podman/systemd → BlueChi → Ankaios); communication (DDS default, Zenoh bridge, `rmw_zenoh` eval); platform (x86_64, arm64-generic, GPU, target silicon, virtual labs); ROS distro (Humble → Jazzy); workloads beyond the golden path. |

| Topic | Position |
| :--- | :--- |
| What it is | Modular deployment, release, validation, and SDV-integration reference for Autoware and adjacent AWF workloads. |
| v2.0 | First trustworthy *release surface* — pinned images, metadata, scans, bundles, docs, compose validation, CARLA 0.9.16. Not the full compatibility-set product. |
| v2.1+ | Releases are **compatibility sets**: lockfile, manifests, validation commands, evidence, limitations, supported-platform matrix. |
| Non-goals | Source-built Autoware dev · easiest first demo · certified safety stack · S-Core module · Kubernetes *in-vehicle runtime* / SOAFEE runtime / OTA vendor · package-per-container decomposition. |
| Safety/claim boundary | **No** ISO 26262, ISO/SAE 21434, ASPICE, S-Core-conformance, production-readiness, or safety-certified-orchestration claims. |

---

## 3. Operating Model

### Principles

| Principle | Rule |
| :--- | :--- |
| One golden path first | Release spine = modular Autoware planning/scenario simulation. CI-runnable, no sensors or GPU needed for the core gate. |
| Trust before framework | v2.0 proves the public release surface. Lockfile, manifests, contracts, and CLI start in v2.1. |
| Compatibility sets from v2.1 | A v2.1+ release is a deployable compatibility set, not just a repo tag. |
| Evidence over claims | Releases publish metadata, digests, validation commands, logs, readiness/test output, scenario results, limitations, trust artifacts. |
| Demos ship from releases | Public demos, including CES, are built from release artifacts — never ad-hoc branches. |
| Native runtimes stay native | Open AD Kit plans, renders, validates, collects evidence. Execution stays with the runtime (Compose, Podman/systemd, BlueChi, Ankaios, partner OTA). |

### Pins and naming

| Decision | Resolution |
| :--- | :--- |
| Canonical repo | `autowarefoundation/openadkit`; roadmap at `roadmap.md`; issue #91 mirrors it. |
| Autoware pin | v2.0 pins **Autoware 1.8.0**. Later releases pin the latest stable meta-release at cut; if it has blocking changes, pin the previous verified version + a dated upgrade-blocker note. |
| Image division | Upstream owns base/devel images; Open AD Kit owns component images, bundles, runtime contracts, compatibility sets, validation evidence, trust artifacts. |
| First validation gate | Scenario Simulator V2 from v2.2. CARLA is a v2.0 sample + secondary lane, not the core gate. |
| CARLA | 0.9.16 committed for v2.0. `carla-interface` stays Humble/amd64 until upstream migration allows more. |
| Jazzy + arm64 | Jazzy-primary + arm64-generic committed for v2.1; Humble stays supported for CARLA during the transition. |
| ROS distro | v2.0: Humble default (quickstart, CARLA), Jazzy in parallel. Humble freeze Jan 2027; final set/EOL with v3.0. |
| Flagship demo | VisionPilot + Safety Island + CARLA at CES 2027 — committed event, not a gate. v3.0 may promote as showcase only if public contracts exist by v2.4. |
| OTA baseline | Registry-digest compatibility-set update/rollback. eSync stays a conditional showcase transport, never blocks core. |

### SDV orchestrator

**BlueChi/systemd is the single first profile** (aligned with AutoSD Quadlet/systemd assets). **Ankaios is deferred** to a v3.0 alternative track, not shipped alongside BlueChi. Open AD Kit plans/validates; the runtime executes.

### Kubernetes posture

**Not an in-vehicle orchestrator** — rejected at the safety-critical edge (footprint, nondeterministic scheduling, no TSN, not ISO 26262-certifiable). K8s/K3s never joins that track. Two bounded exceptions:

1. **K8s manifest as portability contract** — not a runtime. `render` targets only the `podman kube play` subset the SDV runtimes actually consume: BlueChi via a Quadlet `.kube` unit, Ankaios via its `podman-kube` runtime. If `render` ever emits Pod YAML, *that subset* is the honest target, not conformance to the Kubernetes control-plane API.
2. **Full Kubernetes / K3s as `CONDITIONAL`** — scoped to cloud / CI / fleet / non-safety tier only (develop-in-cloud on Graviton, SIL/batch test, OTA distribution). Never the vehicle runtime.

### S-Core posture

**Process spine now, substrate later.**

- **Now:** zero-regret patterns only — static-analysis/lint CI (v2.1), contract traceability as docs-as-code (v2.2).
- **Later:** S-Core gap analysis vs released v1.0 (v2.4), reference-workload attempt (v3.0).
- **Out of scope until gated:** substrate use, until S-Core ships FMEA/DFA, tool qualification, and drops "not for production." **KUKSA** is the conditional VSS/fault layer. **Muto is out of scope** this window.
- **"S-Core compatible" means** clean contracts that can later map to S-Core concepts + adopting its traceability/coding-standard patterns. It does *not* mean replacing ROS 2 with S-Core APIs, adopting S-Core as today's runtime, or claiming certification.
- **Don't:** port to S-Core `ara::com`; run QM Autoware on an S-Core ASIL floor; equate "S-Core compatible" with certification; treat KUKSA/Muto/OpenSOVD/Ankaios/BlueChi as parts of S-Core (they're SDV siblings); integrate every SDV project at once.

**First-blueprint DoD:** reproducible from documented commands; no fixed `sleep`s for core readiness (service/container state visible through the orchestrator); ROS 2 graph readiness checked by observable signals (not just process start); failure/restart behavior documented; the doc states plainly what's experimental and that nothing is safety-certified. This is the acceptance criterion the first SDV blueprint submission must meet.

### Simulation orchestration

Scenario sweep is a **workload, not a CLI job.** `scenario_test_runner` (Scenario Simulator V2, in-tree) iterates scenarios against the running stack and emits JUnit; the native runtime launches it; the CLI only renders the suite and reads results (`readiness`, `collect-evidence`).

A thin **CI-agnostic conductor** (Make/script entrypoint; CI is a swappable trigger) sequences a run and, for split deployments, the two sides.

**Fan-out is two-level:**

- Intra-workload — SS2 runs a scenario list.
- Inter-job parallel — conductor launches more runtime instances.

**Guardrail:** the CLI never gains a verb that starts or sequences workloads.

**Baseline:** `scenario_test_runner` + entrypoint, triggered by GitHub Actions. Escalation to managed batch → cloud-scale queue is `CONDITIONAL`, only when CPU-CI headroom is exhausted.

### Cloud-to-edge closed loop

The committed v3.0 closed loop stays **single-host**. A split run — cloud simulator + edge Autoware bridged by **Zenoh** (the go-to cloud↔edge transport) — is `CONDITIONAL` this window and proves *functional* parity, not hard-real-time control.

**Load-bearing risk:** `scenario_test_runner` readiness/commands resolving across the Zenoh bridge. The v2.4 split-ready sample is the prerequisite.

---

## 4. Artifact and Evidence Model

| Artifact | Required content |
| :--- | :--- |
| v2.0 release surface | Version, Autoware pin, image inventory, tags/digests, release + scan metadata, Autoware lock artifact, deployment bundles, clean-host commands, support matrix, release notes, known limitations. |
| v2.1+ compatibility set | All v2.0 artifacts + Autoware meta-release, ROS distro, architecture, CUDA variant, model artifacts, maps/data refs, component + deployment manifests, validation commands, evidence, supported-platform matrix. |
| Component contract | Name, image, launch/entrypoint, env, volumes, devices, capabilities/privileges, network/IPC, ROS domain/RMW, ROS-graph or non-ROS liveness, readiness, restart/shutdown, logs/evidence paths, criticality, model-artifact deps. |
| Deployment manifest | Components, profile bindings, startup deps, runtime parameters, data mounts, networking, readiness gates, validation commands, evidence outputs. |
| Runtime artifacts | Compose bundles first. Podman/AutoSD → Quadlet/systemd. BlueChi (v2.4) → systemd/BlueChi service mapping + gap list. Ankaios (deferred, v3.0) → workload manifests + gap list. |
| Trust evidence | v2.0: metadata, scans, digests. v2.3: SBOM, provenance, cosign keyless signing, vulnerability policy, scan baseline, static evidence dashboard. |
| Observability evidence | Logs, readiness timeline, ROS-graph checks, topic freshness, scenario pass/fail, MCAP (where appropriate), metrics snapshot, restart/update/rollback result, limitations. Eclipse Lichtblick = standard MCAP review tool. |

### CLI

Plans, renders, validates, observes — **never executes the workload** (no `up`/`deploy`). Runtime owns lifecycle; the CLI only *reads* a running stack (status, ROS graph, logs, freshness) and emits the next command. Deterministic — same lock + args → same output — so every verb is CI-gateable.

- **Adapters:** `render` (compose → quadlet → bluechi → ankaios), `observe` (docker/podman/bluechi).
- **Conventions:** exit codes are contracts; human output + `--format json`; every failure carries remediation; read-only by default (only `plan-update` computes).
- **Distribution:** typed Python package (pipx) + `openadkit/cli` image.
- **Verbs:** v2.1: `validate`, `preflight`, `render`, `collect-evidence`. v2.2: `readiness`. v2.5: `plan-update`, `verify-rollback`.
- **Execution stays outside the CLI** — a thin conductor (Make/script; CI as swappable trigger) sequences workloads and cross-boundary runs.

---

## 5. Release Plan

Each release closes with a **Done when** checklist — the CI gate. Bullets are deliverables (`COMMITTED` unless tagged).

### v2.0.0 — First Trustworthy Release · Jul 2026

**Deliverables:**

- Canonical docs site: roadmap, versioning/support policy, release flow, image tags, bundle instructions, #91 mirror.
- Governance docs: `CONTRIBUTING.md`, `SUPPORT.md`, `SECURITY.md`, release process.
- Autoware 1.8.0 pinned image set: inventory, tags/digests, release + scan metadata, Autoware lock artifact.
- Deployment bundles for documented samples/demos, including CARLA 0.9.16 (validation + limitations).
- Clean-host quickstart on Ubuntu 22.04 / ROS 2 Humble; Ubuntu 24.04 a committed host profile.
- Docker Compose config validation for documented stacks; build matrix green for committed variants.
- Known trust-breakers fixed or documented: GPU compose validation, Zenoh fixed-sleep race, AutoSD `ROS_DOMAIN_ID` behavior.

**Done when:**

- [ ] Docs site builds; every listed page exists and renders.
- [ ] All four governance docs present and linked from README.
- [ ] Image inventory lists every shipped image with tag + digest.
- [ ] Scan metadata attached for each image.
- [ ] `autoware-lock.repos` artifact present and validated.
- [ ] CARLA 0.9.16 deployment bundle has published validation output + known limitations doc.
- [ ] Quickstart runs end-to-end on a clean Ubuntu 22.04 *and* 24.04 host.
- [ ] `docker compose config` passes for every documented stack.
- [ ] Build matrix green for every committed variant.

**Deferred:** lockfile, manifests, CLI, SBOM/signing, BlueChi (v2.4), Ankaios (v3.0), S-Core, OpenSOVD, VisionPilot, OTA flows.

### v2.1.0 — Compatibility-Set MVP · Sep 2026

**Deliverables:**

- Compatibility lockfile pins Open AD Kit version, Autoware ref, ROS distro, image tags/digests, deployment bundle, validation commands, reserved model-artifact fields (full schema → v2.2).
- VisionPilot dependency sourcing begins: model/image artifacts tracked as a committed dependency (dated blocker list if upstream access blocks).
- Golden-path component manifest (launch, env, volumes, network/IPC, basic readiness, evidence paths) + deployment manifest.
- Small CLI — `validate`, `preflight`, `render`, `collect-evidence` — with deterministic evidence-bundle layout. Preflight checks Docker, arch, disk, ports, data paths, image availability, `ROS_DOMAIN_ID`, each with remediation.
- Upstream / Open AD Kit division-of-labor doc.
- S-Core zero-regret patterns (phase 1): static-analysis/lint + type-check CI for tooling and CLI. *No ISO 26262 claim.*
- Jazzy-primary + arm64-generic release path: images already build both; v2.1 commits the validated arm64 quickstart and flips the default ROS-distro alias to Jazzy.

**Done when:**

- [ ] Lockfile schema published; one example lockfile present in the release artifacts.
- [ ] `openadkit validate --lockfile <path>` exits 0 in release CI.
- [ ] Component + deployment manifests render to valid Compose via `openadkit render`.
- [ ] `preflight` on a known-failure scenario produces actionable remediation text.
- [ ] `collect-evidence` produces a byte-stable bundle (identical on two runs).
- [ ] arm64 quickstart validated on a clean host.
- [ ] Default ROS-distro alias flipped to Jazzy; Humble alias still works.
- [ ] Release notes carry compatibility-set artifact, limitations, and no unfounded safety/certification claims.

### v2.2.0 — Readiness and Test Gating · Oct 2026

**Deliverables:**

- Scenario Simulator V2 golden-path harness (in-tree, #78): version-pinned CI gate + published evidence.
- Sim-orchestration baseline: `scenario_test_runner` driven by a CI-agnostic conductor (Make/script; GitHub Actions only triggers), JUnit-gated. CLI renders the suite + collects evidence; it does not run scenarios.
- Readiness tiers: process/container health → ROS graph → topic freshness → scenario semantic check; exposed via `openadkit readiness`. One validated restart path.
- AutoSD single-node readiness spike: golden path on existing Quadlet/systemd profile with health-based readiness replacing fixed sleeps (highest-ROI first SDV step; full AutoSD profile stays v2.4).
- MCAP / readiness timeline / scenario result / metrics snapshot where appropriate; Lichtblick review workflow.
- Golden Path Contract + Reference Architecture page.
- VisionPilot Tier 1.5 contract with non-ROS readiness (process → pipeline/stream liveness → data freshness → semantic check) + model-artifact schema populating v2.1 reserved lockfile fields.
- S-Core patterns (phase 2): requirements/contract traceability as docs-as-code. *No ISO 26262 claim.*
- x86_64 VisionPilot build/smoke gate begins; CUDA/GPU proof job begins (becomes v2.3 trust gate).
- `rmw_zenoh` evaluation starts; DDS over host networking stays default. `(CONDITIONAL)`

**Done when:**

- [ ] Golden Path Contract published.
- [ ] CI runs the full committed scenario suite on a clean host (all pass) and publishes JUnit + readiness timeline evidence.
- [ ] `openadkit readiness` returns all four tiers.
- [ ] One restart path executed end-to-end with published evidence.
- [ ] AutoSD single-node readiness spike green (health-based; no fixed sleeps).
- [ ] VisionPilot manifest + x86_64 smoke gate live (dated blocker list only if an upstream artifact blocks).
- [ ] Reference Architecture page published.

### v2.3.0 — Release Trust · Nov 2026

**Deliverables:**

- Complete image inventory for golden-path + VisionPilot images.
- SBOM, provenance attestation, cosign keyless signing, signature bundle.
- Vulnerability policy: scan baseline, severity thresholds, waiver/exception process, known exceptions.
- Immutable release tags / digest-as-source-of-truth policy (digest promotion already enforced; v2.3 documents and formalizes it).
- GPU functional smoke gate for relevant images; source overlay workflow documented and validated.
- Static evidence dashboard linking release metadata, scans, SBOMs, signatures, scenario results, limitations, known blockers (an artifact index, not a hosted product).
- CARLA demo bundle with pinned scenario subset + limitations.

**Done when:**

- [ ] SBOM, provenance, and cosign signature present and verified for every golden-path + VisionPilot image.
- [ ] Vulnerability policy doc published with current scan baseline.
- [ ] GPU smoke gate green for all relevant images.
- [ ] Static evidence dashboard renders and every link resolves.
- [ ] CARLA demo bundle publishes pinned scenario subset + limitations doc.
- [ ] Post-release: SDV blueprint submission started on v2.3 artifacts; CES freeze begins.

### CES 2027 — Flagship Event · Jan 6–9, 2027

Committed public event, **not a release gate.** Demo: **VisionPilot + Safety Island + CARLA.**

**Deliverables:**

- VisionPilot + CARLA legs from v2.3 release artifacts.
- Safety Island + MCUboot firmware-OTA legs are in-progress v2.4 previews — descopable, not v2.3 artifacts.
- Safety Island on FVP/virtual CAN (committed); AVH/Corellium or physical S32Z/S32Z2 are upgrades if access exists. CARLA Humble-lane pinned scenario subset.
- Scripted one-component registry-digest update/rollback preview (VisionPilot image/model): throwaway preview ahead of v2.5; no v2.5 state machine, no reproducible release claim.
- MCUboot firmware-OTA prototype (signed update, rollback, safe-state on FVP): conditional leg, does not block core releases.

**Done when:**

- [ ] Demo assembly built from v2.3 release artifacts — no ad-hoc branches.
- [ ] Safety Island demo runs on FVP or virtual CAN.
- [ ] Demo script published, rehearsed, and archived post-event.
- [ ] Descope rule honored on any missed preconditions (no main fork, no unreproducible release claim).

### v2.4.0 — Platform Profiles + Ecosystem · Late Jan–Feb 2027

**Deliverables:**

- AutoSD/Podman Quadlet/systemd artifacts (validation evidence or dated blocker list) + Podman contract: rootful/rootless, cgroups, host networking, IPC, devices, systemd lifecycle, evidence collection.
- BlueChi/systemd mapping as the single first SDV orchestrator profile (aligned with AutoSD assets): validation evidence or gap list. Ankaios *not* shipped — deferred to v3.0 alternative track.
- Zenoh bridge modular component images with readiness checks, no fixed sleeps.
- One **split-ready sample**: decoupled cloud/edge compose (no shared `pid`/`ipc`/host-networking), Zenoh bridging the halves — prerequisite for cloud-to-edge. Committed; the cloud-to-edge closed-loop *run* itself is `CONDITIONAL`.
- SOAFEE: Arm Automotive Solutions / RD-1 AE FVP validation path; Integration Lab validation committed (lab/access blockers published if it can't complete).
- S-Core gap analysis vs released v1.0 (or latest shipped), mapping runtime contracts to lifecycle/health/logging/communication gaps. *No conformance, module, or endorsement claim.*
- KUKSA read-only spike: 3–5 selected VSS signals via databroker; OpenSOVD read-only health/fault exposure. Scope-limited; full bidirectional integration lands at v3.0.
- Safety Island classic-CAN contract evidence (CAN-FD stays conditional, undated) + E2E boundary-contract spec published (QM doer / ASIL checker boundary: command interface, E2E + freshness, allowed envelope, MRM triggers, fault-ID set; numbers per-vehicle/ODD). *No ASIL claim; SOTIF out of scope.*
- Evaluating Open AD Kit guide + partner integration guides where owners/access exist. `(CONDITIONAL)`
- SDV blueprint proposal submitted on v2.3 artifacts; blueprint refresh committed for v3.0.

**Done when:**

- [ ] All five gate artifacts published: platform-profile evidence (AutoSD/Podman, Zenoh, classic-CAN), BlueChi profile, S-Core gap analysis, Safety Island E2E spec, SOAFEE validation attempt or blocker list.
- [ ] Split-ready sample deploys from documented commands; Zenoh bridges halves.
- [ ] Evaluation guide `CONDITIONAL`; does not gate.

### v2.5.0 — Update/Rollback Beta · Mar 2027

**Deliverables:**

- Update state machine: staged apply, health-gated promotion, rollback trigger, timeout, cleanup, failure states.
- CLI: `openadkit plan-update`, `openadkit verify-rollback`; registry-digest compatibility-set transition.
- Golden-path non-stateful component update + verified rollback; failure injection that triggers rollback.
- VisionPilot image + model update/rollback using model artifacts as lockfile members.
- Rollback evidence: pre-update state, staged update, health result, rollback action, final known-good state.
- Cloud-edge AWS/AVH/FVP path where owner/access exists; otherwise blocker list. `(CONDITIONAL)`

**Done when:**

- [ ] State machine spec published (states, transitions, timeouts).
- [ ] CI runs `update v2.4 → v2.5` then `rollback`; both exit 0 with evidence bundle.
- [ ] VisionPilot image/model update + rollback works and publishes evidence (committed; upstream block → dated blocker list).
- [ ] Failed update triggers verified rollback; rollback evidence bundle published.
- [ ] Native runtimes execute the update; Open AD Kit plans/verifies.

**Deferred:** multi-component transactions, stateful migration, eSync dependency, production OTA claims.

### v3.0.0 — Closed-Loop Release · May 2027

**Deliverables:**

**Two-phase hard gate:** (1) CI runs the full closed loop end-to-end and passes; (2) release artifacts consumed on a clean host, via documented commands, complete the same loop.

Closed-loop evidence: **build** (pinned refs, SBOM, provenance, signatures, digests) → **deploy** (lockfile + deployment manifest) → **test** (Scenario Simulator V2 pass/fail on the pinned set) → **observe** (logs, MCAP, metrics, readiness history, event markers) → **update** (one component, compatibility-set transition) → **rollback** (previous known-good) → **report** (links all evidence + limitations).

**Done when:**

- [ ] Phase 1: CI runs the full closed loop end-to-end; all phases pass.
- [ ] Phase 2: A consumer on a clean Ubuntu 22.04 *and* 24.04 host follows documented commands and completes the same loop.
- [ ] Closed-loop evidence bundle published and linked from release notes.
- [ ] Jazzy-primary set promoted; final Humble set EOL announced.
- [ ] Full bidirectional KUKSA VSS integration; OpenSOVD diagnostics integrated.
- [ ] S-Core reference-workload validation: evidence or dated blocker list (precondition: S-Core ships FMEA/DFA, tool qualification, drops "not for production").
- [ ] Benchmarks published for x86_64 + arm64-generic.
- [ ] SDV blueprint evidence refresh published.

**`CONDITIONAL` for v3.0** (do not gate): Jetson Orin benchmarks; determinism/CPU-pinning evaluation (no real-time or certification claim); Ankaios alternative-track evaluation; cloud-to-edge closed-loop attempt on v2.4 split-ready sample (functional parity only); foundation-model workload sample with versioned weights via model-artifact lockfile.

**`FUTURE`:** post-v3.0 integration map (directional only). Muto re-evaluation also lands here.
