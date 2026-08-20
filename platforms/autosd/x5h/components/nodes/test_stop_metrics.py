"""Unit tests for scripts/x5h-stop-metrics.awk (stop-distance metric).

Runs plain awk via subprocess -- no ROS. The inline records built by
odom_record() below follow the exact YAML layout `ros2 topic echo` prints
for nav_msgs/Odometry; the fixtures/ excerpts captured on the board pin the
parser against the real thing.

Fixture provenance:
  fixtures/events_fault_record.txt and fixtures/kinematic_state_board_
  excerpt.txt are both REAL board material, cut verbatim from the SAME
  `x5h-stack-smoke.sh drive` run: events_fault_record.txt is that run's
  fault-injection record from /simulation/events, and kinematic_state_
  board_excerpt.txt is a 9-record excerpt of that run's full
  /localization/kinematic_state capture (3 records at the fault, 3
  mid-deceleration, 3 spanning the actual rest transition). Being a
  matched pair from one run lets test_stop_metrics_chain_from_real_
  fixtures below chain t0 extraction into the metric computation exactly
  as x5h-stack-smoke.sh's drive mode does.

Run from this directory with `python3 -m pytest test_stop_metrics.py`.
"""
import subprocess
from pathlib import Path

AWK = Path(__file__).resolve().parents[2] / "scripts" / "x5h-stop-metrics.awk"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def odom_record(sec, x, vx, y=0.0):
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
      y: {y}
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


def test_curved_stop_uses_path_length_not_displacement(tmp_path):
    # A right-angle turn: the ego runs along +x, then turns and runs along
    # +y, coming to rest after the turn. Path length is the sum of the two
    # legs (6 + 6 + 3 = 15.00 m); the straight-line chord from the t0 sample
    # to rest is sqrt(6**2 + 9**2) = 10.82 m. The two numbers must differ,
    # or this test isn't exercising anything -- this is exactly the
    # scenario the awk's header comment cites as the reason path length
    # (not displacement) was chosen: "a stop that begins in a curve
    # compares fairly across runs." A regression that summed displacement
    # instead of per-segment path length would report 10.82, not 15.00.
    text = "".join(
        odom_record(s, x, v, y=y)
        for s, x, y, v in [
            (200, 0.0, 0.0, 8.0),
            (201, 6.0, 0.0, 6.0),
            (202, 6.0, 6.0, 3.0),
            (203, 6.0, 9.0, 0.01),
            (204, 6.0, 9.0, 0.0),
        ]
    )
    r = run_metrics(text, 200, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "stop_distance_m=15.00 rest_x=6.00 rest_y=9.00"


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


def test_board_kinematic_excerpt_parses(tmp_path):
    # Real board excerpt (see module docstring): 9 records cut verbatim
    # from a full 9062-record /localization/kinematic_state capture taken
    # during the same drive run as fixtures/events_fault_record.txt. The
    # 9-record excerpt reproduces the full capture's metric exactly, to
    # both decimals, including the same rest point -- the ego stops nearly
    # straight, so the chord sum across these sparse samples matches the
    # dense path length. Assert the real, board-measured output exactly
    # rather than just checking for a metric line.
    text = (FIXTURES / "kinematic_state_board_excerpt.txt").read_text()
    first_sec = int(
        [l for l in text.splitlines() if l.startswith("    sec: ")][0].split()[1]
    )
    r = run_metrics(text, first_sec, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "stop_distance_m=39.55 rest_x=59084.83 rest_y=42971.53"

    # The fixture genuinely crosses the REST_V boundary (0.05, not a
    # synthetic round number): one real sample at vx=0.05357195454674935
    # (>= REST_V, still counts as moving) is immediately followed by one
    # at vx=0.043572340309790035 (< REST_V, at rest). Confirm both boundary
    # samples are present, in that order, and that rest landed on the
    # record *after* the >= REST_V sample (rest_x=59084.83, matching the
    # second sample's position) rather than being misclassified onto the
    # boundary record itself.
    assert text.count("\n      x: 0.05357195454674935\n") == 1
    assert text.count("\n      x: 0.043572340309790035\n") == 1
    assert text.index("0.05357195454674935") < text.index("0.043572340309790035")
    assert r.stdout.strip().split()[1] == "rest_x=59084.83"


def test_real_events_record_yields_t0(tmp_path):
    text = (FIXTURES / "events_fault_record.txt").read_text()
    r = run_t0(text, "name: cpu_temperature_is_high", tmp_path)
    assert r.returncode == 0
    # This fixture is real board material with a known stamp
    # (sec=1785631510, nanosec=435408440); pin the round-trip exactly
    # rather than just checking positivity. The tolerance (rather than an
    # exact match) accounts for the double-precision rounding awk performs
    # when it sums sec + nanosec/1e9: it prints 1785631510.435408354, not
    # ...440.
    assert abs(float(r.stdout) - 1785631510.435408440) < 1e-3


def test_stop_metrics_chain_from_real_fixtures(tmp_path):
    # The end-to-end chain x5h-stack-smoke.sh's drive mode actually runs:
    # derive t0 from the real fault-injection record, then feed that t0
    # into the metric computation against the real kinematic excerpt from
    # the same run. Both fixtures come from one board session, so this is
    # the first test that exercises the real fault-anchor and the real
    # Odometry parse together.
    events_text = (FIXTURES / "events_fault_record.txt").read_text()
    t0_result = run_t0(events_text, "name: cpu_temperature_is_high", tmp_path)
    assert t0_result.returncode == 0
    t0 = t0_result.stdout.strip()

    kinematic_text = (FIXTURES / "kinematic_state_board_excerpt.txt").read_text()
    r = run_metrics(kinematic_text, t0, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "stop_distance_m=39.55 rest_x=59084.83 rest_y=42971.53"
