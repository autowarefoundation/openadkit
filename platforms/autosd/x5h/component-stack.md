# X5H component stack: the Open AD Kit MRM demo as Quadlet units

Runs the Open AD Kit MRM demo on the board as five Quadlet units — Autoware, the scenario runner, the domain bridge, and two small relay nodes — with the trajectory follower on the CR52 realtime core. Autoware and the scenario tooling live on DDS domain 1 on the application cluster; the CR52 runs the actuation module on domain 2, reached over the `rpmsg-eth` TAP link described in [rpmsg-dualboot.md](rpmsg-dualboot.md). The verdict of a run is a junit file, graded by an on-board smoke script; the board is headless throughout.

This is issue #120 milestone 7. The reference for every configuration value is the working compose demo of this exact topology, not `deployments/samples/scenario-simulation/` — the sample shares the scenario-simulation shape but none of the single-ECU, CR52-in-the-loop constraints that drive this profile. Deviations from the reference compose file are enumerated exhaustively in `components/awf-oak-x5h.env`; anything not listed there is intended to match it.

## The unit set

| Unit | Runs | Notes |
|---|---|---|
| `awf-oak-autoware` | Autoware planning simulator, domain 1 | mounts the stubbed `control.launch.xml`, so nothing local publishes the follower's `control_cmd` |
| `awf-oak-bridge` | `domain_bridge`, domains 1 and 2 | the only participant on both domains; built on the board from `components/bridge/Dockerfile` |
| `awf-oak-relay` | `traj_relay.py`, domain 1 | arc-length downsample of the trajectory so it fits one link frame |
| `awf-oak-restamp` | `control_restamp.py`, domain 1 | rewrites the CR52's uptime-clock stamps onto domain 1's clock |
| `awf-oak-simulator` | scenario_test_runner, domain 1 | `Type=oneshot`, **no `[Install]`** — a scenario must never run unbidden at boot; started only by the smoke script's `drive` mode |

Every inter-unit edge is an ordering edge (`After=`), never a start dependency: the smoke script's Stage 1 gate is "Autoware alone, unbridged", and a `Requires=` anywhere in the set would make that state unreachable. `awf-oak-relay` and `awf-oak-restamp` are load-bearing, not accessories — with the relay down the CR52 never receives a trajectory it can carry, and with restamp down its commands arrive but read as enormously stale.

The scenario unit has no `Exec=` on purpose: the scenario-simulator image's entrypoint runs the scenario only when given no arguments, so any `Exec=` silently replaces the run. Its entire interface is the environment file.

## Assets, staging, and the one source of truth

**The image manifest `aib/x5h-rootfs.aib.yml` is the source of truth for every file on the board that `aib` is able to place there.** Its `add_files` mapping installs the unit files, the environment file, the DDS config, the scenario, the launch stub and the relay nodes, all flattened into one directory beside the units. Hand-installed board copies go stale the moment the repository changes: after any edit, re-copy the file to the board and `systemctl daemon-reload` — or rebuild the image, which is what the mapping is for.

That claim has a named exception: `scripts/x5h-stack-smoke.sh` itself and `scripts/x5h-stop-metrics.awk` (staged next to it, required by `drive`'s stop-distance metric) are **not** in the manifest and cannot be — both live under `/usr/local/sbin`, one of the two paths `aib` rejects outright for `make_dirs`/`add_files` (see the note above `add_files:` in the manifest). They are hand-staged, permanently, the same category as the `rpmsg-eth` daemon in [rpmsg-dualboot.md](rpmsg-dualboot.md#staging); see [mrm-before-after-demo.md](mrm-before-after-demo.md#prerequisites) for the staging commands. Re-stage both whenever either changes — there is no `systemctl daemon-reload` equivalent for a shell script that reads its neighbor by `dirname "$0"`.

Two further asset classes arrive separately from the image:

- **Container images** are staged, never pulled on the board: `scripts/stage-container-images.sh` reads `components/images.txt` (loaded-name and digest-pinned source, two columns that must agree with the environment file because every unit sets `Pull=never`) and loads them over the bench LAN. The bridge image is the exception — it has no registry reference and is built on the board.
- **The map** is staged by `scripts/stage-scenario-map.sh` into the directory the tmpfiles fragment creates. The two map-consuming units carry `ConditionPathExists=` on both map files; with the map missing they are *skipped*, which `systemctl start` reports as success — the smoke script re-checks unit activity after starting for exactly this reason.

## The link dependency

Domain 2 exists only over `tap0`, the `rpmsg-eth` interface, at its frozen MTU. Three consequences shape everything above:

- **The trajectory must be downsampled.** A full Autoware trajectory crosses the link as a fragmented reliable sample, and the CR52's receive pipeline holds every fragment and every out-of-order sample until its heap exhausts. The relay publishes an arc-length-uniform downsample sized to fit one frame; the bridge remaps it back to the real name so the CR52 side is unchanged. The DDS `FragmentSize` in `components/cyclonedds-x5h.xml` and the relay's serialized-size budget move together — change one and the other must follow. `nodes/test_traj_relay.py` pins the budget in CI.
- **Domain 2 cannot be observed with a second participant.** The domain 2 config disables multicast and lists exactly one static peer, the CR52, so a new participant never discovers the bridge's publications there; and tcpdump is not in the board image. Observe `control_cmd_raw` on domain 1 instead — the bridge is its only domain-1 publisher, so a sample there is proof the CR52 produced it.
- **Three of the six bridged topics have no domain-1 publisher without a running scenario.** The ego's kinematic state, steering status and acceleration come from scenario_simulator_v2, not Autoware — which is why the `stack` smoke mode starts the scenario briefly, and why gating anything on those topics with only Autoware up is unsatisfiable by construction.

## Smoke modes and markers

`scripts/x5h-stack-smoke.sh` runs on the board and prints exactly one terminal marker per invocation. The full failure-reason vocabulary is enumerated in the script header; the modes are:

- **`autoware`** — Stage 1 isolation: Autoware alone on domain 1, bridge asserted *inactive*, gated on a live `/system/operation_mode/state` sample. Marker `X5H_AUTOWARE_PASS`.
- **`stack`** — the bridged stack: units active, link at the frozen MTU, and a live `control_cmd_raw` sample plus a nonzero tap0 packet delta proving the CR52 produced it. Starts the scenario briefly because without an ego the CR52 emits nothing. Marker `X5H_STACK_PASS cr52_control_cmd=1 cr52_packets=<n>`.
- **`drive`** — cold-cycles the whole stack (a scenario rerun against a post-run Autoware strands it in `WAITING_FOR_ROUTE`, so the cycle is load-bearing), runs the scenario once, and grades **the MRM chain**, captured on domain 1 during the run: the injected fault appears on `/simulation/events`, operation-mode availability drops `autonomous`, `/system/fail_safe/mrm_state` reaches MRM_OPERATING with COMFORTABLE_STOP and then MRM_SUCCEEDED, and the gate's final commanded velocity is zero. Marker `X5H_DRIVE_PASS junit=<path> tests=<n> failures=<n> errors=<n> mrm=succeeded stop_velocity=<v> stop_distance_m=<d>`; the raw captures are left under the output directory's `drive-probe/` for the operator. The stop distance (path length from the injected fault to rest, computed by `scripts/x5h-stop-metrics.awk` from a `/localization/kinematic_state` capture) is what the [before/after demo](mrm-before-after-demo.md) compares between firmware profiles.

**The junit counts are reported, not graded, and `failures="1"` is the expected value.** The scenario's success condition is a reach-position at the route's end with a one-meter tolerance, but the scenario also injects a latched ERROR partway along the route, the MRM's comfortable stop consumes the remaining distance, and availability never recovers — so the ego always comes to rest short of the goal and the scenario's own time condition then reports failure. That outcome is a property of the scenario's geometry, not of the stack; the MRM chain above is what "passing" means for this profile.

## Troubleshooting

Failure readings, roughly in the order they occur on a broken board:

- `unit_inactive:<unit>` — also covers a unit systemd *skipped*: an unmet `ConditionPathExists=` (the staged map) is a successful start job with an inactive unit. Check the journal for the named path before anything else.
- `tap0_mtu=<n>` at the kernel default — the interface script did not run, or ran after the interface came up. Restart `rpmsg-eth.service`; do not set the MTU by hand and continue, because that hides the ordering defect, and an oversized frame is dropped silently rather than erroring.
- `no_cr52_control_cmd` — the safety island produced nothing. Check that `awf-oak-relay` and `awf-oak-restamp` are genuinely up (either one down fails this way on a healthy link), then `podman logs awf-oak-bridge` and the container's `CYCLONEDDS_URI`, then the CR52 console.
- `no_cr52_packets_on_tap0` — the corroborating packet delta was zero: the link itself, not DDS, is the suspect. Nonzero `dropped_oversize` in the daemon's counters is the MTU-mismatch signature and must be reconciled before any PASS is accepted.
- `autoware_not_ready` — Autoware never answered after the cold cycle; the usual cause is the missing map (see `unit_inactive` above), not a slow start.
- `no_junit` — the runner's global timeout preempted the scenario's own exit conditions, and the interpreter writes a junit only on reaching a verdict. This means the timeout in the environment file is too small relative to the scenario, not that the drive failed.
- `mrm_no_fault_event` — the ego never reached the fault-trigger position, or the interpreter never fired the injection. Read the position trace in `drive-probe/` before touching anything.
- `mrm_availability_never_dropped` — the fault fired but the diagnostic is not reaching the aggregator. The wiring is a demo customization in this image's diagnostics graph (`perception.yaml` links the fault's diagnostic into the perception subtree, under the fault's own name, not the name the fault-injection package's `event_diag_list` suggests). Verify membership with the live `/diagnostics_graph/struct` and `/diagnostics_graph/unknowns` topics, never by grepping yaml.
- `mrm_no_comfortable_stop` / `mrm_never_succeeded` / `mrm_nonzero_final_velocity=<v>` — the handler saw the drop but the stop did not select, complete, or hold. The comfortable stop travels as a decelerating trajectory through the relay, so the relay path is the first suspect, not the emergency path through the command gate.
- `mrm_no_stop_metrics` — the MRM chain completed but the stop distance could not be computed. This covers three distinct causes, all collapsed to the one reason: the `kinematic_state` capture, the staged `x5h-stop-metrics.awk`, or a stamped fault record to anchor t=0 is missing; **or** the ego never came to rest within the capture window (`x5h-stop-metrics.awk`'s own `never_rested` case — the smoke script does not distinguish it from the others). There is no fallback anchor — the availability capture's first `autonomous: false` record predates engagement and is never substituted for the fault stamp. Check `drive-probe/` for `kinematic_state.txt`, confirm `x5h-stop-metrics.awk` sits next to the smoke script, and if both are present and the fault stamp was found, suspect the ego simply not resting before the capture ended.
- A board that behaves inexplicably after repository edits — re-copy the edited files and `systemctl daemon-reload`; the manifest is the source of truth and board-local copies go stale.
