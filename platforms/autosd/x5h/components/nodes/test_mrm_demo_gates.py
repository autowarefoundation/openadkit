"""Tests for x5h-mrm-demo.sh's local payload gates (`check` subcommand).

The check subcommand runs with no board and no site config -- exactly so CI
can exercise the gate logic that stands between a payload file and a slot
write. Run from this directory with `python3 -m pytest test_mrm_demo_gates.py`.
"""
import subprocess
from pathlib import Path

DEMO = Path(__file__).resolve().parents[2] / "scripts" / "x5h-mrm-demo.sh"


def payload(tmp_path, profile, name="p.bin"):
    f = tmp_path / name
    f.write_bytes(
        b"\x00" * 64
        + f"actuation_param_profile={profile}".encode()
        + b"\x00" * 64
    )
    return f


def run_check(profile, path):
    return subprocess.run(
        ["bash", str(DEMO), "check", profile, str(path)],
        capture_output=True, text=True,
    )


def test_check_passes_on_matching_profile(tmp_path):
    r = run_check("before", payload(tmp_path, "before"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("DEMO_CHECK_PASS profile=before sha256=")


def test_check_fails_on_wrong_profile(tmp_path):
    r = run_check("after", payload(tmp_path, "before"))
    assert r.returncode == 1
    assert "X5H_DEMO_FAIL reason=demo_wrong_profile:after" in r.stdout


def test_check_fails_on_missing_file(tmp_path):
    r = run_check("before", tmp_path / "absent.bin")
    assert r.returncode == 1
    assert "demo_flash_failed:before:payload_unreadable" in r.stdout


def test_check_fails_on_empty_file(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    r = run_check("before", f)
    assert r.returncode == 1
    assert "demo_flash_failed:before:payload_empty" in r.stdout


def test_check_rejects_unknown_profile(tmp_path):
    r = run_check("sideways", payload(tmp_path, "before"))
    assert r.returncode == 1
    assert "reason=usage" in r.stdout


def make_site_conf(tmp_path, slot_skip="999999", extent_sectors="1"):
    """A site.conf with obviously-fake placeholder values -- the real slot
    geometry is NDA'd and lives outside this repo."""
    site_conf = tmp_path / "site.conf"
    baseline = tmp_path / "fake-baseline.bin"
    baseline.write_bytes(b"\x00")
    site_conf.write_text(
        "X5H_SLOT_DEV=/dev/fake-slot-placeholder\n"
        f"X5H_SLOT_SKIP={slot_skip}\n"
        f"X5H_SLOT_EXTENT_SECTORS={extent_sectors}\n"
        f"X5H_SLOT_BASELINE={baseline}\n"
    )
    return site_conf


def make_stub_bin_dir(tmp_path):
    """Stub ssh/scp on PATH so a test cannot reach 192.168.0.20 even if a
    gate-ordering regression tries to: any attempted board contact fails
    immediately instead of blocking on a real network call."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for tool in ("ssh", "scp"):
        stub = bin_dir / tool
        stub.write_text("#!/bin/sh\necho 'stub: network access blocked' >&2\nexit 99\n")
        stub.chmod(0o755)
    return bin_dir


def run_env(tmp_path, site_conf):
    bin_dir = make_stub_bin_dir(tmp_path)
    return {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "X5H_DEMO_SITE_CONF": str(site_conf),
    }


def test_run_aborts_before_board_contact_on_bad_before_payload(tmp_path):
    """A failing gate on the FIRST (before) payload of a `run` invocation
    must abort before any board contact -- this is exactly the case the
    subshell bug in gate_payload() would have broken: `run` would have
    sailed past the failed gate and gone on to flash an unvalidated
    payload. Point X5H_DEMO_SITE_CONF at a temp site.conf (with obviously
    fake values) so `run` gets past load_site_conf, then give it a bad
    --before payload. ssh/scp are stubbed onto PATH as scripts that always
    fail, so if the gate did NOT abort first, the test would fail loudly
    (via a demo_flash_failed:*:scp/write_verify marker or a hang) instead
    of silently reaching the network.
    """
    site_conf = make_site_conf(tmp_path)
    bad_before = payload(tmp_path, "wrong-profile", name="before.bin")
    good_after = payload(tmp_path, "after", name="after.bin")

    r = subprocess.run(
        [
            "bash", str(DEMO), "run",
            "--before", str(bad_before),
            "--after", str(good_after),
        ],
        capture_output=True, text=True, env=run_env(tmp_path, site_conf),
        timeout=10,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=demo_wrong_profile:before" in r.stdout
    # The gate must have failed before any ssh/scp stub ran.
    assert "stub: network access blocked" not in r.stderr


def test_run_aborts_before_board_contact_on_bad_after_payload(tmp_path):
    """The design's central safety property: 'Gate BOTH payloads before
    writing ANYTHING'. A good --before with a bad --after must still abort
    before any board contact -- run_leg's own gate on the before leg would
    NOT catch this (the before payload is fine), so this exercises the
    pre-flight double gate specifically, not the per-leg gate inside
    run_leg. If the two pre-flight gate_payload calls were ever deleted,
    this test would fail: the script would flash the before payload (and
    call the ssh/scp stubs) before ever looking at the after payload.
    """
    site_conf = make_site_conf(tmp_path)
    good_before = payload(tmp_path, "before", name="before.bin")
    bad_after = payload(tmp_path, "wrong-profile", name="after.bin")

    r = subprocess.run(
        [
            "bash", str(DEMO), "run",
            "--before", str(good_before),
            "--after", str(bad_after),
        ],
        capture_output=True, text=True, env=run_env(tmp_path, site_conf),
        timeout=10,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=demo_wrong_profile:after" in r.stdout
    # The gate must have failed before any ssh/scp stub ran -- i.e. before
    # the before payload was flashed.
    assert "stub: network access blocked" not in r.stderr


def test_run_fails_fast_on_before_missing_value(tmp_path):
    """A `--before` with no following argument must not hang the argument
    parser. Uses a subprocess timeout so a regression fails fast instead of
    hanging the test suite."""
    site_conf = make_site_conf(tmp_path)
    r = subprocess.run(
        ["bash", str(DEMO), "run", "--before"],
        capture_output=True, text=True, env=run_env(tmp_path, site_conf),
        timeout=10,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=usage" in r.stdout


def test_run_fails_fast_on_after_missing_value(tmp_path):
    """A `--after` with no following argument must not hang the argument
    parser. Uses a subprocess timeout so a regression fails fast instead of
    hanging the test suite."""
    site_conf = make_site_conf(tmp_path)
    good_before = payload(tmp_path, "before", name="before.bin")
    r = subprocess.run(
        ["bash", str(DEMO), "run", "--before", str(good_before), "--after"],
        capture_output=True, text=True, env=run_env(tmp_path, site_conf),
        timeout=10,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=usage" in r.stdout


def test_run_fails_with_marker_on_non_numeric_slot_skip(tmp_path):
    """load_site_conf must reject non-numeric slot geometry with the
    existing site_conf_incomplete marker rather than dying bare from an
    arithmetic expansion (unbound variable / value too great for base)."""
    site_conf = make_site_conf(tmp_path, slot_skip="not-a-number")
    good_before = payload(tmp_path, "before", name="before.bin")
    good_after = payload(tmp_path, "after", name="after.bin")
    r = subprocess.run(
        [
            "bash", str(DEMO), "run",
            "--before", str(good_before),
            "--after", str(good_after),
        ],
        capture_output=True, text=True, env=run_env(tmp_path, site_conf),
        timeout=10,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=site_conf_incomplete" in r.stdout


def test_run_fails_with_marker_on_non_numeric_extent_sectors(tmp_path):
    """Same as above for X5H_SLOT_EXTENT_SECTORS, whose non-numeric value
    is fatal in flash_payload's `$((X5H_SLOT_EXTENT_SECTORS * 4096))`."""
    site_conf = make_site_conf(tmp_path, extent_sectors="8sectors")
    good_before = payload(tmp_path, "before", name="before.bin")
    good_after = payload(tmp_path, "after", name="after.bin")
    r = subprocess.run(
        [
            "bash", str(DEMO), "run",
            "--before", str(good_before),
            "--after", str(good_after),
        ],
        capture_output=True, text=True, env=run_env(tmp_path, site_conf),
        timeout=10,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=site_conf_incomplete" in r.stdout


def test_run_reports_usage_before_loading_site_conf(tmp_path):
    """The header's stated rule is 'earliest break names the reason', and
    a bad invocation is earlier than a missing site config. `run` with no
    payloads at all, on a HOME with no site.conf anywhere under it, must
    report reason=usage, not reason=no_site_conf -- this is exactly the
    ordering load_site_conf vs. the payload-presence checks controls.
    Regression coverage for load_site_conf having been called before those
    checks."""
    bin_dir = make_stub_bin_dir(tmp_path)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        # Deliberately no X5H_DEMO_SITE_CONF override and no
        # ~/.config/x5h-demo/site.conf under this HOME: load_site_conf
        # would fail with no_site_conf if it ran before the usage check.
    }
    r = subprocess.run(
        ["bash", str(DEMO), "run"],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=usage" in r.stdout
    assert "no_site_conf" not in r.stdout
    assert "stub: network access blocked" not in r.stderr


def test_run_flash_aborts_before_scp_when_payload_exceeds_extent(tmp_path):
    """flash_payload's payload_exceeds_extent gate (checked before the scp
    that stages the payload onto the board) must fire on a payload larger
    than the configured slot extent, and must do so before any board
    contact -- same discipline as the pre-flight double gate tests above.
    A 1-sector (4096-byte) extent with a payload just over that size is
    the smallest reliable trigger."""
    site_conf = make_site_conf(tmp_path, extent_sectors="1")
    oversized_before = payload(tmp_path, "before", name="before.bin")
    with open(oversized_before, "ab") as f:
        f.write(b"\x00" * 4096)  # push the file past the 4096-byte extent
    good_after = payload(tmp_path, "after", name="after.bin")

    r = subprocess.run(
        [
            "bash", str(DEMO), "run",
            "--before", str(oversized_before),
            "--after", str(good_after),
        ],
        capture_output=True, text=True, env=run_env(tmp_path, site_conf),
        timeout=10,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=demo_flash_failed:before:payload_exceeds_extent" in r.stdout
    # The gate must have failed before any ssh/scp stub ran.
    assert "stub: network access blocked" not in r.stderr


def make_recording_bin_dir(tmp_path, log_path, down_calls=1,
                           stop_distances=(), fail_scp_profile=None):
    """Stub ssh/scp on PATH that record every argument they were called
    with to log_path, in call order, and then behave like a board -- unlike
    make_stub_bin_dir()'s always-fail stubs, this lets a `run` invocation
    walk past the flash and the reboot so what it does next can be
    inspected. Neither stub talks to anything; there is no real remote
    shell, so a multi-line remote command string is recorded verbatim as a
    single argument rather than executed.

    Three behaviours make it a board rather than a yes-man, each needed by
    a test below:

    down_calls -- how many ssh probes fail after a `reboot` before the
      board answers again. reboot_and_wait() waits for the board to go
      DOWN before waiting for it to come back, so a stub that always
      succeeds is a board that never rebooted; down_calls=0 simulates
      exactly that (a reboot that was not delivered) and any positive
      value simulates a real one.

    stop_distances -- the stop_distance_m values a `drive` invocation
      reports, consumed one per call, so a two-leg run can be given a
      before and an after and the contrast grading downstream of them can
      actually run. With none given, `drive` produces no marker at all,
      which is the no_marker case.

    fail_scp_profile -- makes the scp of one leg's payload fail, to reach
      a failure AFTER an earlier leg has already written the slot.
    """
    bin_dir = tmp_path / "recordingbin"
    bin_dir.mkdir()
    state = tmp_path / "stubstate"
    state.mkdir()
    if stop_distances:
        (state / "stops").write_text(
            "".join(f"{d}\n" for d in stop_distances))
    for tool in ("ssh", "scp"):
        stub = bin_dir / tool
        stub.write_text(
            "#!/bin/sh\n"
            "{\n"
            "    echo '== call =='\n"
            "    for a in \"$@\"; do printf '%s\\n' \"$a\"; done\n"
            f"}} >> \"{log_path}\"\n"
            f"STATE=\"{state}\"\n"
            + (
                'if [ "$(basename "$0")" = scp ]; then\n'
                f'    case "$*" in *x5h-demo-{fail_scp_profile}.bin) exit 1 ;; esac\n'
                "fi\n" if fail_scp_profile else ""
            ) +
            # The REMOTE COMMAND only -- bssh's last argument -- decides
            # what this call is. Matching "$*" would also see the local
            # paths, and pytest's own tmp_path for this module contains
            # the word "reboot": an scp of the payload was then taken for
            # a reboot, and the flash that followed it failed as
            # write_verify against a board the stub thought was down.
            'for _last; do :; done\n'
            'case "$_last" in\n'
            "    reboot) : > \"$STATE/down\"; exit 0 ;;\n"
            "esac\n"
            'if [ -f "$STATE/down" ]; then\n'
            '    n=$(cat "$STATE/downcount" 2>/dev/null || echo 0)\n'
            "    n=$((n + 1))\n"
            '    echo "$n" > "$STATE/downcount"\n'
            f"    if [ \"$n\" -le {down_calls} ]; then exit 255; fi\n"
            '    rm -f "$STATE/down" "$STATE/downcount"\n'
            "fi\n"
            'case "$_last" in\n'
            "    *x5h-stack-smoke.sh\\ drive)\n"
            '        v=$(head -1 "$STATE/stops" 2>/dev/null || true)\n'
            '        if [ -n "$v" ]; then\n'
            '            sed -i 1d "$STATE/stops"\n'
            '            echo "X5H_DRIVE_STOP stop_distance_m=$v rest_x=0 rest_y=0"\n'
            '            printf "X5H_DRIVE_PASS junit=/tmp/r.junit.xml tests=1 "\n'
            '            printf "failures=1 errors=0 mrm=succeeded "\n'
            '            printf "stop_velocity=0.001 stop_distance_m=%s\\n" "$v"\n'
            "        fi\n"
            "        exit 0 ;;\n"
            "esac\n"
            "exit 0\n"
        )
        stub.chmod(0o755)
    return bin_dir


def test_run_reboot_and_wait_starts_the_awf_oak_units_after_reboot(tmp_path):
    """Regression test for the hardware-observed defect: reboot_and_wait()
    used to only ever WAIT for the awf-oak-* units, never start them, so on
    a board where the Quadlet generator's output was discarded (systemd
    generator timeout) the units stayed unknown to systemd forever and
    drive's precondition failed every single time. reboot_and_wait() must
    now issue a `systemctl start` for all four awf-oak-* units, and it must
    do so AFTER the reboot, not before.

    ssh/scp are the recording stubs (make_recording_bin_dir), not the
    always-fail ones, so the run proceeds past the flash and the reboot.
    X5H_BOOT_SETTLE=0 skips the fixed settle sleep and a very small
    X5H_UNITS_TIMEOUT keeps the wait-for-active loop from ever blocking --
    the recording ssh stub always exits 0, so that loop's own poll
    succeeds immediately anyway, but the fast timeout also protects this
    test if that assumption regresses.

    The run is expected to end with X5H_DEMO_FAIL
    reason=demo_drive_failed:after:no_marker -- the stub smoke script
    produces no marker because there is no real remote shell to run it.
    That failure is expected and is NOT what this test asserts on; it
    asserts on the recorded ssh command log instead.
    """
    site_conf = make_site_conf(tmp_path)
    with open(site_conf, "a") as f:
        f.write("X5H_BOOT_SETTLE=0\nX5H_UNITS_TIMEOUT=1\n")
    good_after = payload(tmp_path, "after", name="after.bin")

    log_path = tmp_path / "ssh-calls.log"
    bin_dir = make_recording_bin_dir(tmp_path, log_path)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "X5H_DEMO_SITE_CONF": str(site_conf),
    }

    r = subprocess.run(
        [
            "bash", str(DEMO), "run",
            "--after", str(good_after),
            "--only", "after",
        ],
        capture_output=True, text=True, env=env,
        timeout=15,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=demo_drive_failed:after:no_marker" in r.stdout

    log = log_path.read_text()
    reboot_at = log.find("\nreboot\n")
    assert reboot_at != -1, log
    start_units_at = log.find(
        "systemctl start awf-oak-bridge.service awf-oak-autoware.service "
        "awf-oak-relay.service awf-oak-restamp.service"
    )
    assert start_units_at != -1, log
    assert reboot_at < start_units_at, log


def test_run_aborts_before_board_contact_on_oversized_after_payload(tmp_path):
    """The pre-flight gate has to cover SIZE, not just identity. An
    oversized --after that still carries its profile string used to pass
    the pre-flight double gate -- which only checked identity -- and was
    rejected by flash_payload on the after leg, i.e. after the before
    payload had already been flashed, rebooted and driven. That is exactly
    the stranding the pre-flight exists to prevent, and it is the after
    payload that has to be size-checked to prevent it: the before-payload
    case (test_run_flash_aborts_before_scp_when_payload_exceeds_extent
    above) would fail on the very first gate either way."""
    site_conf = make_site_conf(tmp_path, extent_sectors="1")
    good_before = payload(tmp_path, "before", name="before.bin")
    oversized_after = payload(tmp_path, "after", name="after.bin")
    with open(oversized_after, "ab") as f:
        f.write(b"\x00" * 4096)  # push the file past the 4096-byte extent

    r = subprocess.run(
        [
            "bash", str(DEMO), "run",
            "--before", str(good_before),
            "--after", str(oversized_after),
        ],
        capture_output=True, text=True, env=run_env(tmp_path, site_conf),
        timeout=10,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=demo_flash_failed:after:payload_exceeds_extent" \
        in r.stdout
    # Nothing may have reached the board: the before payload must NOT have
    # been flashed on the way to discovering this.
    assert "stub: network access blocked" not in r.stderr


def test_run_fails_when_the_board_never_goes_down(tmp_path):
    """A reboot that was not delivered leaves the PRE-reboot sshd -- and
    the pre-reboot CR52 image -- answering. reboot_and_wait() used to poll
    only for an ssh that answers, so it accepted that immediately and
    drove the payload the board was already running. Waiting for the board
    to go down first is what makes the reboot observed rather than
    assumed; a stub that never stops answering (down_calls=0) is that
    board, and it must fail as demo_board_no_boot before the smoke is ever
    invoked."""
    site_conf = make_site_conf(tmp_path)
    with open(site_conf, "a") as f:
        f.write("X5H_BOOT_SETTLE=0\nX5H_DOWN_TIMEOUT=3\nX5H_UNITS_TIMEOUT=1\n")
    good_after = payload(tmp_path, "after", name="after.bin")

    log_path = tmp_path / "ssh-calls.log"
    bin_dir = make_recording_bin_dir(tmp_path, log_path, down_calls=0)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "X5H_DEMO_SITE_CONF": str(site_conf),
    }
    r = subprocess.run(
        ["bash", str(DEMO), "run", "--after", str(good_after),
         "--only", "after"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=demo_board_no_boot:after" in r.stdout
    assert "still running the PRE-reboot image" in r.stderr
    assert "x5h-stack-smoke.sh drive" not in log_path.read_text()


def test_failure_after_the_before_leg_prints_the_restore_hint(tmp_path):
    """Once a leg has written the slot the board is no longer on the
    baseline, so EVERY later failure needs the restore text -- not only
    the ones whose call site happens to pass a board-state sentence.
    An after-leg scp failure is the case that used to print nothing: one
    argument to demo_fail, so no restore, while the slot already held the
    untuned before firmware."""
    site_conf = make_site_conf(tmp_path)
    with open(site_conf, "a") as f:
        f.write("X5H_BOOT_SETTLE=0\nX5H_UNITS_TIMEOUT=1\n")
    good_before = payload(tmp_path, "before", name="before.bin")
    good_after = payload(tmp_path, "after", name="after.bin")

    log_path = tmp_path / "ssh-calls.log"
    bin_dir = make_recording_bin_dir(
        tmp_path, log_path, stop_distances=(41.2,), fail_scp_profile="after")
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "X5H_DEMO_SITE_CONF": str(site_conf),
    }
    r = subprocess.run(
        ["bash", str(DEMO), "run",
         "--before", str(good_before), "--after", str(good_after)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=demo_flash_failed:after:scp" in r.stdout
    assert "board is on the before payload" in r.stderr
    assert "restore:" in r.stderr


def test_run_grades_the_contrast_between_the_two_legs(tmp_path):
    """The load-bearing grade -- before_stop > after_stop -> X5H_DEMO_PASS
    -- was unreachable in test: the recording stub never produced a
    X5H_DRIVE_PASS marker, so every full run ended at no_marker and
    neither this branch nor demo_no_contrast below was ever executed. With
    the stub reporting one stop distance per leg, the tuned (after) firmware
    stopping shorter is the passing demo."""
    site_conf = make_site_conf(tmp_path)
    with open(site_conf, "a") as f:
        f.write("X5H_BOOT_SETTLE=0\nX5H_UNITS_TIMEOUT=1\n")
    good_before = payload(tmp_path, "before", name="before.bin")
    good_after = payload(tmp_path, "after", name="after.bin")

    log_path = tmp_path / "ssh-calls.log"
    bin_dir = make_recording_bin_dir(
        tmp_path, log_path, stop_distances=(41.2, 22.5))
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "X5H_DEMO_SITE_CONF": str(site_conf),
    }
    r = subprocess.run(
        ["bash", str(DEMO), "run",
         "--before", str(good_before), "--after", str(good_after)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "X5H_DEMO_PASS before_stop_m=41.2 after_stop_m=22.5 delta_m=18.70" \
        in r.stdout
    # Both legs really ran: two flashes, two reboots, two drives.
    log = log_path.read_text()
    assert log.count("x5h-stack-smoke.sh drive") == 2
    assert log.count("\nreboot\n") == 2


def test_run_reports_no_contrast_when_after_does_not_stop_shorter(tmp_path):
    """The other side of the same grade. An after payload that stops no
    shorter than before is not a demo failure of the board's making, so it
    gets its own reason and a board-state line saying the board is left on
    the after payload."""
    site_conf = make_site_conf(tmp_path)
    with open(site_conf, "a") as f:
        f.write("X5H_BOOT_SETTLE=0\nX5H_UNITS_TIMEOUT=1\n")
    good_before = payload(tmp_path, "before", name="before.bin")
    good_after = payload(tmp_path, "after", name="after.bin")

    log_path = tmp_path / "ssh-calls.log"
    bin_dir = make_recording_bin_dir(
        tmp_path, log_path, stop_distances=(20.0, 30.0))
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "X5H_DEMO_SITE_CONF": str(site_conf),
    }
    r = subprocess.run(
        ["bash", str(DEMO), "run",
         "--before", str(good_before), "--after", str(good_after)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=demo_no_contrast" in r.stdout
    assert "board is on the after payload" in r.stderr
