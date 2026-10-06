"""Emit the release-note verification table from evidence summaries.

Prints the current build's cell metrics and, when a previous summary is
available, an upgrade comparison against it.
"""
import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value) -> str:
    return "-" if value is None else str(value)


def delta(previous, current) -> str:
    if previous is None or current is None:
        return "-"
    change = current - previous
    return f"+{change}" if change > 0 else str(change)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True)
    parser.add_argument("--previous")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    current = load(Path(args.current))
    previous = load(Path(args.previous)) if args.previous else None
    cells = sorted(current.get("cells", []), key=lambda cell: cell["name"])

    passed = sum(cell.get("result") == "PASSED" for cell in cells)
    lines = [f"Evidence result: **{current.get('result', 'UNKNOWN')}**", "", f"Passing cells: **{passed}/{len(cells)}**", ""]
    lines.append("| Cell | Result | Ready (s) | Arrival (s) | Peak MiB |")
    lines.append("|---|---|---|---|---|")
    for cell in cells:
        lines.append(
            "| {name} | {result} | {ready} | {arrival} | {peak} |".format(
                name=cell["name"],
                result=cell.get("result"),
                ready=fmt(cell.get("ready_s")),
                arrival=fmt(cell.get("arrival_s")),
                peak=fmt(cell.get("peak_mib")),
            )
        )

    if previous:
        previous_cells = {cell["name"]: cell for cell in previous.get("cells", [])}
        baseline = previous.get("baseline", {})
        label = baseline.get("version", f"main run {baseline.get('runId', 'unknown')}") if baseline else "historical evidence"
        lines.extend(
            [
                "",
                f"### Upgrade comparison vs build `{previous.get('build_tag', 'unknown')}`",
                "",
                f"Baseline: {label}. Historical metrics are informational, not a release gate.",
                "",
                "| Cell | Metric | Previous | Current | Delta |",
                "|---|---|---|---|---|",
            ]
        )
        for cell in cells:
            baseline = previous_cells.get(cell["name"])
            if not baseline:
                continue
            for metric, label in (
                ("ready_s", "Ready (s)"),
                ("arrival_s", "Arrival (s)"),
                ("peak_mib", "Peak MiB"),
            ):
                before = baseline.get(metric)
                after = cell.get(metric)
                lines.append(
                    f"| {cell['name']} | {label} | {fmt(before)} | {fmt(after)} | {delta(before, after)} |"
                )
    else:
        lines.extend(["", "No previous evidence available for comparison."])

    Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
