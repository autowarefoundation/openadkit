"""Unit tests for make_demo_reel.py. No board, no bench, no ffmpeg run.

What is covered here is the arithmetic that decides which source frame lands
in which output frame, and every refusal. The refusals matter as much as the
arithmetic: this script composes a video that a viewer reads as evidence, so a
stream that is missing, short or misaligned has to stop the composition rather
than become a black pane or a held frame nobody notices.
"""

import json
import subprocess
import sys

import pytest
from PIL import Image

import make_demo_reel as m


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def make_run(tmp_path, *, fault_at=1000.0, hud_frames=20, cam_rows=20, console_from=970.0):
    """A minimal but complete run directory, as record-demo.sh leaves it."""
    run = tmp_path / "run"
    chase = run / "chase"
    camera = run / "camera"
    hud = run / "hud"
    camera.mkdir(parents=True, exist_ok=True)
    rows = ["file,bench_time"]
    for i in range(cam_rows):
        Image.new("RGB", (32, 18), (10, 20, 30)).save(camera / f"cam_{i:04d}.jpg")
        rows.append(f"cam_{i:04d}.jpg,{fault_at - (cam_rows - 1 - i) * 0.1:.3f}")
    write(camera / "index.csv", "\n".join(rows) + "\n")

    chase.mkdir(parents=True, exist_ok=True)
    crows = ["file,bench_time"]
    for i in range(cam_rows * 2):
        Image.new("RGB", (32, 18), (40, 50, 60)).save(chase / f"chase_{i:04d}.jpg")
        crows.append(f"chase_{i:04d}.jpg,{fault_at - (cam_rows * 2 - 1 - i) * 0.05:.3f}")
    write(chase / "index.csv", "\n".join(crows) + "\n")

    hud.mkdir(parents=True, exist_ok=True)
    journal = []
    for i in range(hud_frames):
        Image.new("RGB", (32, 18), (70, 10, 10)).save(hud / f"frame_{i:06d}.png")
        journal.append(
            f"[  {500.0 + i * 0.1:12.6f}] board podman[1]: "
            "[VP] Latency  pre=1.8 ms  merged=21.0 ms  wall=23.6 ms  42 fps"
        )
    write(hud / "vp-journal.txt", "\n".join(journal) + "\n")

    write(run / "cr52-console.txt", "\n".join(
        f"{console_from + i * 0.5:.3f} [SI] beacon {i}" for i in range(80)) + "\n")
    write(run / "trace.csv", "kind,t_rel_s,x,y,value\n"
          "odom,-2.000,10.000,20.000,12.000\n"
          "odom,-1.000,22.000,20.000,12.000\n"
          "odom,0.000,34.000,20.000,12.000\n"
          "odom,1.000,45.000,20.000,9.000\n"
          "ack_accel,0.100,,,-3.000\n"
          "cr52_cmd,0.050,,,\n")
    write(run / "manifest.json", json.dumps({
        "run_id": "20260918-134501",
        "mode": "kill",
        "fault_at": fault_at,
        "streams": {
            "chase": {"dir": "chase", "index": "chase/index.csv"},
            "camera": {"dir": "camera", "index": "camera/index.csv"},
            "hud": {"dir": "hud", "journal": "hud/vp-journal.txt"},
            "console": {"file": "cr52-console.txt"},
            "trace": {"file": "trace.csv"},
        },
    }))
    return run


# --- the index files ---------------------------------------------------------

def test_read_index_sorts_by_time(tmp_path):
    p = write(tmp_path / "index.csv", "file,bench_time\nb.jpg,2.0\na.jpg,1.0\n")
    assert m.read_index(p) == [(1.0, "a.jpg"), (2.0, "b.jpg")]


def test_read_index_rejects_a_wrong_header(tmp_path):
    p = write(tmp_path / "index.csv", "name,t\na.jpg,1.0\n")
    with pytest.raises(m.ReelError) as e:
        m.read_index(p)
    assert e.value.reason == "bad_index_header"


def test_read_index_rejects_an_empty_index(tmp_path):
    p = write(tmp_path / "index.csv", "file,bench_time\n")
    with pytest.raises(m.ReelError) as e:
        m.read_index(p)
    assert e.value.reason == "empty_index"


# --- the board clock offset --------------------------------------------------

def test_hud_times_put_the_last_rendered_frame_at_the_fault():
    journal = "\n".join(
        f"[  {100.0 + i * 0.1:12.6f}] x podman[1]: [VP] Latency  pre=1.8 ms  wall=23.6 ms  42 fps"
        for i in range(4))
    t = m.hud_frame_times(journal, fault_at=5000.0)
    assert t[-1] == pytest.approx(5000.0)
    # The offset is one constant, so the board's own spacing survives it.
    assert t[0] == pytest.approx(4999.7)
    assert len(t) == 4


def test_hud_times_ignore_lines_that_are_not_per_frame_latency():
    journal = (
        "[    100.000000] x podman[1]: [VP] starting, Latency budget 30 ms\n"
        "[    100.100000] x podman[1]: [VP] Latency  pre=1.8 ms  wall=23.6 ms  42 fps\n"
        "[    100.200000] x podman[1]: [VP] Latency  pre=1.9 ms  wall=24.1 ms  41 fps\n")
    assert len(m.hud_frame_times(journal, fault_at=1.0)) == 2


def test_hud_times_refuse_a_journal_with_no_frames():
    with pytest.raises(m.ReelError) as e:
        m.hud_frame_times("[ 1.000000] x podman[1]: [VP] starting\n", fault_at=1.0)
    assert e.value.reason == "no_hud_frames"


def test_hud_times_refuse_a_journal_with_no_monotonic_stamp():
    # journalctl -o short-monotonic is what the pull script asks for. Any other
    # output format silently yields no stamps, and a reel anchored on nothing
    # is worse than no reel.
    with pytest.raises(m.ReelError) as e:
        m.hud_frame_times("Sep 18 13:45:01 board podman[1]: [VP] Latency  wall=23.6 ms\n", 1.0)
    assert e.value.reason == "no_hud_frames"


# --- the cross-check --------------------------------------------------------

def test_alignment_accepts_a_small_count_difference():
    hud = [1000.0 + i * 0.1 for i in range(-20, 1)]
    cam = [1000.0 + i * 0.1 for i in range(-23, 1)]
    m.check_alignment(hud, cam, fault_at=1000.0, pre_window=2.0)


def test_alignment_refuses_a_run_that_dropped_input_frames():
    # 21 HUD frames against 41 camera samples over the same two seconds: the
    # positional frame-to-line mapping cannot be trusted here.
    hud = [1000.0 + i * 0.1 for i in range(-20, 1)]
    cam = [1000.0 + i * 0.05 for i in range(-40, 1)]
    with pytest.raises(m.ReelError) as e:
        m.check_alignment(hud, cam, fault_at=1000.0, pre_window=2.0)
    assert e.value.reason == "count_mismatch"


# --- the output timeline ----------------------------------------------------

def test_timeline_spaces_a_real_time_chapter_by_the_output_tick():
    t = m.timeline([m.Chapter("drive", -1.0, 0.0, 1.0)], fps=20)
    assert len(t) == 20
    assert t[0] == pytest.approx(-1.0)
    assert t[1] == pytest.approx(-0.95)


def test_timeline_stretches_a_slow_chapter():
    # One second of source at a quarter speed is four seconds of screen time.
    t = m.timeline([m.Chapter("fault", -0.5, 0.5, 0.25)], fps=20)
    assert len(t) == 80
    assert t[-1] < 0.5


def test_timeline_concatenates_chapters_in_order():
    t = m.timeline([m.Chapter("a", 0.0, 1.0, 1.0), m.Chapter("b", 5.0, 6.0, 1.0)], fps=20)
    assert len(t) == 40
    assert t[20] == pytest.approx(5.0)


def test_timeline_refuses_a_chapter_that_runs_backwards():
    with pytest.raises(m.ReelError) as e:
        m.timeline([m.Chapter("bad", 1.0, 0.0, 1.0)], fps=20)
    assert e.value.reason == "bad_chapter"


# --- placing a source frame in an output frame ------------------------------

def test_pick_takes_the_newest_frame_at_or_before_the_instant():
    times = [10.0, 10.1, 10.2]
    assert m.pick(times, 10.15) == 1
    assert m.pick(times, 10.2) == 2


def test_pick_holds_the_first_frame_before_the_stream_starts():
    assert m.pick([10.0, 10.1], 9.0) == 0


def test_pick_holds_the_last_frame_after_the_stream_ends():
    # The HUD stream ends at the fault by construction: every output frame
    # after it holds VisionPilot's last picture, which is the truth.
    assert m.pick([10.0, 10.1], 30.0) == 1


# --- the console pane -------------------------------------------------------

def test_console_window_returns_the_lines_already_printed():
    lines = m.read_console("100.000 a\n100.500 b\n101.000 c\n")
    assert m.console_window(lines, 100.7, 10) == ["100.000 a", "100.500 b"]


def test_console_window_keeps_only_the_last_n_lines():
    lines = m.read_console("".join(f"{100 + i}.000 line {i}\n" for i in range(20)))
    assert len(m.console_window(lines, 200.0, 5)) == 5


def test_console_refuses_a_capture_that_misses_the_window():
    lines = m.read_console("100.000 a\n100.500 b\n")
    with pytest.raises(m.ReelError) as e:
        m.check_console_covers(lines, first=99.0, last=120.0)
    assert e.value.reason == "console_short"


def test_console_refuses_an_unstamped_capture():
    with pytest.raises(m.ReelError) as e:
        m.read_console("[SI] beacon 1\n[SI] beacon 2\n")
    assert e.value.reason == "console_unstamped"


# --- the trace pane ---------------------------------------------------------

def test_read_trace_splits_the_kinds_and_keeps_fault_relative_time():
    tr = m.read_trace("kind,t_rel_s,x,y,value\n"
                      "odom,-1.000,1.0,2.0,12.000\n"
                      "ack_accel,0.100,,,-3.000\n"
                      "cr52_cmd,0.050,,,\n")
    assert tr["odom"] == [(-1.0, 12.0)]
    assert tr["ack_accel"] == [(0.1, -3.0)]
    assert tr["cr52_cmd"] == [(0.05, 0.0)]


def test_read_trace_refuses_a_file_with_no_odometry():
    with pytest.raises(m.ReelError) as e:
        m.read_trace("kind,t_rel_s,x,y,value\nack_accel,0.100,,,-3.000\n")
    assert e.value.reason == "no_odom"


# --- loading a whole run ----------------------------------------------------

def test_load_run_reads_a_complete_run(tmp_path):
    run = make_run(tmp_path)
    r = m.load_run(run)
    assert r.fault_at == 1000.0
    assert r.mode == "kill"
    assert len(r.hud) == 20
    assert r.hud_times[-1] == pytest.approx(1000.0)


def test_load_run_refuses_a_manifest_without_the_fault(tmp_path):
    run = make_run(tmp_path)
    data = json.loads((run / "manifest.json").read_text())
    del data["fault_at"]
    (run / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(m.ReelError) as e:
        m.load_run(run)
    assert e.value.reason == "no_fault_at"


def test_load_run_refuses_a_missing_stream(tmp_path):
    run = make_run(tmp_path)
    (run / "trace.csv").unlink()
    with pytest.raises(m.ReelError) as e:
        m.load_run(run)
    assert e.value.reason == "missing_stream"


def test_load_run_refuses_an_empty_hud_directory(tmp_path):
    run = make_run(tmp_path)
    for p in (run / "hud").glob("*.png"):
        p.unlink()
    with pytest.raises(m.ReelError) as e:
        m.load_run(run)
    assert e.value.reason == "no_hud_pngs"


def test_load_run_refuses_a_rate_limited_journal(tmp_path):
    # journald drops messages under its own rate limit and says so in one line.
    # VisionPilot prints a Latency line per frame at up to 40 frames a second,
    # which is exactly the traffic that limit exists to cut. A journal with a
    # hole in it maps HUD frames to the wrong instants and looks fine.
    run = make_run(tmp_path)
    j = run / "hud" / "vp-journal.txt"
    j.write_text(j.read_text() + "[    501.000000] board systemd-journald[9]: "
                 "Suppressed 214 messages from x5h-vp.service\n")
    with pytest.raises(m.ReelError) as e:
        m.load_run(run)
    assert e.value.reason == "journal_suppressed"


def test_load_run_drops_the_one_frame_the_kill_truncated(tmp_path):
    # The sink writes the PNG, then VisionPilot prints that frame's Latency
    # line. A kill between the two leaves exactly one PNG with no time.
    run = make_run(tmp_path)
    j = run / "hud" / "vp-journal.txt"
    lines = j.read_text().splitlines()
    j.write_text("\n".join(lines[:-1]) + "\n")
    r = m.load_run(run)
    assert len(r.hud) == len(r.hud_times) == 19


def test_load_run_refuses_fewer_pngs_than_journal_frames(tmp_path):
    # The sink writes one PNG per rendered frame, so a shortfall means the pull
    # lost files. Composing anyway shifts every HUD frame by the difference.
    run = make_run(tmp_path)
    (run / "hud" / "frame_000019.png").unlink()
    with pytest.raises(m.ReelError) as e:
        m.load_run(run)
    assert e.value.reason == "hud_png_count"


# --- rendering --------------------------------------------------------------

def test_render_frame_returns_one_composed_picture(tmp_path):
    r = m.load_run(make_run(tmp_path))
    img = m.render_frame(r, t_rel=-0.5, chapter=m.Chapter("drive", -2.0, 0.0, 1.0))
    assert img.size == (m.WIDTH, m.HEIGHT)
    assert img.mode == "RGB"


def test_render_frame_after_the_fault_still_composes(tmp_path):
    r = m.load_run(make_run(tmp_path))
    img = m.render_frame(r, t_rel=1.0, chapter=m.Chapter("stop", 0.0, 2.0, 1.0))
    assert img.size == (m.WIDTH, m.HEIGHT)


def test_cards_are_the_declared_size(tmp_path):
    r = m.load_run(make_run(tmp_path))
    assert m.title_card(r).size == (m.WIDTH, m.HEIGHT)
    assert m.closing_card(r).size == (m.WIDTH, m.HEIGHT)


# --- the ffmpeg call --------------------------------------------------------

def test_ffmpeg_argv_feeds_raw_frames_of_the_declared_size(tmp_path):
    argv = m.ffmpeg_argv(tmp_path / "reel.mp4", fps=20)
    assert argv[0] == "ffmpeg"
    assert f"{m.WIDTH}x{m.HEIGHT}" in argv
    assert "rawvideo" in argv
    assert str(tmp_path / "reel.mp4") in argv
    assert "-r" in argv and "20" in argv


# --- the command line -------------------------------------------------------

def test_the_script_fails_loudly_on_a_run_that_is_not_there(tmp_path):
    p = subprocess.run(
        [sys.executable, str(m.__file__), str(tmp_path / "nope"), "--dry-run"],
        capture_output=True, text=True)
    assert p.returncode != 0
    assert "DEMO_REEL_FAIL reason=" in p.stdout + p.stderr


def test_dry_run_reports_the_frame_count_without_writing_a_file(tmp_path):
    run = make_run(tmp_path)
    out = tmp_path / "reel.mp4"
    p = subprocess.run(
        [sys.executable, str(m.__file__), str(run), "--out", str(out), "--dry-run",
         "--card-seconds", "1",
         "--chapter", "drive:-1.5:-0.5:1", "--chapter", "fault:-0.5:0:0.25"],
        capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "DEMO_REEL_PLAN frames=" in p.stdout
    assert not out.exists()


# --- clipping the cut to the recorded material ------------------------------

def test_clip_drops_a_late_chapter_and_reports_it(tmp_path):
    r = m.load_run(make_run(tmp_path))       # chase covers -2.0 .. 0.0
    kept, notes = m.clip_chapters([
        m.Chapter("drive", -1.5, -0.5, 1.0),
        m.Chapter("fault", -0.5, 0.0, 0.25),
        m.Chapter("reset", 20.0, 40.0, 1.0),
    ], r)
    assert [c.name for c in kept] == ["drive", "fault"]
    assert any("reset" in n for n in notes)


def test_clip_refuses_to_lose_the_fault(tmp_path):
    r = m.load_run(make_run(tmp_path))
    with pytest.raises(m.ReelError) as e:
        m.clip_chapters([
            m.Chapter("drive", -120.0, -100.0, 1.0),
            m.Chapter("fault", -100.0, -99.0, 0.25),
        ], r)
    assert e.value.reason == "fault_uncovered"


def test_the_built_in_cut_runs_about_three_minutes():
    # The cut is a table meant to be tuned, but a cut nobody can sit through,
    # or one that is over before it explains anything, is a defect in the table
    # rather than in the code. 20 fps, two 15 s cards, a 10 s card per chapter
    # that has one.
    chapters = [m.Chapter(*c) for c in m.DEFAULT_CHAPTERS]
    n = (len(m.timeline(chapters, fps=20)) + 2 * 15 * 20
         + 10 * 20 * sum(1 for c in chapters if c.intro))
    assert 165 <= n / 20 <= 300


def test_every_chapter_but_the_last_explains_itself():
    # The explanation cards are the reason this reel is watchable by someone
    # who has never seen the bench. Losing one to an edit would not fail
    # anything else.
    chapters = [m.Chapter(*c) for c in m.DEFAULT_CHAPTERS]
    assert all(c.intro for c in chapters[:-1])
