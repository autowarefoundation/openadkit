import os
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "install.sh"
PLANNING_SUM = "5536fce7bb8db7688fdf94ec004118b898637ad0d5b6175108b10989dd6e93b9"


def write_planning_zip(path, *, complete=True, traversal=False):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sample-map-planning/", "")
        archive.writestr("sample-map-planning/lanelet2_map.osm", "lanelet map")
        if complete:
            archive.writestr("sample-map-planning/pointcloud_map.pcd", "pointcloud")
        if traversal:
            archive.writestr("sample-map-planning/../escaped", "unsafe")


def install_stubs(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl-calls"
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s\\n" "$*" >> "$CURL_LOG"\n'
        "output=\n"
        "while (($#)); do\n"
        '  if [ "$1" = -o ]; then shift; output="$1"; fi\n'
        "  shift\n"
        "done\n"
        'cp "$FIXTURE_ZIP" "$output"\n'
    )
    sha256sum = bin_dir / "sha256sum"
    sha256sum.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s  %s\\n' '{PLANNING_SUM}' \"$1\"\n"
    )
    curl.chmod(0o755)
    sha256sum.chmod(0o755)
    return bin_dir, curl_log


def run_planning(tmp_path, fixture, *, force=False, map_root=None):
    bin_dir, curl_log = install_stubs(tmp_path)
    map_root = map_root or tmp_path / "maps"
    env = os.environ | {
        "AUTOWARE_MAP_DIR": str(map_root),
        "CURL_LOG": str(curl_log),
        "FIXTURE_ZIP": str(fixture),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    command = ["bash", str(INSTALLER), "sample-data", "planning-simulation"]
    if force:
        command.append("--force")
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    return result, map_root, curl_log


def assert_complete(target):
    assert (target / "lanelet2_map.osm").read_text() == "lanelet map"
    assert (target / "pointcloud_map.pcd").read_text() == "pointcloud"


def test_valid_sample_installs_and_existing_complete_target_skips_download(tmp_path):
    fixture = tmp_path / "planning.zip"
    write_planning_zip(fixture)
    result, map_root, curl_log = run_planning(tmp_path, fixture)

    assert result.returncode == 0, result.stderr
    target = map_root / "sample-map-planning"
    assert_complete(target)
    assert len(curl_log.read_text().splitlines()) == 1

    second = subprocess.run(
        ["bash", str(INSTALLER), "sample-data", "planning-simulation"],
        env=os.environ
        | {
            "AUTOWARE_MAP_DIR": str(map_root),
            "CURL_LOG": str(curl_log),
            "FIXTURE_ZIP": str(fixture),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        },
        text=True,
        capture_output=True,
    )
    assert second.returncode == 0, second.stderr
    assert len(curl_log.read_text().splitlines()) == 1


def test_partial_existing_target_fails_without_download(tmp_path):
    fixture = tmp_path / "planning.zip"
    write_planning_zip(fixture)
    target = tmp_path / "maps/sample-map-planning"
    target.mkdir(parents=True)
    (target / "lanelet2_map.osm").write_text("old map")

    result, _, curl_log = run_planning(
        tmp_path, fixture, map_root=tmp_path / "maps"
    )

    assert result.returncode != 0
    assert "incomplete" in result.stdout
    assert not curl_log.exists() or not curl_log.read_text()
    assert (target / "lanelet2_map.osm").read_text() == "old map"


def test_force_failure_preserves_complete_existing_target(tmp_path):
    fixture = tmp_path / "invalid.zip"
    write_planning_zip(fixture, complete=False)
    target = tmp_path / "maps/sample-map-planning"
    target.mkdir(parents=True)
    (target / "lanelet2_map.osm").write_text("old lanelet")
    (target / "pointcloud_map.pcd").write_text("old pointcloud")
    (target / "sentinel").write_text("keep")

    result, map_root, _ = run_planning(
        tmp_path, fixture, force=True, map_root=tmp_path / "maps"
    )

    assert result.returncode != 0
    assert (target / "sentinel").read_text() == "keep"
    assert (target / "pointcloud_map.pcd").read_text() == "old pointcloud"
    assert not list(map_root.glob(".sample-map-planning.stage.*"))


def test_force_atomically_replaces_complete_existing_target(tmp_path):
    fixture = tmp_path / "planning.zip"
    write_planning_zip(fixture)
    target = tmp_path / "maps/sample-map-planning"
    target.mkdir(parents=True)
    (target / "lanelet2_map.osm").write_text("old lanelet")
    (target / "pointcloud_map.pcd").write_text("old pointcloud")
    (target / "old-only").write_text("remove")

    result, map_root, _ = run_planning(
        tmp_path, fixture, force=True, map_root=tmp_path / "maps"
    )

    assert result.returncode == 0, result.stderr
    assert_complete(target)
    assert not (target / "old-only").exists()
    assert not list(map_root.glob(".sample-map-planning.stage.*"))


def test_archive_traversal_is_rejected_without_replacing_target(tmp_path):
    fixture = tmp_path / "traversal.zip"
    write_planning_zip(fixture, traversal=True)
    target = tmp_path / "maps/sample-map-planning"
    target.mkdir(parents=True)
    (target / "lanelet2_map.osm").write_text("old lanelet")
    (target / "pointcloud_map.pcd").write_text("old pointcloud")

    result, _, _ = run_planning(
        tmp_path, fixture, force=True, map_root=tmp_path / "maps"
    )

    assert result.returncode != 0
    assert not (tmp_path / "maps/escaped").exists()
    assert (target / "pointcloud_map.pcd").read_text() == "old pointcloud"


def test_parent_symlink_is_rejected_before_download(tmp_path):
    fixture = tmp_path / "planning.zip"
    write_planning_zip(fixture)
    referent = tmp_path / "referent"
    referent.mkdir()
    symlink = tmp_path / "linked-parent"
    symlink.symlink_to(referent, target_is_directory=True)

    result, _, curl_log = run_planning(
        tmp_path, fixture, map_root=symlink / "maps"
    )

    assert result.returncode != 0
    assert "Refusing symlink path component" in result.stdout
    assert not curl_log.exists() or not curl_log.read_text()
    assert not (referent / "maps").exists()
