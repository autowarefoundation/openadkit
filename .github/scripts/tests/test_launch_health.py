"""The `ros2 launch` option that records a process that dies (components/shared/entrypoint/health)."""

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
HEALTH = ROOT / "components/shared/entrypoint/health"


@pytest.fixture
def health(tmp_path, monkeypatch):
    """The option, loaded against stand-ins for the launch packages of a ROS image."""
    names = {
        "launch": ["LaunchDescription"],
        "launch.actions": ["RegisterEventHandler"],
        "launch.event_handlers": ["OnProcessExit"],
        "ros2launch": [],
        "ros2launch.option": ["OptionExtension"],
    }
    for name, attributes in names.items():
        module = types.ModuleType(name)
        for attribute in attributes:
            setattr(module, attribute, type(attribute, (), {"__init__": lambda self, *args, **keywords: vars(self).update(
                args=args, **keywords)}))
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("openadkit_health", HEALTH / "openadkit_health.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "MARKER", str(tmp_path / "died"))
    return module


def exited(code, shutdown=False):
    return SimpleNamespace(process_name="tracker-4", returncode=code), SimpleNamespace(is_shutdown=shutdown)


def test_only_a_process_that_dies_while_the_launch_runs_is_recorded(health, tmp_path):
    marker = tmp_path / "died"
    health.record(*exited(0))
    health.record(*exited(-2, shutdown=True))
    assert not marker.exists()
    health.record(*exited(-9))
    health.record(*exited(1))
    assert marker.read_text() == "tracker-4 died with exit code -9\ntracker-4 died with exit code 1\n"


def test_a_marker_that_cannot_be_written_does_not_end_the_launch(health, monkeypatch, tmp_path):
    monkeypatch.setattr(health, "MARKER", str(tmp_path / "missing/died"))
    health.record(*exited(-9))


def test_the_option_puts_its_handler_before_what_is_launched(health):
    launched = object()
    (description,) = health.HealthOption().prelaunch(launched, None)
    handler, last = description.args[0]
    assert last is launched and handler.args[0].on_exit is health.record


def test_ros2_launch_finds_the_option_and_every_image_ships_it():
    (metadata,) = HEALTH.glob("*.dist-info")
    assert "[ros2launch.option]\nopenadkit_health = openadkit_health:HealthOption\n" == (metadata / "entry_points.txt").read_text()
    assert (metadata / "METADATA").read_text().startswith("Metadata-Version:")
    entrypoint = (ROOT / "components/shared/entrypoint/entrypoint.sh").read_text()
    assert 'export PYTHONPATH="/opt/openadkit/health${PYTHONPATH:+:${PYTHONPATH}}"' in entrypoint
    copies = [path for path in (ROOT / "components").glob("*/Dockerfile*")
              if "COPY components/shared/entrypoint/entrypoint.sh" in path.read_text()]
    assert len(copies) == 3
    for path in copies:
        assert "COPY components/shared/entrypoint/health/ /opt/openadkit/health/\n" in path.read_text(), path
