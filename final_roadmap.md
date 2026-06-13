# Open AD Kit 2026–2027 Roadmap

Date: 2026-06-12

Window: June 2026 – May 2027

Status: Final — locked by chair decisions of 2026-06-12 (supersedes the 2026-06-10 roadmap and the 2026-06-11 draft; disposition of prior locked decisions in Appendix A)

---

## 1. North Star

By mid-2027, Open AD Kit lets a user take a pinned modular Autoware compatibility set, deploy it from documented commands, validate it in simulation, observe it through standard evidence artifacts, update one component, and roll back reproducibly to a previous known-good compatibility set — in a non-certified validation environment, with proof attached to the release.

And it does this as a visible citizen of the SDV ecosystem: submitted to Eclipse SDV Blueprints, gap-analyzed against Eclipse S-Core v1.0, validated through the SOAFEE Integration Lab, and premiered at CES 2027 from release artifacts.

> Open AD Kit is the modular deployment, release, validation, and SDV-integration reference for Autoware.

---

## 2. Project Identity

### 2.1 What Open AD Kit Is

The trustworthy modular deployment reference and compatibility-set reference for Autoware and AWF sibling stacks. It wins where deployment reality matters: pinned compatibility sets, modular component images, runtime contracts, deployment profiles, runtime-native artifacts, readiness and restart behavior, release evidence, observability artifacts, update and rollback flows, platform mappings for SDV runtimes, and the working blueprint OEMs use to evaluate all of it.

### 2.2 What Open AD Kit Is Not

- A replacement for source-built Autoware development.
- The easiest first Autoware demo path (use monolithic images).
- A certified safety stack.
- An Eclipse S-Core module.
- A Kubernetes, SOAFEE-runtime, or OTA-vendor product.
- A package-per-container decomposition experiment.

### 2.3 Public Positioning

> Open AD Kit turns Autoware into a modular, reproducible, evidence-backed deployment workload for software-defined-vehicle development and integration.

Short version: **the modular deployment and validation layer for Autoware.**

---

## 3. Strategic Principles

### 3.1 Compatibility Sets Over Loose Images

An Open AD Kit release is a deployable compatibility set, never merely a tag or a group of independently tagged images. Every release pins: Open AD Kit version, Autoware semver meta-release (latest stable at release cut), ROS distro, architecture, CUDA variant where relevant, image tags and digests, **model artifacts (name/version/digest, bound to image versions)**, deployment bundles, component and deployment manifests, runtime contracts, supported hardware/platform matrix, validation commands, and release evidence.

### 3.2 One Golden Path First

The release spine is **modular Autoware planning simulation** — Autoware-native, CI-runnable, no sensors or GPU required, exercising deployment, readiness, ROS graph behavior, maps, launch configuration, logs, and release evidence. Every platform mechanism proves itself on the golden path before anything harder.

### 3.3 Golden Path Contract

Each release gating on the golden path publishes a Golden Path Contract:

| Field | Requirement |
| :--- | :--- |
| Workload | Modular Autoware planning simulation. |
| Primary simulator | Scenario Simulator V2, **version pinned in the compatibility set** (upstream releases ~monthly). |
| Runtime profile | Docker Compose first; other profiles use rendered runtime-native artifacts. |
| Host profile | Clean documented host profile: architecture, OS, ROS distro, CPU/GPU expectation, disk, memory. |
| Inputs | Compatibility lockfile, image digests, deployment bundle, map/data paths, scenario set, model artifacts if any. |
| Commands | Exact preflight, render, native deploy, readiness, scenario execution, and evidence-collection commands. |
| Readiness thresholds | Required containers, ROS graph surface, topics/services/actions, freshness thresholds, timeout. |
| Scenario pass/fail | Scenario names, timeout, pass condition, explicit retry/flake policy (end-to-end runs are not bit-deterministic), failure classification. |
| Evidence bundle | Metadata, lockfile, rendered artifacts, image inventory, logs, readiness timeline, scenario result, MCAP where applicable, metrics snapshot, known limitations. |
| CI gate | Workflow/job name, artifact path, pass/fail threshold, waiver owner. |

### 3.4 Release Gate Format

Every gate is executable: command or CI workflow, expected artifact paths, pass/fail threshold, waiver owner with expiration, known limitations carried into release notes. A gate is not complete because a document exists.

### 3.5 Evidence Over Claims

Every meaningful milestone produces evidence: version metadata, image digests, runtime logs, readiness state, ROS graph checks, topic freshness, scenario pass/fail, MCAP where appropriate, metrics snapshot, release notes, known limitations.

### 3.6 Honest Platform Labels

`COMMITTED` (release-gated and maintained) · `EXPERIMENTAL` (validated or blocker list published) · `BEST-EFFORT` (useful, not release-blocking) · `PARTNER-GATED` (depends on partner access) · `COMMUNITY-GATED` (depends on an external community decision, e.g. a blueprint vote) · `FUTURE` (named, not scheduled) · `UNSUPPORTED` (explicitly out of scope).

### 3.7 No Overclaiming

No ISO 26262, ISO/SAE 21434, ASPICE, Eclipse S-Core conformance/module/endorsement, production-readiness, or safety-certified-orchestration claims. Safety language stays limited to architecture alignment, safety-island experiments, deployment hygiene, and validation evidence.

### 3.8 Demos Ship From Releases

Public demos and showcases (CES included) are built from release artifacts — never from ad-hoc branches. December 2026 is CES-freeze month: the demo is assembled and rehearsed from v2.3 artifacts, and no release ships that month. If v2.3 slips past November, the CES demo descopes to v2.2 artifacts rather than forking — dropping the legs that depend on v2.3 signing and GPU gating (§12).

### 3.9 Slip, Don't Split

A release slips whole rather than shipping with waived gates. Targets are re-baselined quarterly; the only immovable release date in the window is v2.0 in July 2026 (CES 2027 is externally fixed, but it is a milestone, not a release).

---

## 4. Hard Decisions

| Decision | Resolution |
| :--- | :--- |
| Canonical repo | `autowarefoundation/openadkit`. Older repos (pix-openadkit, open-ad-kit-docs) are historical. Issue #91 mirrors this roadmap. |
| Release unit | A compatibility set, not images or repo tags. |
| Autoware pin | Latest stable semver meta-release at release cut (v2.0 pins 1.8.0). |
| Upstream images | Division of labor formalized with upstream (doc by v2.1): upstream Autoware owns base/devel images; Open AD Kit owns component images, runtime contracts, compatibility sets. v2.0 tag coordinated with the in-flight base-image migration (#85/#92/#63). |
| First hard gate | Modular Autoware planning simulation (Scenario Simulator V2 primary). |
| VisionPilot | **Tier 1.5, named.** Full component contract + adapted non-ROS readiness; release-gated build/smoke from v2.2; trust artifacts from v2.3; v2.5 update showcase. Never blocks core releases: it ships inside a compatibility set only when its gates pass, and is otherwise excluded with a release-note entry. |
| Flagship demo | VisionPilot + Safety Island + CARLA is the **CES 2027 showcase (Jan 6–9), non-blocking**, built from v2.3 artifacts. Promoted to a v3.0 showcase only if public contracts exist by v2.4. |
| OTA baseline | Registry-digest compatibility-set update and rollback. eSync is a PARTNER-GATED showcase transport (no OSS implementation; spec v2.2; Arm charter member since Nov 2025). No release ever gates on eSync. |
| SI firmware OTA | Re-scoped **openadkit-side**: MCUboot-style signed update/rollback/safe-state prototype on the hardware-agnostic FVP container, target Oct–Dec 2026, EXPERIMENTAL, demoed at CES. SI upstream scopes OTA out — noted honestly. |
| Safety language | No certification or conformance claims anywhere. |
| Communication | ROS 2 DDS over host networking default. Zenoh bridge = cloud-edge profile. `rmw_zenoh` = time-boxed Q4 2026 experiment with documented go/no-go. |
| ROS strategy | **Green-matrix rule:** Jazzy becomes primary documented path at the first release with a green Jazzy amd64+arm64 matrix — target v2.1. A red matrix at v2.3 planning triggers a re-baseline review, never a forced promotion. Jazzy matrix health is a tracked hard dependency of v3.0 (Humble EOLs the same month). Humble lane retained for CARLA/flagship until `autoware_carla_interface` migrates; Humble freeze Jan 2027. |
| Platform scope | Ubuntu/Compose, AutoSD/Podman, x86_64, arm64, Jetson Orin. Ankaios first among SDV orchestrators, BlueChi second. Everything else experimental, partner-gated, or future. |
| Tooling model | Artifact-first, CLI-light. The CLI validates, preflights, renders, inspects readiness, plans updates, collects evidence; native runtimes deploy. |
| Ecosystem program | Dated commitments: SDV blueprint (Nov–Dec 2026, COMMUNITY-GATED), S-Core gap analysis (Jan–Feb 2027) + experiment (Apr 2027), SOAFEE Integration Lab validation (Jan–Feb 2027), OpenSOVD spike (Apr 2027), SOAFEE blueprint repo refresh (Dec 2026), partner guide refresh (with v2.4). |
| Roadmap style | Fewer promises, executable gates, release evidence, honest labels. Changes land as PRs. |

---

## 5. Goal Set

| Goal | Done When |
| :--- | :--- |
| G1: First trustworthy release | v2.0 ships in July: PR #90 merged, docs aligned, release bundle, pinned images (latest stable Autoware meta-release at cut — 1.8.0 today), release notes, support matrix, clean-host quickstart, versioning/support policy (closes #62). |
| G2: Compatibility-set MVP | v2.1 ships: lockfile (incl. model artifacts), component/deployment manifests, validate/preflight/render/collect-evidence, golden-path evidence collection, upstream division-of-labor doc. |
| G3: Evidence-backed golden path | v2.2 ships: Golden Path Contract published, scenario harness gates releases in CI, tiered readiness, restart evidence. |
| G4: Component contracts | Core containers + VisionPilot publish runtime contracts (launch, env, volumes, devices, network/IPC, readiness, restart, logs, evidence). VisionPilot uses adapted non-ROS tiers: process → pipeline/stream liveness → data freshness → semantic. |
| G5: Release trust | v2.3 ships: SBOM, provenance, signing, scan policy, immutable tags, published inventory for golden-path **and VisionPilot** images; GPU functional smoke gate; source overlay; dashboard MVP. |
| G6: SDV platform bridge | v2.4 ships: AutoSD/Podman validated or blocker list, Ankaios mapping first and BlueChi second (validated or blocker lists), Zenoh bridge modularized, Arm Automotive Solutions / RD-1 AE FVP target with SOAFEE Integration Lab validation or dated blocker list. |
| G7: Update and rollback | v2.5 proves one-component compatibility-set update/rollback (VisionPilot model+image as showcase); v3.0 runs the full closed loop with evidence. |
| G8: Flagship showcase | CES 2027 premiere (Jan 6–9) of VisionPilot + Safety Island + CARLA built from v2.3 artifacts, including scripted update/rollback preview and the MCUboot firmware prototype. Milestone, not a release gate. |
| G9: Ecosystem anchor | SDV blueprint submitted Nov–Dec 2026 on running v2.3 artifacts, with Ankaios/AutoSD extensions landing v2.4 (acceptance target Q1 2027); S-Core gap analysis + April experiment published; OpenSOVD spike result; SOAFEE blueprint repo refreshed. |
| G10: OEM blueprint package | Reference Architecture page (v2.2) and "Evaluating Open AD Kit" guide (v2.4) published; ≥1 external organization completes a documented evaluation by v3.0 (health metric, not gate). |
| G11: Upstream alignment | Division-of-labor doc published by v2.1; v2.0 coordinated with the base-image migration; joint review cadence with upstream maintainers. |
| G12: Community health, no overclaiming | Contribution docs, labels, support policy, release calendar, public board; ≥2 active maintainers from ≥2 orgs by v3.0 (health metric, not gate); docs never overclaim certification or maturity. |

---

## 6. Core Artifact Pillars

### 6.1 Compatibility Sets

A compatibility set answers: which Autoware meta-release, which Open AD Kit release, which ROS distro, which images and digests, **which model artifacts (name/version/digest)**, which maps/data, which deployment profiles, which hardware/platform profiles, which validation commands, what evidence proves it, and what is explicitly unsupported.

### 6.2 Runtime Contracts

Each component declares: name, image, root launch surface, entrypoint, env, volumes, devices, capabilities/privileges, network and IPC mode, ROS domain and RMW assumptions, expected ROS graph surface (or non-ROS liveness equivalent), readiness checks, restart behavior, shutdown behavior, logs and evidence paths, criticality assumption, model artifact dependencies.

### 6.3 Deployment Manifests

One manifest family describes components, profile bindings, startup dependencies, runtime parameters, data mounts, networking assumptions, readiness gates, validation commands, and evidence outputs — and feeds every profile. Open AD Kit renders runtime-native artifacts; each runtime keeps its native control surface:

| Runtime | Artifact |
| :--- | :--- |
| Docker Compose | `docker-compose.yaml`, `.env`, release bundle. |
| Podman / AutoSD | Quadlet files, systemd units, env files. |
| Ankaios (first) | Workload manifests + unsupported-field list. |
| BlueChi (second) | systemd/BlueChi service mapping + unsupported-field list. |
| Kubernetes | Only if a concrete user or partner need appears (FUTURE). |
| OTA / update | Compatibility-set transition plan, not a custom OTA runtime. |

### 6.4 CLI

Small, practical, subordinate to artifacts. v2.1: `validate`, `preflight`, `render`, `collect-evidence`. v2.2 adds `readiness`. v2.5 adds `plan-update`, `verify-rollback`. Deployment, restart, status, and update execution remain with native tools (`docker compose`, `systemctl`, `podman`, `ank`, partner OTA tooling).

### 6.5 Evidence Format

Release/validation evidence: release metadata, lockfile, image inventory, SBOM, provenance attestation, signature bundle, vulnerability scan summary, logs, runtime metrics, MCAP where applicable, scenario pass/fail, readiness timeline, restart/update/rollback result, known limitations. MCAP is the committed recording artifact; Eclipse Lichtblick is the standard review tool; Rerun and others remain time-boxed experiments.

---

## 7. Release Train

| Release | Target | Theme | Dominant Question |
| :--- | :--- | :--- | :--- |
| v2.0.0 | **July 2026 (hard line)** | First trustworthy release | Can users trust the public release surface? |
| v2.1.0 | September 2026 | Compatibility-set MVP | Can we describe a known-good deployment? |
| v2.2.0 | October 2026 | Readiness and test gating | Can we prove it is alive and working? |
| v2.3.0 | November 2026 | Release trust | Can users trust the supply chain? |
| — | December 2026 | **CES freeze — no release** | Demo assembled from v2.3 artifacts |
| CES 2027 | January 6–9, 2027 | **Flagship showcase milestone** | Not a release gate |
| v2.4.0 | Late January – February 2027 | Platform profiles + ecosystem artifacts | Does the model export to vehicle-like runtimes? |
| v2.5.0 | March 2027 | Update/rollback beta | Can we update and roll back one component? |
| v3.0.0 | May 2027 | Closed-loop release | Does the whole loop run end to end with evidence? |

Cadence rules: slip-don't-split (§3.9); December never ships a release; quarterly re-baseline; v2.0 July is the only immovable date.

---

## 8. v2.0.0 — First Trustworthy Release (July 2026)

**Theme:** stop looking experimental; ship a small release users can trust.

| Area | Deliverable |
| :--- | :--- |
| Docs | Merge PR #90; docs site becomes the canonical public surface. |
| Versioning | Versioning/support policy against Autoware semver meta-releases (closes #62); README/docs/release notes agree on `v2.0.0`. |
| Upstream coordination | Tag pinned to the then-current base-image state, explicitly coordinated with upstream (#85/#92/#63) so v2.0 does not land mid-migration. |
| Release bundle | Sample deployment bundles published as release assets (no cloning branches to run the golden path). |
| Images | Pinned image set: latest stable Autoware meta-release at cut (1.8.0 today); humble + jazzy variants where green; architectures; digests. |
| Support matrix | Supported and unsupported variants explicit; failing variants dropped rather than pretended. |
| Quickstart | Clean-host quickstart passes on the committed v2.0 host profile — Ubuntu 22.04 / ROS 2 Humble (the current release-workflow default); Jazzy promotion follows §17. |
| Smoke bundle | Exact commands, pinned digests, startup log, ROS graph check, log archive. |
| CI | `docker compose config` validation for documented files; **scheduled-build failure (#87) fixed or the failing variant dropped from the matrix**. |
| Trust breakers | GPU compose validation fixed or documented; Zenoh bridge `sleep 15` readiness race fixed or documented; AutoSD quadlets: parameterize hardcoded `ROS_DOMAIN_ID`. |
| Governance | CONTRIBUTING/SECURITY refresh, issue labels, release process, support policy (July/August, non-blocking). |

**Ships when:** PR #90 merged; docs/README agree on identity and versioning; release bundle exists; pinned image set published; release notes + support matrix exist; quickstart passes on the committed host profile; smoke bundle exists; CI validates compose files; build matrix green or failing variants dropped; trust breakers fixed or documented.

**Non-goals:** deployment framework, CLI, lockfile, SBOM/signing, Ankaios/BlueChi, S-Core, OpenSOVD, Safety Island, VisionPilot gating, CARLA, eSync.

---

## 9. v2.1.0 — Compatibility-Set MVP (September 2026)

| Area | Deliverable |
| :--- | :--- |
| Compatibility lockfile MVP | Pins Open AD Kit version, Autoware ref, ROS distro, image tags/digests, **model artifacts (name/version/digest bound to image versions; schema field — first real entries come from VisionPilot)**, deployment bundle, validation commands. |
| Component manifest MVP | Launch command, env, volumes, network/IPC, basic readiness hook, evidence paths for golden-path components. |
| Deployment manifest MVP | Golden-path deployment as components + Compose profile bindings. |
| Tooling MVP | `validate`, `preflight`, `render`, `collect-evidence` only. |
| Preflight MVP | Docker, architecture, disk, ports, data paths, image availability, `ROS_DOMAIN_ID`; every failure maps to a documented remediation entry. |
| Compose export | Renders/verifies the golden-path Compose bundle from the manifest. |
| Evidence bundle MVP | Deterministic evidence directory: metadata, lockfile, image inventory, logs, validation result. |
| Upstream division-of-labor doc | Published: upstream owns base/devel images; Open AD Kit owns component images, runtime contracts, compatibility sets; joint review cadence. |
| Jazzy check | If the Jazzy amd64+arm64 matrix is green, Jazzy becomes the primary documented path at this release (§17). |

**Ships when:** lockfile consumed by `validate`; manifests exist; every preflight failure emits a documented remediation message (failure catalog ships with the release); `render` and `collect-evidence` produce documented artifacts; division-of-labor doc published; release notes include the compatibility-set artifact and limitations; no unsupported safety claims.

**Non-goals:** full readiness tiers, scenario harness, restart validation, SBOM/signing as gates, dashboard, AutoSD, Ankaios/BlueChi, update/rollback.

---

## 10. v2.2.0 — Readiness and Test Gating (October 2026)

| Area | Deliverable |
| :--- | :--- |
| Golden-path test harness | Scenario Simulator V2-based release gate (version pinned), CI-run, evidence published. |
| Tiered readiness | Process → container health → ROS graph → topic freshness → scenario semantic check. |
| VisionPilot contract (Tier 1.5) | Component manifest + adapted non-ROS readiness tiers (process → pipeline/stream liveness → data freshness → semantic); release-gated container build/smoke on x86_64 from this release onward. |
| Readiness tooling | `openadkit readiness` evaluates a deployed golden path; no deployment ownership. |
| Restart evidence | One golden-path component restart path documented and validated. |
| Evidence format | MCAP where applicable, readiness timeline, scenario result, metrics snapshot; Eclipse Lichtblick as review tool. |
| Golden Path Contract | Published with exact commands, CI job, artifact paths, thresholds, retry/flake policy, waiver owner. |
| Reference Architecture page | The two-diagram layering story published: Autoware/VisionPilot (application) → Open AD Kit (deployment/evidence) → SDV platform (AutoSD, Ankaios/BlueChi; S-Core as the adjacent platform-services layer) → silicon + Safety Island (safety MCU). |
| `rmw_zenoh` experiment | Time-boxed (Oct–Nov): alternate golden-path sample, benchmark vs DDS-over-host, documented go/no-go. DDS default unchanged. |
| CARLA demo lane (Tier 3, non-gating) | PR #73 disposition: pin CARLA 0.9.16 if validated against `autoware_carla_interface`, else 0.9.15; demo-lane sample deployment merged (feeds the CES leg, never gates v2.2). |
| GPU runner proof | At least one CUDA inference smoke job executes on a provisioned GPU runner — de-risks the v2.3 GPU gate (runners provisioned July–August). |

**Ships when:** Golden Path Contract public; planning simulation passes from clean-host docs; CI runs the harness and publishes evidence; readiness includes ROS graph + freshness; VisionPilot manifest + smoke gate live (or VisionPilot excluded per the Tier 1.5 never-blocks rule, with a release-note entry); one CUDA smoke job has executed in CI; one restart path validated; reference architecture page live.

---

## 11. v2.3.0 — Release Trust (November 2026)

| Area | Deliverable |
| :--- | :--- |
| Inventory | Published for golden-path **and VisionPilot** images. |
| SBOM + provenance + signing | SBOM, build provenance attestation, cosign keyless signing for those images. |
| Vulnerability policy | Scan baseline, severity thresholds, waiver process, known exceptions. |
| Immutable tags | Immutable release tags or digest-as-source-of-truth enforced. |
| GPU functional smoke gate | No CUDA image publishes without passing a GPU inference smoke test (kills silent GPU disablement). x86_64 GPU promotes to COMMITTED when this gate is green. |
| Source overlay | One component rebuilt/overridden locally inside a known-good compatibility set. |
| Dashboard MVP | CI-generated static release page: artifacts, scans, scenario results, limitations. |
| CARLA demo bundle (non-gating) | CARLA sample deployment + pinned scenario subset published as v2.3 release assets (BEST-EFFORT — feeds the CES leg per §3.8, never gates v2.3). |

**Ships when:** all golden-path images — and VisionPilot images when included in the set — have inventory/SBOM/provenance/signature; vulnerability policy published; immutability enforced; GPU smoke gate green; source overlay documented and validated; dashboard links evidence.

**Post-release (Nov–Dec):** SDV blueprint proposal submitted on v2.3 artifacts (running golden path + Zenoh bridge; Ankaios/AutoSD declared as v2.4 extensions); SOAFEE GitLab blueprint repo refreshed; CES freeze begins.

---

## 12. CES Freeze and Premiere (December 2026 – January 2027)

### December 2026 — CES Freeze (no release)

- Flagship demo assembled and rehearsed **from v2.3 artifacts**: VisionPilot + Safety Island (FVP/virtual CAN; AVH or physical S32Z2 upgrade the demo, never block) + CARLA (the v2.3 demo bundle: pinned scenario subset, Humble lane).
- **Preconditions, tracked from October:** VisionPilot contract live (v2.2); CARLA demo bundle in v2.3 release assets (PR #73 disposition at v2.2); SI re-pin coordinated (target Oct 2026 — if missed, the SI leg demos against its existing pin with the mismatch documented) plus a demo-scoped SI interface note from the Aug CAN-contract work; GPU runner proven (v2.2 CUDA smoke job). A missed precondition descopes that leg — the demo never forks from main.
- **Scripted update/rollback preview**: one-component registry-digest compatibility-set transition (VisionPilot model+image), explicitly labeled a preview of v2.5 machinery.
- **MCUboot firmware OTA prototype** (openadkit-side, Oct–Dec window): signed update, rollback, safe-state on the hardware-agnostic FVP container. EXPERIMENTAL; SI upstream scopes OTA out — stated honestly.
- SOAFEE blueprint repo (gitlab soafee/blueprints/open-ad-kit, stale since 2025-09-03) refreshed or redirected to the canonical repo.
- **Descope rule:** if v2.3 slipped, the demo rebuilds from v2.2 artifacts — VisionPilot smoke, SI FVP, and CARLA best-effort legs only; the signed update/rollback preview and GPU-committed claims are dropped, not faked (v2.2 has no signing or GPU gate).

### CES 2027 — January 6–9 (milestone, not a gate)

Premiere of the flagship showcase; releases announced via Autoware Foundation, SOAFEE, and eSync Alliance channels. February consolidates the demo into a reproducible pipeline.

---

## 13. v2.4.0 — Platform Profiles + Ecosystem Artifacts (late January – February 2027)

| Area | Deliverable |
| :--- | :--- |
| AutoSD/Podman | Runtime-native Quadlet/systemd artifacts for the golden path: validated, or blocker list published. |
| Podman runtime contract | Rootful/rootless, cgroups, host networking, IPC, devices, systemd lifecycle, evidence collection. |
| Ankaios (first) | Experimental mapping to Ankaios v1.x workload descriptors + unsupported-field list; validated or blockers. |
| BlueChi (second) | Experimental mapping to BlueChi/systemd service control + unsupported-field list. Retained because it is the AutoSD default; upstream is maintenance-cadence — noted. |
| Zenoh | Bridge converted to modular component images with real readiness checks (no fixed sleeps). |
| SOAFEE-aligned target | Arm Automotive Solutions reference stack v2.2 / RD-1 AE FVP (EXPERIMENTAL, free) and AVH/Corellium (PARTNER-GATED); **v2.4-rc artifacts validated through the SOAFEE Integration Lab** (Linaro remote labs; lab scheduling is external — a dated blocker list is the fallback). |
| S-Core gap analysis | Published against released v1.0 (v1.0 is due 2026-12-14; the analysis runs against whatever shipped): map Open AD Kit runtime contracts ↔ S-Core lifecycle/health, logging, communication (LoLa); note FEO/orchestrator excluded from v1.0 and the absence of any container/OCI story (feature request #2597 only). Positioning: application workload above platform services — no conformance/module/endorsement claims. |
| Safety Island contract | Formalized interface contract + validated classic-CAN evidence (builds on the Aug 2026 contract and the December demo-scoped note); CAN-FD best-effort, undated; safe-state assumptions; no certification claims. Cross-repo coordination with SI maintainers. |
| "Evaluating Open AD Kit" guide | The OEM evaluation path: run golden path → inspect evidence bundle → map deployment profiles to your platform → known limitations. |
| Partner guides | Arm Learning Path, AWS workshop, Corellium/AVH guide refreshed against v2.3/v2.4 where owners exist (PARTNER-GATED); upstream path for partner blueprint flavors documented. |

**Ships when:** AutoSD validates or publishes blockers; Podman contract published; Ankaios and BlueChi mappings exist with validation or blockers; Zenoh bridge sleep-free; Integration Lab run on v2.4-rc artifacts or a dated blocker list published; S-Core gap analysis published; evaluation guide live; partner docs refreshed or gaps documented.

**Principle:** blocker lists are acceptable outcomes — honest platform evidence, not pretended maturity.

---

## 14. v2.5.0 — Update/Rollback Beta (March 2027)

| Area | Deliverable |
| :--- | :--- |
| Update state machine | Staged apply, health-gated promotion, rollback trigger, timeout, cleanup, failure states. |
| Planning commands | `openadkit plan-update`, `openadkit verify-rollback`. |
| Transport | Registry-digest compatibility-set transition (baseline). |
| Showcase case | **VisionPilot model + image update and rollback** — exercises model artifacts as lockfile members (productizes the CES preview). |
| Failure injection | One intentional failed update that triggers rollback to the previous known-good set. |
| Rollback evidence | Pre-update state, staged update, health result, rollback action, final known-good state. |
| Cloud-edge rehearsal | AWS/AVH/FVP path documented if owners and access exist; otherwise blocker list (owner-gated, non-blocking). |

**Ships when:** state machine published; one non-stateful golden-path component updates between compatibility sets; failed update triggers verified rollback; `plan-update`/`verify-rollback` work against native runtimes; VisionPilot showcase case documented (with a golden-path component fallback if VisionPilot is excluded per Tier 1.5); limitations in release notes.

**Non-goals:** multi-component transactions, stateful migration, eSync transport, production OTA claims.

---

## 15. v3.0.0 — Closed-Loop Release (May 2027)

**Hard release gate — the golden-path closed loop:** build → deploy → test → observe → update → rollback.

| Step | Required Evidence |
| :--- | :--- |
| Build | Pinned images, source refs, SBOM, provenance, signatures. |
| Deploy | Lockfile + deployment manifest via documented commands. |
| Test | Scenario harness pass/fail on the pinned scenario set. |
| Observe | Logs, MCAP, metrics, readiness history, event markers. |
| Update | One component updated by compatibility-set transition. |
| Rollback | Failed or manual rollback returns to the previous known-good set. |
| Report | Release notes with evidence links and known limitations. |

**Also ships:** benchmarks for committed hardware (x86_64, arm64, Jetson Orin if validated; determinism/CPU-pinning experiment best-effort, no real-time claims); Jazzy-primary compatibility set + final Humble set marked EOL; April deliverables folded in — **S-Core reference workload experiment evidence** (coexistence on a shared AutoSD bootc target + one Open AD Kit process supervised by S-Core lifecycle/health; published evidence or gap list), **OpenSOVD diagnostics spike** result (selected health/fault events or blocker list; upstream has no stable release — watch status), foundation-model workload sample (best-effort: containerized E2E inference with versioned weights via model-artifact lockfile); future integration map (Muto, Kuksa, uProtocol, eCAL/iceoryx, deeper S-Core, `rmw_zenoh` per go/no-go — named, not dated); SDV blueprint status report (accepted or in-review; COMMUNITY-GATED, non-blocking).

**Optional showcase:** the flagship composition, promoted only if public contracts existed by v2.4. **Non-blocking for v3.0:** flagship, Safety Island physical hardware, CARLA stability, eSync timing, S-Core integration depth, OpenSOVD implementation, Kubernetes/SOAFEE full profile, RHIVOS product path.

---

## 16. Workload Model

| Tier | Workload | Commitment |
| :--- | :--- | :--- |
| Tier 1 | Modular Autoware golden path | Full release gates, CI evidence, manifests, readiness, update/rollback planning and verification. |
| **Tier 1.5** | **VisionPilot** (AWF sibling stack: GStreamer + ONNX Runtime, non-ROS) | Full component contract + adapted readiness tiers (process → pipeline/stream liveness → data freshness → semantic); release-gated build/smoke on x86_64 from v2.2; trust artifacts from v2.3; the v2.5 update/rollback showcase. **Never blocks core releases:** VisionPilot ships inside a compatibility set only when its gates pass; otherwise the release ships without it and the exclusion is a release-note entry. |
| Tier 2 | Safety Island | Integration/demo track. Committed validation: hardware-agnostic container on FVP/virtual CAN (CI-validated upstream); AVH/Corellium is the partner-gated upgrade lane. Physical NXP S32Z/S32Z2 best-effort (DDS round-trip achieved 2026-06-09); Renesas partner-gated. Classic CAN contract target Aug 2026 (cross-repo); CAN-FD best-effort, undated. Firmware OTA: openadkit-side MCUboot prototype Oct–Dec 2026 (EXPERIMENTAL). Flagship precondition: re-pin SI from Autoware 2025.02 to the deployment's meta-release (coordination target Oct 2026). |
| Tier 3 | CARLA (0.9.16 contingent on PR #73 validation against `autoware_carla_interface`, else 0.9.15; Humble lane; 0.10/UE5 future), tier4/AWSIM v2 (best-effort, binary pull at runtime, no redistribution), foundation-model sample (best-effort, Apr 2027) | Showcase and partner tracks, never core release gates. |

---

## 17. ROS Distro Strategy

| Milestone | Rule / Date |
| :--- | :--- |
| Every release | ROS distro pinned in every compatibility set; humble+jazzy built while both are green. |
| Jazzy promotion | **Green-matrix rule:** Jazzy becomes the primary documented path at the first release with a green Jazzy amd64+arm64 matrix — target v2.1 (Sep). If the matrix is not green by v2.3 planning, the chair triggers a re-baseline review — never a forced promotion of red variants. From v2.2 onward, Jazzy matrix health is tracked as a hard dependency of v3.0 (which must ship Jazzy-primary: Humble EOLs the same month). Upstream reality: Autoware 1.8.0 Docker defaults to Jazzy; scenario_simulator_v2 has Jazzy CI; JetPack 7.2 puts Orin on Ubuntu 24.04. |
| Humble lane | Retained for the CARLA/flagship track until `autoware_carla_interface` migrates (pins 0.9.15/Humble/22.04 today). |
| Humble freeze | January 2027 — critical fixes only. Humble EOL is May 2027. |
| v3.0 | Ships Jazzy-primary; final Humble compatibility set published and marked EOL. |
| Out of scope | Kilted (EOL Nov/Dec 2026) and Lyrical Luth (released 2026-05-22, LTS, Ubuntu 26.04 — no Autoware support in this window). |

---

## 18. OTA and Update Semantics

**Baseline rule:** update = move from one signed compatibility set to another signed compatibility set. Open AD Kit plans and verifies; native runtimes execute.

| Transport | Status |
| :--- | :--- |
| Registry-digest update (pull digests → validate set → stage → readiness → promote/rollback) | **COMMITTED baseline.** |
| eSync | PARTNER-GATED showcase transport. No OSS implementation exists (spec v2.2, member SDKs); Arm joined as charter member Nov 2025 — the three-consortia narrative stays alive. **No release ever gates on eSync.** |
| MCUboot signed firmware update | EXPERIMENTAL, openadkit-side SI firmware prototype, Oct–Dec 2026. |
| Custom OTA product | UNSUPPORTED. |

---

## 19. Communication Strategy

| Scope | Default | Notes |
| :--- | :--- | :--- |
| Intra-deployment | ROS 2 DDS over host networking | Closest to Autoware runtime assumptions; documented before reduced (host networking, host IPC, privileged mode, devices — the DDS/RMW runtime contract). |
| Cloud-edge | Zenoh bridge | Committed profile; modular images + real readiness in v2.4. |
| Alternative | `rmw_zenoh` | Tier-1 RMW upstream, but Fast DDS remains the ROS 2 default. Time-boxed Q4 2026 experiment with benchmark and documented go/no-go; does not replace the DDS default without evidence. |
| Security posture | Trusted deployment boundary first | DDS Security/SROS2 and network isolation are future hardening tracks. No cybersecurity-certification claims. |

---

## 20. Ecosystem Milestones

| Artifact | Target | Label |
| :--- | :--- | :--- |
| SDV blueprint proposal — submitted on running v2.3 artifacts (Compose golden path + Zenoh bridge = running public code using an SDV project); Ankaios-first mapping + AutoSD bootc target declared as in-window extensions that land with v2.4 during review | November–December 2026 | COMMUNITY-GATED (3× +1 vote; acceptance target Q1 2027) |
| SOAFEE GitLab blueprint repo refresh | December 2026 | COMMITTED |
| CES 2027 flagship premiere (from v2.3 artifacts) | January 6–9, 2027 | MILESTONE |
| Eclipse S-Core gap analysis (vs released v1.0) | January–February 2027 | COMMITTED |
| SOAFEE Integration Lab validation of v2.4-rc artifacts (RD-1 AE FVP; AVH partner-gated) | January–February 2027 | COMMITTED submission — lab scheduling external; dated blocker list is the fallback |
| Partner enablement refresh (Arm Learning Path, AWS workshop, AVH guide) | With v2.4 | PARTNER-GATED |
| S-Core reference workload experiment (AutoSD bootc coexistence + lifecycle/health-supervised process; evidence or gap list) | April 2027 | COMMITTED |
| OpenSOVD diagnostics spike (selected health/fault events or blocker list) | April 2027 | EXPERIMENTAL (upstream pre-1.0) |
| SDV blueprint evidence refresh + future integration map | May 2027 (v3.0) | COMMITTED |

Future tracks (named, not dated): Muto, Kuksa, uProtocol, eCAL, iceoryx, Leda, openDuT, Symphony, deeper S-Core communication/orchestration, Pullpiri.

---

## 21. Platform Commitments

| Platform | Status | Gate / Notes |
| :--- | :--- | :--- |
| Ubuntu 22.04/24.04 + Docker Compose | COMMITTED | v2.0 quickstart and release bundle; default developer path. |
| x86_64 CPU | COMMITTED | v2.0 smoke bundle; v2.2 golden path. |
| x86_64 NVIDIA GPU | EXPERIMENTAL → COMMITTED at v2.3 | Via the GPU functional smoke gate (required for the CES flagship). |
| arm64 generic | EXPERIMENTAL → COMMITTED when matrix green | Tied to the Jazzy green-matrix rule; failing variants dropped, never pretended. |
| Jetson Orin | BEST-EFFORT | JetPack 7.2 / Ubuntu 24.04 (Jazzy-native); target v3.0 validation if capacity exists. |
| AutoSD + Podman/Quadlet/systemd | EXPERIMENTAL | v2.4 validates or publishes blockers; AutoSD compatibility = RHIVOS readiness (Nissan/Red Hat momentum noted). |
| Ankaios | EXPERIMENTAL (first orchestrator) | v2.4 mapping validates or publishes blockers; upstream v1.0.1, active. |
| BlueChi | EXPERIMENTAL (second) | v2.4 mapping or blockers; upstream maintenance-cadence; retained as AutoSD default. |
| Arm Automotive Solutions v2.2 / RD-1 AE FVP | EXPERIMENTAL | Free FVP; SOAFEE Integration Lab validation Jan–Feb 2027. |
| AVH / Corellium | PARTNER-GATED | RD-1 AE AVH device exists; used when access exists. |
| NXP S32Z/S32Z2 (Safety Island) | BEST-EFFORT | Real-hardware DDS round-trip achieved upstream; BSP repo NXP-confidential (reproducibility limit noted). |
| Renesas safety silicon | PARTNER-GATED | Named, partner track only. |
| Kubernetes / SOAFEE full profile | FUTURE | Only on concrete user/partner need. |
| RHIVOS certified product | PARTNER-GATED | Any certification belongs to RHIVOS, not Open AD Kit. |

---

## 22. Documentation Package

| Page | Purpose |
| :--- | :--- |
| What Is Open AD Kit? | Deployment/integration reference for modular Autoware. |
| Choose Your Path | Source-built vs monolithic container vs Open AD Kit. |
| Quickstart | One clean, release-bundle-based path. |
| **Reference Architecture** (v2.2) | The layering story: Autoware/VisionPilot → Open AD Kit → SDV platform (AutoSD, Ankaios/BlueChi; S-Core adjacent) → silicon + Safety Island. Built from the generic-AD-stack and S-Core-scope diagrams. |
| Compatibility Sets | How releases are pinned and validated. |
| Components | Runtime contracts and image inventory. |
| Deployments | Golden path, logging, Zenoh, AutoSD, experimental profiles. |
| Validation Evidence | Scenario results, MCAP, logs, metrics, release evidence. |
| Platform Support | Committed / experimental / best-effort / unsupported. |
| Security & Trust | SBOM, signatures, provenance, vulnerability policy. |
| **Evaluating Open AD Kit** (v2.4) | The OEM evaluation path: run → inspect evidence → map profiles → limitations. |
| Partner Integration | How Arm/AWS/Corellium/AutoSD/eSync/SOAFEE flavors plug in. |
| Roadmap | Public, maintained, with gates and non-goals; mirrored in issue #91. |

---

## 23. Governance

| Practice | Rule |
| :--- | :--- |
| Chair go/no-go | Chair (or delegated release lead) makes release decisions against the gates. |
| Release owner | One named owner per release. |
| Review rule | No major item without owner, acceptance gate, command/CI proof, artifact path, evidence plan. |
| Downgrade rule | No owner by planning freeze → FUTURE, BEST-EFFORT, or removed from the gate. |
| Waiver rule | Waivers carry owner, reason, expiration, known limitation, release-note entry. |
| Partner/community-gated rule | Such items never block a core release without owner, public contract, access path, and acceptance evidence. |
| Demos rule | Public demos ship from release artifacts, never ad-hoc branches (§3.8). |
| Cadence rules | Slip-don't-split; December = CES freeze; quarterly re-baseline (§3.9). |
| Roadmap changes | Land as PRs (with issue #91 kept in sync). |
| Public board | Tracks the full v2.0–v2.5–v3.0 ladder with gates. |
| Monthly working group | Public status: shipped, blocked, next gates. |

---

## 24. Success Metrics

| Metric | Target |
| :--- | :--- |
| Clean quickstart | New user runs the v2.0 golden path from release docs. |
| Release reproducibility | Every release has lockfile, digests, evidence bundle. |
| CI coverage | Compose validation, lint, image build, scan, golden-path scenario gate, GPU smoke (v2.3+). |
| Readiness | Status reports process, ROS graph, freshness, scenario result (+ VisionPilot adapted tiers). |
| Update/rollback | v2.5 one-component beta with evidence; v3.0 full closed loop as release evidence. |
| Hardware matrix | x86_64, arm64, Jetson Orin status published honestly. |
| **Adoption** | Image pulls, quickstart feedback (issue-template submissions), downstream blueprint/flavor count, partner-showcased deployments — reviewed at each release. |
| **Community** | External contributors per quarter; first response < 7 days; good-first-issue throughput; ≥2 active maintainers from ≥2 orgs by v3.0 (health metric, not gate). |
| **OEM evaluation** | ≥1 external organization completes a documented evaluation via the guide by v3.0 (health metric, not gate). |
| Ecosystem | SDV blueprint accepted or in review; Integration Lab validation run; S-Core analysis + experiment published. |
| No overclaims | Docs contain no unsupported safety/certification/compliance claims. |

---

## 25. Detailed Timeline

| Date | Milestone |
| :--- | :--- |
| June 2026 | Roadmap finalized; issue #91 updated; `ROADMAP.md` lands in the repo via PR; PR #90 merged; versioning/support policy (closes #62); base-image migration coordination. |
| July 2026 | **v2.0.0 (hard line)**; GPU CI runner provisioning (proof job due by v2.2); repo hygiene (non-blocking, may absorb to August). |
| August 2026 | Lockfile/manifest schemas drafted (incl. model artifacts); division-of-labor doc drafted; SI classic CAN contract (cross-repo target); AutoSD groundwork. |
| September 2026 | **v2.1.0**; Jazzy-primary if matrix green; division-of-labor doc published. |
| October 2026 | **v2.2.0**; VisionPilot contract + smoke gate; CARLA PR #73 disposition; first CUDA smoke job in CI; SI re-pin coordination (cross-repo); Reference Architecture page; `rmw_zenoh` experiment starts; MCUboot prototype work starts. |
| November 2026 | **v2.3.0**; GPU smoke gate → GPU committed; CARLA demo bundle published as release assets; SDV blueprint proposal submitted on v2.3 artifacts. |
| December 2026 | **CES freeze (no release)**; demo from v2.3 artifacts; scripted update/rollback preview; MCUboot prototype demo-ready; SOAFEE blueprint repo refreshed. |
| January 2027 | **CES 2027 premiere (Jan 6–9)**; Humble freeze; S-Core gap analysis begins (v1.0 shipped 2026-12-14). |
| Late Jan–Feb 2027 | **v2.4.0**; Integration Lab validation; S-Core gap analysis published; evaluation guide; partner guides. |
| March 2027 | **v2.5.0**; VisionPilot update/rollback showcase; cloud-edge rehearsal (owner-gated). |
| April 2027 | v3.0 hardening: benchmarks; S-Core experiment; OpenSOVD spike; foundation-model sample (best-effort). |
| May 2027 | **v3.0.0** closed-loop release; final Humble set; future integration map; blueprint evidence refresh. |

---

## 26. Risk Register

| Risk | L | I | Mitigation |
| :--- | :--- | :--- | :--- |
| v2.0 slips again | High | High | Narrow scope; July hard line; migration coordination; everything else non-blocking. |
| Upstream base-image migration churn under v2.0 | Med | Med | Pin to current state; explicit coordination with upstream maintainers; division-of-labor doc by v2.1. |
| Sep/Oct/Nov release chain slips | Med | Med | Slip-don't-split; December buffer; quarterly re-baseline; each release deliberately small. |
| v2.3 slip breaks CES freeze | Med | High | Defined descope: v2.2-artifact demo without the signed-update preview or GPU-committed claims; never forks from main. |
| Demo sprawl returns | High | High | Golden path is the only release spine; demos attach via contracts; demos ship from releases. |
| VisionPilot velocity vs Tier 1.5 contract | Med | Med | Adapted tiers; smoke-only release gating; never blocks core releases; slip downgrades the CES leg, not the release. |
| SI firmware OTA owner bandwidth (openadkit-side) | Med | Med | Minimal prototype scope (sign/update/rollback/safe-state on FVP); escape hatch: downgrade to undated EXPERIMENTAL at v2.3 planning. |
| GPU CI cost/instability | Med | Med | RC-branch gating; AWS credits/self-hosted spot; smoke gate scoped to publishable images. |
| arm64/Jazzy matrix breaks | Med | High | Green-matrix rule; failing variants dropped from the support matrix, never pretended; tracked as a v3.0 hard dependency from v2.2. |
| CARLA Humble pin vs Jazzy-primary | Med | Med | Dual-lane strategy; flagship stays Humble until `autoware_carla_interface` migrates; SSV2 carries the Jazzy golden path. |
| S-Core v1.0 slips past 2026-12-14 | Low | Med | Gap analysis runs against whatever shipped; experiment scope flexes; no Open AD Kit gate depends on S-Core. |
| SDV blueprint vote stalls | Low | Med | COMMUNITY-GATED label; submission scoped to running v2.3 code (extensions land during review); resubmission path; the artifacts retain value as docs regardless. |
| BlueChi upstream stagnates | Low | Low | Ankaios-first; BlueChi is mapping-only, justified by AutoSD default. |
| Single-maintainer bus factor | High | High | Upstream division of labor; contribution funnel; release-area owners; two-maintainer target. |
| Docs overclaim safety | Med | High | No-certification language + release review checklist. |
| eSync access never materializes | Low | Low | Never gates anything; registry-digest baseline carries all milestones. |

---

## 27. Roadmap Package

1. `ROADMAP.md` (this document) + issue #91 kept in sync
2. `SUPPORT.md`, `SECURITY.md`, `CONTRIBUTING.md`, `RELEASE.md`
3. `docs/compatibility-sets.md`, `docs/component-contracts.md`, `docs/release-evidence.md`, `docs/platform-support.md`, `docs/choose-your-path.md`
4. `docs/reference-architecture.md` (v2.2), `docs/evaluating-openadkit.md` (v2.4)
5. `examples/compatibility/openadkit-v2.1.0.lock.yaml` (incl. a model-artifact entry), `examples/manifests/planning-simulation.component.yaml`, `examples/deployments/planning-simulation.deployment.yaml`

---

## 28. Final One-Sentence Roadmap

Ship v2.0 as the trustworthy first release, v2.1 as the compatibility-set MVP, v2.2 as readiness and test gating, v2.3 as release trust, CES 2027 as the flagship showcase built from those artifacts, v2.4 as the SDV platform-and-ecosystem bridge, v2.5 as the update/rollback beta, and v3.0 as the evidence-backed closed-loop deployment reference for modular Autoware — submitted to Eclipse SDV, gap-analyzed against S-Core v1.0, and validated through SOAFEE.

---

## Appendix A — Disposition of the 2026-06-10 Locked Decisions

| # | Locked 2026-06-10 | Final 2026-06-12 |
| :--- | :--- | :--- |
| 0 | Plain roadmap, no ceremony | Kept (changes land as PRs; lean governance). |
| 1 | SI hardware: NXP + Renesas named best-effort; FVP/AVH committed | Kept, with one honesty refinement: committed validation = FVP/virtual CAN (free); AVH is the partner-gated upgrade lane. S32Z2 hardware DDS round-trip since achieved upstream (2026-06-09). |
| 2 | SI classic CAN validated Aug 2026; CAN-FD best-effort | Kept as cross-repo coordination target. |
| 3 | SI firmware OTA prototype Oct 2026 | **Re-scoped openadkit-side** (SI upstream declares OTA out of scope): MCUboot prototype on FVP container, Oct–Dec 2026, EXPERIMENTAL, CES demo leg; escape hatch at v2.3 planning. |
| 4 | eSync primary, fallbacks; gate on "eSync or fallback" | **Reversed:** registry-digest baseline; eSync PARTNER-GATED showcase; nothing gates on eSync. |
| 5 | VisionPilot Tier 1 | **Revised: Tier 1.5, named** — full contract + adapted readiness + gated smoke; never blocks core releases. |
| 6 | Flagship = blocking v3.0 gate (virtually satisfiable) | **Revised:** non-blocking; dated **CES 2027 showcase** from v2.3 artifacts; v3.0 showcase only if contracts exist by v2.4. |
| 7 | Autoware pin: latest stable semver at cut; SI re-pin precondition | Kept (v2.0 pins 1.8.0). |
| 8 | SOAFEE target: Kronos RD-1 AE + Integration Lab; EWAOL dropped | Kept; renamed to **Arm Automotive Solutions reference stack v2.2 / RD-1 AE**; Integration Lab validation dated Jan–Feb 2027. |
| 9 | CARLA 0.9.16 contingent on PR #73, else 0.9.15; retry/flake policy | Kept; Humble-lane note added (`autoware_carla_interface` pin). |
| 10 | v2.0 gate: CI matrix green or variants dropped | Kept; scheduled-build #87 explicitly included. |
| 11 | Q1 re-baseline; v2.0 "no later than July" hard line | Kept; generalized into the quarterly re-baseline + slip-don't-split rules. |
| — | 3-release train (v2.0/v2.1/v3.0) | **Restructured** into the 7-release ladder with one dominant question per release, December CES freeze, and dated ecosystem milestones (§20). |
