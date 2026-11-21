"""Readiness of this kit: the acme-probe service's healthcheck.

The kit's C++ node publishes (it survived the ABI boundary), its parameter
override is applied while the base's other parameters are not, and Autoware
runs with the kit's own vehicle package. Docker reruns the check until it
passes, so `openadkit run` returns only once the kit is ready.
"""
import subprocess

# (node, parameter, value): the override in config/autoware, a parameter the
# override leaves alone, and a dimension only acme_vehicle_description has.
EXPECTED = [
    ("/control/trajectory_follower/lane_departure_checker_node", "update_rate", "Double value is: 20.0"),
    ("/control/trajectory_follower/lane_departure_checker_node", "boundary_departure_checker", "Boolean value is: True"),
    ("/control/vehicle_cmd_gate", "vehicle_height", "Double value is: 2.1"),
]


def ros2(*arguments):
    try:
        return subprocess.run(["ros2", *arguments], capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        return None


def main():
    probe = ros2("topic", "echo", "--once", "/acme/probe")
    if probe is None or probe.returncode != 0:
        print("not ready: no message on /acme/probe", flush=True)
        return 1
    for node, parameter, value in EXPECTED:
        result = ros2("param", "get", node, parameter)
        if result is None or result.returncode != 0 or result.stdout.strip() != value:
            print(f"not ready: {parameter} of {node} is not {value!r}", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
