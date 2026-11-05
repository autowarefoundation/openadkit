"""The AutoSD translation of a resolved Compose model (platforms/autosd/quadlet.py)."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]

spec = importlib.util.spec_from_file_location("openadkit_quadlet", ROOT / "platforms/autosd/quadlet.py")
quadlet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quadlet)


def model(tmp_path):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    (config / "dds.xml").write_text("<dds/>")
    empty = tmp_path / "empty"
    empty.mkdir(exist_ok=True)
    volumes = [
        {"type": "bind", "source": str(config / "dds.xml"), "target": "/etc/dds.xml", "read_only": True, "bind": {}},
        {"type": "bind", "source": str(empty), "target": "/openadkit/overlay_ws", "read_only": True, "bind": {}},
    ]
    return {"name": "openadkit-example", "services": {
        "map-check": {
            "image": "ghcr.io/x/oak:map-humble", "container_name": "autoware-map-check", "network_mode": "host",
            "init": True, "restart": "no", "entrypoint": ["bash", "-lc"], "command": ['echo "$${f}" 100%\n'],
        },
        "map": {
            "image": "ghcr.io/x/oak:map-humble", "container_name": "autoware-map", "network_mode": "host", "ipc": "host",
            "restart": "on-failure", "command": ["ros2", "launch", "map"], "volumes": volumes,
            "depends_on": {"map-check": {"condition": "service_completed_successfully", "required": True}},
        },
        "control": {
            "image": "ghcr.io/x/oak@sha256:abc", "container_name": "autoware-control", "network_mode": "host",
            "ipc": "host", "pid": "service:map", "init": True, "restart": "on-failure", "command": ["ros2", "a b"],
            "environment": {"ROS_DOMAIN_ID": "1", "HOST_UID": "1000", "HOST_GID": "1000", "TEXT": "a b"},
            "depends_on": {"map": {"condition": "service_started", "required": True}},
        },
    }}


def unit(output, name):
    return (output / "rootfs/etc/containers/systemd" / f"{name}.container").read_text()


def test_units_keep_the_compose_behaviour(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "out"
    quadlet.write(model(tmp_path), output, [])
    control = unit(output, "autoware-control")
    assert "Requires=autoware-map.service\nAfter=autoware-map.service" in control
    assert "PodmanArgs=--ipc=host --pid=container:autoware-map" in control
    assert "Restart=on-failure" in control and "Network=host" in control
    assert 'Exec=ros2 "a b"' in control
    assert 'Environment="TEXT=a b"' in control and "Environment=ROS_DOMAIN_ID=1" in control
    assert "HOST_UID" not in control and "HOST_GID" not in control
    assert "RunInit" not in control
    check = unit(output, "autoware-map-check")
    assert "Type=oneshot\nRemainAfterExit=yes" in check and "Restart=" not in check
    assert "RunInit=true" in check and "PodmanArgs=--entrypoint=bash" in check
    assert r'Exec=-lc "echo \"$${f}\" 100%%\n"' in check


def test_mounts_land_by_target_and_the_manifest_creates_an_empty_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "out"
    quadlet.write(model(tmp_path), output, [])
    root = output / "rootfs/usr/share/openadkit"
    assert (root / "etc/dds.xml").read_text() == "<dds/>"
    assert (root / "openadkit/overlay_ws").is_dir()
    directories = json.loads((output / "image.aib.yml").read_text())["content"]["make_dirs"]
    assert {"path": "/usr/share/openadkit/openadkit/overlay_ws", "parents": True, "exist_ok": True} in directories
    assert "Volume=/usr/share/openadkit/etc/dds.xml:/etc/dds.xml:ro" in unit(output, "autoware-map")


def test_manifest_embeds_each_image_once_by_tag_or_digest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "out"
    quadlet.write(model(tmp_path), output, [])
    content = yaml.safe_load((output / "image.aib.yml").read_text())["content"]
    assert content["container_images"] == [
        {"source": "ghcr.io/x/oak", "tag": "map-humble"},
        {"source": "ghcr.io/x/oak", "digest": "sha256:abc"},
    ]
    assert {"path": "/usr/share/openadkit/etc/dds.xml", "source_path": "rootfs/usr/share/openadkit/etc/dds.xml"} in content["add_files"]


def test_an_output_outside_the_working_directory_still_translates(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(quadlet, "EMBEDDED_LIMIT", 3)
    quadlet.write(model(tmp_path), tmp_path / "out", [])
    assert (tmp_path / "out/image.aib.yml").is_file()


def test_a_large_file_reaches_the_image_builder_by_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(quadlet, "EMBEDDED_LIMIT", 3)
    output = tmp_path / "out"
    quadlet.write(model(tmp_path), output, [])
    files = json.loads((output / "image.aib.yml").read_text())["content"]["add_files"]
    assert {"path": "/usr/share/openadkit/etc/dds.xml",
            "url": "file:///host/out/rootfs/usr/share/openadkit/etc/dds.xml"} in files
    assert (output / "rootfs/usr/share/openadkit/etc/dds.xml").is_file()


@pytest.mark.parametrize("reference, expected", [
    ("ghcr.io/x/oak:tag", {"source": "ghcr.io/x/oak", "tag": "tag"}),
    ("ghcr.io/x/oak:tag@sha256:abc", {"source": "ghcr.io/x/oak", "digest": "sha256:abc"}),
    ("localhost:5000/oak@sha256:abc", {"source": "localhost:5000/oak", "digest": "sha256:abc"}),
])
def test_image_references(reference, expected):
    assert quadlet.container_image(reference) == expected


@pytest.mark.parametrize("change, message", [
    (lambda m: m["services"]["map"].update(devices=["/dev/x"]), "devices has no translation"),
    (lambda m: m["services"]["map"].update(network_mode="none"), "network_mode"),
    (lambda m: m["services"]["map"].update(ipc="private"), "ipc"),
    (lambda m: m["services"]["control"].update(pid="host"), "pid"),
    (lambda m: m["services"]["map"]["volumes"][0].update(read_only=False), "writable"),
    (lambda m: m["services"]["map"]["volumes"][0].update(source="/no/such/file"), "does not exist"),
    (lambda m: m["services"]["map"]["depends_on"]["map-check"].update(condition="service_healthy"), "service_healthy"),
])
def test_what_has_no_translation_stops_and_writes_nothing(tmp_path, change, message):
    data = model(tmp_path)
    change(data)
    output = tmp_path / "out"
    with pytest.raises(quadlet.TranslationError, match=message):
        quadlet.write(data, output, [])
    assert not output.exists()


def test_a_mount_target_has_one_source(tmp_path):
    data = model(tmp_path)
    other = dict(data["services"]["map"]["volumes"][0], source=str(tmp_path / "empty"))
    data["services"]["control"]["volumes"] = [other]
    with pytest.raises(quadlet.TranslationError, match="two sources"):
        quadlet.write(data, tmp_path / "out", [])


def test_leaving_out_a_needed_service_stops(tmp_path):
    with pytest.raises(quadlet.TranslationError, match="map is needed"):
        quadlet.write(model(tmp_path), tmp_path / "out", ["map"])
    with pytest.raises(quadlet.TranslationError, match="no such service"):
        quadlet.write(model(tmp_path), tmp_path / "out", ["typo"])


def test_an_existing_output_is_not_replaced(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(quadlet.TranslationError, match="already exists"):
        quadlet.write(model(tmp_path), output, [])


def test_planning_simulation_translates_from_openadkit_config(tmp_path):
    """Every service of the real deployment has a translation, through the real command."""
    result = subprocess.run(
        [str(ROOT / "openadkit"), "config", "planning-simulation"],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
        # CI installs Compose v5 into ~/.docker, which the new HOME would hide.
        env={**os.environ, "HOME": str(tmp_path), "DOCKER_CONFIG": os.environ.get("DOCKER_CONFIG", str(Path.home() / ".docker"))},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    data["services"].pop("visualizer")
    names = set(data["services"])
    oneshots = {"map-check"}
    for name, service in data["services"].items():
        assert "[Container]" in quadlet.translate(name, service, data["services"], oneshots)
    assert {"map", "control", "planning"} <= names
