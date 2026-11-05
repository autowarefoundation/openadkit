"""Integrator evidence covers the example kit as a release would stage it."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from release_fixtures import RELEASE_SHA, build_metadata

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))

import validation_matrix  # noqa: E402


def identities(cells):
    return [{key: cell[key] for key in ("deployment", "distro", "node", "kit") if key in cell} for cell in cells]


def test_example_evidence_cells_follow_the_base_distros():
    runtime = validation_matrix.load_runtime(ROOT)
    assert identities(validation_matrix.example_kit_cells(runtime, ROOT)) == [
        {"deployment": kit, "distro": distro, "kit": f"deployments/{kit}"}
        for kit in ("custom-kit", "safety-island") for distro in ("humble", "jazzy")
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
