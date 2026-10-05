"""L1 readiness check: required AD API services and topics are present, and a
set of topics is actually publishing.

Runs inside a deployment's api container with the ROS and Autoware
environments sourced (see run_cell.sh). Writes a timeline JSON and exits
non-zero when an item misses its deadline.
"""
import argparse
import json
import subprocess
import time


def run(command, timeout):
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired:
        return 124, ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", action="append", default=[])
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--fresh", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--fresh-timeout", type=float, default=30.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    start = time.monotonic()
    failed = False
    timeline = {"items": [], "result": "FAILED", "elapsed_s": 0.0}

    def wait_for_listing(kind, name):
        command = ["ros2", kind, "list"]
        while args.timeout - (time.monotonic() - start) > 0:
            rc, out = run(command, timeout=30)
            if rc == 0 and name in out.split():
                return True
            time.sleep(2)
        return False

    for kind, names in (("service", args.service), ("topic", args.topic)):
        for name in names:
            found = wait_for_listing(kind, name)
            timeline["items"].append(
                {
                    "kind": kind,
                    "name": name,
                    "ok": found,
                    "ready_s": round(time.monotonic() - start, 1) if found else None,
                }
            )
            failed = failed or not found

    for name in args.fresh:
        rc, _ = run(
            ["timeout", str(int(args.fresh_timeout)), "ros2", "topic", "echo", "--once", name],
            timeout=args.fresh_timeout + 5,
        )
        fresh = rc == 0
        timeline["items"].append(
            {
                "kind": "fresh",
                "name": name,
                "ok": fresh,
                "ready_s": round(time.monotonic() - start, 1) if fresh else None,
            }
        )
        failed = failed or not fresh

    timeline["elapsed_s"] = round(time.monotonic() - start, 1)
    timeline["result"] = "FAILED" if failed else "PASSED"
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(timeline, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(timeline, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())