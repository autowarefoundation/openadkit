"""Unit tests for scripts/x5h-stop-metrics.awk (stop-distance metric).

Runs plain awk via subprocess -- no ROS. The synthetic records below follow
the exact YAML layout `ros2 topic echo` prints for nav_msgs/Odometry; the
fixtures/ excerpts captured on the board pin the parser against the real
thing.

Fixture provenance:
  fixtures/events_fault_record.txt is REAL board material, copied verbatim
  from a probe capture of /simulation/events.
  fixtures/kinematic_state_synthetic_excerpt.txt is SYNTHETIC. The board's
  existing kinematic-state log on disk is a `--field` projection (x:/y:/z:
  only, no stamp, no velocity) and cannot pin the nav_msgs/Odometry parser,
  and the board's stack was not brought up to capture a fresh one for this
  task. This fixture must be re-pinned against a real board capture in the
  Task 8 board session.

Run from this directory with `python3 -m pytest test_stop_metrics.py`.
"""
import subprocess
from pathlib import Path

AWK = Path(__file__).resolve().parents[2] / "scripts" / "x5h-stop-metrics.awk"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def odom_record(sec, x, vx):
    return f"""header:
  stamp:
    sec: {sec}
    nanosec: 0
  frame_id: map
child_frame_id: base_link
pose:
  pose:
    position:
      x: {x}
      y: 0.0
      z: 0.0
    orientation:
      x: 0.0
      y: 0.0
      z: 0.0
      w: 1.0
  covariance:
  - 0.0
twist:
  twist:
    linear:
      x: {vx}
      y: 0.0
      z: 0.0
    angular:
      x: 0.0
      y: 0.0
      z: 0.0
  covariance:
  - 0.0
---
"""


def run_metrics(text, t0, tmp_path):
    f = tmp_path / "capture.txt"
    f.write_text(text)
    return subprocess.run(
        ["awk", "-v", f"t0={t0}", "-f", str(AWK), str(f)],
        capture_output=True, text=True,
    )


def run_t0(text, pat, tmp_path):
    f = tmp_path / "capture.txt"
    f.write_text(text)
    return subprocess.run(
        ["awk", "-v", "mode=t0", "-v", f"pat={pat}", "-f", str(AWK), str(f)],
        capture_output=True, text=True,
    )


def test_straight_line_stop_distance(tmp_path):
    # 8 -> 0 m/s over positions 0,8,14,18,20,20: rest is the first sample
    # whose speed stays < 0.05, so distance = 20.00 from the t0 sample.
    text = "".join(
        odom_record(s, x, v)
        for s, x, v in [
            (100, 0.0, 8.0), (101, 8.0, 6.0), (102, 14.0, 4.0),
            (103, 18.0, 2.0), (104, 20.0, 0.01), (105, 20.0, 0.0),
        ]
    )
    r = run_metrics(text, 100, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("stop_distance_m=20.00 rest_x=20.00")


def test_samples_before_t0_are_excluded(tmp_path):
    text = "".join(
        odom_record(s, x, v)
        for s, x, v in [
            (90, -100.0, 8.0),  # pre-fault: must not count
            (100, 0.0, 8.0), (101, 8.0, 0.0), (102, 8.0, 0.0),
        ]
    )
    r = run_metrics(text, 100, tmp_path)
    assert r.returncode == 0
    assert r.stdout.startswith("stop_distance_m=8.00")


def test_never_rested(tmp_path):
    text = "".join(odom_record(100 + i, 8.0 * i, 8.0) for i in range(4))
    r = run_metrics(text, 100, tmp_path)
    assert r.returncode == 1
    assert "never_rested" in r.stdout


def test_empty_capture_is_no_metrics(tmp_path):
    r = run_metrics("", 100, tmp_path)
    assert r.returncode == 1
    assert "no_stop_metrics" in r.stdout


def test_t0_mode_extracts_fault_stamp(tmp_path):
    text = (
        "stamp:\n  sec: 200\n  nanosec: 500000000\n"
        "level: 2\nname: cpu_temperature_is_high\n---\n"
    )
    r = run_t0(text, "name: cpu_temperature_is_high", tmp_path)
    assert r.returncode == 0
    assert abs(float(r.stdout) - 200.5) < 1e-6


def test_t0_mode_no_match_fails(tmp_path):
    r = run_t0("name: something_else\n---\n", "name: cpu_temperature_is_high", tmp_path)
    assert r.returncode == 1
    assert r.stdout.strip() == ""


def test_synthetic_kinematic_excerpt_parses(tmp_path):
    # Synthetic excerpt (see module docstring): the parser must extract
    # >= 2 samples and produce a metric line (values asserted loosely --
    # this fixture is not yet pinned to a real board capture).
    text = (FIXTURES / "kinematic_state_synthetic_excerpt.txt").read_text()
    first_sec = int(
        [l for l in text.splitlines() if l.startswith("    sec: ")][0].split()[1]
    )
    r = run_metrics(text, first_sec, tmp_path)
    assert "stop_distance_m=" in r.stdout or "never_rested" in r.stdout


def test_real_events_record_yields_t0(tmp_path):
    text = (FIXTURES / "events_fault_record.txt").read_text()
    r = run_t0(text, "name: cpu_temperature_is_high", tmp_path)
    assert r.returncode == 0
    # This fixture is real board material with a known stamp
    # (sec=1785573136, nanosec=845681675); pin the round-trip exactly
    # rather than just checking positivity.
    assert abs(float(r.stdout) - 1785573136.845681675) < 1e-3
