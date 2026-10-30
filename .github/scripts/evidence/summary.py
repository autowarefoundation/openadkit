"""Aggregate evidence cells into the run's summary and JUnit view.

Outputs, under --output-dir:
  evidence-summary.json   result and cells, read by the release gate and notes
  evidence.junit.xml      JUnit view of the run

The result is PASSED only when every expected cell produced a passing result.
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cells import normalize_cell  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation_matrix import evidence_cell_name  # noqa: E402


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def expected_cell_names(matrix):
    """Cell names as the evidence workflow composes them (deployment-distro[-node]-linux-amd64)."""
    if isinstance(matrix, dict):
        matrix = matrix["include"]
    return [evidence_cell_name(entry) for entry in matrix]


def summarize(cells, expected_names):
    """The run result: missing and failed cells fail it, as does an empty run."""
    seen = {cell["name"] for cell in cells}
    missing = [name for name in expected_names if name not in seen]
    failed = [cell["name"] for cell in cells if cell.get("result") != "PASSED"]
    result = "PASSED" if cells and not missing and not failed else "FAILED"
    return result, missing


def write_junit(path: Path, cells) -> None:
    suite = ET.Element("testsuite", {"name": "evidence"})
    cases = failures = 0
    for cell in cells:
        for level, data in sorted(cell.get("levels", {}).items()):
            cases += 1
            case = ET.SubElement(
                suite,
                "testcase",
                {"name": f'{cell["name"]}.{level}', "classname": cell["deployment"]},
            )
            if not data.get("ok"):
                failures += 1
                ET.SubElement(case, "failure", {"message": f"{level} failed"})
    suite.set("tests", str(cases))
    suite.set("failures", str(failures))
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cells-dir", required=True)
    parser.add_argument("--build-metadata", required=True)
    parser.add_argument(
        "--source-sha",
        help="commit the cells tested, when it is not the build's own (not release evidence)",
    )
    parser.add_argument(
        "--expected-cells",
        help="JSON matrix of the cells the run was supposed to produce",
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    metadata = load(Path(args.build_metadata))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    cells = sorted(
        (normalize_cell(load(path)) for path in Path(args.cells_dir).rglob("cell.json")),
        key=lambda cell: cell.get("name", ""),
    )
    expected = json.loads(args.expected_cells) if args.expected_cells else []
    result, missing = summarize(cells, expected_cell_names(expected))
    for name in missing:
        print(f"::error title=evidence missing::{name} produced no cell result")

    build_sha = metadata.get("openadkit_sha")
    source_sha = args.source_sha or build_sha
    summary = {
        "schemaVersion": 3,
        "build_tag": metadata.get("build_tag", "unknown"),
        "build_sha": build_sha,
        "source_sha": source_sha,
        "release_evidence": source_sha == build_sha,
        "result": result,
        "missing": missing,
        "cells": cells,
    }
    run_url = os.environ.get("EVIDENCE_RUN_URL", "")
    if run_url:
        summary["url"] = run_url
    (output / "evidence-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_junit(output / "evidence.junit.xml", cells)

    print(json.dumps({"result": result, "cells": len(cells), "missing": len(missing)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
