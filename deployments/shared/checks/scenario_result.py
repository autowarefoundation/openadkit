"""Exit with the verdict of a scenario run.

scenario_test_runner exits 0 whatever the scenarios did, so the scenario
service ends with this instead: every JUnit case written under the output
directory since the run began must pass, and there must be one.

    python3 scenario_result.py OUTPUT_DIRECTORY SINCE_EPOCH_SECONDS
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def verdict(directory: Path, since: float) -> int:
    cases = failed = 0
    for path in sorted(directory.rglob("*.junit.xml")):
        if path.stat().st_mtime < since:
            continue
        for case in ET.parse(path).getroot().iter("testcase"):
            cases += 1
            if any(case.find(outcome) is not None for outcome in ("failure", "error", "skipped")):
                failed += 1
                print(f"scenario: {case.get('name')} did not pass", file=sys.stderr)
    if not cases:
        print(f"scenario: no result under {directory}", file=sys.stderr)
        return 1
    print(f"scenario: {cases - failed} of {cases} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(verdict(Path(sys.argv[1]), float(sys.argv[2])))
