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
the drive marker. The order is fixed, before → after, so the board always
ends on the tuned production firmware.

## What the numbers mean

`drive` computes the stop distance as the ego's **path length** from the
injected fault (t=0, anchored on the events capture's own stamp) to rest
(speed below 0.05 m/s for the remainder of the capture), integrated from
the `/localization/kinematic_state` capture by
`scripts/x5h-stop-metrics.awk` — path length, not straight-line
displacement, so a stop that begins in a curve compares fairly. The junit
verdict stays reported-not-graded, exactly as in
[component-stack.md](component-stack.md): the scenario cannot go green
with the MRM acting, and a *before* run that stops long enough to roll
into the goal would go green — that too is reported, never graded. The
demo's grading is: both MRM chains complete, and
`before_stop_m > after_stop_m` strictly.

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
(the smoke script's own reason, forwarded); `demo_no_contrast` (both
drives passed but before did not stop longer than after). On any failure
the orchestrator stops, recovers nothing automatically, and prints the
board's state plus the restore commands.
