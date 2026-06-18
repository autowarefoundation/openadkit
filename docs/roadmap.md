# Open AD Kit 2026-2027 Roadmap

Date: 2026-06-18

Window: June 2026 - May 2027

This page is the public roadmap; GitHub issue #91 mirrors it. It summarizes the
staged release ladder. Per-release gates, the artifact/evidence model, and the
full risk register live in the working roadmap.

---

## 1. North Star

By mid-2027, Open AD Kit should let users take a pinned modular Autoware deployment, deploy it from documented commands, validate it in simulation, observe it through standard evidence artifacts, update one component, and roll back reproducibly to a previous known-good set.

Open AD Kit is the **modular deployment and validation layer for Autoware**.

It turns Autoware into a reproducible, evidence-backed workload for software-defined-vehicle development and integration.

---

## 2. Positioning

| Topic | Position |
| :--- | :--- |
| What it is | Modular deployment, release, validation, and SDV-integration reference for Autoware. |
| v2.0 | First trustworthy release surface: pinned images, metadata, scans, bundles, docs, compose validation, CARLA 0.9.16. |
| v2.1+ | Compatibility sets: lockfile, manifests, validation commands, evidence, limitations, platform matrix. |
| Not claiming | Safety certification, production readiness, ISO 26262, ISO/SAE 21434, ASPICE, S-Core conformance, an Eclipse S-Core module, or OTA-vendor status. |

Platform docs may use supplier terms such as real-time, mixed criticality, safety island, and safety-qualified hardware. Open AD Kit itself makes no certification or production-readiness claim.

---

## 3. Release Ladder

| Release | Target | Theme | Outcome |
| :--- | :--- | :--- | :--- |
| v2.0.0 | July 2026 | First trustworthy release | Users can trust the public release surface. |
| v2.1.0 | September 2026 | Compatibility-set MVP | Open AD Kit can describe a known-good deployment. |
| v2.2.0 | October 2026 | Readiness and test gating | Open AD Kit can prove the deployment is alive and working. |
| v2.3.0 | November 2026 | Release trust | Users can trust supply-chain and release evidence. |
| CES 2027 | Jan 6-9, 2027 | Flagship event | VisionPilot + Safety Island + CARLA demo from release artifacts. |
| v2.4.0 | Late Jan-Feb 2027 | Platform profiles | AutoSD/BlueChi runtime profile, SDV ecosystem evidence, Safety Island E2E contract. |
| v2.5.0 | March 2027 | Update/rollback beta | Golden-path component and VisionPilot image/model can update and roll back. |
| v3.0.0 | May 2027 | Closed-loop release | Golden path completes build, deploy, test, observe, update, rollback. |

Several v2.0-v2.4 items already exist in-tree (Scenario Simulator V2 integration, the CARLA 0.9.16 sample, arm64 + Jazzy image builds, digest-based promotion, the Autoware lock artifact, scan metadata, and the AutoSD Quadlet/systemd profile). For those, the remaining work is CI gating, validation evidence, and contracts, not initial implementation.

---

## 4. Release Details

### v2.0.0 - First Trustworthy Release

Target: July 2026.

Committed scope:

- Autoware 1.8.0 pinned image set.
- Image inventory, tags/digests, release metadata, scan metadata, Autoware lock artifact.
- Deployment bundle assets for documented samples/demos.
- CARLA 0.9.16 sample with validation output and known limitations.
- Clean-host quickstart on Ubuntu 22.04 / ROS 2 Humble.
- Ubuntu 24.04 documented as committed host profile.
- Docker Compose config validation for documented stacks.
- Minimal governance docs: `CONTRIBUTING.md`, `SUPPORT.md`, `SECURITY.md`, release process, support policy.
- `docs/roadmap.md` and issue #91 as public roadmap surfaces.

Deferred from v2.0: lockfile, manifests, CLI, SBOM/signing, BlueChi mapping (v2.4) and Ankaios (v3.0), S-Core validation, OpenSOVD, VisionPilot gating, OTA/update flows.

### v2.1.0 - Compatibility-Set MVP

Target: September 2026.

Committed scope:

- Compatibility lockfile.
- Component and deployment manifests for the golden path.
- Small CLI: `validate`, `preflight`, `render`, `collect-evidence`.
- Preflight checks with actionable remediation.
- Deterministic evidence bundle layout.
- Model-artifact schema supporting VisionPilot entries.
- S-Core "zero-regret" process patterns (subset): static-analysis/lint CI for Open AD Kit tooling and the CLI, plus requirements/contract traceability as docs-as-code. No ISO 26262 conformance claim.
- Jazzy-primary and arm64-generic committed release path (images already build for both; v2.1 commits the validated arm64 quickstart and flips the published default alias to Jazzy).
- Upstream/Open AD Kit division-of-labor document.

### v2.2.0 - Readiness and Test Gating

Target: October 2026.

Committed scope:

- Scenario Simulator V2 golden-path gate (harness already integrated; v2.2 adds the version-pinned CI gate and evidence).
- Readiness tiers: process/container health, ROS graph, topic freshness, scenario semantic check.
- `openadkit readiness` command.
- One validated restart path.
- AutoSD single-node readiness spike: golden path on AutoSD (existing Quadlet/systemd profile) with health-based readiness replacing fixed sleeps. Highest-ROI first SDV-integration step; full validated profile remains v2.4.
- Golden Path Contract and Reference Architecture page.
- VisionPilot Tier 1.5 component contract and x86_64 build/smoke gate.
- CUDA/GPU proof job starts.
- `rmw_zenoh` evaluation starts; DDS over host networking remains default.

### v2.3.0 - Release Trust

Target: November 2026.

Committed scope:

- SBOM, provenance attestation, cosign keyless signing, signature bundle.
- Vulnerability policy with scan baseline and exception process.
- Immutable release tags or digest-as-source-of-truth policy (digest promotion already enforced; v2.3 formalizes the policy).
- GPU functional smoke gate.
- Source overlay workflow.
- Static evidence dashboard linking metadata, scans, SBOMs, signatures, scenario results, limitations, and blockers.
- CARLA demo bundle with pinned scenario subset and limitations.

### CES 2027 - Flagship Event

Target: January 6-9, 2027.

CES is a committed public event milestone, not a release gate.

Target demo:

- VisionPilot + Safety Island + CARLA assembled from v2.3 release artifacts.
- Safety Island on FVP/virtual CAN as committed validation path.
- AVH/Corellium or physical S32Z/S32Z2 as conditional upgrades.
- CARLA Humble-lane pinned scenario subset.
- Scripted VisionPilot registry-digest update/rollback preview (throwaway, built ahead of the v2.5 beta; creates no reproducible release claim).
- MCUboot signed firmware OTA prototype as conditional demo leg.

Descope rule: missed preconditions descope that demo leg; the demo never forks from main; v3.0 flagship showcase claim requires public contracts by v2.4.

### v2.4.0 - Platform Profiles and Ecosystem Evidence

Target: late January-February 2027.

Committed or committed-effort scope:

- AutoSD/Podman Quadlet/systemd artifacts and Podman contract.
- BlueChi/systemd as the single first SDV orchestrator profile (aligns with the existing AutoSD Quadlet/systemd assets). Ankaios is deferred to v3.0 as the alternative/advanced track — one orchestrator per first profile.
- Zenoh modular component images with readiness checks and no fixed sleeps.
- SOAFEE validation path on Arm Automotive Solutions / RD-1 AE FVP.
- S-Core gap analysis against released v1.0 or latest shipped version (latest shipped is the v0.6.0 beta milestone as of mid-2026).
- Safety Island classic-CAN contract evidence.
- Safety Island E2E boundary-contract spec as an explicit artifact: command interface (acceleration, steering, mode + timestamp, sequence, DataID, CRC), E2E + freshness, allowed envelope, MRM triggers, and a read-only fault-ID set. No ASIL claim; SOTIF insufficiency is out of scope.
- Evaluating Open AD Kit guide and partner integration docs.

External scheduling or access blockers are acceptable if published as dated blocker lists.

### v2.5.0 - Update/Rollback Beta

Target: March 2027.

Committed scope:

- Update state machine: staged apply, health-gated promotion, rollback trigger, timeout, cleanup, failure states.
- CLI: `openadkit plan-update`, `openadkit verify-rollback`.
- Registry-digest compatibility-set transition.
- Golden-path non-stateful component update and verified rollback (primary closed-loop gate).
- VisionPilot image + model update/rollback using lockfile model artifacts (committed deliverable; dated blocker list only if an upstream artifact dependency blocks).
- Failure injection that triggers rollback.
- Rollback evidence bundle.

Deferred: multi-component transactions, stateful migration, eSync transport dependency, production OTA claims.

### v3.0.0 - Closed-Loop Release

Target: May 2027.

Hard gate: golden-path build -> deploy -> test -> observe -> update -> rollback.

Evidence must show:

- Build uses pinned images/source refs, SBOM, provenance, signatures, and digests.
- Deploy uses compatibility lockfile and deployment manifest via documented commands.
- Test uses Scenario Simulator V2 scenario harness.
- Observe includes logs, metrics, readiness history, event markers, and MCAP where appropriate.
- Update changes one component by compatibility-set transition.
- Rollback returns to previous known-good state.

Also ships: benchmarks, Jazzy-primary set, final Humble set EOL, S-Core reference workload evidence/blocker list (gated on S-Core maturity: FMEA/DFA, tool qualification, and dropping "not for production"), OpenSOVD + KUKSA spike (read-only fault-model exposure), Ankaios alternative-track evaluation, conditional foundation-model workload sample, and future integration map.

---

## 5. Technical Tracks

| Track | Commitment |
| :--- | :--- |
| Golden path | Tier 1 release spine and v3.0 closed-loop gate. |
| VisionPilot | Tier 1.5 `COMMITTED` workload; committed v2.5 image/model update/rollback proof; sequenced from v2.2 (contract/smoke) onward. |
| Safety Island | CES event integration on FVP/virtual CAN; E2E boundary contract (QM doer / independent ASIL checker) published v2.4; firmware OTA conditional demo leg. |
| CARLA | v2.0 committed sample; showcase/secondary validation lane (Humble/amd64). |
| ROS | v2.0 Humble default; Jazzy-primary and arm64-generic committed by v2.1; final Humble set at v3.0. |
| OTA | Registry-digest update/rollback baseline; eSync conditional showcase transport. |
| Communication | DDS over host networking default; Zenoh bridge committed cloud-edge profile; `rmw_zenoh` evaluated. |
| SDV ecosystem / S-Core | AutoSD + one orchestrator (BlueChi) first, then Zenoh, then KUKSA/OpenSOVD. S-Core: process spine now (static-analysis CI, docs-as-code traceability), substrate later. Muto out of scope this window. |
| Platforms | Ubuntu 22.04/24.04 + Docker Compose committed; AutoSD, BlueChi (first profile), Ankaios (deferred to v3.0), RD-1 AE FVP, AVH/Corellium, Jetson Orin conditional by evidence/access. |

---

## 6. Slide Message

Open AD Kit 2026-2027 moves from **trusted release surface** to **compatibility-set deployment model** to **evidence-backed closed loop**.
`v2.0 trust` -> `v2.1 compatibility set` -> `v2.2 readiness` -> `v2.3 release trust` -> `v2.5 update/rollback` -> `v3.0 closed loop`.
