#!/usr/bin/env python3
"""Compose the CES 2027 demo reel from one recording run.

  make_demo_reel.py <run-dir> [--out reel.mp4] [--fps 20] [--dry-run]
                    [--chapter NAME:T0:T1:SPEED ...]

The run directory is what Simulation/CARLA/ROS2/si/record-demo.sh on the bench
leaves behind, with the board's HUD frames added by x5h-pull-demo-frames.sh.
manifest.json describes it. Every path in the manifest is relative to the run
directory, and every time in this script is in seconds relative to the fault,
because that is the only instant all five streams share.

Four panes, 2x2 under one banner: the chase camera, VisionPilot's own HUD from
the board, the CR52 console, and the speed and command trace. The banner reads
the offset from the fault, so the claim that the four pictures show the same
instant is on screen and checkable.

**Why the fault and not a clock.** The X5H board has no RTC and no NTP on the
bench LAN, so its log timestamps are wrong by days. The board clock is steady
inside a run, so one constant offset is enough, and the run supplies it: the
`kill` route ends VisionPilot, so its last rendered frame IS the fault. The
offset is fault_at minus the monotonic stamp of the last per-frame Latency
line. Alignment is therefore good to one VisionPilot frame, 25 to 40 ms at the
measured 23.6 ms wall time, plus the rpmsg and DDS latency the fault itself
takes to reach the firmware. The reel never claims better than that.

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

WIDTH, HEIGHT = 1920, 1080
BANNER_H = 60
PANE_W, PANE_H = WIDTH // 2, (HEIGHT - BANNER_H) // 2
CONSOLE_LINES = 16
# How far before the fault the HUD and camera frame counts are compared. Two
# seconds is enough to catch a run that dropped input frames and short enough
# that a late start does not read as a drop.
PRE_WINDOW = 2.0
# A positional HUD-frame-to-journal-line mapping tolerates a small count
# difference (a stream starting a frame early, the window edge) and nothing
# more. Five frames is half a second of input at 10 Hz.
COUNT_TOLERANCE = 5

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
        ("Bottom right: the car's speed, and the commands it is given.", 30),
        ("", 20),
        ("The board has no clock the bench can read, so all four panes", 26),
        ("are aligned on the fault instant, to within one rendered frame.", 26),
    )),
    ("the fault: VisionPilot stops answering", -3.0, 1.0, 0.25, (
        ("VisionPilot sends the Safety Island a heartbeat over rpmsg.", 30),
        ("The process is killed here. The heartbeat stops with it.", 30),
        ("", 20),
        ("Quarter speed from here, so the half second the CR52 waits", 26),
        ("before it decides is long enough to watch.", 26),
    )),
    ("the Safety Island brakes the car", 1.0, 11.0, 0.5, (
        ("The CR52 latches the stale heartbeat and takes the actuation path.", 30),
        ("It commands a steady stop. Nothing on the Linux side is involved.", 30),
    )),
    ("the car is stopped", 11.0, 22.0, 1.0, ()),
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


# journalctl -o short-monotonic: "[  1234.567890] host unit[pid]: message".
MONO = re.compile(r"^\[\s*(\d+\.\d+)\]")


def hud_frame_times(journal, fault_at):
    """Bench time of every rendered HUD frame, from the VisionPilot journal.

    A per-frame line is a Latency line that carries wall=; VisionPilot also
    prints Latency in other contexts, and counting those shifts every frame.
    The last such line is the fault, so the whole list is offset onto the bench
    clock by one constant.
    """
    stamps = []
    for ln in journal.splitlines():
        mono = MONO.match(ln)
        if mono and "Latency" in ln and "wall=" in ln:
            stamps.append(float(mono.group(1)))
    if not stamps:
        raise ReelError("no_hud_frames")
    offset = fault_at - stamps[-1]
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


def check_console_covers(lines, first, last):
    if not lines or lines[0][0] > first or lines[-1][0] < last:
        raise ReelError("console_short",
                        f"have {lines[0][0]:.3f}..{lines[-1][0]:.3f} want {first:.3f}..{last:.3f}")


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
    if not isinstance(streams, dict) or set(streams) < {"chase", "camera", "hud", "console", "trace"}:
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
    run.hud_times = hud_frame_times(journal, fault_at)
    hud_dir = run_dir / streams["hud"]["dir"]
    run.hud = sorted(hud_dir.glob("frame_*.png"))
    if not run.hud:
        raise ReelError("no_hud_pngs", str(hud_dir))
    if len(run.hud) != len(run.hud_times):
        raise ReelError("hud_png_count", f"pngs={len(run.hud)} frames={len(run.hud_times)}")

    run.console = read_console(need(streams["console"]["file"]).read_text())
    run.trace = read_trace(need(streams["trace"]["file"]).read_text())
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
        d.text((10, y), text[:96], font=f, fill=(120, 230, 140))
        y += 20
    return _label(pane, "CR52 Safety Island console")


def trace_pane(run, t_rel, box):
    pane = Image.new("RGB", box, (18, 18, 22))
    d = ImageDraw.Draw(pane)
    left, right, top, bottom = 60, box[0] - 20, 50, box[1] - 34
    odom = run.trace["odom"]
    # The axis covers the whole trace and never moves. Deriving it from the
    # samples drawn so far rescales the plot on every output frame, which makes
    # a still car look like it is still slowing down.
    every = [t for rows in run.trace.values() for t, _ in rows]
    t_min, t_max = min(every), max(max(every), t_rel)
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
    for t, acc in run.trace.get("ack_accel", []):
        if t <= t_rel:
            x, _ = xy(t, 0)
            d.line([x, bottom, x, bottom - (bottom - top) * min(abs(acc) / 4.0, 1.0)],
                   fill=(255, 140, 90), width=2)
    for t, _ in run.trace.get("cr52_cmd", []):
        if t <= t_rel:
            x, _ = xy(t, 0)
            d.line([x, top, x, bottom], fill=(255, 220, 90), width=1)
    x0, _ = xy(0.0, 0)
    d.line([x0, top, x0, bottom], fill=(220, 80, 80), width=2)
    d.text((x0 + 4, top + 4), "fault", font=_font(15), fill=(220, 80, 80))
    return _label(pane, "ego speed, CR52 commands (yellow), braking command (orange)")


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
    hud = _label(_fit(run.hud[pick(run.hud_times, bench)], box),
                 "VisionPilot HUD, rendered on the X5H board")
    img.paste(chase, (0, BANNER_H))
    img.paste(hud, (PANE_W, BANNER_H))
    img.paste(console_pane(run, bench, box), (0, BANNER_H + PANE_H))
    img.paste(trace_pane(run, t_rel, box), (PANE_W, BANNER_H + PANE_H))
    d = ImageDraw.Draw(img)
    d.line([PANE_W, BANNER_H, PANE_W, HEIGHT], fill=(60, 60, 68), width=2)
    d.line([0, BANNER_H + PANE_H, WIDTH, BANNER_H + PANE_H], fill=(60, 60, 68), width=2)
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
        chapters = ([parse_chapter(s) for s in a.chapter] if a.chapter
                    else [Chapter(*c) for c in DEFAULT_CHAPTERS])
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
