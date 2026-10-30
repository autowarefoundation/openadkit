"""Derived CI/release view; optional local comparison, no history/network lookup."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence.cells import METRICS, report_cells  # noqa: E402


def fmt(value):
    return "-" if value is None else str(value)


def render(current, previous=None):
    cells = report_cells(current)
    passed = sum(cell.get("result") == "PASSED" for cell in cells)
    lines = [
        f"Evidence result: **{current.get('result', 'UNKNOWN')}**", "",
        f"Passing cells: **{passed}/{len(cells)}**", "",
        "| Cell | Deployment | Distro | Node | Result | Ready (s) | Arrival (s) | Peak MiB | Overlay conformant |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for cell in cells:
        values = [cell["name"], cell.get("deployment"), cell.get("distro"), cell.get("node"), cell.get("result")]
        values.extend(cell["metrics"].get(name) for name in METRICS)
        values.append(cell.get("overlayConformant"))
        lines.append("| " + " | ".join(fmt(value) for value in values) + " |")
    for name in current.get("missing", []):
        lines.append(f"- Missing cell: {name}")

    if previous is not None:
        baseline = {cell["name"]: cell for cell in report_cells(previous)}
        lines.extend([
            "", f"### Metrics comparison vs build `{previous.get('build_tag', 'unknown')}`", "",
            "Informational only; not an upgrade acceptance test or release gate.", "",
            "| Cell | Metric | Previous | Current | Delta |", "|---|---|---|---|---|",
        ])
        for cell in cells:
            if cell["name"] not in baseline:
                continue
            for metric in METRICS:
                before = baseline[cell["name"]]["metrics"].get(metric)
                after = cell["metrics"].get(metric)
                delta = None if before is None or after is None else after - before
                lines.append(f"| {cell['name']} | {metric} | {fmt(before)} | {fmt(after)} | {fmt(delta)} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--previous", type=Path, help="explicit local input; never used during release")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    text = render(current, previous)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
