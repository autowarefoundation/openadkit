#!/usr/bin/env python3
"""Check that the images' launch files read every launch argument the catalog
deployments pass.

`ros2 launch` ignores an argument that no launch file reads, so a setting that
an Autoware release renamed or removed keeps its place in settings.env and does
nothing. This check finds those arguments for every deployment, the ones that
are exempt from the evidence cells included.

For each service whose command is `ros2 launch ...`, it starts the service's
image and follows the launch file's includes there, with the overrides the
entrypoint applies. An argument is read when a file of that tree declares it,
substitutes it, or names it in Python. Python launch files are searched but
their own includes are not followed.

Usage: launch_arguments.py <openadkit> <ros-distro>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Runs inside the image, with ROS sourced by its entrypoint.
INNER = r'''
import json, re, sys
from pathlib import Path
from ament_index_python.packages import PackageNotFoundError, get_package_share_directory

spec, values = json.loads(sys.argv[1]), json.loads(sys.argv[2])


def share(package):
    try:
        return get_package_share_directory(package)
    except (PackageNotFoundError, ValueError):
        return None


def start_files():
    """The launch file the command names, and what Open AD Kit's wrapper includes."""
    if len(spec) == 1:
        files = [Path(spec[0])]
        component = values.get("component")
        if component and share("autoware_launch"):
            folder = "" if "/" in component else "components/"
            files.append(Path(share("autoware_launch")) / "launch" / f"{folder}{component}.launch.xml")
        return files
    root = share(spec[0])
    return list(Path(root).rglob(spec[1]))[:1] if root else []


def resolve(expression, current, local):
    for _ in range(8):
        replaced = re.sub(
            r"\$\(var ([^)\s]+)\)",
            lambda match: local.get(match.group(1), values.get(match.group(1), match.group(0))),
            expression,
        )
        if replaced == expression:
            break
        expression = replaced
    match = re.match(r"\$\(find-pkg-share ([^)\s]+)\)(.*)", expression)
    if match:
        root = share(match.group(1))
        return Path(root + match.group(2)) if root else None
    if "$(" in expression:
        return None
    return Path(expression) if expression.startswith("/") else current.parent / expression


todo, seen, unresolved = start_files(), {}, []
if not todo or not todo[0].is_file():
    print(json.dumps({"error": f"launch file not found: {' '.join(spec)}"}))
    sys.exit(0)
while todo:
    path = todo.pop()
    if path in seen or not path.is_file():
        continue
    text = seen[path] = path.read_text(errors="ignore")
    local = dict(re.findall(r'<(?:let|arg)\s+name="([^"]+)"\s+(?:value|default)="([^"]*)"', text))
    for expression in re.findall(r'<include\s+file="([^"]+)"', text):
        target = resolve(expression, path, local)
        if target is not None and target.is_file():
            todo.append(target)
        else:
            unresolved.append(expression)
text = "\n".join(seen.values())
unread = [
    name for name in values
    if name != "component" and not re.search(
        r'(name="{0}"|\(var {0}\)|[\'"]{0}[\'"])'.format(re.escape(name)), text)
]
print(json.dumps({"files": len(seen), "unread": unread, "unresolved": sorted(set(unresolved))}))
'''


def cli(openadkit: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([openadkit, *arguments], capture_output=True, text=True, check=False)


def launches(model: dict) -> list[dict]:
    """The `ros2 launch` commands of a resolved Compose model."""
    found = []
    for name, service in sorted(model.get("services", {}).items()):
        command = service.get("command") or []
        if command[:2] != ["ros2", "launch"]:
            continue
        words = command[2:]
        spec = [word for word in words if ":=" not in word]
        values = dict(word.split(":=", 1) for word in words if ":=" in word)
        mounts = [
            (volume["source"], volume["target"]) for volume in service.get("volumes", [])
            if volume.get("type") == "bind" and Path(volume["source"]).exists()
        ]
        found.append({"service": name, "image": service["image"], "spec": spec, "values": values, "mounts": mounts})
    return found


def inspect(launch: dict) -> dict:
    command = ["docker", "run", "--rm", "-i"]
    for source, target in launch["mounts"]:
        command += ["-v", f"{source}:{target}:ro"]
    command += [launch["image"], "python3", "-", json.dumps(launch["spec"]), json.dumps(launch["values"])]
    result = subprocess.run(command, input=INNER, capture_output=True, text=True, check=False)
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    return {"error": (result.stderr.strip().splitlines() or ["no output"])[-1]}


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    openadkit, distro = sys.argv[1:]
    listing = cli(openadkit, "list", "--json")
    if listing.returncode != 0:
        print(listing.stderr, file=sys.stderr)
        return 1
    # One check per launch command: deployments share most services. A CUDA
    # image has the launch files of its CPU image, which is the smaller pull.
    unique: dict[str, dict] = {}
    for deployment in json.loads(listing.stdout)["deployments"]:
        options = ["--ros-distro", distro] + (["--gpu"] if deployment["requirements"]["gpu"] == "required" else [])
        config = cli(openadkit, "config", deployment["name"], *options)
        if config.returncode != 0:
            # A deployment that does not support this distro has nothing to check.
            print(f"skipped {deployment['name']}: {(config.stderr.strip().splitlines() or ['no model'])[-1]}")
            continue
        for launch in launches(json.loads(config.stdout)):
            key = json.dumps([launch["spec"], sorted(launch["values"])])
            launch["deployment"] = deployment["name"]
            if key not in unique or ("-cuda" in unique[key]["image"] and "-cuda" not in launch["image"]):
                unique[key] = launch
    failed = False
    for launch in unique.values():
        result = inspect(launch)
        where = f"{launch['deployment']} {launch['service']}"
        if "error" in result:
            print(f"FAILED {where}: {result['error']}")
            failed = True
            continue
        for expression in result["unresolved"]:
            print(f"note   {where}: include not followed: {expression}")
        if result["unread"]:
            print(f"FAILED {where}: no launch file reads {', '.join(result['unread'])}")
            failed = True
        else:
            print(f"ok     {where}: {len(launch['values'])} arguments, {result['files']} launch files")
    if not unique:
        print("FAILED: no ros2 launch command found")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
