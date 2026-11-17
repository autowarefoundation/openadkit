"""Follow a replayed recording: localization initializes from it, and the pose
and the tracked objects keep arriving.

The verify step of logging simulation (deployment.json): `openadkit run
--verify` runs it in the api service while the rosbag plays. Exit 0 once all
three hold. The counts are in recorded time, so a slower replay passes too.
"""
import sys
import time

import rclpy
from autoware_adapi_v1_msgs.msg import LocalizationInitializationState
from autoware_perception_msgs.msg import PredictedObjects
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)

# One second of the recording each: the pose at 50 Hz, the objects at 10 Hz.
POSES, OBJECT_MESSAGES = 50, 10
TIMEOUT = 300.0


class FollowReplay(Node):
    def __init__(self):
        super().__init__("openadkit_follow_replay")
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
        self.state = None
        self.poses = self.object_messages = self.objects = 0
        self.create_subscription(
            LocalizationInitializationState, "/api/localization/initialization_state",
            lambda m: setattr(self, "state", m.state), latched)
        self.create_subscription(Odometry, "/localization/kinematic_state", self.on_pose, qos_profile_sensor_data)
        self.create_subscription(
            PredictedObjects, "/perception/object_recognition/objects", self.on_objects, qos_profile_sensor_data)
        self.t0 = time.monotonic()

    def initialized(self):
        return self.state == LocalizationInitializationState.INITIALIZED

    def on_pose(self, _):
        # Poses before the initialization are not localization on the recording.
        if self.initialized():
            self.poses += 1

    def on_objects(self, m):
        self.object_messages += 1
        self.objects += len(m.objects)

    def spin_until(self, cond, what):
        end = self.t0 + TIMEOUT
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.2)
            if cond():
                print(f"[verify] {time.monotonic() - self.t0:6.1f}s {what}", flush=True)
                return True
        self.get_logger().error(f"timeout: {what}")
        return False

    def run(self):
        if not self.spin_until(self.initialized, "localization initialized"):
            return 3
        if not self.spin_until(lambda: self.poses >= POSES, f"{POSES} poses"):
            return 4
        if not self.spin_until(
            lambda: self.object_messages >= OBJECT_MESSAGES and self.objects > 0,
            f"{OBJECT_MESSAGES} object messages, with tracked objects",
        ):
            return 5
        return 0


def main():
    rclpy.init()
    node = FollowReplay()
    try:
        return node.run()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
