"""The evidence summary as a Markdown table, for the job summary and release notes."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence.cells import METRICS, report_cells  # noqa: E402


def fmt(value):
    return "-" if value is None else str(value)


def render(current, summary=True):
    """The cells table, after the result and passing count unless the caller
    states those itself. A cell's name already holds its deployment, distro,
    role and platform."""
    cells = report_cells(current)
    passed = sum(cell.get("result") == "PASSED" for cell in cells)
    lines = [
        f"Evidence result: **{current.get('result', 'UNKNOWN')}**", "",
        f"Passing cells: **{passed}/{len(cells)}**", "",
    ] if summary else []
    lines += [
        "| Cell | Result | Ready (s) | Arrival (s) | Peak MiB |",
        "|---|---|---|---|---|",
    ]
    for cell in cells:
        values = [cell["name"], cell.get("result")]
        values.extend(cell["metrics"].get(name) for name in METRICS)
        lines.append("| " + " | ".join(fmt(value) for value in values) + " |")
    for name in current.get("missing", []):
        lines.append(f"- Missing cell: {name}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    text = render(current)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
