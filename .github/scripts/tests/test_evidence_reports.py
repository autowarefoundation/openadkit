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
    assert "| PASSED | 12 | - | - |" in text
    assert "comparison" not in text


def test_comparison_is_explicit_and_uses_the_same_canonical_metrics():
    current = {"result": "PASSED", "cells": [{
        "schemaVersion": 1, "name": "one", "result": "PASSED",
        "metrics": {"ready_s": 12, "arrival_s": None, "peak_mib": 200},
    }]}
    previous = {"build_tag": "previous-build", "cells": [{
        "schemaVersion": 1, "name": "one", "metrics": {"ready_s": 10, "arrival_s": None, "peak_mib": 150},
    }]}
    text = render(current, previous)
    assert "Metrics comparison vs build `previous-build`" in text
    assert "| one | ready_s | 10 | 12 | 2 |" in text
    assert "| one | arrival_s | - | - | - |" in text
    assert "not an upgrade acceptance test" in text


def test_report_keeps_missing_cells_visible():
    text = render({"result": "FAILED", "cells": [], "missing": ["absent"]})
    assert "Evidence result: **FAILED**" in text
    assert "Missing cell: absent" in text
