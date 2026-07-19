import os
from pathlib import Path
import subprocess
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "install.sh"
PLANNING_SUM = "5536fce7bb8db7688fdf94ec004118b898637ad0d5b6175108b10989dd6e93b9"


def planning_zip(path, *, complete=True, traversal=False):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sample-map-planning/lanelet2_map.osm", "lanelet")
        if complete:
            archive.writestr("sample-map-planning/pointcloud_map.pcd", "pointcloud")
        if traversal:
            archive.writestr("sample-map-planning/../escaped", "unsafe")


def run_install(tmp_path, fixture, *, force=False, map_root=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "curl-calls"
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'printf "%s\\n" "$*" >> "$CURL_LOG"\n'
        'while (($#)); do if [ "$1" = -o ]; then shift; output="$1"; fi; shift; done\n'
        'cp "$FIXTURE_ZIP" "$output"\n'
    )
    checksum = bin_dir / "sha256sum"
    checksum.write_text(f"#!/usr/bin/env bash\nprintf '%s  %s\\n' '{PLANNING_SUM}' \"$1\"\n")
    curl.chmod(0o755)
    checksum.chmod(0o755)
    env = os.environ | {
        "AUTOWARE_MAP_DIR": str(map_root or tmp_path / "maps"),
        "CURL_LOG": str(log),
        "FIXTURE_ZIP": str(fixture),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    command = ["bash", str(INSTALLER), "sample-data", "planning-simulation"]
    if force:
        command.append("--force")
    return subprocess.run(command, env=env, text=True, capture_output=True), log


def existing_target(tmp_path):
    target = tmp_path / "maps/sample-map-planning"
    target.mkdir(parents=True)
    (target / "lanelet2_map.osm").write_text("old lanelet")
    (target / "pointcloud_map.pcd").write_text("old pointcloud")
    (target / "sentinel").write_text("keep")
    return target


def test_valid_sample_install(tmp_path):
    fixture = tmp_path / "sample.zip"
    planning_zip(fixture)
    result, _ = run_install(tmp_path, fixture)
    assert result.returncode == 0, result.stderr
    target = tmp_path / "maps/sample-map-planning"
    assert (target / "lanelet2_map.osm").read_text() == "lanelet"
    assert (target / "pointcloud_map.pcd").read_text() == "pointcloud"


@pytest.mark.parametrize(("complete", "traversal"), [(False, False), (True, True)])
def test_invalid_archive_preserves_existing_data(tmp_path, complete, traversal):
    fixture = tmp_path / "sample.zip"
    planning_zip(fixture, complete=complete, traversal=traversal)
    target = existing_target(tmp_path)
    result, _ = run_install(tmp_path, fixture, force=True)
    assert result.returncode != 0
    assert (target / "sentinel").read_text() == "keep"
    assert not (tmp_path / "maps/escaped").exists()


def test_parent_symlink_is_rejected_before_download(tmp_path):
    fixture = tmp_path / "sample.zip"
    planning_zip(fixture)
    referent = tmp_path / "referent"
    referent.mkdir()
    link = tmp_path / "linked-parent"
    link.symlink_to(referent, target_is_directory=True)
    result, log = run_install(tmp_path, fixture, map_root=link / "maps")
    assert result.returncode != 0
    assert not log.exists()
    assert not (referent / "maps").exists()


def test_carla_sample_data_is_unsupported(tmp_path):
    result = subprocess.run(
        ["bash", str(INSTALLER), "sample-data", "carla-simulation"],
        env=os.environ | {"AUTOWARE_MAP_DIR": str(tmp_path / "maps")},
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "deployments/carla-simulation/start-carla-e2e-demo.sh" in result.stdout
    assert not (tmp_path / "maps").exists()
