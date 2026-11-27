#!/usr/bin/env python3
"""Render the architecture diagrams in docs/assets/images.

    python3 docs/diagrams.py          # write the SVG files
    python3 docs/diagrams.py --check  # fail when a file differs from what this renders

One overview of Open AD Kit, and one diagram per catalog deployment that shows
what the deployment runs, read from its Compose files. Each comes in a light and
a dark variant: an SVG in an <img> cannot follow the page's theme.
"""

import re
import sys
from html import escape
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets" / "images"

MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
THEMES = {
    "light": {
        "frame": "#d0d7de", "pill": "#0d1117", "pill_stroke": "#0d1117", "line": "#afb8c1",
        "band": "#f6f8fa", "muted": "#656d76", "dim": "#8c959f", "fill": "#eef4ff",
        "accent": "#2f6fe4", "text": "#1f2328",
    },
    "dark": {
        "frame": "#30363d", "pill": "#161b22", "pill_stroke": "#3d444d", "line": "#484f58",
        "band": "#161b22", "muted": "#8b949e", "dim": "#6e7681", "fill": "#17233b",
        "accent": "#7cacff", "text": "#e6edf3",
    },
}
WIDTH, LEFT, RIGHT = 1000, 41, 960

# The Autoware pipeline, one component image each, in data-flow order.
PIPELINE = ["sensing-perception", "localization-mapping", "planning", "control", "vehicle-system"]
# What runs around the pipeline, in the order drawn. The simulator and the
# visualizer are component images too; the others a deployment brings.
AROUND = ["simulator", "Scenario Simulator", "CARLA", "rosbag", "Safety Island", "visualizer"]
IMAGES = {*PIPELINE, "simulator", "visualizer"}
IMAGE_BOX = {
    "SENSING_PERCEPTION_IMAGE": "sensing-perception",
    "SENSING_PERCEPTION_GPU_IMAGE": "sensing-perception",
    "LOCALIZATION_MAPPING_IMAGE": "localization-mapping",
    "PLANNING_IMAGE": "planning",
    "PLANNING_GPU_IMAGE": "planning",
    "CONTROL_IMAGE": "control",
    "VEHICLE_SYSTEM_IMAGE": "vehicle-system",
    "SIMULATOR_IMAGE": "simulator",
    "VISUALIZER_IMAGE": "visualizer",
    "SCENARIO_SIMULATOR_IMAGE": "Scenario Simulator",
    "CARLA_IMAGE": "CARLA",
}
# Services that are a box of their own, whatever image runs them.
SERVICE_BOX = {"rosbag": "rosbag", "safety-island": "Safety Island", "safety-island-bridge": "Safety Island"}


def compose_images(path: Path) -> dict[str, str]:
    """The image variable of each service of a Compose file and the files it includes."""
    model = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    images: dict[str, str] = {}
    for included in model.get("include") or []:
        images.update(compose_images(path.parent / included))
    for name, service in (model.get("services") or {}).items():
        match = re.match(r"\$\{(\w+)", (service or {}).get("image", ""))
        if match:
            images[name] = match.group(1)
    return images


def deployment_boxes(name: str) -> set[str]:
    """The boxes a deployment's default mode runs."""
    boxes = set()
    for service, image in compose_images(ROOT / "deployments" / name / "compose.yaml").items():
        boxes.add(SERVICE_BOX.get(service) or IMAGE_BOX[image])
    return boxes


class Svg:
    def __init__(self, theme: str, height: int, title: str, desc: str):
        self.c = THEMES[theme]
        self.height = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" '
            f'height="{height}" role="img" aria-labelledby="title desc">',
            f'  <title id="title">{escape(title)}</title>',
            f'  <desc id="desc">{escape(desc)}</desc>',
        ]

    def add(self, element: str) -> None:
        self.parts.append("  " + element)

    def text(self, x, y, content, *, font=SANS, size=14, weight=400, fill=None, anchor="middle", spacing=None):
        extra = f' letter-spacing="{spacing}"' if spacing else ""
        self.add(
            f'<text x="{x:g}" y="{y:g}" text-anchor="{anchor}" font-family="{font}" font-size="{size}" '
            f'font-weight="{weight}"{extra} fill="{fill or self.c["text"]}">{content}</text>'
        )

    def frame(self, bottom: int, command: str) -> None:
        """The outer frame, with the command on its top edge."""
        c = self.c
        self.add(
            f'<rect x="12" y="52" width="976" height="{bottom - 52}" rx="16" fill="none" '
            f'stroke="{c["frame"]}" stroke-width="1.5"/>'
        )
        width = round(len(command) * 9.6 + 80)
        self.add(
            f'<rect x="{(WIDTH - width) / 2:g}" y="30" width="{width}" height="44" rx="10" fill="{c["pill"]}" '
            f'stroke="{c["pill_stroke"]}" stroke-width="1.5"/>'
        )
        self.text(500, 57.5, f'<tspan fill="#7cacff">$</tspan> {escape(command)}', font=MONO, size=16, fill="#e6edf3")

    def caption(self, y, label, note="") -> None:
        self.text(LEFT, y, label, size=13, weight=600, fill=self.c["muted"], anchor="start", spacing=0.6)
        if note:
            self.text(RIGHT, y, note, size=13, fill=self.c["muted"], anchor="end")

    def box(self, x, y, width, label, *, height=56, on=True, mono=True, dashed=False, sub="") -> None:
        c = self.c
        if on and not dashed:
            style = f'fill="{c["fill"]}" stroke="{c["accent"]}" stroke-width="1.5"'
        else:
            style = f'fill="none" stroke="{c["line"]}" stroke-width="1.5" stroke-dasharray="5 5"'
        self.add(f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{height}" rx="10" {style}/>')
        middle = y + height / 2 + 5
        font, weight, fill = (MONO if mono else SANS), (500 if on else 400), (c["text"] if on else c["dim"])
        if sub:
            self.text(x + width / 2, middle - 9, label, font=font, weight=weight, fill=fill)
            self.text(x + width / 2, middle + 10, sub, size=12.5, fill=c["muted"])
        else:
            self.text(x + width / 2, middle, label, font=font, weight=weight, fill=fill)

    def arrow(self, x, y, *, down=False, strong=True) -> None:
        """An 18 px arrow that starts at (x, y)."""
        path = f"M{x:g} {y:g}V{y + 18:g}M{x - 4.5:g} {y + 13:g}L{x:g} {y + 18:g}L{x + 4.5:g} {y + 13:g}"
        if not down:
            path = f"M{x:g} {y:g}H{x + 18:g}M{x + 13:g} {y - 4.5:g}L{x + 18:g} {y:g}L{x + 13:g} {y + 4.5:g}"
        stroke = self.c["muted"] if strong else self.c["line"]
        self.add(
            f'<path d="{path}" fill="none" stroke="{stroke}" stroke-width="1.5" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )

    def pipeline(self, y, on: set[str]) -> dict[str, float]:
        """The five pipeline images across the full width; returns each box's centre."""
        centres, x = {}, float(LEFT)
        for index, name in enumerate(PIPELINE):
            width = box_width(name)
            self.box(x, y, width, name, on=name in on)
            centres[name] = x + width / 2
            if index:
                self.arrow(x - 26, y + 28, strong=name in on and PIPELINE[index - 1] in on)
            x += width + 34
        return centres

    def row(self, y, labels) -> dict[str, float]:
        """Boxes centred as a group; returns each box's centre."""
        x = (WIDTH - sum(map(box_width, labels)) - 34 * (len(labels) - 1)) / 2
        centres = {}
        for label in labels:
            width = box_width(label)
            self.box(x, y, width, label, mono=label in IMAGES)
            centres[label] = x + width / 2
            x += width + 34
        return centres

    def render(self) -> str:
        return "\n".join([*self.parts, "</svg>"]) + "\n"


def box_width(label: str) -> int:
    return max(80, round(len(label) * 8.4 + 44))


def overview(theme: str) -> str:
    svg = Svg(
        theme,
        646,
        "Open AD Kit: Autoware as images, deployments and one command",
        "Open AD Kit packages Autoware into component images: sensing-perception, localization-mapping, "
        "planning, control and vehicle-system, with a simulator and a visualizer. Deployments combine them "
        "into ready-to-run stacks: Planning, Scenario, Logging, CARLA and Safety Island Simulation, and your "
        "own kit puts your vehicle on top of one. openadkit run starts a deployment on an Ubuntu host with "
        "Docker Compose, split over two hosts, or on in-vehicle Linux with AutoSD. Caption: one reproducible "
        "path from simulation to in-vehicle systems.",
    )
    c = svg.c
    svg.frame(580, "openadkit run <deployment>")

    svg.caption(108, "Component images", "Autoware, one image per function")
    svg.pipeline(122, set(PIPELINE))
    svg.row(190, ["simulator", "visualizer"])
    svg.arrow(500, 256, down=True)

    svg.caption(300, "Deployments", "ready-to-run stacks of those images")
    names = ["Planning", "Scenario", "Logging", "CARLA", "Safety Island"]
    width = (RIGHT - LEFT - 20 * (len(names) - 1)) / len(names)
    for index, name in enumerate(names):
        svg.box(LEFT + index * (width + 20), 314, width, name, mono=False, sub="Simulation")
    svg.box(LEFT, 382, RIGHT - LEFT, "Your kit: your vehicle on top of a deployment", height=44, mono=False, dashed=True)
    svg.arrow(500, 436, down=True)

    svg.caption(480, "Hosts", "the same command and the same pinned images")
    hosts = [("Ubuntu", "Docker Compose"), ("Two hosts", "Zenoh, experimental"), ("In-vehicle Linux", "AutoSD, experimental")]
    width = (RIGHT - LEFT - 20 * (len(hosts) - 1)) / len(hosts)
    for index, (name, sub) in enumerate(hosts):
        x = LEFT + index * (width + 20)
        svg.add(
            f'<rect x="{x:g}" y="494" width="{width:g}" height="56" rx="10" fill="none" '
            f'stroke="{c["line"]}" stroke-width="1.5"/>'
        )
        svg.text(x + width / 2, 518, name, weight=500)
        svg.text(x + width / 2, 537, sub, size=12.5, fill=c["muted"])

    accent = c["accent"]
    svg.text(
        500, 620,
        f'One reproducible path from <tspan fill="{accent}">simulation</tspan> to '
        f'<tspan fill="{accent}">in-vehicle systems</tspan>',
        font=MONO, size=16,
    )
    return svg.render()


def deployment(name: str, theme: str) -> str:
    on = deployment_boxes(name)
    unknown = on - set(PIPELINE) - set(AROUND)
    if unknown:
        raise SystemExit(f"{name}: no place in the diagram for {sorted(unknown)}")
    title = name.replace("-", " ").title().replace("Carla", "CARLA").replace("Hil", "HIL")
    around = [box for box in AROUND if box in on]
    svg = Svg(
        theme,
        400,
        f"What {title} runs",
        f"openadkit run {name} starts {', '.join([box for box in PIPELINE if box in on] + around)}, "
        "which talk over ROS 2.",
    )
    c = svg.c
    svg.frame(376, f"openadkit run {name}")

    svg.caption(108, "Autoware")
    top = svg.pipeline(122, on)
    svg.add(
        f'<rect x="{LEFT}" y="202" width="{RIGHT - LEFT}" height="28" rx="8" fill="{c["band"]}" '
        f'stroke="{c["line"]}" stroke-width="1.5"/>'
    )
    svg.text(500, 220.5, "ROS 2", size=13, weight=600, fill=c["muted"], spacing=0.6)
    svg.caption(287, "Simulation and tools")
    bottom = svg.row(254, around)
    taps = [(x, 178) for box, x in top.items() if box in on] + [(x, 230) for x in bottom.values()]
    for x, y in taps:
        svg.add(f'<line x1="{x:g}" y1="{y}" x2="{x:g}" y2="{y + 24}" stroke="{c["line"]}" stroke-width="1.5"/>')

    svg.add(f'<rect x="330" y="337" width="14" height="14" rx="4" fill="{c["fill"]}" stroke="{c["accent"]}" stroke-width="1.5"/>')
    svg.text(352, 348.5, "runs in this deployment", size=13, fill=c["muted"], anchor="start")
    svg.add(
        f'<rect x="530" y="337" width="14" height="14" rx="4" fill="none" stroke="{c["line"]}" '
        'stroke-width="1.5" stroke-dasharray="3 3"/>'
    )
    svg.text(552, 348.5, "not in this deployment", size=13, fill=c["muted"], anchor="start")
    return svg.render()


def diagrams() -> dict[str, str]:
    files = {}
    names = sorted(path.parent.name for path in (ROOT / "deployments").glob("*/deployment.json"))
    for theme in THEMES:
        files[f"readme-hero-{theme}.svg"] = overview(theme)
        for name in names:
            files[f"deployment-{name}-{theme}.svg"] = deployment(name, theme)
    return files


def main() -> int:
    stale = []
    for name, content in diagrams().items():
        path = OUT / name
        if "--check" in sys.argv[1:]:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
        else:
            path.write_text(content, encoding="utf-8")
    if stale:
        print(f"stale diagrams, run python3 docs/diagrams.py: {', '.join(stale)}", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
