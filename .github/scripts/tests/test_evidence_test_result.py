"""Cell collection and aggregation for the evidence Test Result."""
import importlib.util
import sys
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[1] / "evidence"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


test_result = load_module("evidence_test_result", EVIDENCE / "test_result.py")


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