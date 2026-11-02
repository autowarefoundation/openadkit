"""Runtime acceptance checks for deployments/safety-island (inside the API image).

The golden path then proves the vehicle drives; this proves who drives it: the
control command reaches Autoware only through the Safety Island's bridge, and
Autoware's own trajectory follower is not running.
"""
import re
import subprocess
import sys

TOPIC = "/control/trajectory_follower/control_cmd"
# domain_bridge names its node on each domain <name>_<domain>; Autoware is on 1.
BRIDGE = "safety_island_bridge_1"
FOLLOWER = "controller_node_exe"


def ros2(*arguments):
    return subprocess.run(
        ["ros2", *arguments, "--no-daemon", "--spin-time", "5"],
        capture_output=True, text=True, timeout=60, check=False,
    )


def main():
    info = ros2("topic", "info", "--verbose", TOPIC)
    sections = re.split(r"\n(?=Subscription count:)", info.stdout)
    publishers = re.findall(r"^Node name: (\S+)", sections[0], re.MULTILINE)
    print(f"{TOPIC} publishers: {publishers}", flush=True)
    if info.returncode != 0 or publishers != [BRIDGE]:
        print(info.stderr, file=sys.stderr, flush=True)
        return 1
    nodes = ros2("node", "list")
    if nodes.returncode != 0 or any(line.rsplit("/", 1)[-1] == FOLLOWER for line in nodes.stdout.split()):
        print(f"{FOLLOWER} is running, or the node list failed: {nodes.stderr}", file=sys.stderr, flush=True)
        return 1
    print(f"{FOLLOWER} is not running", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
