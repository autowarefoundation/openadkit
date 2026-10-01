"""Aggregate evidence cells into the inputs of an in-toto Test Result attestation.

Outputs, under --output-dir:
  evidence-subjects.txt   subjects-checksums lines for actions/attest
  evidence-predicate.json Test Result v0.1 predicate
  evidence-summary.json   cells summary for the job summary and exit status
  evidence.junit.xml      JUnit view of the run
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from subjects import build_subjects, write_subjects  # noqa: E402


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cells-dir", required=True)
    parser.add_argument("--build-metadata", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    metadata = load(Path(args.build_metadata))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    cells = []
    for path in sorted(Path(args.cells_dir).rglob("*.cell.json")):
        cells.append(load(path))
    cells.sort(key=lambda cell: cell.get("name", ""))

    subjects = build_subjects(metadata, Path(args.source_root).resolve())
    write_subjects(output / "evidence-subjects.txt", subjects)

    passed = [cell["name"] for cell in cells if cell.get("result") == "PASSED"]
    failed = [cell["name"] for cell in cells if cell.get("result") != "PASSED"]
    result = "PASSED" if cells and not failed else "FAILED"

    configuration = []
    for cell in cells:
        levels = {name: bool(data.get("ok")) for name, data in cell.get("levels", {}).items()}
        configuration.append(
            {
                "name": cell["name"],
                "annotations": {
                    "deployment": cell.get("deployment"),
                    "rosDistro": cell.get("distro"),
                    "node": cell.get("node") or None,
                    "platform": cell.get("platform"),
                    "levels": levels,
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
        "warnedTests": [],
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
        "cells": [
            {
                "name": cell["name"],
                "deployment": cell.get("deployment"),
                "distro": cell.get("distro"),
                "node": cell.get("node"),
                "platform": cell.get("platform"),
                "result": cell.get("result"),
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
                junit_failures += 1
                ET.SubElement(case, "failure", {"message": f"{level} failed"})
    suite.set("tests", str(junit_cases))
    suite.set("failures", str(junit_failures))
    ET.ElementTree(suite).write(output / "evidence.junit.xml", encoding="utf-8", xml_declaration=True)

    print(json.dumps({"result": result, "cells": len(cells), "subjects": len(subjects)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())