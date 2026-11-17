import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))
from evidence.report import render  # noqa: E402


def test_missing_metrics_are_not_zero():
    summary = {"result": "PASSED", "cells": [{
        "schemaVersion": 1, "name": "one", "result": "PASSED",
        "metrics": {"ready_s": 12, "arrival_s": None, "peak_mib": None},
    }]}
    text = render(summary)
    assert "Passing cells: **1/1**" in text
    assert "| Cell | Result | Ready (s) | Arrival (s) | Peak MiB |" in text
    assert "| one | PASSED | 12 | - | - |" in text
    assert render(summary, summary=False).startswith("| Cell |")


def test_report_keeps_missing_cells_visible():
    text = render({"result": "FAILED", "cells": [], "missing": ["absent"]})
    assert "Evidence result: **FAILED**" in text
    assert "Missing cell: absent" in text
