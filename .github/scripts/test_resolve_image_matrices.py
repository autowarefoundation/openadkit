import json
import pathlib
import subprocess
import sys

import resolve_image_matrices as r

INVENTORY = json.loads(pathlib.Path(".github/image-inventory.json").read_text())


def manifest_index(matrices):
    return {
        (e["repo"], e["target"], e["ros-distro"]): e["arches"]
        for e in matrices["manifest_matrix"]["include"]
    }


def test_multiarch_component_has_both_arches():
    idx = manifest_index(r.build_matrices(INVENTORY))
    assert idx[("component", "planning-control", "humble")] == "amd64 arm64"
    assert idx[("component", "planning-control", "jazzy")] == "amd64 arm64"


def test_amd64_only_targets_have_single_arch():
    idx = manifest_index(r.build_matrices(INVENTORY))
    assert idx[("component", "sensing-perception-cuda", "humble")] == "amd64"
    assert idx[("component", "sensing-perception-cuda", "jazzy")] == "amd64"


def test_carla_is_humble_only():
    idx = manifest_index(r.build_matrices(INVENTORY))
    assert idx[("component", "carla-interface", "humble")] == "amd64"
    assert ("component", "carla-interface", "jazzy") not in idx


def test_common_images_included_multiarch():
    idx = manifest_index(r.build_matrices(INVENTORY))
    assert idx[("common", "universe-common", "humble")] == "amd64 arm64"
    assert idx[("common", "universe-common-devel", "jazzy")] == "amd64 arm64"


def test_existing_matrices_unchanged_shape():
    m = r.build_matrices(INVENTORY)
    entry = m["component_matrix"]["include"][0]
    assert set(entry) == {"platform", "platform-label", "ros-distro", "target"}
    common_entry = m["common_matrix"]["include"][0]
    assert set(common_entry) == {"platform", "platform-label", "ros-distro"}


def test_old_outputs_removed():
    m = r.build_matrices(INVENTORY)
    assert "manifest_targets" not in m
    assert "component_manifest_targets" not in m
    assert "single_arch_component_targets" not in m


def test_cli_emits_exactly_three_keys():
    out = subprocess.run(
        [sys.executable, ".github/scripts/resolve_image_matrices.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    keys = {line.split("=", 1)[0] for line in out.splitlines() if line}
    assert keys == {"common_matrix", "component_matrix", "manifest_matrix"}
