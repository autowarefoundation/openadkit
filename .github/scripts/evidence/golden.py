"""Golden path over AD API: initialize, route, engage, wait for ARRIVED.

Runs inside a deployment's api container (see run_cell.sh). Exit 0 on arrival.
Ported from the 2026-09-27 spike; Humble passed 10/10 there.
"""
import sys
import time

import rclpy
from autoware_adapi_v1_msgs.msg import (
    LocalizationInitializationState,
    OperationModeState,
    RouteState,
)
from autoware_adapi_v1_msgs.srv import (
    ChangeOperationMode,
    InitializeLocalization,
    SetRoutePoints,
)
from geometry_msgs.msg import Pose, PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

START = dict(x=3648.464, y=73505.020, z=18.924, qz=0.750460, qw=0.660916)
GOAL = dict(x=3638.004, y=73587.122, z=19.612, qz=0.750462, qw=0.660913)
TIMEOUT_READY, TIMEOUT_DRIVE = 300.0, 300.0


def pose(p):
    m = Pose()
    m.position.x, m.position.y, m.position.z = p["x"], p["y"], p["z"]
    m.orientation.z, m.orientation.w = p["qz"], p["qw"]
    return m


class Golden(Node):
    def __init__(self):
        super().__init__("openadkit_golden_path")
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
        self.route = self.loc = self.op = None
        self.create_subscription(RouteState, "/api/routing/state", lambda m: setattr(self, "route", m.state), latched)
        self.create_subscription(LocalizationInitializationState, "/api/localization/initialization_state", lambda m: setattr(self, "loc", m.state), latched)
        self.create_subscription(OperationModeState, "/api/operation_mode/state", lambda m: setattr(self, "op", m), latched)
        self.init_cli = self.create_client(InitializeLocalization, "/api/localization/initialize")
        self.route_cli = self.create_client(SetRoutePoints, "/api/routing/set_route_points")
        self.auto_cli = self.create_client(ChangeOperationMode, "/api/operation_mode/change_to_autonomous")
        self.t0 = time.monotonic()

    def spin_until(self, cond, timeout, what):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.2)
            if cond():
                return True
        self.get_logger().error(f"timeout: {what}")
        return False

    def call(self, cli, req, what, timeout=10.0):
        fut = cli.call_async(req)
        if not self.spin_until(fut.done, timeout, what):
            return False
        st = fut.result().status
        if not st.success:
            self.get_logger().warn(f"{what}: {st.message}")
        return st.success

    def mark(self, what):
        print(f"[golden] {time.monotonic() - self.t0:6.1f}s {what}", flush=True)

    def run(self):
        for cli in (self.init_cli, self.route_cli, self.auto_cli):
            if not self.spin_until(cli.service_is_ready, TIMEOUT_READY, cli.srv_name):
                return 2
        self.mark("services ready")

        # 1) initial pose (retry until localization reports INITIALIZED)
        req = InitializeLocalization.Request()
        p = PoseWithCovarianceStamped()
        p.header.frame_id = "map"
        p.pose.pose = pose(START)
        p.pose.covariance[0] = p.pose.covariance[7] = 0.25
        p.pose.covariance[35] = 0.0685
        req.pose = [p]
        ok = False
        for _ in range(30):
            self.call(self.init_cli, req, "initialize", 30.0)
            if self.spin_until(lambda: self.loc == LocalizationInitializationState.INITIALIZED, 10.0, "localization"):
                ok = True
                break
        if not ok:
            return 3
        self.mark("localization initialized")

        # 2) route (retry while planning comes up)
        rreq = SetRoutePoints.Request()
        rreq.header.frame_id = "map"
        rreq.goal = pose(GOAL)
        ok = False
        for _ in range(30):
            if self.call(self.route_cli, rreq, "set_route_points") and self.spin_until(
                lambda: self.route == RouteState.SET, 10.0, "route SET"
            ):
                ok = True
                break
            time.sleep(2)
        if not ok:
            return 4
        self.mark("route set")

        # 3) engage
        if not self.spin_until(
            lambda: self.op is not None and self.op.is_autonomous_mode_available, TIMEOUT_READY, "autonomous available"
        ):
            return 5
        ok = False
        for _ in range(30):
            if self.call(self.auto_cli, ChangeOperationMode.Request(), "change_to_autonomous"):
                ok = True
                break
            time.sleep(2)
        if not ok:
            return 6
        self.mark("autonomous engaged")

        # 4) drive
        if not self.spin_until(lambda: self.route == RouteState.ARRIVED, TIMEOUT_DRIVE, "ARRIVED"):
            return 7
        self.mark("ARRIVED")
        return 0


rclpy.init()
node = Golden()
rc = node.run()
node.destroy_node()
rclpy.shutdown()
sys.exit(rc)