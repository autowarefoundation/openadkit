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


def test_run_aborts_before_board_contact_on_bad_before_payload(tmp_path):
    """A failing gate on the FIRST (before) payload of a `run` invocation
    must abort before any board contact -- this is exactly the case the
    subshell bug in gate_payload() would have broken: `run` would have
    sailed past the failed gate and gone on to flash an unvalidated
    payload. Point X5H_DEMO_SITE_CONF at a temp site.conf (with obviously
    fake values -- the real slot geometry is NDA'd and lives outside this
    repo) so `run` gets past load_site_conf, then give it a bad --before
    payload. ssh/scp are stubbed onto PATH as scripts that always fail, so
    if the gate did NOT abort first, the test would fail loudly (via a
    demo_flash_failed:*:scp/write_verify marker or a hang) instead of
    silently reaching the network.
    """
    site_conf = tmp_path / "site.conf"
    site_conf.write_text(
        "X5H_SLOT_DEV=/dev/fake-slot-placeholder\n"
        "X5H_SLOT_SKIP=999999\n"
        "X5H_SLOT_EXTENT_SECTORS=1\n"
        f"X5H_SLOT_BASELINE={tmp_path / 'fake-baseline.bin'}\n"
    )
    (tmp_path / "fake-baseline.bin").write_bytes(b"\x00")

    # Stub ssh/scp on PATH so the test cannot reach 192.168.0.20 even if the
    # gate fix regresses: any attempted board contact fails immediately
    # instead of blocking on a real network call.
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for tool in ("ssh", "scp"):
        stub = bin_dir / tool
        stub.write_text("#!/bin/sh\necho 'stub: network access blocked' >&2\nexit 99\n")
        stub.chmod(0o755)

    bad_before = payload(tmp_path, "wrong-profile", name="before.bin")
    good_after = payload(tmp_path, "after", name="after.bin")

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "X5H_DEMO_SITE_CONF": str(site_conf),
    }
    r = subprocess.run(
        [
            "bash", str(DEMO), "run",
            "--before", str(bad_before),
            "--after", str(good_after),
        ],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "X5H_DEMO_FAIL reason=demo_wrong_profile:before" in r.stdout
    # The gate must have failed before any ssh/scp stub ran.
    assert "stub: network access blocked" not in r.stderr
