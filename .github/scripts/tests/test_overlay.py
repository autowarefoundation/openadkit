"""The image entrypoint hook's overlay builder (components/overlay/overlay.py)."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "openadkit_overlay", ROOT / "components/overlay/overlay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path / "tmp-openadkit")
    monkeypatch.setattr(
        module, "LAYERS", [tmp_path / "layers" / name for name in ("shared", "base", "deployment")]
    )
    return module


def install(prefix, package, files):
    """An isolated colcon install prefix holding one package."""
    share = prefix / "share" / package
    for relative, content in files.items():
        (share / relative).parent.mkdir(parents=True, exist_ok=True)
        (share / relative).write_text(content)
    marker = prefix / "share/ament_index/resource_index/packages" / package
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    (prefix / "lib" / package).mkdir(parents=True)
    (prefix / "lib" / package / "node").write_text("binary")


def layer(tmp_path, name, package, relative, content):
    path = tmp_path / "layers" / name / "autoware" / package / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


GATE = "config/gate.param.yaml"
BASE_GATE = (
    "/**:\n  ros__parameters:\n    use_emergency_handling: true\n"
    "    check_heartbeat: $(var check_heartbeat)\n"
    "    nominal:\n      vel_lim: 25.0\n      lon_acc: [5.0, 4.0]\n"
)


def run(overlay, tmp_path, monkeypatch, capsys):
    prefix = tmp_path / "opt/autoware_launch"
    install(prefix, "autoware_launch", {GATE: BASE_GATE, "rviz/a.rviz": "rviz"})
    monkeypatch.setenv("AMENT_PREFIX_PATH", str(prefix))
    assert overlay.main() == 0
    out = capsys.readouterr()
    return out.out.strip(), out.err, overlay.ROOT


def test_layers_merge_in_order_and_keep_untouched_values(overlay, tmp_path, monkeypatch, capsys):
    layer(tmp_path, "shared", "autoware_launch", GATE,
          "/**:\n  ros__parameters:\n    use_emergency_handling: false\n")
    layer(tmp_path, "deployment", "autoware_launch", GATE,
          "/**:\n  ros__parameters:\n    nominal:\n      vel_lim: 8.0\n")
    prefixes, err, root = run(overlay, tmp_path, monkeypatch, capsys)
    assert prefixes == str(root / "autoware_launch")
    merged = yaml.safe_load((root / "autoware_launch/share/autoware_launch" / GATE).read_text())
    parameters = merged["/**"]["ros__parameters"]
    assert parameters["use_emergency_handling"] is False
    assert parameters["nominal"] == {"vel_lim": 8.0, "lon_acc": [5.0, 4.0]}
    # Launch substitutions are strings and survive the merge.
    assert parameters["check_heartbeat"] == "$(var check_heartbeat)"
    assert err == ""


def test_the_stable_path_exists_without_overrides_and_keeps_executables(
    overlay, tmp_path, monkeypatch, capsys
):
    prefixes, _, root = run(overlay, tmp_path, monkeypatch, capsys)
    share = root / "autoware_launch/share/autoware_launch"
    assert (share / "rviz/a.rviz").read_text() == "rviz"
    assert (root / "autoware_launch/share/ament_index/resource_index/packages/autoware_launch").exists()
    # Only share/ is copied; executables stay where they are.
    assert (root / "autoware_launch/lib").is_symlink()
    assert (root / "autoware_launch/lib/autoware_launch/node").read_text() == "binary"
    assert (tmp_path / "opt/autoware_launch/share/autoware_launch" / GATE).read_text() == BASE_GATE


def test_overrides_without_a_base_are_reported(overlay, tmp_path, monkeypatch, capsys):
    layer(tmp_path, "deployment", "autoware_launch", GATE,
          "/**:\n  ros__parameters:\n    use_emergncy_handling: false\n")
    layer(tmp_path, "deployment", "autoware_launch", "config/new.param.yaml", "a: 1\n")
    layer(tmp_path, "deployment", "missing_package", "config/x.yaml", "a: 1\n")
    _, err, root = run(overlay, tmp_path, monkeypatch, capsys)
    report = json.loads((root / "overlay-report.json").read_text())
    assert report == {
        "unknownPackages": ["missing_package"],
        "unknownFiles": ["autoware_launch/config/new.param.yaml"],
        "unknownKeys": [
            "autoware_launch/config/gate.param.yaml: /**.ros__parameters.use_emergncy_handling"
        ],
    }
    assert "use_emergncy_handling" in err


def test_non_yaml_files_replace_and_the_vehicle_description_is_linked(
    overlay, tmp_path, monkeypatch, capsys
):
    layer(tmp_path, "base", "autoware_launch", "rviz/a.rviz", "custom rviz")
    description = tmp_path / "ws/install/acme_description"
    install(description, "acme_description", {"config/vehicle_info.param.yaml": "wheel: 1\n"})
    monkeypatch.setenv("VEHICLE_MODEL", "acme")
    prefix = tmp_path / "opt/autoware_launch"
    install(prefix, "autoware_launch", {GATE: BASE_GATE, "rviz/a.rviz": "rviz"})
    monkeypatch.setenv("AMENT_PREFIX_PATH", f"{description}:{prefix}")
    assert overlay.main() == 0
    root = overlay.ROOT
    assert (root / "autoware_launch/share/autoware_launch/rviz/a.rviz").read_text() == "custom rviz"
    assert (root / "vehicle_description/config/vehicle_info.param.yaml").read_text() == "wheel: 1\n"
