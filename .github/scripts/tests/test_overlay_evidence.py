"""Integrator evidence binds the source overlay and checks every hook report."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))

import validation_matrix  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "evidence" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


conformance = load("overlay_conformance")
subjects = load("subjects")


def test_example_evidence_cells_follow_the_base_distros():
    runtime = validation_matrix.load_runtime(ROOT)
    assert validation_matrix.example_kit_cells(runtime, ROOT) == [
        {"deployment": "custom-planning", "distro": distro, "kit": "examples/custom-kit"}
        for distro in ("humble", "jazzy")
    ]


def test_overlay_subject_ignores_build_products_but_binds_sources(tmp_path):
    tree = tmp_path / "source"
    for directory in ("cli", "deployments", "examples"):
        shutil.copytree(ROOT / directory, tree / directory, ignore=shutil.ignore_patterns("__pycache__", "build", "install", "log"))
    shutil.copy2(ROOT / "openadkit.json", tree / "openadkit.json")
    kit = tree / "examples/custom-kit"

    def digest():
        return dict((name, digest) for digest, name in subjects.build_subjects({}, tree))["overlay:examples/custom-kit"]

    initial = digest()
    generated = kit / "deployments/custom-planning/overlay_ws/install"
    generated.mkdir()
    (generated / "host-binary").write_bytes(b"binary")
    assert digest() == initial
    (kit / "deployments/custom-planning/config.env").write_text("VEHICLE_ID=changed\n")
    assert digest() != initial


@pytest.mark.parametrize("report, expected", [
    (json.dumps({"unknownPackages": [], "unknownFiles": [], "unknownKeys": []}), True),
    (json.dumps({"unknownPackages": [], "unknownFiles": [], "unknownKeys": ["typo"]}), False),
    ("", False),
    ("[]", False),
    (json.dumps({"unknownPackages": [], "unknownFiles": [], "unknownKeys": "bad"}), False),
])
def test_hook_reports_are_required_and_unknown_keys_are_nonconformant(report, expected):
    containers = [
        {"Id": "hooked", "Name": "/control", "Mounts": [{"Destination": "/openadkit/config/deployment"}]},
        {"Id": "external", "Name": "/heartbeat", "Mounts": []},
    ]
    reports = conformance.collect_reports(containers, lambda id: report)
    assert len(reports) == 1
    assert reports[0]["container"] == "control"
    assert reports[0]["conformant"] is expected


def test_test_result_preserves_overlay_conformance(tmp_path):
    cells = tmp_path / "cells"
    cells.mkdir()
    (cells / "cell.json").write_text(json.dumps({
        "name": "custom-planning-humble-linux-amd64", "deployment": "custom-planning",
        "distro": "humble", "result": "PASSED", "overlayConformant": False,
        "levels": {"L0": {"ok": True}, "L1": {"ok": True}, "L2": {"ok": True}},
    }))
    metadata = tmp_path / "metadata.json"
    metadata.write_text('{}')
    output = tmp_path / "attestation"
    result = subprocess.run([
        sys.executable, str(SCRIPTS / "evidence/test_result.py"), "--cells-dir", str(cells),
        "--build-metadata", str(metadata), "--source-root", str(ROOT), "--output-dir", str(output),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    predicate = json.loads((output / "evidence-predicate.json").read_text())
    assert predicate["configuration"][0]["annotations"]["overlayConformant"] is False
    assert json.loads((output / "evidence-summary.json").read_text())["cells"][0]["overlayConformant"] is False
