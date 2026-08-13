# Deploy-time interface-admission gate

<!-- cspell:ignore skopeo -->

`deploy_check.sh` is the operator / CI entry point for **deploy-time static admission** of Autoware's component interfaces. It rejects an interface-incompatible image set **before `docker compose up`**, at deploy-config / OTA-assembly time — the cheapest place to catch a mismatch, before any build, pull, boot, or vehicle dispatch is paid for, and before any container in the set is actually created or started.

Open AD Kit is where the gate belongs: `components/docker-bake.hcl` builds **per-component images** and `deployments/samples/*` compose **multi-container deployments** out of them, which is exactly the boundary the gate inspects. A monolithic single-image deployment has no per-component image boundary for a per-image manifest to attach to, so it has nothing for this gate to compare and falls back to the runtime trigger instead.

## Manifest resolution: label primary, installed fragments as fallback

Each component image should carry its interface manifest as **pure image metadata**, so the gate can read it without creating or starting a container and without any source present in the image (a binary-only third-party image works):

- **Primary**: the OCI image label `org.autoware.interface_manifest`, whose value is the manifest JSON payload. Read with `docker inspect` (or `skopeo inspect` / `crane config` against a registry, without pulling).
- **Fallback**: for an image that carries no such label, the `interface_manifest_fragment.json` file(s) installed under `/opt/autoware/share/<pkg>/` by every package that registers interfaces through `autoware_component_interface_utils`. `deploy_check.sh` `docker create`s the image to obtain a container ID and `docker cp`s `/opt/autoware/share` out of it, then admits every fragment it finds. **That container is created but never started** — the fallback is exactly as boot-free as the label path — and it is removed again once its filesystem has been read.

The fallback is what makes an **unmodified** Open AD Kit component image conformant as soon as the packages inside it install their manifest fragments: no `Dockerfile` or bake change is needed to make an image checkable.

An image with neither the label nor any installed fragment is not IF-versioning conformant and is rejected as an operational error (exit 2).

The JSON payload schema (the fields of `provided[]` / `required[]` and the manifest envelope) is defined once by the `autoware_component_interface_admission` package in `autoware_core`; see that package's README for the authoritative schema. `deploy_check.sh` treats a manifest as an opaque JSON document and hands it to `manifest_admit`, which owns parsing and the verdict.

## One rule, several triggers

The gate does not reimplement compatibility. It runs the **same admission rule** — "the consumer's accepted MAJOR range contains the provider's MAJOR", plus the remap-safe name match, plus the QoS conformance check described below — that the runtime handshake will use, via the shared `manifest_admit` in `autoware_component_interface_admission`. Deploy-time and runtime are triggers of one rule, not parallel implementations. Because the deploy-time image set is **complete** (unlike runtime observe mode, where a provider may simply not have started yet), the deploy trigger additionally rejects a required interface with **no provider** anywhere in the set (`NO_PROVIDER`).

### QoS conformance: exact match against the spec

`manifest_admit` additionally accepts `--spec-manifest <path>`, `autoware_component_interface_specs`' `interface_manifest.json`, which declares the reliability / durability each interface is specified to use. Conformance is **exact**: whenever the spec set declares a QoS for an interface, every `provided` and every `required` entry that carries `qos` for that interface must use exactly that reliability and durability, and any difference is a `QOS_SPEC_MISMATCH` rejection. A specification that says `reliable` means the interface is carried without drops; a subscription that quietly requests `best_effort` still connects under DDS's request-vs-offered rule but no longer gets that property, and preventing exactly that class of mistake is what declaring the QoS in the specification is for. `depth` is endpoint-local and never compared.

Exact means exact in **both** directions: a *stronger* QoS than the spec declares — `transient_local` where the spec says `volatile` — is rejected just as a weaker one is. The declared QoS is a requirement on every endpoint, not a floor endpoints may exceed, so an endpoint that silently upgrades is deviating from the specification and gets a `QOS_SPEC_MISMATCH` too. (The stronger direction is where an exact rule and a rank-based "at least as strong as" rule actually differ; the self-test has a fixture row for it precisely for that reason.)

The check is **per endpoint**, not per pairing: a publisher-only image is exactly as checkable as a full provider/consumer pair, since conformance is a property of one endpoint and its spec. For an interface the spec set declares no QoS for at all (e.g. a vendor / out-of-tree interface) there is nothing to hold either side to, so a stage-1-matched pair is instead checked directly against itself with the DDS request-vs-offered rule (`QOS_PAIR_INCOMPATIBLE`).

When the admission tool image carries a spec manifest at `/opt/autoware/interface_manifest.json`, `admit-tool-entrypoint.sh` (the reference tool image's entrypoint) prepends `--spec-manifest` automatically, so the gate enforces QoS conformance too. A tool image without that file still runs the version-only admission rule — and both the entrypoint and `manifest_admit` itself warn on stderr in that case, because silently dropping the QoS check is never safe for a deploy-time gate. A pairing with no QoS on either side is accepted with a warning (QoS compatibility not evaluated for that pairing), not rejected.

## `deploy_check.sh`

```bash
# Reject an incompatible set before `docker compose up`
ADMIT_TOOL_IMAGE=my/admit-tool:jazzy ./deployments/common/admission/deploy_check.sh \
  deployments/samples/planning-simulation/docker-compose.yaml
```

It resolves the image set with `docker compose config --images`, reads each image's manifest(s) (label primary, installed fragments as fallback — see above), writes each manifest to a file, and runs `manifest_admit` over the whole set from the tool image.

| Exit code | Meaning                                                                                                                                                                                                          |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0`       | every required interface is satisfied by a compatible provider — deploy may proceed                                                                                                                               |
| `1`       | at least one admission rejection (`MAJOR` / `MINOR` mismatch, `NO_PROVIDER`, or a `QOS_*` verdict — the endpoint's QoS differs from the QoS its spec declares) — deploy blocked                                    |
| `2`       | operational error: `docker compose config` failed, no images in the compose file, `docker inspect` failed, an image has neither the label nor any installed manifest fragment (or carries one that cannot be read), or the tool image could not be run — including a tool image that exits `1` without emitting a single verdict line |

A present image that carries **no** `org.autoware.interface_manifest` label and no installed manifest fragment (exit 2, "not IF-versioning conformant") is kept distinct in the diagnostics from a `docker inspect` / `docker create` that failed because the image is absent locally or the daemon is down (exit 2, "not present locally or Docker unavailable") — the former is a non-conformant image, the latter an environment problem.

### `ADMIT_TOOL_IMAGE`

`manifest_admit` runs from a **dedicated tool image**, `ADMIT_TOOL_IMAGE`, and **never** from an image under test — so the admission binary is always trusted, independent of the (possibly third-party, possibly hostile) images it inspects. The tool image contract: its entrypoint runs `manifest_admit` with the ROS overlay sourced, takes the manifest JSON file paths as arguments, prepends `--spec-manifest` when a spec manifest is present at `/opt/autoware/interface_manifest.json`, and honours `manifest_admit`'s 0/1/2 exit-code contract — which specifically means **reserving exit `1` for real admission verdicts** and using exit `2` for its own failures. `test/admit-tool.Dockerfile` + `test/admit-tool-entrypoint.sh` are a reference tool image, built on `ros:jazzy-ros-base`; the entrypoint exits `2` if either overlay cannot be sourced or if `manifest_admit` is not installed in it. It is a **test tool, not a hardened production image**: the build is single-stage, so its build-time dependencies (`git`, `python3-colcon-common-extensions`, `ros-jazzy-autoware-cmake`, `nlohmann-json3-dev`) and the whole `/ws` colcon build tree remain in the shipped layers. Minimality is not what makes it trustworthy here — what does is that the only Autoware code built into it is `manifest_admit`, from an `autoware_core` checkout the operator picks explicitly (`CORE_REPO` / `CORE_REF`), and that it is never one of the images under test. A production tool image should be built multi-stage, copying only the admission install space onto a runtime base.

A tool image is not taken on trust either: `deploy_check.sh` re-classifies an exit `1` that is not accompanied by at least one verdict line on stdout as an operational error (exit `2`). A fault in the tool must never be reported as an interface rejection of the images under test — that is the one conflation the 0/1/2 split exists to prevent, since a deploy pipeline acts on exit `1` by blaming the composed image set.

There is no published tool image yet; set `ADMIT_TOOL_IMAGE` to one you build (the self-test builds its own):

```bash
cd deployments/common/admission/test
docker build -t autoware-admit-tool:jazzy -f admit-tool.Dockerfile .
```

The `CORE_REPO` / `CORE_REF` build args select the `autoware_core` checkout `manifest_admit` is built from; they default to `autowarefoundation/autoware_core` @ `main`.

## Scope and honest limitations

- **Matches version + `interface_name`, plus the QoS the spec declares.** A compose file can remap a topic name after the image is built, and that remap happens in the launch / compose layer, not in the image itself — it is **not statically resolvable from image metadata**, so a remap-induced `TOPIC_MISMATCH` is left for the runtime trigger to catch instead. The deploy-time gate checks that the `interface_name` matches, the MAJOR version is compatible, and (when a spec manifest is supplied) each endpoint's QoS is exactly the QoS its spec declares.
- **Cooperative manifests.** The gate assumes honest, self-declared manifests. Tamper resistance (signing / attestation) is out of scope.
- **Multi-container prerequisite.** The per-image mechanisms (OCI label and installed fragment alike) presuppose per-component (multi-container) images, since both attach to a single image; a native / monolithic deployment has no per-component image boundary for either to attach to, so it falls back to the runtime trigger instead.

## What this directory ships — and what it does not

This directory ships the **gate, the label/fragment resolution, the spec-QoS wiring, and a self-test**. It deliberately does **not** touch the component `Dockerfile`s or `components/docker-bake.hcl`: the fragment fallback already makes an unmodified component image checkable once the packages inside it install their manifest fragments, and attaching the OCI label at bake time is separate follow-up work. Until then the gate is exercised end-to-end against fixture images built by the self-test, which proves the mechanism without changing any production image.

## Self-test

`test/run_self_test.sh` resolves an `ADMIT_TOOL_IMAGE` containing `manifest_admit` (with the fixture spec manifest baked in, so the QoS cases are enforced), builds a matrix of fixture images from the manifests under `test/fixtures/manifests/`, and asserts `deploy_check.sh`'s exit code — and, where an exit code alone would have more than one possible cause, its diagnostic output — on the compose sets under `test/fixtures/compose/`:

| Compose set                   | Fixture                                                                                                                                                                                                | Expected exit                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| `compose.compatible.yaml`     | provider 0.1.0 + consumer accepting MAJOR 0                                                                                                                                                            | `0`                                                                            |
| `compose.incompatible.yaml`   | provider 0.1.0 + consumer accepting MAJOR 1                                                                                                                                                            | `1` (MAJOR)                                                                    |
| `compose.no-provider.yaml`    | consumer requires an interface no image provides                                                                                                                                                       | `1` (NO_PROVIDER)                                                              |
| `compose.unlabeled.yaml`      | one image present but carrying no label and no installed manifest fragment                                                                                                                             | `2`                                                                            |
| `compose.broken-config.yaml`  | interpolates a required (`${VAR:?...}`) variable that is never set, so `docker compose config` itself fails                                                                                            | `2` (reported as a `docker compose` failure, not "no images")                   |
| `compose.fragments.yaml`      | a label-less provider carrying only an installed `interface_manifest_fragment.json`                                                                                                                    | `0` (fallback discovers and admits the fragment)                               |
| `compose.unreadable-fragment.yaml` | a label-less image whose only fragment match is a *directory* of that name, so it cannot be read                                                                                                  | `2` (never `cp`'s own status `1`, which would read as a rejection)             |
| `compose.qos-reject.yaml`     | a lone provider offering `best_effort` where the fixture spec manifest declares `reliable` — a deviation in the *weaker* direction                                                                      | `1` (QOS_SPEC_MISMATCH — asserted on the verdict text, not just the exit code) |
| `compose.qos-stronger.yaml`   | the same, deviating in the *stronger* direction: `transient_local` where the spec declares `volatile`. A rank-based rule would admit it; exact matching rejects it, so this is the row that pins the semantics | `1` (QOS_SPEC_MISMATCH — verdict text asserted)                          |
| `compose.qos-conformant.yaml` | the same provider with exactly the QoS its spec declares — the control for both rejections above, identical to each but for the one field it deviates in                                               | `0`                                                                            |
| `compose.multi-fragment.yaml` | one image carrying two installed fragments: one at the documented depth-2 path and one nested one level deeper, the way `install(DIRECTORY config DESTINATION share/${PROJECT_NAME})` would install it | `1` (NO_PROVIDER — proves the deeper fragment is still discovered)             |

Two further properties are asserted about the **tool** rather than the images under test: that `admit-tool-entrypoint.sh` warns on stderr when the tool image carries no spec manifest (run directly against the spec-manifest-less base image, so QoS enforcement can never silently no-op), and that a broken tool image is an operational error rather than a rejection. The latter is exercised three ways, each against `compose.compatible.yaml`, whose only correct verdicts are ACCEPTED: an image whose admission overlay cannot be sourced, one whose `manifest_admit` executable is missing, and one that simply exits `1` in silence (the foreign-tool-image case, caught by `deploy_check.sh` itself). All three must exit `2`.

All images it builds are tagged `autoware-admission-self-test-*` and removed on exit.

```bash
# Default: build the tool image from autowarefoundation/autoware_core @ main, then run the matrix.
./deployments/common/admission/test/run_self_test.sh

# Until the admission package merges into autoware_core, point the tool build at the branch that
# carries it. An already-built autoware-admit-tool:jazzy is reused as-is instead of rebuilt.
CORE_REPO=https://github.com/<owner>/autoware_core.git CORE_REF=<branch> \
  ./deployments/common/admission/test/run_self_test.sh
```

The GitHub Actions workflow `deploy-admission-self-test.yaml` runs the self-test on `pull_request` (paths under `deployments/common/admission/**`) and on `workflow_dispatch` (with `core-repo` / `core-ref` inputs). **Maintainers: please leave this workflow out of the required-checks set until `autoware_component_interface_admission` has merged into `autoware_core`.** Until then it cannot pass with the committed default build args, because the package it builds `manifest_admit` from does not exist on `autoware_core` `main` yet; the landing order is admission package first, then this gate. Whether the check is required is a branch-protection setting of this repository, which this document cannot assert on its maintainers' behalf.
