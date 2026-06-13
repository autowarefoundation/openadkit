#!/usr/bin/env python3

import argparse
import math
import os
import time


_MISSING = object()


def _env(name, cast=str, default=_MISSING):
    value = os.environ.get(name)
    if value is None or value == "":
        if default is not _MISSING:
            return default
        raise KeyError(name)
    return cast(value)


def _yaw_from_quaternion(q):
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


def _quaternion_from_yaw(yaw):
    from geometry_msgs.msg import Quaternion

    q = Quaternion()
    q.z = math.sin(yaw / 2.0)
    q.w = math.cos(yaw / 2.0)
    return q


def verify_runtime():
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import PointCloud2

    rclpy.init()
    node = rclpy.create_node("openadkit_awsim_e2e_runtime_verifier")
    try:
        state = {"clock": None, "odom": None, "lidar": None}

        node.create_subscription(Clock, "/clock", lambda msg: state.__setitem__("clock", msg), 10)
        node.create_subscription(Odometry, "/localization/kinematic_state", lambda msg: state.__setitem__("odom", msg), 10)
        node.create_subscription(
            PointCloud2,
            "/sensing/lidar/top/pointcloud_raw",
            lambda msg: state.__setitem__("lidar", msg),
            qos_profile_sensor_data,
        )

        deadline = time.time() + _env("AUTOWARE_E2E_VERIFY_RUNTIME_TIMEOUT", float, 20.0)
        while time.time() < deadline and any(value is None for value in state.values()):
            rclpy.spin_once(node, timeout_sec=0.2)

        missing = [name for name, value in state.items() if value is None]
        if missing:
            raise RuntimeError("Timed out waiting for " + ", ".join(missing))

        pose = state["odom"].pose.pose.position
        print(f"AWSIM runtime verified: pose=({pose.x:.2f}, {pose.y:.2f})")
    finally:
        node.destroy_node()
        rclpy.shutdown()


def set_route_and_engage():
    import rclpy
    from autoware_adapi_v1_msgs.msg import OperationModeState, RouteState
    from autoware_adapi_v1_msgs.srv import ChangeOperationMode, ClearRoute, SetRoutePoints
    from autoware_vehicle_msgs.srv import ControlModeCommand
    from geometry_msgs.msg import Pose
    from nav_msgs.msg import Odometry

    forward_distance = _env("AUTOWARE_E2E_ROUTE_FORWARD_DISTANCE", float)
    settle_timeout = _env("AUTOWARE_E2E_ROUTE_SETTLE_TIMEOUT", float)
    autonomous_mode = OperationModeState.AUTONOMOUS

    rclpy.init()
    node = rclpy.create_node("openadkit_awsim_e2e_route_and_engage")
    try:
        state = {"odom": None, "operation": None, "route": None}

        node.create_subscription(Odometry, "/localization/kinematic_state", lambda msg: state.__setitem__("odom", msg), 10)
        node.create_subscription(OperationModeState, "/api/operation_mode/state", lambda msg: state.__setitem__("operation", msg), 10)
        node.create_subscription(RouteState, "/api/routing/state", lambda msg: state.__setitem__("route", msg), 10)

        def spin_until(predicate, timeout, description):
            deadline = time.time() + timeout
            while time.time() < deadline:
                rclpy.spin_once(node, timeout_sec=0.2)
                if predicate():
                    return
            raise RuntimeError(f"Timed out waiting for {description}")

        def wait_for_service(client, timeout):
            deadline = time.time() + timeout
            while time.time() < deadline:
                if client.wait_for_service(timeout_sec=1.0):
                    return True
            return False

        def call_service(client, request, timeout, name, required=True):
            if not wait_for_service(client, timeout):
                if required:
                    raise RuntimeError(f"Timed out waiting for service {name}")
                print(f"Service unavailable, skipping: {name}")
                return None
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
        change_to_autonomous = node.create_client(ChangeOperationMode, "/api/operation_mode/change_to_autonomous")
        awsim_control_mode = node.create_client(ControlModeCommand, "input/control_mode_request")

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

        goal_x = _env("AWSIM_E2E_GOAL_X", float, None)
        goal_y = _env("AWSIM_E2E_GOAL_Y", float, None)
        goal_yaw = _env("AWSIM_E2E_GOAL_YAW", float, None)
        yaw = _yaw_from_quaternion(start_pose.orientation)
        if goal_x is None or goal_y is None:
            forward_x = math.cos(yaw) * forward_distance
            forward_y = math.sin(yaw) * forward_distance
            if goal_x is None:
                goal_x = start_pose.position.x + forward_x
            if goal_y is None:
                goal_y = start_pose.position.y + forward_y
        if goal_yaw is None:
            goal_yaw = yaw

        request.goal.position.x = goal_x
        request.goal.position.y = goal_y
        request.goal.position.z = 0.0
        request.goal.orientation = _quaternion_from_yaw(goal_yaw)

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
            lambda: state["operation"] is not None and state["operation"].is_autonomous_mode_available,
            settle_timeout,
            "autonomous mode availability",
        )
        call_service(change_to_autonomous, ChangeOperationMode.Request(), settle_timeout, "/api/operation_mode/change_to_autonomous")
        spin_until(lambda: state["operation"] is not None and state["operation"].mode == autonomous_mode, settle_timeout, "autonomous mode transition")

        control_mode_request = ControlModeCommand.Request()
        control_mode_request.mode = 1
        call_service(awsim_control_mode, control_mode_request, 5.0, "input/control_mode_request", required=False)
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
    node = rclpy.create_node("openadkit_awsim_e2e_motion_verifier")
    try:
        state = {"odom": None}
        node.create_subscription(Odometry, "/localization/kinematic_state", lambda msg: state.__setitem__("odom", msg), 10)

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
                return

        current = state["odom"].pose.pose.position
        distance = math.hypot(current.x - start_x, current.y - start_y)
        raise RuntimeError(f"Autonomous motion verification failed: moved {distance:.2f} m")
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description="AWSIM e2e helper commands")
    parser.add_argument("command", choices=["verify-runtime", "set-route-and-engage", "verify-motion"])
    args = parser.parse_args()

    commands = {
        "verify-runtime": verify_runtime,
        "set-route-and-engage": set_route_and_engage,
        "verify-motion": verify_motion,
    }
    commands[args.command]()


if __name__ == "__main__":
    main()
