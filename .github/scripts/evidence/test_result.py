"""Aggregate evidence cells into the inputs of an in-toto Test Result attestation.

Outputs, under --output-dir:
  evidence-subjects.txt   subjects-checksums lines for actions/attest
  evidence-predicate.json Test Result v0.1 predicate
  evidence-summary.json   cells summary for the job summary and exit status
  evidence.junit.xml      JUnit view of the run
"""
import argparse
import fnmatch
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from subjects import build_subjects, write_subjects  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation_matrix import evidence_cell_name  # noqa: E402


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_quarantine(path: Path | None):
    """Load the time-boxed quarantine list; malformed entries fail loudly."""
    if path is None or not path.exists():
        return []
    data = load(path)
    entries = data.get("quarantine", [])
    if not isinstance(entries, list):
        raise SystemExit(f"{path}: quarantine must be a list")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SystemExit(f"{path}: quarantine[{index}] must be an object")
        for field in ("cell", "reason", "expires"):
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                raise SystemExit(
                    f"{path}: quarantine[{index}].{field} must be a nonempty string"
                )
        try:
            date.fromisoformat(entry["expires"])
        except ValueError:
            raise SystemExit(
                f"{path}: quarantine[{index}].expires must be YYYY-MM-DD"
            ) from None
    return entries


def classify_cells(cells, quarantine, today: date):
    """Split cells into passed/warned/failed, applying the quarantine list.

    A failed cell whose name matches an unexpired quarantine entry becomes
    warned; an expired entry no longer suppresses the failure.
    """
    passed: list[str] = []
    warned: list[str] = []
    failed: list[str] = []
    notes: list[dict] = []
    for cell in cells:
        name = cell["name"]
        if cell.get("result") == "PASSED":
            passed.append(name)
            continue
        entry = next(
            (
                candidate
                for candidate in quarantine
                if fnmatch.fnmatchcase(name, candidate["cell"])
            ),
            None,
        )
        if entry is not None:
            note = {
                "cell": name,
                "reason": entry["reason"],
                "expires": entry["expires"],
                "expired": date.fromisoformat(entry["expires"]) < today,
            }
            notes.append(note)
            if not note["expired"]:
                warned.append(name)
                continue
        failed.append(name)

    if failed:
        result = "FAILED"
    elif warned:
        result = "WARNED"
    else:
        result = "PASSED"
    return result, passed, warned, failed, notes


def expected_cell_names(matrix):
    """Cell names as the evidence workflow composes them (deployment-distro[-node]-linux-amd64)."""
    if isinstance(matrix, dict):
        matrix = matrix["include"]
    return [evidence_cell_name(entry) for entry in matrix]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cells-dir", required=True)
    parser.add_argument("--build-metadata", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--quarantine")
    parser.add_argument(
        "--expected-cells",
        help="JSON matrix of the cells the run was supposed to produce",
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    metadata = load(Path(args.build_metadata))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    cells = []
    for path in sorted(Path(args.cells_dir).rglob("cell.json")):
        cells.append(load(path))
    cells.sort(key=lambda cell: cell.get("name", ""))

    subjects = build_subjects(metadata, Path(args.source_root).resolve())
    write_subjects(output / "evidence-subjects.txt", subjects)

    quarantine = load_quarantine(Path(args.quarantine) if args.quarantine else None)
    result, passed, warned, failed, quarantine_notes = classify_cells(cells, quarantine, date.today())
    expected = json.loads(args.expected_cells) if args.expected_cells else []
    seen = {cell["name"] for cell in cells}
    missing = [name for name in expected_cell_names(expected) if name not in seen]
    if missing:
        result = "FAILED"
        failed.extend(name for name in missing if name not in failed)
        for name in missing:
            print(f"::error title=evidence missing::{name} produced no cell result")
    if not cells:
        result = "FAILED"
    for note in quarantine_notes:
        state = "expired" if note["expired"] else "quarantined"
        print(f"::warning title=evidence {state}::{note['cell']}: {note['reason']} (expires {note['expires']})")

    configuration = []
    for cell in cells:
        levels = {name: data.get("ok") is True for name, data in cell.get("levels", {}).items()}
        configuration.append(
            {
                "name": cell["name"],
                "annotations": {
                    "buildTag": cell.get("build_tag"),
                    "sourceSha": cell.get("source_sha"),
                    "kit": cell.get("kit") or None,
                    "deployment": cell.get("deployment"),
                    "rosDistro": cell.get("distro"),
                    "node": cell.get("node") or None,
                    "platform": cell.get("platform"),
                    "levels": levels,
                    "overlayConformant": cell.get("overlayConformant"),
                    "readyS": cell.get("metrics", {}).get("ready_s"),
                    "arrivalS": cell.get("metrics", {}).get("arrival_s"),
                    "peakMib": cell.get("metrics", {}).get("peak_mib"),
                },
            }
        )

    predicate = {
        "result": result,
        "configuration": configuration,
        "passedTests": passed,
        "warnedTests": warned,
        "failedTests": failed,
    }
    run_url = os.environ.get("EVIDENCE_RUN_URL", "")
    if run_url:
        predicate["url"] = run_url
    (output / "evidence-predicate.json").write_text(
        json.dumps(predicate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    summary = {
        "build_tag": metadata.get("build_tag", "unknown"),
        "source_sha": metadata.get("openadkit_sha"),
        "result": result,
        "quarantine": quarantine_notes,
        "missing": missing,
        "cells": [
            {
                "name": cell["name"],
                "deployment": cell.get("deployment"),
                "distro": cell.get("distro"),
                "node": cell.get("node"),
                "platform": cell.get("platform"),
                "result": cell.get("result"),
                "overlayConformant": cell.get("overlayConformant"),
                "ready_s": cell.get("metrics", {}).get("ready_s"),
                "arrival_s": cell.get("metrics", {}).get("arrival_s"),
                "peak_mib": cell.get("metrics", {}).get("peak_mib"),
                "scenario": cell.get("levels", {}).get("L2", {}).get("scenario"),
            }
            for cell in cells
        ],
    }
    (output / "evidence-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    junit_cases = 0
    junit_failures = 0
    warned_cells = set(warned)
    suite = ET.Element("testsuite", {"name": "evidence"})
    for cell in cells:
        for level, data in sorted(cell.get("levels", {}).items()):
            junit_cases += 1
            case = ET.SubElement(
                suite,
                "testcase",
                {"name": f'{cell["name"]}.{level}', "classname": cell["deployment"]},
            )
            if not data.get("ok"):
                if cell["name"] in warned_cells:
                    ET.SubElement(case, "skipped", {"message": "quarantined"})
                else:
                    junit_failures += 1
                    ET.SubElement(case, "failure", {"message": f"{level} failed"})
    suite.set("tests", str(junit_cases))
    suite.set("failures", str(junit_failures))
    ET.ElementTree(suite).write(output / "evidence.junit.xml", encoding="utf-8", xml_declaration=True)

    print(
        json.dumps(
            {
                "result": result,
                "cells": len(cells),
                "warned": len(warned),
                "subjects": len(subjects),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
