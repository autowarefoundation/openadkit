import hashlib
import os
from pathlib import Path
import subprocess
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "install.sh"
PLANNING_SUM = "5536fce7bb8db7688fdf94ec004118b898637ad0d5b6175108b10989dd6e93b9"


def planning_zip(path, *, omit=None, traversal=False):
    files = {
        "lanelet2_map.osm": "lanelet",
        "pointcloud_map.pcd": "pointcloud",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in files.items():
            if name != omit:
                archive.writestr(f"sample-map-planning/{name}", payload)
        if traversal:
            archive.writestr("sample-map-planning/../escaped", "unsafe")


def run_install(tmp_path, fixture, *, force=False, map_root=None, checksum_mode="real"):
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
    if checksum_mode == "always-ok":
        checksum.write_text(
            f"#!/usr/bin/env bash\nprintf '%s  %s\\n' '{PLANNING_SUM}' \"$1\"\n"
        )
    elif checksum_mode == "always-bad":
        bad = "0" * 64
        checksum.write_text(
            f"#!/usr/bin/env bash\nprintf '%s  %s\\n' '{bad}' \"$1\"\n"
        )
    else:
        # Delegate to a real digest of the file under test.
        checksum.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'python3 - "$1" <<\'PY\'\n'
            "import hashlib, sys\n"
            "path = sys.argv[1]\n"
            "digest = hashlib.sha256(open(path, 'rb').read()).hexdigest()\n"
            "print(f'{digest}  {path}')\n"
            "PY\n"
        )
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
    # Structure path uses a permissive checksum mock; integrity is covered by
    # test_checksum_mismatch_rejects_download and test_real_sha256sum_accepts_matching_digest.
    result, _ = run_install(tmp_path, fixture, checksum_mode="always-ok")
    assert result.returncode == 0, result.stderr + result.stdout
    target = tmp_path / "maps/sample-map-planning"
    assert (target / "lanelet2_map.osm").read_text() == "lanelet"
    assert (target / "pointcloud_map.pcd").read_text() == "pointcloud"


def test_sample_install_makes_files_world_readable(tmp_path):
    fixture = tmp_path / "sample.zip"
    with zipfile.ZipFile(fixture, "w") as archive:
        osm = zipfile.ZipInfo("sample-map-planning/lanelet2_map.osm")
        osm.external_attr = (0o100644 << 16)
        archive.writestr(osm, "lanelet")
        pcd = zipfile.ZipInfo("sample-map-planning/pointcloud_map.pcd")
        pcd.external_attr = (0o100600 << 16)
        archive.writestr(pcd, "pointcloud")
    result, _ = run_install(tmp_path, fixture, checksum_mode="always-ok")
    assert result.returncode == 0, result.stderr + result.stdout
    mode = (tmp_path / "maps/sample-map-planning/pointcloud_map.pcd").stat().st_mode
    assert mode & 0o044, oct(mode)


@pytest.mark.parametrize(
    ("omit", "traversal"),
    [
        ("pointcloud_map.pcd", False),
        ("lanelet2_map.osm", False),
        (None, True),
    ],
)
def test_invalid_archive_preserves_existing_data(tmp_path, omit, traversal):
    fixture = tmp_path / "sample.zip"
    planning_zip(fixture, omit=omit, traversal=traversal)
    target = existing_target(tmp_path)
    result, _ = run_install(tmp_path, fixture, force=True, checksum_mode="always-ok")
    assert result.returncode != 0
    assert (target / "sentinel").read_text() == "keep"
    assert not (tmp_path / "maps/escaped").exists()


def test_checksum_mismatch_rejects_download(tmp_path):
    fixture = tmp_path / "sample.zip"
    planning_zip(fixture)
    target = existing_target(tmp_path)
    result, _ = run_install(tmp_path, fixture, force=True, checksum_mode="always-bad")
    assert result.returncode != 0, result.stdout + result.stderr
    assert (target / "sentinel").read_text() == "keep"
    combined = (result.stdout + result.stderr).lower()
    assert "checksum" in combined


def test_real_sha256sum_accepts_matching_digest(tmp_path):
    """End-to-end path: real sha256sum must match installer-embedded digest."""
    fixture = tmp_path / "sample.zip"
    planning_zip(fixture)
    # Patch the expected digest in a copy of install.sh for this test only.
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    patched = tmp_path / "install.sh"
    text = INSTALLER.read_text()
    assert PLANNING_SUM in text
    patched.write_text(text.replace(PLANNING_SUM, digest))
    patched.chmod(0o755)

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
    curl.chmod(0o755)
    env = os.environ | {
        "AUTOWARE_MAP_DIR": str(tmp_path / "maps"),
        "CURL_LOG": str(log),
        "FIXTURE_ZIP": str(fixture),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", str(patched), "sample-data", "planning-simulation"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert (tmp_path / "maps/sample-map-planning/lanelet2_map.osm").exists()


def test_parent_symlink_is_rejected_before_download(tmp_path):
    fixture = tmp_path / "sample.zip"
    planning_zip(fixture)
    referent = tmp_path / "referent"
    referent.mkdir()
    link = tmp_path / "linked-parent"
    link.symlink_to(referent, target_is_directory=True)
    result, log = run_install(tmp_path, fixture, map_root=link / "maps", checksum_mode="always-ok")
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
