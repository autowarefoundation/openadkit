"""Summarize a scenario-simulation run from its JUnit XML and simulator log.

The simulator writes JUnit XML under the deployment output directory and logs
one "Run sample" line per run. A run counts as passed when every sample ran,
none failed or timed out, and the JUnit suite has no failures or errors.
"""
import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()

    cases = passed = failed = errors = skipped = 0
    junit_files = 0
    for path in sorted(Path(args.output_dir).rglob("*.junit.xml")):
        junit_files += 1
        root = ET.parse(path).getroot()
        for case in root.iter("testcase"):
            cases += 1
            if case.find("failure") is not None:
                failed += 1
            elif case.find("error") is not None:
                errors += 1
            elif case.find("skipped") is not None:
                skipped += 1
            else:
                passed += 1

    log_path = Path(args.log)
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    runs = len(re.findall(r"Run sample", log))
    log_passed = len(re.findall(r"\bPassed\b", log))
    timeouts = len(re.findall(r"Timeout: The simulation", log))

    ok = (
        junit_files > 0
        and cases > 0
        and failed == 0
        and errors == 0
        and timeouts == 0
        and runs > 0
        and runs == log_passed
    )
    metrics = {
        "junit_files": junit_files,
        "cases": cases,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "log_runs": runs,
        "log_passed": log_passed,
        "log_timeouts": timeouts,
        "ok": ok,
    }
    Path(args.json).write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    print(json.dumps(metrics, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())