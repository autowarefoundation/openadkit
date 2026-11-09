"""Readiness of this kit: the acme-probe service's healthcheck.

The kit's C++ node publishes (it survived the ABI boundary), and its
parameter override is applied while the base's other parameters are not.
Docker reruns the check until it passes, so `openadkit run` returns only
once the kit is ready.
"""
import subprocess

NODE = "/control/trajectory_follower/lane_departure_checker_node"
EXPECTED = {
    "update_rate": "Double value is: 20.0",
    "boundary_departure_checker": "Boolean value is: True",
}


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
    for parameter, value in EXPECTED.items():
        result = ros2("param", "get", NODE, parameter)
        if result is None or result.returncode != 0 or result.stdout.strip() != value:
            print(f"not ready: {parameter} is not {value!r}", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
