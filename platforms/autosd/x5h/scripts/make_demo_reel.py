#!/usr/bin/env python3
"""Compose the CES 2027 demo reel from one recording run.

  make_demo_reel.py <run-dir> [--out reel.mp4] [--fps 20] [--dry-run]
                    [--chapter NAME:T0:T1:SPEED ...]

The run directory is what Simulation/CARLA/ROS2/si/record-demo.sh on the bench
leaves behind, with the board's HUD frames added by x5h-pull-demo-frames.sh.
manifest.json describes it. Every path in the manifest is relative to the run
directory, and every time in this script is in seconds relative to the fault,
because that is the only instant all six streams share.

Four panes, 2x2 under one banner, over a full-width DLT strip: the chase
camera, VisionPilot's own HUD from the board, the CR52 console, and a plot pane
with two rows, VisionPilot's frame time over its deadline and the speed and
command trace. The strip shows the last DLT messages from the S-CORE launch
manager and VisionPilot. The banner reads the offset from the fault, so the
claim that every pane shows the same instant is on screen and checkable.

**Why the fault and not a clock.** The X5H board has no RTC and no NTP on the
bench LAN, so its log timestamps are wrong by days. The board clock is steady
inside a run, so one constant offset is enough, and the run supplies it: the
`kill` route ends VisionPilot, so its last rendered frame IS the fault. The
offset is fault_at minus the monotonic stamp of the last per-frame Latency
line. A `slow` run anchors on the first frame over its deadline instead,
because VisionPilot renders on until the launch manager stops it. Alignment is therefore good to one VisionPilot frame, 25 to 40 ms at the
measured 23.6 ms wall time, plus the rpmsg and DDS latency the fault itself
takes to reach the firmware.
DLT messages carry the board's own monotonic stamp, the clock of the journal,
so the same offset places them. The reel never claims better than that.

Underscores in the file name, unlike its hyphenated neighbours in this
directory: its tests import it, and `import make-demo-reel` is not a thing.

Dependencies: Pillow, and the ffmpeg binary for anything but --dry-run.
Markers: DEMO_REEL_PLAN / DEMO_REEL_WRITTEN / DEMO_REEL_FAIL reason=<slug>.
"""

import argparse
import bisect
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from dlt_file import LEVELS, DltError, read_dlt

WIDTH, HEIGHT = 1920, 1080
BANNER_H = 60
# The full-width DLT strip under the 2x2 panes, and how many lines it shows.
STRIP_H = 180
DLT_LINES = 6
PANE_W, PANE_H = WIDTH // 2, (HEIGHT - BANNER_H - STRIP_H) // 2
# The frame time row at the top of the bottom-right pane, and its y axis. A
# slow-fault frame takes about 280 ms in a recording run.
FT_H = 180
FT_MAX_MS = 400.0
APP_COLOURS = {"VP": (120, 200, 255), "LM": (255, 200, 90)}
CONSOLE_LINES = 16
# How far before the fault the HUD and camera frame counts are compared. Two
# seconds is enough to catch a run that dropped input frames and short enough
# that a late start does not read as a drop.
PRE_WINDOW = 2.0
# Seconds either side of the fault that the speed plot covers.
PLOT_WINDOW_S = 15.0
# A positional HUD-frame-to-journal-line mapping tolerates a small count
# difference (a stream starting a frame early, the window edge) and nothing
# more. Five frames is half a second of input at 10 Hz.
COUNT_TOLERANCE = 5
# Every stream load_run reads. record-demo.sh names all six in the manifest.
REQUIRED_STREAMS = {"chase", "camera", "hud", "console", "trace", "dlt"}
# The arrival lag a DLT message may show against its own board stamp, once both
# are on the bench clock. The datarouter reads its clients and flushes every
# 100 ms, so a real lag is 0 to about 250 ms. The margins cover one VisionPilot
# frame of anchor error. A wrong offset, or a board up longer than 4.97 days
# (the 0.1 ms stamp is 32 bits), is off by far more.
DLT_LAG_S = (-0.5, 1.0)

# The cut. Times are seconds from the fault, speed is playback rate: 0.25 means
# one second of the run takes four seconds of screen time. Tune this table once
# real material exists. --dry-run prints the resulting length, and a chapter
# that reaches past the recorded material is clipped or dropped, with a note.
#
# This cut asks the recording for about 70 s of driving before the fault, which
# is DRIVE_S=70 in record-demo.sh. It asks for nothing after the gate's own 30 s
# measuring window, because the bench recorders stop when run-d6.sh returns: a
# chapter about the operator's reset would have no pictures in it.
#
# Slower than 0.25x is not worth asking for. The chase camera is capped by the
# CARLA server's own 10 Hz step, so at 0.25x each of its frames already fills
# eight output frames, and below that the pane visibly steps instead of moving.
#
# The explanation cards are what make this a 3 minute video rather than a 2
# minute one. Padding the driving chapter would be the other way to get there,
# and it would teach the viewer nothing.
DEFAULT_CHAPTERS = [
    ("normal driving: VisionPilot steers on the NPU", -65.0, -3.0, 1.0, (
        ("Top left: CARLA on the bench host, chasing the car.", 30),
        ("Top right: what VisionPilot draws, rendered on the X5H board itself.", 30),
        ("Bottom left: the CR52 Safety Island's own console.", 30),
        ("Bottom right: VisionPilot's frame time, then the car's speed and commands.", 30),
        ("Bottom strip: S-CORE and VisionPilot log messages, over DLT.", 30),
        ("", 20),
        ("The board has no clock the bench can read, so every pane", 26),
        ("is aligned on the fault instant, to within one rendered frame.", 26),
    )),
    ("the fault: VisionPilot stops answering", -3.0, 1.0, 0.25, (
        ("VisionPilot sends the Safety Island a heartbeat over rpmsg.", 30),
        ("The process is killed here. The heartbeat stops with it.", 30),
        ("The S-CORE launch manager sees the exit and switches to its fallback.", 30),
        ("", 20),
        ("Quarter speed from here, so the half second the CR52 waits", 26),
        ("before it decides is long enough to watch.", 26),
    )),
    ("the Safety Island brakes the car", 1.0, 11.0, 0.5, (
        ("Two routes reach the CR52: the launch manager's fallback over rpmsg,", 30),
        ("and the heartbeat that stopped. The first to arrive starts a steady stop.", 30),
    )),
    ("the car is stopped", 11.0, 22.0, 1.0, ()),
]
# The cut for a slow run under the S-CORE launch manager. The fault chapter runs
# to 1.5 s because the CR52 command comes 1.1-1.2 s after the fault, not 0.5 s.
SLOW_CHAPTERS = [
    DEFAULT_CHAPTERS[0],
    ("the fault: VisionPilot runs too slow", -3.0, 1.5, 0.25, (
        ("VisionPilot reports every frame to the S-CORE health monitor.", 30),
        ("From here each frame takes 200 ms longer, and the output rate drops with it.", 30),
        ("Its output still reaches the Safety Island inside the 0.5 s limit,", 30),
        ("so only the health monitor sees that it is late.", 30),
        ("", 20),
        ("The health monitor fails the first late frame, and the launch", 26),
        ("manager stops VisionPilot. Quarter speed, so it can be watched.", 26),
    )),
    ("the Safety Island brakes the car", 1.5, 11.5, 0.5, (
        ("The heartbeat ends with VisionPilot, and the CR52 takes over.", 30),
        ("It commands a steady stop. The launch manager's fallback also latches the fault.", 30),
    )),
    ("the car is stopped", 11.5, 22.0, 1.0, ()),
]
# Clipping a chapter shortens the reel. Clipping these two would remove the
# event the reel exists to show, so they are refused instead.
REQUIRED_CHAPTERS = 2


class ReelError(Exception):
    """A refusal with a slug, so the marker line names the cause."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason} {detail}".strip())
        self.reason = reason


@dataclass
class Chapter:
    name: str
    t0: float
    t1: float
    speed: float
    # Lines of an explanation card shown before the chapter, as (text, size).
    intro: tuple = ()


@dataclass
class Run:
    run_dir: Path
    mode: str
    fault_at: float
    chase: list = field(default_factory=list)      # [(bench_time, Path)]
    camera: list = field(default_factory=list)     # [(bench_time, Path)]
    hud: list = field(default_factory=list)        # [Path], frame order
    hud_times: list = field(default_factory=list)  # bench time per hud frame
    console: list = field(default_factory=list)    # [(bench_time, text)]
    trace: dict = field(default_factory=dict)
    frame_ms: list = field(default_factory=list)   # [(bench_time, ms)], one per frame
    dlt: list = field(default_factory=list)        # [(bench_time, DltMsg)], sorted

    def rel(self, bench_time):
        return bench_time - self.fault_at


# --- reading the streams ----------------------------------------------------

def read_index(path):
    """[(bench_time, file name)] from an image stream's index.csv, sorted.

    The recorders write frames in arrival order, but a sorted list is what
    pick() bisects, and an unsorted index would place frames at random with no
    symptom other than a jumpy pane.
    """
    lines = [ln for ln in Path(path).read_text().splitlines() if ln.strip()]
    if not lines or lines[0].strip() != "file,bench_time":
        raise ReelError("bad_index_header", str(path))
    rows = []
    for ln in lines[1:]:
        name, _, t = ln.rpartition(",")
        try:
            rows.append((float(t), name))
        except ValueError as exc:
            raise ReelError("bad_index_row", ln) from exc
    if not rows:
        raise ReelError("empty_index", str(path))
    return sorted(rows)


# The CR52 console carries ANSI colour codes. Drawn literally they read as
# "[0m[22:14:33.356]" and bury the firmware's own text, which is the evidence
# this pane exists to show. Board-seen 2026-09-18.
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\[0m")

# journalctl -o short-monotonic: "[  1234.567890] host unit[pid]: message".
MONO = re.compile(r"^\[\s*(\d+\.\d+)\]")
# VisionPilot prints frame_ms= at the end of each frame, after the slow fault's
# injected sleep, so a slow frame shows here and not in its Latency line.
FRAME_MS = re.compile(r"frame_ms=(\d+(?:\.\d+)?)")
# SCORE_VP_FRAME_MAX_MS in score/config/recording, the launch manager
# configuration of a recording run: the first frame over it is the one the
# health monitor fails. A recording frame takes 72-85 ms (board 2,
# 2026-10-06), and the slow fault adds 200 ms to every frame.
LATE_FRAME_MS = 150.0


def journal_frames(journal):
    """([board stamp per rendered frame], [(board stamp, frame_ms)]) from the journal.

    A per-frame line is a Latency line that carries wall=. VisionPilot also
    prints Latency in other contexts, and counting those shifts every frame.
    """
    stamps, frame_ms = [], []
    for ln in journal.splitlines():
        mono = MONO.match(ln)
        if not mono:
            continue
        if "Latency" in ln and "wall=" in ln:
            stamps.append(float(mono.group(1)))
        else:
            ms = FRAME_MS.search(ln)
            if ms:
                frame_ms.append((float(mono.group(1)), float(ms.group(1))))
    return stamps, frame_ms


def board_offset(journal, fault_at, mode="kill"):
    """Seconds to add to a board monotonic time to put it on the bench clock.

    One frame is the fault, so one constant places every board stamp: the HUD
    frames, the frame times and the DLT messages. In a kill run that frame is
    the last one. In a slow run it is the first frame over the deadline:
    SIGUSR1 lands while that frame or the one before it runs, and VisionPilot
    renders on until the launch manager stops it.
    """
    stamps, frame_ms = journal_frames(journal)
    if not stamps:
        raise ReelError("no_hud_frames")
    if mode != "slow":
        return fault_at - stamps[-1]
    for mono, ms in frame_ms:
        before = [s for s in stamps if s <= mono]
        if ms > LATE_FRAME_MS and before:
            return fault_at - before[-1]
    raise ReelError("no_late_frame")


def hud_frame_times(journal, fault_at, mode="kill"):
    """Bench time of every rendered HUD frame, from the VisionPilot journal."""
    stamps, _ = journal_frames(journal)
    offset = board_offset(journal, fault_at, mode)
    return [s + offset for s in stamps]


def read_console(text):
    """[(bench_time, raw line)] from the stamped CR52 capture.

    The stamper prefixes every line with the bench clock precisely because the
    board's own clock cannot be used. An unstamped capture cannot be placed in
    time at all, so it is refused rather than shown scrolling at a guess.
    """
    out = []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        head, _, _rest = ln.partition(" ")
        try:
            out.append((float(head), ln))
        except ValueError:
            continue
    if not out:
        raise ReelError("console_unstamped")
    return out


def console_window(lines, bench_time, n=CONSOLE_LINES):
    """The last n console lines that had already been printed at bench_time."""
    upto = bisect.bisect_right([t for t, _ in lines], bench_time)
    return [ln for _, ln in lines[max(0, upto - n):upto]]


# mw::log logs its own buffer statistics (context STAT) at every process start
# and stop. They say nothing about the fault and would take strip rows from it.
HIDDEN_DLT_CONTEXTS = {"STAT"}


def dlt_window(placed, bench_time, n=DLT_LINES):
    """The last n DLT messages already logged at bench_time, without mw::log's statistics."""
    upto = bisect.bisect_right([t for t, _ in placed], bench_time)
    shown = [p for p in placed[:upto] if p[1].ctx not in HIDDEN_DLT_CONTEXTS]
    return shown[-n:]


def output_hz(run, bench_time):
    """Frames VisionPilot rendered in the one second up to bench_time."""
    return sum(1 for t in run.hud_times if bench_time - 1.0 < t <= bench_time)


def check_console_covers(lines, first, last):
    if not lines or lines[0][0] > first or lines[-1][0] < last:
        raise ReelError("console_short",
                        f"have {lines[0][0]:.3f}..{lines[-1][0]:.3f} want {first:.3f}..{last:.3f}")


def place_dlt(msgs, offset):
    """[(bench_time, DltMsg)] by each message's own board stamp, sorted.

    The stamp is the board's CLOCK_MONOTONIC at the log call, the clock of the
    journal's short-monotonic stamps, so the offset that places the HUD frames
    places these too. The arrival time is late by up to the datarouter's 100 ms
    flush, and serves only as the cross-check in check_dlt_clock.
    """
    placed = sorted(((m.tmsp + offset, m) for m in msgs if m.tmsp is not None),
                    key=lambda p: p[0])
    if not placed:
        raise ReelError("dlt_unstamped")
    return placed


def check_dlt_clock(placed, lag=DLT_LAG_S):
    lags = sorted(m.recv - t for t, m in placed)
    mid = lags[len(lags) // 2]
    if not lag[0] <= mid <= lag[1]:
        raise ReelError("dlt_clock", f"median arrival lag {mid:.3f} s")


def read_trace(text):
    """{kind: [(t_rel_s, value)]} from si_stop_gate.py --trace.

    That script already writes times relative to the fault, which is the axis
    this reel uses everywhere, so nothing is converted here.
    """
    out = {}
    for ln in text.splitlines()[1:]:
        if not ln.strip():
            continue
        parts = ln.split(",")
        if len(parts) < 5:
            continue
        kind, t_rel = parts[0], float(parts[1])
        value = float(parts[4]) if parts[4] else 0.0
        out.setdefault(kind, []).append((t_rel, value))
    if not out.get("odom"):
        raise ReelError("no_odom")
    for rows in out.values():
        rows.sort()
    return out


# --- the cross-check --------------------------------------------------------

def check_alignment(hud_times, camera_times, fault_at, pre_window=PRE_WINDOW):
    """Refuse a run whose HUD frames cannot be mapped positionally.

    One PNG per rendered frame and one journal line per rendered frame is the
    whole basis of the mapping. If VisionPilot dropped input frames, the two
    streams carry different numbers of samples over the same seconds, and the
    mapping is wrong everywhere with no visible symptom.
    """
    lo = fault_at - pre_window
    n_hud = sum(1 for t in hud_times if lo <= t <= fault_at)
    n_cam = sum(1 for t in camera_times if lo <= t <= fault_at)
    if abs(n_hud - n_cam) > COUNT_TOLERANCE:
        raise ReelError("count_mismatch", f"hud={n_hud} camera={n_cam} window={pre_window}s")


def load_run(run_dir):
    run_dir = Path(run_dir)
    man_path = run_dir / "manifest.json"
    if not man_path.exists():
        raise ReelError("no_manifest", str(man_path))
    man = json.loads(man_path.read_text())
    if "fault_at" not in man:
        raise ReelError("no_fault_at")
    streams = man.get("streams")
    if not isinstance(streams, dict) or not REQUIRED_STREAMS <= set(streams):
        raise ReelError("bad_manifest")

    def need(rel):
        p = run_dir / rel
        if not p.exists() or (p.is_file() and p.stat().st_size == 0):
            raise ReelError("missing_stream", str(rel))
        return p

    fault_at = float(man["fault_at"])
    run = Run(run_dir=run_dir, mode=man.get("mode", "?"), fault_at=fault_at)

    for key, target in (("chase", "chase"), ("camera", "camera")):
        idx = need(streams[key]["index"])
        base = run_dir / streams[key]["dir"]
        rows = [(t, base / name) for t, name in read_index(idx)]
        missing = [p.name for _, p in rows if not p.exists()]
        if missing:
            raise ReelError("missing_frames", f"{key}: {len(missing)} of {len(rows)}")
        setattr(run, target, rows)

    journal = need(streams["hud"]["journal"]).read_text()
    # journald drops messages under its own rate limit and prints one line
    # about it. VisionPilot prints a Latency line per frame at up to 40 frames
    # a second, which is the traffic that limit exists to cut, and a journal
    # with a hole in it maps HUD frames to the wrong instants while looking
    # perfectly well formed.
    if "uppressed" in journal:
        raise ReelError("journal_suppressed")
    run.hud_times = hud_frame_times(journal, fault_at, run.mode)
    offset = board_offset(journal, fault_at, run.mode)
    run.frame_ms = [(mono + offset, ms) for mono, ms in journal_frames(journal)[1]]
    hud_dir = run_dir / streams["hud"]["dir"]
    run.hud = sorted(hud_dir.glob("frame_*.png"))
    if not run.hud:
        raise ReelError("no_hud_pngs", str(hud_dir))
    # Exactly one extra PNG is what the kill route produces: the sink writes
    # the frame and VisionPilot is killed before it prints that frame's
    # Latency line. Board-measured 2026-09-18, 396 against 395. The frame has
    # no time, so it is dropped rather than guessed at. Any other difference
    # means the directory was not emptied or the pull lost files, and the
    # positional mapping would be shifted everywhere with no symptom.
    if len(run.hud) == len(run.hud_times) + 1:
        run.hud = run.hud[:-1]
    if len(run.hud) != len(run.hud_times):
        raise ReelError("hud_png_count", f"pngs={len(run.hud)} frames={len(run.hud_times)}")

    run.console = read_console(need(streams["console"]["file"]).read_text())
    run.trace = read_trace(need(streams["trace"]["file"]).read_text())
    try:
        msgs = read_dlt(need(streams["dlt"]["file"]).read_bytes())
    except DltError as exc:
        raise ReelError("bad_dlt", str(exc)) from exc
    run.dlt = place_dlt(msgs, offset)
    check_dlt_clock(run.dlt)
    check_alignment(run.hud_times, [t for t, _ in run.camera], fault_at)
    return run


# --- the output timeline ----------------------------------------------------

def timeline(chapters, fps):
    """Source time, relative to the fault, for every output frame."""
    out = []
    for ch in chapters:
        if ch.t1 <= ch.t0 or ch.speed <= 0:
            raise ReelError("bad_chapter", ch.name)
        step = ch.speed / fps
        t = ch.t0
        while t < ch.t1 - 1e-9:
            out.append(t)
            t += step
    return out


def pick(times, t):
    """Index of the newest sample at or before t, holding at both ends.

    Holding the last HUD frame after the fault is not a fallback: the `kill`
    route ends VisionPilot, so its last picture is what the board really had
    from then on.
    """
    i = bisect.bisect_right(times, t) - 1
    return max(0, min(i, len(times) - 1))


def clip_chapters(chapters, run):
    """Drop what was never recorded, and say so. Refuse to lose the event.

    The chase pane is the one that must keep moving, so coverage is measured
    against it.
    """
    first = run.rel(run.chase[0][0])
    last = run.rel(run.chase[-1][0])
    kept, notes = [], []
    for i, ch in enumerate(chapters):
        t0, t1 = max(ch.t0, first), min(ch.t1, last)
        if t1 - t0 < 1.0 / 20:
            if i < REQUIRED_CHAPTERS:
                raise ReelError("fault_uncovered",
                                f"{ch.name}: have {first:.1f}..{last:.1f} want {ch.t0}..{ch.t1}")
            notes.append(f"dropped={ch.name!r}")
            continue
        if (t0, t1) != (ch.t0, ch.t1):
            notes.append(f"clipped={ch.name!r} to {t0:.1f}..{t1:.1f}")
        kept.append(Chapter(ch.name, t0, t1, ch.speed, ch.intro))
    if not kept:
        raise ReelError("nothing_covered")
    return kept, notes


# --- drawing ----------------------------------------------------------------

def _font(size, mono=False):
    names = (["DejaVuSansMono.ttf", "LiberationMono-Regular.ttf"] if mono
             else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    # No TTF on this host (a bare CI container). The reel looks worse and
    # still says the same thing, which beats refusing to render.
    return ImageFont.load_default()


def _fit(path, box):
    img = Image.open(path).convert("RGB")
    img.thumbnail(box)
    pane = Image.new("RGB", box, (0, 0, 0))
    pane.paste(img, ((box[0] - img.width) // 2, (box[1] - img.height) // 2))
    return pane


def _label(img, text):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, 28], fill=(0, 0, 0))
    d.text((10, 5), text, font=_font(18), fill=(220, 220, 220))
    return img


def console_pane(run, bench_time, box):
    pane = Image.new("RGB", box, (12, 12, 12))
    d = ImageDraw.Draw(pane)
    f = _font(17, mono=True)
    y = 34
    for ln in console_window(run.console, bench_time):
        # Drop the bench stamp: the banner already carries the time, and the
        # firmware's own text is what the viewer is being shown.
        _, _, text = ln.partition(" ")
        d.text((10, y), ANSI.sub("", text)[:96], font=f, fill=(120, 230, 140))
        y += 20
    return _label(pane, "CR52 Safety Island console")


def hud_caption(run, t_rel):
    """(label, dim) for the HUD pane at t_rel.

    After VisionPilot's last rendered frame the pane holds that frame. A bright,
    normal-looking HUD next to a braking car reads as a live picture, so the
    frame is dimmed and says what it is. A slow run renders on past the fault
    until the launch manager stops it, and those frames are live.
    """
    if run.fault_at + t_rel > run.hud_times[-1]:
        return "VisionPilot HUD: the last frame it rendered, held", True
    if t_rel > 0:
        if run.mode != "slow":
            return "VisionPilot HUD: the last frame it rendered, held", True
        return "VisionPilot HUD, each frame now 200 ms late", False
    return "VisionPilot HUD, rendered on the X5H board", False


def plot_window(run, t_rel):
    """(t_min, t_max) of both bottom-right plots, in seconds from the fault.

    The axis covers the trace and never moves. Deriving it from the samples
    drawn so far rescales the plot on every output frame, which makes a still
    car look like it is still slowing down. It is a window around the fault,
    not the whole trace: the run drives for over a minute and stops in nine
    seconds, so an axis over all of it compresses the braking into the last
    tenth of the width.
    """
    every = [t for rows in run.trace.values() for t, _ in rows]
    t_min = max(min(every), -PLOT_WINDOW_S)
    t_max = min(max(every), PLOT_WINDOW_S)
    return t_min, max(t_max, t_rel)


def frame_time_pane(run, t_rel, box):
    """VisionPilot's time per frame against the deadline, and its output rate.

    The slow route's story in one row: the frame time steps over the deadline
    at the fault, and the rate falls with it. The time axis is the speed
    plot's, so the two rows read as one timeline.
    """
    pane = Image.new("RGB", box, (18, 18, 22))
    d = ImageDraw.Draw(pane)
    left, right, top, bottom = 60, box[0] - 20, 50, box[1] - 12
    t_min, t_max = plot_window(run, t_rel)

    def xy(t, ms):
        x = left + (right - left) * (t - t_min) / max(t_max - t_min, 1e-6)
        y = bottom - (bottom - top) * min(ms, FT_MAX_MS) / FT_MAX_MS
        return x, y

    small = _font(15)
    d.rectangle([left, top, right, bottom], outline=(70, 70, 80))
    d.text((6, top - 4), f"{FT_MAX_MS:.0f}", font=small, fill=(160, 160, 170))
    d.text((6, bottom - 16), "0", font=small, fill=(160, 160, 170))
    _, yd = xy(t_min, LATE_FRAME_MS)
    for x in range(left, right, 16):
        d.line([x, yd, min(x + 8, right), yd], fill=(255, 220, 90), width=1)
    d.text((left + 6, yd - 18),
           f"deadline {LATE_FRAME_MS:.0f} ms (recording run; the demo runs 80 ms)",
           font=small, fill=(255, 220, 90))
    pts = [xy(run.rel(t), ms) for t, ms in run.frame_ms if t_min <= run.rel(t) <= t_rel]
    if len(pts) > 1:
        d.line(pts, fill=(140, 230, 140), width=2)
    x0, _ = xy(0.0, 0)
    d.line([x0, top, x0, bottom], fill=(220, 80, 80), width=2)
    d.text((right - 170, top + 4), f"output {output_hz(run, run.fault_at + t_rel):2d} Hz",
           font=_font(20, mono=True), fill=(235, 235, 235))
    return _label(pane, "VisionPilot frame time, ms, and its output rate")


def dlt_strip(run, bench_time, box):
    """The last DLT_LINES messages logged by bench_time, VP and LM in their colours.

    A warning or worse gets a red bar at the left edge instead of a third text
    colour, so the line still says which process wrote it.
    """
    pane = Image.new("RGB", box, (12, 12, 16))
    d = ImageDraw.Draw(pane)
    f = _font(18, mono=True)
    y = 34
    for t, msg in dlt_window(run.dlt, bench_time):
        if 1 <= msg.level <= 3:
            d.rectangle([0, y, 5, y + 19], fill=(230, 70, 70))
        level = LEVELS.get(msg.level, "-")
        stamp = f"T{run.rel(t):+.2f}"
        text = msg.text.replace("\n", " ")
        line = f"{stamp:<8}  {msg.app:<4} {level:<5} {text}"
        d.text((12, y), line[:160], font=f, fill=APP_COLOURS.get(msg.app, (190, 190, 200)))
        y += 23
    return _label(pane, "DLT on the bench host: the S-CORE launch manager (LM) and VisionPilot (VP)")


def trace_pane(run, t_rel, box):
    pane = Image.new("RGB", box, (18, 18, 22))
    d = ImageDraw.Draw(pane)
    left, right, top, bottom = 60, box[0] - 20, 50, box[1] - 34
    odom = run.trace["odom"]
    t_min, t_max = plot_window(run, t_rel)
    v_max = max(max(v for _, v in odom), 1.0) * 1.15

    def xy(t, v):
        x = left + (right - left) * (t - t_min) / max(t_max - t_min, 1e-6)
        y = bottom - (bottom - top) * v / v_max
        return x, y

    d.rectangle([left, top, right, bottom], outline=(70, 70, 80))
    d.text((6, top - 4), f"{v_max:.0f}", font=_font(15), fill=(160, 160, 170))
    d.text((6, bottom - 16), "0", font=_font(15), fill=(160, 160, 170))
    d.text((left + 6, top - 20), "ego speed, m/s", font=_font(15), fill=(160, 160, 170))
    pts = [xy(t, v) for t, v in odom if t <= t_rel]
    if len(pts) > 1:
        d.line(pts, fill=(120, 200, 255), width=3)
    # The commanded acceleration lives on its own scale, so it is drawn as a
    # band rather than a second axis: the point is when it appears and how long
    # it lasts, not its exact value against the speed curve.
    # Braking as one line that reads zero whenever nothing is braking. Filling
    # the area under it drew a polygon straight across the gaps between braking
    # samples, which invented a brake that lasted the whole run; drawing every
    # commanded acceleration instead put VisionPilot's own +1.5 m/s2 under a
    # legend reading "braking". Both were composed from a real run and both
    # said something the run did not do.
    brake = [(t, acc) for t, acc in run.trace.get("ack_accel", []) if t <= t_rel]
    if len(brake) > 1:
        pts = [(xy(t, 0)[0],
                bottom - (bottom - top) * min(max(-acc, 0.0) / 4.0, 1.0))
               for t, acc in brake]
        d.line(pts, fill=(255, 140, 90), width=3)
    # One line, at the first command the CR52 sent after the fault. The rest
    # arrive at 20 Hz and say nothing the first one does not.
    after = [t for t, _ in run.trace.get("cr52_cmd", []) if t >= 0.0 and t <= t_rel]
    if after:
        x, _ = xy(after[0], 0)
        d.line([x, top, x, bottom], fill=(255, 220, 90), width=2)
        d.text((x + 4, top + 22), f"CR52 +{after[0] * 1000:.0f} ms",
               font=_font(15), fill=(255, 220, 90))
    x0, _ = xy(0.0, 0)
    d.line([x0, top, x0, bottom], fill=(220, 80, 80), width=2)
    d.text((x0 + 4, top + 4), "fault", font=_font(15), fill=(220, 80, 80))
    return _label(pane, "ego speed, first CR52 command (yellow), braking (orange)")


def banner(run, t_rel, chapter):
    img = Image.new("RGB", (WIDTH, BANNER_H), (24, 24, 28))
    d = ImageDraw.Draw(img)
    d.text((16, 16), chapter.name, font=_font(26), fill=(235, 235, 235))
    sign = "+" if t_rel >= 0 else "-"
    d.text((WIDTH - 210, 14), f"T{sign}{abs(t_rel):.2f} s", font=_font(30, mono=True),
           fill=(255, 210, 90) if t_rel >= 0 else (200, 200, 210))
    if chapter.speed != 1.0:
        d.text((WIDTH - 300, 20), f"{chapter.speed:g}x", font=_font(22), fill=(160, 200, 255))
    return img


def render_frame(run, t_rel, chapter):
    bench = run.fault_at + t_rel
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    img.paste(banner(run, t_rel, chapter), (0, 0))
    box = (PANE_W, PANE_H)
    chase = _label(_fit(run.chase[pick([t for t, _ in run.chase], bench)][1], box),
                   "CARLA, chase camera")
    caption, dim = hud_caption(run, t_rel)
    hud_img = _fit(run.hud[pick(run.hud_times, bench)], box)
    if dim:
        hud_img = Image.eval(hud_img, lambda v: v * 4 // 10)
    lower = BANNER_H + PANE_H
    img.paste(chase, (0, BANNER_H))
    img.paste(_label(hud_img, caption), (PANE_W, BANNER_H))
    img.paste(console_pane(run, bench, box), (0, lower))
    img.paste(frame_time_pane(run, t_rel, (PANE_W, FT_H)), (PANE_W, lower))
    img.paste(trace_pane(run, t_rel, (PANE_W, PANE_H - FT_H)), (PANE_W, lower + FT_H))
    img.paste(dlt_strip(run, bench, (WIDTH, STRIP_H)), (0, HEIGHT - STRIP_H))
    d = ImageDraw.Draw(img)
    d.line([PANE_W, BANNER_H, PANE_W, HEIGHT - STRIP_H], fill=(60, 60, 68), width=2)
    d.line([0, lower, WIDTH, lower], fill=(60, 60, 68), width=2)
    d.line([PANE_W, lower + FT_H, WIDTH, lower + FT_H], fill=(60, 60, 68), width=1)
    d.line([0, HEIGHT - STRIP_H, WIDTH, HEIGHT - STRIP_H], fill=(60, 60, 68), width=2)
    return img


def _card(lines, title):
    img = Image.new("RGB", (WIDTH, HEIGHT), (16, 16, 20))
    d = ImageDraw.Draw(img)
    d.text((120, 110), title, font=_font(56), fill=(240, 240, 240))
    y = 260
    for text, size in lines:
        d.text((120, y), text, font=_font(size), fill=(200, 205, 215))
        y += size + 22
    return img


def title_card(run):
    """The data path, drawn once, so the four panes have somewhere to fit."""
    img = _card([], "CES 2027: VisionPilot on the X5H, with a Safety Island")
    d = ImageDraw.Draw(img)
    boxes = [
        (120, 300, "CARLA\non the bench", (60, 90, 140)),
        (560, 300, "VisionPilot\nX5H NPU", (60, 130, 90)),
        (1000, 300, "ego command\nCARLA", (60, 90, 140)),
        (560, 640, "Safety Island\nCR52", (150, 110, 50)),
    ]
    for x, y, text, colour in boxes:
        d.rectangle([x, y, x + 340, y + 180], fill=colour, outline=(220, 220, 220))
        d.multiline_text((x + 24, y + 46), text, font=_font(30), fill=(245, 245, 245), spacing=10)
    for x0, x1 in ((460, 560), (900, 1000)):
        d.line([x0, 390, x1, 390], fill=(230, 230, 230), width=5)
    d.line([730, 480, 730, 640], fill=(230, 230, 230), width=5)
    d.text((750, 520), "heartbeat over rpmsg", font=_font(24), fill=(230, 230, 230))
    d.text((120, 880), f"one recorded run, mode {run.mode}, "
                       "aligned on the fault instant to within one frame",
           font=_font(26), fill=(180, 185, 195))
    return img


def closing_card(run):
    return _card([
        ("Gates D1a to D7 of openadkit issue #147", 34),
        ("D1a role boot, D1b CR52 up, D2 payload, D3 channel: PASS on board 2", 28),
        ("D4 lap, D5 NPU under 30 ms, D6 Safety Island stop: PASS", 28),
        ("D7 cold boot: run by hand at the bench", 28),
        ("", 20),
        (f"This reel is one recording run ({run.mode}), not a gate run.", 26),
        ("Its own latency carries the cost of recording.", 26),
    ], "What was measured")


# --- output -----------------------------------------------------------------

def ffmpeg_argv(out, fps):
    return ["ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
            "-r", str(fps), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]


def chapter_frames(run, chapters, fps):
    """[(source time, chapter)] for every output frame, cards excluded."""
    frames = []
    for ch in chapters:
        for t in timeline([ch], fps):
            frames.append((t, ch))
    return frames


def write_frames(sink, img, n):
    """One picture, n times, straight down the pipe.

    Rendering the whole reel into a list first is the obvious way to write this
    and it does not fit in memory: three thousand output frames of 1920x1080
    RGB is about 18 GB.
    """
    raw = img.tobytes()
    for _ in range(n):
        sink.write(raw)


def parse_chapter(spec):
    parts = spec.split(":")
    if len(parts) != 4:
        raise ReelError("bad_chapter", spec)
    try:
        return Chapter(parts[0], float(parts[1]), float(parts[2]), float(parts[3]))
    except ValueError as exc:
        raise ReelError("bad_chapter", spec) from exc


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("run_dir")
    p.add_argument("--out", default="reel.mp4")
    p.add_argument("--fps", type=int, default=20)
    p.add_argument("--card-seconds", type=float, default=15.0)
    p.add_argument("--intro-seconds", type=float, default=10.0,
                   help="how long each chapter's explanation card is held")
    p.add_argument("--chapter", action="append", default=[],
                   help="NAME:T0:T1:SPEED, repeatable, replaces the built-in cut")
    p.add_argument("--dry-run", action="store_true",
                   help="plan and check the run, write no file")
    a = p.parse_args(argv)
    try:
        run = load_run(a.run_dir)
        cut = SLOW_CHAPTERS if run.mode == "slow" else DEFAULT_CHAPTERS
        chapters = ([parse_chapter(s) for s in a.chapter] if a.chapter
                    else [Chapter(*c) for c in cut])
        chapters, notes = clip_chapters(chapters, run)
        frames = chapter_frames(run, chapters, a.fps)
        check_console_covers(run.console,
                             run.fault_at + frames[0][0], run.fault_at + frames[-1][0])
        card_frames = int(a.card_seconds * a.fps)
        intro_frames = int(a.intro_seconds * a.fps)
        total = (len(frames) + 2 * card_frames
                 + intro_frames * sum(1 for ch in chapters if ch.intro))
        for note in notes:
            print(f"DEMO_REEL_CLIP {note}")
        if a.dry_run:
            print(f"DEMO_REEL_PLAN frames={total} seconds={total / a.fps:.1f} "
                  f"chapters={len(chapters)}")
            return 0
        proc = subprocess.Popen(ffmpeg_argv(a.out, a.fps), stdin=subprocess.PIPE)
        write_frames(proc.stdin, title_card(run), card_frames)
        for ch in chapters:
            if ch.intro:
                write_frames(proc.stdin, _card(list(ch.intro), ch.name), intro_frames)
            for t in timeline([ch], a.fps):
                write_frames(proc.stdin, render_frame(run, t, ch), 1)
        write_frames(proc.stdin, closing_card(run), card_frames)
        proc.stdin.close()
        if proc.wait() != 0:
            raise ReelError("ffmpeg_failed", f"exit {proc.returncode}")
        print(f"DEMO_REEL_WRITTEN frames={total} seconds={total / a.fps:.1f} path={a.out}")
        return 0
    except ReelError as exc:
        print(f"DEMO_REEL_FAIL reason={exc.reason} {exc}".rstrip())
        return 1


if __name__ == "__main__":
    sys.exit(main())
