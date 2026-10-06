"""Quarantine handling in the evidence Test Result aggregation."""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


test_result = load_module("evidence_test_result", EVIDENCE / "test_result.py")

TODAY = date(2026, 10, 1)


def cell(name, result):
    return {"name": name, "result": result}


def test_all_passing_cells_pass():
    result, passed, warned, failed, notes = test_result.classify_cells(
        [cell("planning-simulation-humble-linux-amd64", "PASSED")], [], TODAY
    )
    assert result == "PASSED"
    assert passed == ["planning-simulation-humble-linux-amd64"]
    assert warned == []
    assert failed == []
    assert notes == []


def test_failure_without_quarantine_fails():
    result, _, warned, failed, _ = test_result.classify_cells(
        [cell("planning-simulation-humble-linux-amd64", "FAILED")], [], TODAY
    )
    assert result == "FAILED"
    assert warned == []
    assert failed == ["planning-simulation-humble-linux-amd64"]


def test_unexpired_quarantine_warns_instead_of_failing():
    quarantine = [{"cell": "scenario-*", "reason": "known flake", "expires": "2026-11-01"}]
    result, _, warned, failed, notes = test_result.classify_cells(
        [cell("scenario-simulation-jazzy-split-linux-amd64", "FAILED")], quarantine, TODAY
    )
    assert result == "WARNED"
    assert warned == ["scenario-simulation-jazzy-split-linux-amd64"]
    assert failed == []
    assert notes == [
        {
            "cell": "scenario-simulation-jazzy-split-linux-amd64",
            "reason": "known flake",
            "expires": "2026-11-01",
            "expired": False,
        }
    ]


def test_expired_quarantine_no_longer_suppresses_failure():
    quarantine = [{"cell": "scenario-*", "reason": "known flake", "expires": "2026-09-01"}]
    result, _, warned, failed, notes = test_result.classify_cells(
        [cell("scenario-simulation-jazzy-split-linux-amd64", "FAILED")], quarantine, TODAY
    )
    assert result == "FAILED"
    assert warned == []
    assert failed == ["scenario-simulation-jazzy-split-linux-amd64"]
    assert notes[0]["expired"] is True


def test_real_failure_beats_quarantined_failure():
    quarantine = [{"cell": "flaky-*", "reason": "known flake", "expires": "2026-11-01"}]
    result, _, warned, failed, _ = test_result.classify_cells(
        [cell("flaky-cell", "FAILED"), cell("solid-cell", "FAILED")], quarantine, TODAY
    )
    assert result == "FAILED"
    assert warned == ["flaky-cell"]
    assert failed == ["solid-cell"]


def test_quarantined_cell_that_passes_counts_as_passed():
    quarantine = [{"cell": "flaky-*", "reason": "known flake", "expires": "2026-11-01"}]
    result, passed, warned, failed, notes = test_result.classify_cells(
        [cell("flaky-cell", "PASSED")], quarantine, TODAY
    )
    assert result == "PASSED"
    assert passed == ["flaky-cell"]
    assert warned == []
    assert notes == []


def test_malformed_quarantine_entry_fails_loudly(tmp_path):
    path = tmp_path / "quarantine.json"
    path.write_text(
        '{"quarantine": [{"cell": "x", "reason": "why", "expires": "soon"}]}', encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        test_result.load_quarantine(path)


def test_missing_quarantine_file_is_allowed(tmp_path):
    assert test_result.load_quarantine(tmp_path / "missing.json") == []
    assert test_result.load_quarantine(None) == []


def test_expected_cell_names_match_workflow_composition():
    matrix = [
        {"deployment": "planning-simulation", "distro": "humble"},
        {"deployment": "scenario-simulation", "distro": "jazzy", "node": "split"},
        {"deployment": "scenario-simulation", "distro": "humble", "node": None},
    ]
    assert test_result.expected_cell_names(matrix) == [
        "planning-simulation-humble-linux-amd64",
        "scenario-simulation-jazzy-split-linux-amd64",
        "scenario-simulation-humble-linux-amd64",
    ]


def test_expected_cell_names_empty_matrix():
    assert test_result.expected_cell_names([]) == []


def test_expected_cells_accepts_the_workflow_include_matrix():
    assert test_result.expected_cell_names({"include": [{"deployment": "planning-simulation", "distro": "humble"}]}) == ["planning-simulation-humble-linux-amd64"]
