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

    def remaining():
        return deadline - time.monotonic()

    def rpc_timeout():
        # Cap every blocking call to the time left so no single RPC can overrun
        # the overall CARLA_LOAD_TIMEOUT budget.
        return min(10.0, remaining())

    # Phase 1: is the requested map already loaded?
    while remaining() > 0:
        try:
            client.set_timeout(rpc_timeout())
            current = client.get_world().get_map().name
            if current == map_name or current.endswith(f"/{map_name}"):
                print(f"CARLA map already loaded: {current}")
                return 0
            break
        except RuntimeError as error:
            last_error = error
            if remaining() <= 0:
                break
            time.sleep(min(2.0, remaining()))

    # Phase 2: request the load, leaving slack for phase-3 confirmation so a
    # slow load cannot consume the entire timeout budget.
    confirm_slack = 15.0
    if remaining() > confirm_slack:
        budget = max(1.0, remaining() - confirm_slack)
        print(f"Loading CARLA map {map_name} via {host}:{port} (timeout {budget:.0f}s)")
        try:
            client.set_timeout(budget)
            client.load_world_if_different(map_name)
        except RuntimeError as error:
            last_error = error

    # Phase 3: confirm the load completed within the remaining budget.
    while remaining() > 0:
        try:
            client.set_timeout(rpc_timeout())
            current = client.get_world().get_map().name
            if current == map_name or current.endswith(f"/{map_name}"):
                print(f"CARLA map loaded: {current}")
                return 0
        except RuntimeError as error:
            last_error = error
        if remaining() <= 0:
            break
        time.sleep(min(2.0, remaining()))

    print(f"Timed out waiting for CARLA map {map_name}: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
