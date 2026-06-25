# OpenADKit × Autoware Safety Island × Eclipse S-Core — Integration Guide

Date: 2026-06-18

One document explaining how OpenADKit, the Autoware Safety Island, and Eclipse S-Core
fit together: what each one is, what "S-Core compatible" really means, the integration
story, and a roadmap of what to do and when.

## TL;DR

- **Don't port OpenADKit to S-Core.** Run OpenADKit (Autoware on ROS 2) as the
  application workload; let S-Core stay below/beside it.
- OpenADKit = **QM doer**. Autoware Safety Island = independent **ASIL checker**.
  S-Core = **process spine now**, a possible Safety Island substrate later.
- First real integration = **AutoSD + BlueChi (single first orchestrator profile, v2.4) + real readiness/health checks**. Ankaios deferred to v3.0 alternative track. Then Zenoh bridge (v2.4), KUKSA + OpenSOVD read-only spike (v2.4), full bidirectional KUKSA + full OpenSOVD diagnostics (v3.0).
- S-Core does **not** make OpenADKit ASIL-certified, and it does not solve SOTIF
  (perception/planning insufficiency) — that stays with the integrator.

## 1. The relationship in one picture

```text
  QM side (no ASIL claim)
  ┌──────────────────────────────────────────────┐
  │ OpenADKit / Autoware / ROS 2   (the "doer")    │  perception · planning · control
  │ AutoSD + BlueChi              (first profile)  │
  │ Ankaios                       (alt, v3.0)      │
  │ Zenoh                         (bridge, v2.4)   │
  │ KUKSA · OpenSOVD              (read-only v2.4, │
  │                                full v3.0)      │
  └──────────────────────────────────────────────┘
                      │  E2E-protected gateway
                      │  CRC · sequence · timestamp · freshness · plausibility
                      ▼
  ASIL side (independent)
  ┌──────────────────────────────────────────────┐
  │ Autoware Safety Island         (the "checker") │  monitor · fallback/MRM · safe state
  │ substrate: S32Z2/Zephyr today · S-Core later   │
  └──────────────────────────────────────────────┘
```

Roles: **OpenADKit = supervised QM doer · Safety Island = independent ASIL checker ·
S-Core = process spine now and checker-substrate candidate later.**

## 2. What S-Core is — and isn't

| It IS | It IS NOT |
|---|---|
| A system substrate (IPC, lifecycle, logging, OS abstraction) | An AD stack (no perception/planning/control) |
| An ISO 26262 process spine (traceability, work products, coding rules) | An Autoware or ROS 2 replacement |
| A safety-oriented platform, SEooC with Assumptions of Use | A ready-to-integrate, certified product (its own docs say so) |

S-Core's own scope diagram leaves the **AD application box dashed and empty** — that
box is exactly where OpenADKit/Autoware lives.

Context to avoid a common confusion: **Eclipse SDV is the umbrella** (a working group
and project portfolio); **S-Core is one project** under it. AutoSD, Ankaios, BlueChi,
Zenoh, KUKSA, OpenSOVD and Muto are S-Core's **SDV siblings — not parts of S-Core**.

**Out of scope here** (cross-referenced in `roadmap.md`): SOAFEE Integration Lab validation
and the cloud-edge closed-loop split-ready sample. This doc focuses on the Eclipse SDV
integration story; SOAFEE and cloud-edge belong to the roadmap's v2.4 / v3.0 tracks.

## 3. What "S-Core compatible" means (and doesn't)

| ✅ Means | ❌ Doesn't mean |
|---|---|
| OpenADKit defines clean lifecycle/health/diagnostics/logging contracts | Replacing ROS 2/rclcpp with S-Core APIs (a 1,500+ file rewrite) |
| Those contracts can later map to S-Core concepts | Adopting S-Core as the runtime today |
| Adopting S-Core's traceability and coding-standard patterns | Claiming OpenADKit is safety-certified |
| OpenADKit can later exercise S-Core lifecycle/health ideas | Claiming OpenADKit *is* S-Core, or inheriting its safety evidence |

## 4. The Safety Island connection (rough contract)

The integration's real value is making the boundary the Safety Island supervises
**explicit, observable, and independent**. The doer's output crosses an
E2E-protected gateway and is treated as untrusted input.

The boundary contract (to be detailed per vehicle/ODD; numbers are project decisions):

- **Command interface** — acceleration, steering, mode + `timestamp`, `sequence`,
  `data_id`, `crc`.
- **E2E + freshness** — CRC, sequence counter, DataID, freshness window, liveness timeout.
- **Allowed envelope** — min/max/rate limits; out-of-envelope commands clamped or faulted.
- **MRM triggers** — stale command, doer silence, envelope breach, E2E failure, ODD exit.
- **Fault model** — a small set of fault IDs, exposed read-only via OpenSOVD / KUKSA.

Hard rules:

- The island must **not** depend on doer liveness for its own scheduling.
- The MRM's sensing and actuation must be **independent** of the doer's world model.
- This boundary catches faults (stale/implausible/silent). It does **not** catch a
  plausible-but-wrong command from **SOTIF** perception insufficiency — that is the
  integrator's problem and out of scope here.
- A safe/certified substrate is not the same as coverage: defining this profile or
  picking S-Core creates **no ASIL claim** for OpenADKit.

## 5. Eclipse SDV components & ROI order

These are **Eclipse SDV ecosystem projects, not S-Core modules.** Status verified
against official Eclipse pages and GitHub repos on 2026-06-18.

| Rank | Component | Status / evidence | Role for OpenADKit |
|---|---|---|---|
| 1 | **AutoSD** | SDV, incubating; repo active June 2026 | Reproducible SDV runtime target (highest strategic ROI) |
| 2 | **Zenoh** | IoT+SDV; `1.9.0`, active | Cloud-edge/ROS 2 bridge; fixes the current `sleep 15` bridge race (fast win) |
| 3 | **BlueChi** | SDV, **mature**; `v1.2.2` | **First SDV orchestrator profile** (v2.4) — aligned with existing AutoSD Quadlet/systemd assets |
| 4 | **Ankaios** | SDV, **mature**; `v1.0.1` (Feb 2026) | Alternative/advanced track — **deferred to v3.0**; v1.0 is fresh (4 months at publication) |
| 5 | **KUKSA** | SDV, incubating; databroker active | VSS vehicle-signal layer. **v2.4 read-only spike** (3–5 selected signals); **v3.0 full bidirectional** integration |
| 6 | **OpenSOVD** | SDV, incubating; active | Standards-based diagnostics. **v2.4 read-only health/fault exposure**; **v3.0 full diagnostics** |
| — | **Muto** | SDV, incubating; `v0.42_build_2` (prerelease) | **FUTURE / post-v3.0** — re-evaluate once it matures past v0.4x and OpenADKit's first SDV profile is in production |
| — | **S-Core** | Automotive, incubating; `v0.7.0` (mid-2026) | Process spine now; Safety Island substrate candidate later |

Best sequence: **AutoSD → Zenoh → BlueChi (first profile) → KUKSA read-only → OpenSOVD read-only → v3.0 KUKSA full + OpenSOVD full → Ankaios eval.**
**BlueChi is the single first orchestrator profile** (v2.4). Ankaios is the **alternative track**, evaluated at v3.0 — not shipped alongside BlueChi. Other adjacent SDV projects (uProtocol, Leda, eCAL, iceoryx, Velocitas, openDuT) exist but are off the critical path.

## 6. Roadmap — what to do and when

| When | Do |
|---|---|
| **Now** (target v2.1, Sep 2026) | Position OpenADKit as an SDV workload (not S-Core). Adopt S-Core's zero-regret process patterns: requirements traceability (docs-as-code), ISO 26262 work-product framing, exception-free base libraries (for a future island element), coding-standard/static-analysis CI. Keep ROS 2. |
| **Phase 1** (target v2.4) | Run one golden OpenADKit scenario on **AutoSD** with **BlueChi/Quadlet as the single first orchestrator profile**. Replace fixed `sleep`s with readiness/health checks. Ankaios deferred to v3.0 alternative track. |
| **Phase 2** (target v2.4) | Publish service/workload descriptors; make state observable; stabilize the **Zenoh** bridge with real readiness/failure handling. Also: establish the **split-ready sample** (single-host first; cloud-edge *run* is conditional). See `roadmap.md` §3 Cloud-to-edge closed loop. |
| **Phase 3** (target v2.4 read-only / v3.0 full) | v2.4: **read-only** KUKSA databroker connection (3–5 selected VSS signals) + **read-only** OpenSOVD health/fault exposure. v3.0: **full bidirectional** KUKSA + **full** OpenSOVD diagnostics. Keep v2.4 scope small. |
| **FUTURE (post-v3.0)** | Re-evaluate **Muto** once it matures past v0.4x and OpenADKit's first SDV profile is in production. Not in this release window. |
| **Later (gated)** | Define the Safety Island boundary contract (§4); evaluate **S-Core** as a substrate for a native checker/MRM element vs S32Z2/Zephyr — only if S-Core ships real FMEA/DFA, tool qualification, and drops "not for production". |

**Definition of done (first blueprint):** a new user can reproduce it from the docs;
no fixed `sleep`s for core readiness; container/service state visible through the
orchestrator; ROS 2 graph readiness checked by observable signals (not just process
start); failure/restart behavior documented; the doc states plainly what is
experimental and that nothing is safety-certified.

## 7. Don't do these

- ❌ Replace ROS 2/rclcpp with S-Core `ara::com`.
- ❌ Run QM Autoware "on top of" an S-Core ASIL floor (it voids the ASIL).
- ❌ Claim S-Core compatibility = safety certification.
- ❌ Treat KUKSA/Muto/OpenSOVD/Ankaios/BlueChi as parts of S-Core.
- ❌ Integrate every SDV project at once.

## Sources

- Autoware × S-Core safety discussion: <https://github.com/orgs/autowarefoundation/discussions/7166>
- Eclipse S-Core: <https://eclipse.dev/score/> · docs: <https://eclipse-score.github.io/score/main/>
- Eclipse SDV Blueprints: <https://sdv-blueprints.eclipse.dev/>
- Eclipse project pages (AutoSD, Ankaios, BlueChi, Zenoh, KUKSA, OpenSOVD, Muto): <https://projects.eclipse.org/>
