# X5H MRM before/after demo

Runs the MRM scenario twice with the CR52 trajectory follower on two
actuation parameter profiles and compares the measured stop distance:
**before** (the CES 2026 untuned deceleration limits — the vehicle stops
long) and **after** (the tuned limits this platform normally runs — it
stops short). The board is headless, so the contrast is two numbers on one
line, not a picture:

    X5H_DEMO_PASS before_stop_m=<a> after_stop_m=<b> delta_m=<d>

The orchestrator is `scripts/x5h-mrm-demo.sh`, and it runs **on the
companion host**, never on the board — a demo leg reboots the board, so an
on-board orchestrator would not survive its own flash step. Each leg is:
gate the payload → write the CR52 boot slot
([cr52-slot-update.md](cr52-slot-update.md)'s procedure) → reboot → wait
for the stack → `x5h-stack-smoke.sh drive` → read `stop_distance_m=` off
the drive marker. For a full `run` (both legs), the order is fixed,
before → after, so the board always ends on the tuned production
firmware.

`run` also accepts `--only before` or `--only after` to execute a single
leg instead of the pair — useful for re-running just one side after a
transient failure, without redoing the other. `--only` deliberately
**breaks** the end-on-production-firmware invariant above: `--only before`
flashes the untuned payload, drives it, and exits 0 with the board left on
that untuned firmware; it must be followed by a `--only after` leg (or a
full `run`) before the board is considered back in its normal state. A
single leg's marker is `X5H_DEMO_LEG profile=<p> stop_distance_m=<d>`,
not `X5H_DEMO_PASS` — there is no before/after contrast to report from one
leg. `--only`-driven demos also honor `X5H_DEMO_LOGDIR` (default
`~/x5h-demo-logs`), which selects where each run's timestamped log
directory (`drive-<profile>.log`, `drive-probe-<profile>/`) is created.

## Prerequisites

Stage two board-side scripts by hand before the first run — neither is in
`aib/x5h-rootfs.aib.yml`'s manifest, and neither can be: both live under
`/usr/local/sbin`, one of the two paths `aib` rejects outright for
`make_dirs`/`add_files` (see [component-stack.md](component-stack.md#assets-staging-and-the-one-source-of-truth)).
`x5h-stack-smoke.sh` is `$X5H_SMOKE` (default
`/usr/local/sbin/x5h-stack-smoke.sh`, overridable in `site.conf`);
`x5h-stop-metrics.awk` must sit next to it, in the same directory, because
`drive` locates it with `$(dirname "$0")`:

```
scp platforms/autosd/x5h/scripts/x5h-stack-smoke.sh \
    platforms/autosd/x5h/scripts/x5h-stop-metrics.awk \
    root@192.168.0.20:/usr/local/sbin/
ssh root@192.168.0.20 chmod 0755 /usr/local/sbin/x5h-stack-smoke.sh \
                                  /usr/local/sbin/x5h-stop-metrics.awk
```

Re-stage both whenever either changes. There is no `systemctl daemon-reload`
equivalent here — a stale copy of either file is silently used as-is, and
`drive`'s failure mode for a missing (never a stale) awk is
`mrm_no_stop_metrics` (see the failure vocabulary below), discovered only
once a leg has already flashed and rebooted the board onto that leg's
payload.

## What the numbers mean

`drive` computes the stop distance as the ego's **path length** from the
injected fault (t=0, anchored on the events capture's own stamp) to rest
(speed below 0.05 m/s for the remainder of the capture), integrated from
the `/localization/kinematic_state` capture by
`scripts/x5h-stop-metrics.awk` — path length, not straight-line
displacement, so a stop that begins in a curve compares fairly. The awk's
`nav_msgs/Odometry` parsing is pinned by `test_stop_metrics.py` against a
real board capture of `/localization/kinematic_state` — see that test
file's module docstring for the fixture provenance. The junit
verdict stays reported-not-graded, exactly as in
[component-stack.md](component-stack.md): the scenario cannot go green
with the MRM acting, and a *before* run that stops long enough to roll
into the goal would go green — that too is reported, never graded. The
demo's grading is: both MRM chains complete, and
`before_stop_m > after_stop_m` strictly.

That "rolls into the goal" case is worth being explicit about, because it
does not actually produce a green-junit-but-passing leg. Reaching the goal
ends the scenario (`ReachPositionCondition`) regardless of whether the ego
has actually come to rest, and a `before` leg only reaches the goal at all
because it is engineered to stop *longer* than `after` — so if it reaches
the goal, it is most likely still executing the comfortable stop's
deceleration at that instant, not yet at the near-zero velocity
`MRM_SUCCEEDED` requires. `drive`'s capture processes are `pkill`'d right
after the scenario's oneshot unit exits, so `MRM_SUCCEEDED` most likely
never lands in the capture, and the MRM oracle — graded in causal order,
earliest break wins — fails the leg at `mrm_never_succeeded` (or,
depending on exactly how far the stop had progressed, at
`mrm_nonzero_final_velocity=<v>`) before the stop-distance metric is ever
computed. So this case is reported as `demo_drive_failed:before:...`, the
same as any other MRM-chain break, not as a passing leg with an
uninteresting junit. This is what the chain of reasoning predicts from the
code; it has not been confirmed with a `before` run that actually reaches
the goal on hardware.

## Firmware provenance

The two payloads come from CI-built ELFs of the `autoware-safety-island`
repository (`build.sh --platform freertos-x5h`, `--param-profile before`
for the untuned build; CI artifacts `freertos-x5h-elfs` and
`freertos-x5h-before-elfs`). Each ELF embeds the identity string
`actuation_param_profile=<name>` in `.rodata` via its boot banner;
`check-elf-contract.sh <elf> rpmsg-eth <profile>` verifies it at build
time, and the orchestrator's gate greps the same string out of the flat
payload before anything is written. The two builds differ in exactly five
longitudinal-controller deceleration defaults; everything else is
byte-identical by construction.

## What is deliberately not in this repository

The CR52 slot's device, offset and extent, and the ELF→payload conversion
step, derive from the vendor SDK and stay in the site's own records (the
"numbers live elsewhere" rule of
[cr52-slot-update.md](cr52-slot-update.md)). The orchestrator reads them
from a site-local config file (`~/.config/x5h-demo/site.conf` or
`$X5H_DEMO_SITE_CONF`); its header documents every required variable.
Keep the pristine slot baseline staged and hash-verified before any demo —
it is the restore path, and the orchestrator refuses to run without it.

## Failure vocabulary

One terminal marker per invocation. `X5H_DEMO_FAIL reason=` names the
earliest break: `usage` (bad invocation); `no_site_conf` (the site config
file, `run` mode only, is missing or unreadable) and
`site_conf_incomplete` (the site config is missing a required variable, a
slot-geometry value is not numeric, or the baseline path is unreadable —
also `run` mode only, since `check` never loads the site config);
`demo_wrong_profile:<p>` (payload lacks the identity string);
`demo_flash_failed:<p>[:detail]` (gate or write/verify);
`demo_board_no_boot:<p>` (reboot watchdog); `demo_drive_failed:<p>:<r>`
(`<r>` is either the smoke script's own `reason=` value — including
`mrm_no_stop_metrics`, which covers the stop distance being uncomputable
*or* the ego never coming to rest within the capture window, see
[component-stack.md](component-stack.md#troubleshooting) — **or** one of
this orchestrator's own two: `no_marker`, no `X5H_DRIVE_PASS`/`X5H_DRIVE_FAIL`
line appeared in the smoke script's output at all, and `no_stop_distance`,
a `X5H_DRIVE_PASS` marker was seen but it carried no `stop_distance_m=`
field); `demo_no_contrast` (both drives passed but before did not stop
longer than after). On any failure
the orchestrator stops and recovers nothing automatically, but whether it
also prints the board's state and the restore commands depends on how far
the leg got: `usage`, `no_site_conf`, `site_conf_incomplete`,
`demo_wrong_profile:<p>`, and the pre-write
`demo_flash_failed:<p>:payload_unreadable` / `:payload_empty` /
`:payload_exceeds_extent` / `:scp` gate failures print only the `reason=`
line, because nothing has touched the board's slot yet and there is
nothing to restore. From `demo_flash_failed:<p>:write_verify` onward — a
slot write has actually been attempted — the orchestrator also prints the
board's state and the restore commands.
