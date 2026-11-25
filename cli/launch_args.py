"""Launch arguments: what each `ros2 launch` service accepts, and the
<SERVICE>_LAUNCH_ARGS setting that passes more of them than the settings do."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import settings
from catalog import Deployment
from compose import docker, run_compose
from manifest import OpenADKitError
from settings import Selection, configuration_environment

# Open AD Kit's wrapper of autoware_launch components (deployments/shared/launch).
WRAPPER = "/openadkit/launch/component.launch.py"
# A setting resolved as a marker; a path, so it also stands where a setting names a bind mount.
MARKER = re.compile(r"/@([A-Za-z_][A-Za-z0-9_]*)@")
# A setting in a launch argument's value, such as module_preset:=${PLANNING_MODULE_PRESET}.
ARGUMENT_SETTING = re.compile(r":=\S*?(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)")


def passthrough_setting(service: str) -> str:
    return service.upper().replace("-", "_") + "_LAUNCH_ARGS"


def passthrough_value(selection: Selection, setting: str) -> str:
    """What Compose gives a <SERVICE>_LAUNCH_ARGS: the env files' value, or else the shell's."""
    return selection.environment[setting] if setting in selection.environment else os.environ.get(setting, "")


@dataclass
class LaunchService:
    name: str
    image: str
    # What `ros2 launch --show-args` reads: a package and a file, or a path.
    launch: list[str]
    # The arguments its command passes, each with the setting that sets it, if one does.
    fixed: dict[str, str | None]
    mounts: list[tuple[str, str]]

    @property
    def setting(self) -> str:
        return passthrough_setting(self.name)


def _services(deployment: Deployment, selection: Selection) -> dict[str, Any]:
    return json.loads(run_compose(deployment, selection, ["config", "--format", "json"]).stdout).get("services") or {}


def launch_services(deployment: Deployment, selection: Selection) -> dict[str, LaunchService]:
    """The services whose `ros2 launch` command ends in their <SERVICE>_LAUNCH_ARGS.

    A second model resolves as a marker each setting a launch argument reads,
    so each command shows which setting sets which argument, also in a kit
    that includes its base. Only those: a marker is no number or duration.
    """
    model = _services(deployment, selection)
    files = configuration_environment(deployment, selection.gpu)
    read = {
        name for path in settings.setting_files(deployment)
        for name in ARGUMENT_SETTING.findall(path.read_text(errors="ignore"))
    }
    # The CLI's own settings stay real, and so does the shell Compose runs in: a marker is no HOME.
    names = {
        name for name in read
        if name not in selection.injections and not name.startswith("OPENADKIT_") and (name in files or name not in os.environ)
    }
    markers = {name: f"/@{name}@" for name in names | set(map(passthrough_setting, model))}
    probe = _services(deployment, dataclasses.replace(selection, injections={**selection.injections, **markers}))
    found = {}
    for name, service in sorted(probe.items()):
        words = service.get("command") or []
        if words[:2] != ["ros2", "launch"] or markers[passthrough_setting(name)] not in words:
            continue
        launch: list[str] = []
        fixed: dict[str, str | None] = {}
        for word in words[2:]:
            argument, separator, value = word.partition(":=")
            if separator:
                marker = MARKER.search(value)
                fixed[argument] = marker.group(1) if marker else None
            elif not MARKER.fullmatch(word):
                launch.append(word)
        resolved = model[name]
        component = next((word.split(":=", 1)[1] for word in resolved["command"] if word.startswith("component:=")), None)
        if launch == [WRAPPER] and component:
            # The wrapper includes the component at runtime, so --show-args reads the component.
            launch = ["autoware_launch", Path(component).name + ".launch.xml"]
        mounts = [
            (volume["source"], volume["target"]) for volume in resolved.get("volumes") or []
            if volume.get("type") == "bind" and Path(volume["source"]).exists()
        ]
        found[name] = LaunchService(name, resolved["image"], launch, fixed, mounts)
    return found


def parse_show_args(text: str) -> dict[str, tuple[str | None, str]]:
    """`ros2 launch --show-args` output: each argument's default and description."""
    arguments: dict[str, tuple[str | None, str]] = {}
    name = None
    for line in text.splitlines():
        heading = re.fullmatch(r"    '(.+)':", line)
        if heading:
            name = heading.group(1)
            arguments[name] = (None, "")
        elif name and line.startswith("        "):
            default, description = arguments[name]
            detail = line.strip()
            value = re.fullmatch(r"\(default: (.*)\)", detail)
            if value:
                # A plain string is quoted; a substitution stays as launch prints it.
                default = value.group(1)
                if re.fullmatch(r"'[^']*'", default):
                    default = default[1:-1]
            elif detail != "no description given":
                description = f"{description} {detail}".strip()
            arguments[name] = (default, description)
    return arguments


def declared(service: LaunchService) -> dict[str, tuple[str | None, str]]:
    """The arguments the service's launch files declare, read in its image
    with its config overrides and overlay workspace mounted."""
    volumes = [option for source, target in service.mounts for option in ("--volume", f"{source}:{target}:ro")]
    result = docker(
        # A source checkout's images are its own builds, never pulled (compose.require_local_images).
        ["docker", "run", "--rm", "--pull", "never", *volumes, service.image,
         "ros2", "launch", *service.launch, "--show-args"],
        check=False,
    )
    if result.returncode:
        detail = (result.stderr.strip() or result.stdout.strip() or "no output").splitlines()[-1]
        raise OpenADKitError(f"could not read the launch arguments of {service.name}: {detail}")
    return parse_show_args(result.stdout)


def image_present(image: str) -> bool:
    return docker(["docker", "image", "inspect", image], check=False, trace=False).returncode == 0


def check(deployment: Deployment, selection: Selection, *, pull: bool) -> None:
    """Refuse a <SERVICE>_LAUNCH_ARGS that is not name:=value pairs or passes
    an argument the service's command already passes. Warn about an argument
    its launch files do not declare: `ros2 launch` ignores an argument nothing
    reads, but --show-args misses one a launch file reads without declaring.

    Pulls the images it reads, or else skips a service whose image is missing.
    """
    given = {
        name for name in {*selection.environment, *os.environ}
        if name.endswith("_LAUNCH_ARGS") and passthrough_value(selection, name).strip()
    }
    if not given:
        return
    services = {service.setting: service for service in launch_services(deployment, selection).values()}
    problems = []
    wanted: dict[str, list[str]] = {}
    # One for no service of this deployment does nothing; the unused-settings warning names it.
    for setting in sorted(given & services.keys()):
        service = services[setting]
        try:
            words = shlex.split(passthrough_value(selection, setting))
        except ValueError as error:
            problems.append(f"{setting}: {error}")
            continue
        for word in words:
            argument, separator, _ = word.partition(":=")
            if not argument or not separator:
                problems.append(f"{setting}: {word!r} is not name:=value")
            elif argument in service.fixed:
                via = service.fixed[argument]
                hint = f"set {via} instead" if via else "Open AD Kit sets it"
                problems.append(f"{setting}: {service.name} already passes {argument}; {hint}")
            else:
                wanted.setdefault(setting, []).append(argument)
    if wanted and pull:
        run_compose(
            deployment, selection, ["pull", "--policy", "missing", *sorted(services[s].name for s in wanted)], show=True
        )
    for setting in sorted(wanted):
        if not image_present(services[setting].image):
            print(f"note: {setting} not checked: {services[setting].image} is not pulled yet; run checks it", file=sys.stderr)
            del wanted[setting]
    with ThreadPoolExecutor(max_workers=8) as pool:
        known = dict(zip(wanted, pool.map(declared, [services[setting] for setting in wanted]), strict=True))
    for setting, arguments in sorted(wanted.items()):
        service = services[setting]
        unknown = [argument for argument in arguments if argument not in known[setting]]
        if unknown:
            print(
                f"warning: {setting}: the launch files of {service.name} declare no {', '.join(unknown)}, "
                f"so nothing may read it; list them with: openadkit settings {deployment.name} --service {service.name}",
                file=sys.stderr,
            )
    if problems:
        raise OpenADKitError("invalid launch arguments:\n  " + "\n  ".join(problems))
