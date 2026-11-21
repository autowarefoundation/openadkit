"""Print a running deployment's AD API state as one JSON object.

Runs inside its api container, with ROS and Autoware sourced: `openadkit status`
passes this file to python3. Only AD API topics are read, so the result means
the same across Autoware versions. A topic with no message within the timeout
is null.
"""

import json
import time

import rclpy
from autoware_adapi_v1_msgs.msg import (
    LocalizationInitializationState,
    MrmState,
    OperationModeState,
    RouteState,
)
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

TIMEOUT = 5.0
TOPICS = {
    "localization": ("/api/localization/initialization_state", LocalizationInitializationState),
    "routing": ("/api/routing/state", RouteState),
    "mode": ("/api/operation_mode/state", OperationModeState),
    "mrm": ("/api/fail_safe/mrm_state", MrmState),
}
LOCALIZATION = {1: "uninitialized", 2: "initializing", 3: "initialized"}
ROUTING = {1: "unset", 2: "set", 3: "arrived", 4: "changing"}
MODE = {1: "stop", 2: "autonomous", 3: "local", 4: "remote"}
MRM = {1: "normal", 2: "operating", 3: "succeeded", 4: "failed"}
MRM_BEHAVIOR = {2: "emergency stop", 3: "comfortable stop", 4: "pull over"}


def describe(name, message):
    if name == "localization":
        return {"state": LOCALIZATION.get(message.state, "unknown")}
    if name == "routing":
        return {"state": ROUTING.get(message.state, "unknown")}
    if name == "mode":
        return {
            "state": MODE.get(message.mode, "unknown"),
            "autowareControl": message.is_autoware_control_enabled,
            "autonomousAvailable": message.is_autonomous_mode_available,
        }
    return {
        "state": MRM.get(message.state, "unknown"),
        "behavior": MRM_BEHAVIOR.get(message.behavior),
    }


def main():
    rclpy.init()
    node = rclpy.create_node("openadkit_status")
    # AD API states are latched: a late subscriber gets the current one.
    qos = QoSProfile(
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    state = dict.fromkeys(TOPICS)
    for name, (topic, kind) in TOPICS.items():
        node.create_subscription(
            kind, topic, lambda message, name=name: state.__setitem__(name, describe(name, message)), qos
        )
    deadline = time.monotonic() + TIMEOUT
    while None in state.values() and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)
    print(json.dumps(state))
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
