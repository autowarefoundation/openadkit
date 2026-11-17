"""Readiness of the Autoware graph, checked once: the api service's healthcheck.

The deployment's settings.env names what to check (READINESS_CHECKS): AD API
services and topics that must be listed, and topics that must deliver a
message. Docker reruns the check until it passes, so `openadkit run` returns
only once Autoware is ready. Nothing to check passes at once.
"""
import argparse
import subprocess


def ros2(*arguments, timeout):
    try:
        return subprocess.run(["ros2", *arguments], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", action="append", default=[])
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--fresh", action="append", default=[], help="a topic that must deliver a message")
    args = parser.parse_args()

    missing = []
    for kind, names in (("service", args.service), ("topic", args.topic)):
        if names:
            listed = ros2(kind, "list", timeout=30)
            present = set(listed.stdout.split()) if listed and listed.returncode == 0 else set()
            missing += [f"{kind} {name}" for name in names if name not in present]
    # A topic that is not listed yet cannot deliver either.
    if not missing:
        for name in args.fresh:
            echo = ros2("topic", "echo", "--once", name, timeout=30)
            if echo is None or echo.returncode != 0:
                missing.append(f"no message on {name}")
    for item in missing:
        print(f"not ready: {item}", flush=True)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
