"""The evidence summary passes only when every expected cell passed."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import summary  # noqa: E402


@pytest.mark.parametrize(("results", "expected", "result", "missing"), [
    (["PASSED", "PASSED"], ["a", "b"], "PASSED", []),
    (["PASSED", "FAILED"], ["a", "b"], "FAILED", []),
    (["PASSED"], ["a", "b"], "FAILED", ["b"]),
    ([], [], "FAILED", []),
])
def test_summary_result(results, expected, result, missing):
    cells = [{"name": name, "result": status} for name, status in zip("ab"[:len(results)], results, strict=True)]
    assert summary.summarize(cells, expected) == (result, missing)


@pytest.mark.parametrize("include", [False, True])
def test_expected_names_match_workflow_matrix(include):
    matrix = [{"deployment": "planning-simulation", "distro": "humble"},
              {"deployment": "scenario-simulation", "distro": "jazzy", "node": "split"},
              {"deployment": "scenario-simulation", "distro": "humble", "node": None}]
    assert summary.expected_cell_names({"include": matrix} if include else matrix) == [
        "planning-simulation-humble-linux-amd64", "scenario-simulation-jazzy-split-linux-amd64",
        "scenario-simulation-humble-linux-amd64",
    ]
    assert summary.expected_cell_names({"include": []} if include else []) == []


@pytest.mark.parametrize(("source_sha", "release"), [(None, True), ("b" * 40, True), ("c" * 40, False)])
def test_summary_names_the_tested_commit_and_the_build(tmp_path, source_sha, release):
    root = Path(__file__).resolve().parents[3]
    cells = tmp_path / "cells/one"
    cells.mkdir(parents=True)
    (cells / "cell.json").write_text(json.dumps({
        "schemaVersion": 1, "name": "one", "deployment": "planning-simulation", "result": "PASSED", "levels": {},
        "metrics": {"ready_s": 1, "arrival_s": None, "peak_mib": None}}))
    metadata = tmp_path / "build-metadata.json"
    metadata.write_text(json.dumps({"build_tag": "1-1", "openadkit_sha": "b" * 40, "images": []}))
    command = [sys.executable, str(root / ".github/scripts/evidence/summary.py"), "--cells-dir", str(tmp_path / "cells"),
               "--build-metadata", str(metadata), "--output-dir", str(tmp_path / "out")]
    if source_sha:
        command += ["--source-sha", source_sha]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    written = json.loads((tmp_path / "out/evidence-summary.json").read_text())
    assert written["result"] == "PASSED"
    assert written["build_sha"] == "b" * 40
    assert written["source_sha"] == (source_sha or "b" * 40)
    assert written["release_evidence"] is release
