#!/usr/bin/env python3
"""Restamp control_cmd arriving from the CR52 safety island.

Why this node exists
--------------------
The safety island runs FreeRTOS with no wall-clock synchronisation, so it
stamps autoware_control_msgs/msg/Control with its own uptime clock -- values
on the order of hundreds of seconds, against Autoware's ~1.78e9. Every
domain-1 consumer that checks message age therefore sees the command as
enormously stale: the topic-state monitors and the control-validation
latency check both raise errors, and `change_to_autonomous` is rejected with
"target mode not available". The commands themselves are correct; only the
timebase is wrong.

The fix, verified on hardware: the bridge delivers the domain-2 command onto
domain 1 under a `_raw` name, this node overwrites the timestamps with the
clock domain 1 actually uses, and republishes under the real topic name so
every existing subscriber is unchanged. Result: stamps became current,
/diagnostics non-OK count dropped from 10 to 6, and the engage response
changed from "target mode not available" to "same as current".

ALL THREE stamps must be rewritten -- Control.stamp, Control.lateral.stamp
and Control.longitudinal.stamp. They are separate builtin_interfaces/Time
fields filled independently by the safety island, and different consumers
read different ones; leaving any one of them on the uptime clock leaves a
monitor erroring.

Control.control_time, Lateral.control_time and Longitudinal.control_time are
deliberately NOT touched. Those are the optional "time this state is
expected to be achieved" fields, not message-age fields; nothing in the
domain-1 monitor set reads them, and rewriting a target time to *now* would
be a lie about the command rather than a correction to its timebase.

Running it
----------
Runs from the staged universe image with this file mounted in; it needs only
rclpy and autoware_control_msgs, both present there.
"""

DEFAULT_INPUT_TOPIC = "/control/trajectory_follower/control_cmd_raw"
DEFAULT_OUTPUT_TOPIC = "/control/trajectory_follower/control_cmd"


def main(args=None):
    import rclpy
    from autoware_control_msgs.msg import Control
    from rclpy.qos import (
        QoSDurabilityPolicy,
        QoSHistoryPolicy,
        QoSProfile,
        QoSReliabilityPolicy,
    )

    rclpy.init(args=args)
    node = rclpy.create_node("control_cmd_restamp")

    input_topic = node.declare_parameter("input_topic", DEFAULT_INPUT_TOPIC).value
    output_topic = node.declare_parameter("output_topic", DEFAULT_OUTPUT_TOPIC).value

    # Reliable/volatile/keep_last 1, matching what the trajectory follower
    # would have published on the real topic and what the bridge delivers on
    # the _raw one, so no subscriber sees a QoS change from the stub being
    # replaced by the safety island.
    qos = QoSProfile(
        depth=1,
        history=QoSHistoryPolicy.KEEP_LAST,
        reliability=QoSReliabilityPolicy.RELIABLE,
        durability=QoSDurabilityPolicy.VOLATILE,
    )
    publisher = node.create_publisher(Control, output_topic, qos)

    def on_control(msg):
        # The NODE's clock, not time.time(): with use_sim_time unset this is
        # the wall clock, which is the hardware-validated behaviour, and with
        # use_sim_time set it follows /clock. Either way it is the same clock
        # the domain-1 monitors compare against, which is the property that
        # actually matters -- stamping wall-clock time into a stack running
        # on simulated time would reintroduce the staleness from the other
        # direction.
        now = node.get_clock().now().to_msg()
        msg.stamp = now
        msg.lateral.stamp = now
        msg.longitudinal.stamp = now
        publisher.publish(msg)

    node.create_subscription(Control, input_topic, on_control, qos)
    node.get_logger().info(f"restamping {input_topic} -> {output_topic}")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
