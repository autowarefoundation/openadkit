"""Integrator evidence binds the source overlay and checks every hook report."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from release_fixtures import RELEASE_SHA, build_metadata

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))

import validation_matrix  # noqa: E402


def identities(cells):
    return [{key: cell[key] for key in ("deployment", "distro", "node", "kit") if key in cell} for cell in cells]


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "evidence" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


conformance = load("overlay_conformance")


def test_example_evidence_cells_follow_the_base_distros():
    runtime = validation_matrix.load_runtime(ROOT)
    assert identities(validation_matrix.example_kit_cells(runtime, ROOT)) == [
        {"deployment": "custom-kit", "distro": distro, "kit": "deployments/custom-kit"}
        for distro in ("humble", "jazzy")
    ]


def test_staged_flat_example_inherits_pins_without_host_build_products(tmp_path):
    source = tmp_path / "source"
    for directory in ("cli", "deployments", ".github/scripts"):
        shutil.copytree(ROOT / directory, source / directory, ignore=shutil.ignore_patterns("__pycache__", "build", "install", "log"))
    for file in ("openadkit", "openadkit.json", "components/docker-bake.hcl"):
        (source / file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / file, source / file)
    workspace = source / "deployments/custom-kit/overlay_ws"
    for product in ("build", "install", "log"):
        (workspace / product).mkdir()
        (workspace / product / "host-product").write_text("not evidence")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(build_metadata()))
    staged = tmp_path / "staged"
    result = subprocess.run(["bash", str(source / ".github/scripts/evidence/stage_kit.sh"), str(source), str(metadata), str(staged), RELEASE_SHA],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    runtime = validation_matrix.load_runtime(staged)
    example = staged / "deployments/custom-kit"
    kit = runtime.load_kit(example)
    assert set(kit.deployments) == {"custom-kit"} and kit.deployments["custom-kit"].path == "."
    assert all("@sha256:" in ref for refs in kit.images.values() for ref in refs.values())
    assert (example / "overlay_ws/src/acme_probe/src/probe.cpp").is_file()
    assert not any((example / "overlay_ws" / product).exists() for product in ("build", "install", "log"))


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


def test_deployment_overlay_workspace_is_a_hooked_service():
    containers = [
        {"Id": "kit", "Name": "/acme", "Mounts": [{"Destination": "/openadkit/overlay_ws_deployment"}]},
        {"Id": "external", "Name": "/heartbeat", "Mounts": []},
    ]
    reports = conformance.collect_reports(
        containers,
        lambda _: json.dumps({"unknownPackages": [], "unknownFiles": [], "unknownKeys": []}),
    )
    assert [item["container"] for item in reports] == ["acme"]
    assert reports[0]["conformant"] is True


def test_a_package_is_unknown_only_when_no_service_has_it():
    def report(packages):
        return json.dumps({"unknownPackages": packages, "unknownFiles": [], "unknownKeys": []})

    containers = [
        {"Id": name, "Name": f"/{name}", "Mounts": [{"Destination": "/openadkit/config/shared"}]}
        for name in ("control", "planning")
    ]
    reports = conformance.collect_reports(containers, {
        "control": report([]),
        "planning": report(["autoware_control_config"]),
    }.get)
    assert [item["conformant"] for item in reports] == [True, True]
    reports = conformance.collect_reports(containers, {
        "control": report(["typo_package"]),
        "planning": report(["autoware_control_config", "typo_package"]),
    }.get)
    assert [item["conformant"] for item in reports] == [False, False]


def test_summary_preserves_overlay_conformance(tmp_path):
    cells = tmp_path / "cells"
    cells.mkdir()
    (cells / "cell.json").write_text(json.dumps({
        "schemaVersion": 1, "name": "custom-kit-humble-linux-amd64", "deployment": "custom-kit",
        "distro": "humble", "result": "PASSED", "overlayConformant": False,
        "levels": {"L0": {"ok": True}, "L1": {"ok": True}, "L2": {"ok": True}},
        "metrics": {"ready_s": None, "arrival_s": None, "peak_mib": None},
    }))
    metadata = tmp_path / "metadata.json"
    metadata.write_text('{}')
    output = tmp_path / "summary"
    result = subprocess.run([
        sys.executable, str(SCRIPTS / "evidence/summary.py"), "--cells-dir", str(cells),
        "--build-metadata", str(metadata), "--output-dir", str(output),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads((output / "evidence-summary.json").read_text())["cells"][0]["overlayConformant"] is False
