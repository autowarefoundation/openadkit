#!/usr/bin/env python3
"""VisionPilot liveness for the Safety Island.

Every /vehicle/throttle_cmd sample VisionPilot publishes becomes one
/safety_island/vp_heartbeat sample stamped with THIS node's clock. The CR52
watches the arrival rate, not the value: when the stream stops for 0.5 s it
ramps the vehicle to a stop. The value rides along for the operator's log.
Stamped here, not by VisionPilot, so the CR52 side never depends on
VisionPilot's clock. rclpy imports are deferred so the pure part is testable.
"""
import math

INPUT_TOPIC = "/vehicle/throttle_cmd"
OUTPUT_TOPIC = "/safety_island/vp_heartbeat"


def make_heartbeat(stamp_sec, stamp_nanosec, value):
    return {"stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)},
            "data": float(value) if math.isfinite(value) else 0.0}


def main():
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
    from std_msgs.msg import Float64
    from tier4_debug_msgs.msg import Float64Stamped

    class Heartbeat(Node):
        def __init__(self):
            super().__init__("vp_heartbeat")
            qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST)
            self.pub = self.create_publisher(Float64Stamped, OUTPUT_TOPIC, qos)
            self.create_subscription(Float64, INPUT_TOPIC, self.on_cmd, qos)

        def on_cmd(self, msg):
            now = self.get_clock().now().to_msg()
            d = make_heartbeat(now.sec, now.nanosec, msg.data)
            out = Float64Stamped()
            out.stamp.sec, out.stamp.nanosec, out.data = d["stamp"]["sec"], d["stamp"]["nanosec"], d["data"]
            self.pub.publish(out)

    rclpy.init()
    rclpy.spin(Heartbeat())


if __name__ == "__main__":
    main()
