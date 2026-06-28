#!/usr/bin/env python3
import os
import sys
import time

import carla


def main():
    host = os.environ.get("CARLA_RPC_HOST", "127.0.0.1")
    port = int(os.environ.get("CARLA_RPC_PORT", "2000"))
    map_name = os.environ.get("CARLA_WORLD", "Town01")
    timeout = float(os.environ.get("CARLA_LOAD_TIMEOUT", "180"))
    deadline = time.monotonic() + timeout

    client = carla.Client(host, port)
    last_error = None

    while time.monotonic() < deadline:
        try:
            client.set_timeout(10.0)
            current = client.get_world().get_map().name
            if current == map_name or current.endswith(f"/{map_name}"):
                print(f"CARLA map already loaded: {current}")
                return 0
            break
        except RuntimeError as error:
            last_error = error
            time.sleep(2.0)

    remaining = max(10.0, deadline - time.monotonic())
    print(f"Loading CARLA map {map_name} via {host}:{port} (timeout {remaining:.0f}s)")

    try:
        client.set_timeout(remaining)
        client.load_world_if_different(map_name)
    except RuntimeError as error:
        last_error = error

    while time.monotonic() < deadline:
        try:
            client.set_timeout(10.0)
            current = client.get_world().get_map().name
            if current == map_name or current.endswith(f"/{map_name}"):
                print(f"CARLA map loaded: {current}")
                return 0
        except RuntimeError as error:
            last_error = error
        time.sleep(2.0)

    print(f"Timed out waiting for CARLA map {map_name}: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
