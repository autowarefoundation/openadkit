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
