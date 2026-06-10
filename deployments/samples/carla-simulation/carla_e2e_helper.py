#!/usr/bin/env python3

import argparse
import math
import os
import time


def _env(name, cast=str):
    return cast(os.environ[name])


def wait_api():
    import carla

    client = carla.Client(_env("CARLA_RPC_HOST"), _env("CARLA_RPC_PORT", int))
    client.set_timeout(_env("CARLA_API_TIMEOUT", float))
    print(client.get_world().get_map().name)


def preload_world():
    import carla

    client = carla.Client(_env("CARLA_RPC_HOST"), _env("CARLA_RPC_PORT", int))
    client.set_timeout(_env("CARLA_LOAD_TIMEOUT", float))
    world = client.load_world(_env("CARLA_WORLD"))
    print(world.get_map().name)


def verify_runtime():
    import carla
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2

    rclpy.init()
    node = rclpy.create_node("openadkit_e2e_runtime_verifier")
    try:
        state = {"odom": None, "lidar": None}

        def on_odom(msg):
            state["odom"] = msg

        def on_lidar(msg):
            state["lidar"] = msg

        node.create_subscription(Odometry, "/localization/kinematic_state", on_odom, 10)
        node.create_subscription(
            PointCloud2,
            "/sensing/lidar/top/pointcloud_before_sync",
            on_lidar,
            qos_profile_sensor_data,
        )

        deadline = time.time() + 20.0
        while time.time() < deadline and (state["odom"] is None or state["lidar"] is None):
            rclpy.spin_once(node, timeout_sec=0.2)

        if state["odom"] is None:
            raise RuntimeError("Timed out waiting for /localization/kinematic_state")
        if state["lidar"] is None:
            raise RuntimeError("Timed out waiting for /sensing/lidar/top/pointcloud_before_sync")

        client = carla.Client(_env("CARLA_RPC_HOST"), _env("CARLA_RPC_PORT", int))
        client.set_timeout(10)
        world = client.get_world()
        world.tick(2)
        vehicles = [a for a in world.get_actors() if a.type_id.startswith("vehicle.")]
        ego = [v for v in vehicles if v.attributes.get("role_name") == "ego_vehicle"]
        print(world.get_map().name)
        print("vehicles", len(vehicles), "ego", len(ego))
        if not ego:
            raise SystemExit(1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def set_route_and_engage():
    import rclpy
    from autoware_adapi_v1_msgs.msg import OperationModeState, RouteState
    from autoware_adapi_v1_msgs.srv import ChangeOperationMode, ClearRoute, SetRoutePoints
    from geometry_msgs.msg import Pose
    from nav_msgs.msg import Odometry

    forward_distance = _env("AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE", float)
    settle_timeout = _env("AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT", float)
    autonomous_mode = getattr(OperationModeState, "AUTONOMOUS", 2)

    rclpy.init()
    node = rclpy.create_node("openadkit_e2e_route_and_engage")
    try:
        state = {"odom": None, "operation": None, "route": None}

        def on_odom(msg):
            state["odom"] = msg

        def on_operation(msg):
            state["operation"] = msg

        def on_route(msg):
            state["route"] = msg

        node.create_subscription(Odometry, "/localization/kinematic_state", on_odom, 10)
        node.create_subscription(OperationModeState, "/api/operation_mode/state", on_operation, 10)
        node.create_subscription(RouteState, "/api/routing/state", on_route, 10)

        def spin_until(predicate, timeout, description):
            deadline = time.time() + timeout
            while time.time() < deadline:
                rclpy.spin_once(node, timeout_sec=0.2)
                if predicate():
                    return True
            raise RuntimeError(f"Timed out waiting for {description}")

        def wait_for_service(client, timeout, name):
            deadline = time.time() + timeout
            while time.time() < deadline:
                if client.wait_for_service(timeout_sec=1.0):
                    return
            raise RuntimeError(f"Timed out waiting for service {name}")

        def call_service(client, request, timeout, name):
            wait_for_service(client, timeout, name)
            future = client.call_async(request)
            deadline = time.time() + timeout
            while time.time() < deadline:
                rclpy.spin_once(node, timeout_sec=0.2)
                if future.done():
                    response = future.result()
                    if response is None:
                        raise RuntimeError(f"{name} returned no response")
                    status = getattr(response, "status", None)
                    if status is not None and not status.success:
                        raise RuntimeError(f"{name} failed: {status.message}")
                    return response
            raise RuntimeError(f"Timed out waiting for response from {name}")

        spin_until(lambda: state["odom"] is not None, settle_timeout, "/localization/kinematic_state")
        start_pose = state["odom"].pose.pose

        clear_route = node.create_client(ClearRoute, "/api/routing/clear_route")
        set_route = node.create_client(SetRoutePoints, "/api/routing/set_route_points")
        change_route = node.create_client(SetRoutePoints, "/api/routing/change_route_points")
        change_to_autonomous = node.create_client(
            ChangeOperationMode, "/api/operation_mode/change_to_autonomous"
        )

        call_service(clear_route, ClearRoute.Request(), settle_timeout, "/api/routing/clear_route")

        clear_deadline = time.time() + min(10.0, settle_timeout)
        while time.time() < clear_deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
            if state["route"] is not None and state["route"].state == RouteState.UNSET:
                break

        request = SetRoutePoints.Request()
        request.header.frame_id = "map"
        request.option.allow_goal_modification = True
        request.goal = Pose()
        request.goal.position.x = start_pose.position.x + forward_distance
        request.goal.position.y = start_pose.position.y
        request.goal.position.z = 0.0
        request.goal.orientation = start_pose.orientation

        try:
            call_service(set_route, request, settle_timeout, "/api/routing/set_route_points")
        except RuntimeError as error:
            error_text = str(error).lower()
            if "route is already set" not in error_text and "invalid_state" not in error_text:
                raise
            call_service(change_route, request, settle_timeout, "/api/routing/change_route_points")
        print(
            "Route set: "
            f"start=({start_pose.position.x:.2f}, {start_pose.position.y:.2f}) "
            f"goal=({request.goal.position.x:.2f}, {request.goal.position.y:.2f})"
        )

        spin_until(
            lambda: state["operation"] is not None
            and state["operation"].is_autonomous_mode_available,
            settle_timeout,
            "autonomous mode availability",
        )
        call_service(
            change_to_autonomous,
            ChangeOperationMode.Request(),
            settle_timeout,
            "/api/operation_mode/change_to_autonomous",
        )
        spin_until(
            lambda: state["operation"] is not None and state["operation"].mode == autonomous_mode,
            settle_timeout,
            "autonomous mode transition",
        )
        print("Autonomous mode active")
    finally:
        node.destroy_node()
        rclpy.shutdown()


def verify_motion():
    import rclpy
    from nav_msgs.msg import Odometry

    timeout = _env("AUTOWARE_E2E_DRIVE_VERIFY_TIMEOUT", float)
    required_distance = _env("AUTOWARE_E2E_DRIVE_VERIFY_DISTANCE", float)

    rclpy.init()
    node = rclpy.create_node("openadkit_e2e_motion_verifier")
    try:
        state = {"odom": None}

        def on_odom(msg):
            state["odom"] = msg

        node.create_subscription(Odometry, "/localization/kinematic_state", on_odom, 10)

        deadline = time.time() + timeout
        while state["odom"] is None and time.time() < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)

        if state["odom"] is None:
            raise RuntimeError("Timed out waiting for /localization/kinematic_state")

        start = state["odom"].pose.pose.position
        start_x = start.x
        start_y = start.y

        while time.time() < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
            current = state["odom"].pose.pose.position
            distance = math.hypot(current.x - start_x, current.y - start_y)
            if distance >= required_distance:
                print(
                    f"Moved {distance:.2f} m: "
                    f"start=({start_x:.2f}, {start_y:.2f}) "
                    f"current=({current.x:.2f}, {current.y:.2f})"
                )
                raise SystemExit(0)

        current = state["odom"].pose.pose.position
        distance = math.hypot(current.x - start_x, current.y - start_y)
        raise RuntimeError(f"Autonomous motion verification failed: moved {distance:.2f} m")
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description="CARLA e2e helper commands")
    parser.add_argument(
        "command",
        choices=["wait-api", "preload-world", "verify-runtime", "set-route-and-engage", "verify-motion"],
    )
    args = parser.parse_args()

    commands = {
        "wait-api": wait_api,
        "preload-world": preload_world,
        "verify-runtime": verify_runtime,
        "set-route-and-engage": set_route_and_engage,
        "verify-motion": verify_motion,
    }
    commands[args.command]()


if __name__ == "__main__":
    main()
