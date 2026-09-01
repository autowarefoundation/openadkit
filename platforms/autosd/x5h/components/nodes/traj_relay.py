#!/usr/bin/env python3
"""Downsampling relay for the Autoware trajectory crossing into domain 2.

Why this node exists
--------------------
The CR52 safety island is a RELIABLE DDS reader on a 3 MB heap. A full
Autoware trajectory is ~170 points / ~15 kB serialized, so every sample
arrives as a fragmented RTPS message. RELIABLE forces the CycloneDDS
receive pipeline to hold every fragment until defragmentation completes and
every out-of-order sample in the reorder admin pending retransmit. Under
sustained load that backlog grows faster than it drains, the rmsg/rbuf pool
exhausts the heap and the firmware calls `_exit`. Measured on hardware: the
board dies after 51 control commands, roughly 8 s after the trajectory
starts flowing, with the dead task being the CycloneDDS `recv` thread.

That backlog lives BELOW the reader cache, so `KEEP_LAST 1` and the
reorder/defrag `maxsamples` limits do not bound it. Three mitigations were
tried on hardware and all failed; none of them should be reintroduced here:

  1. Bounding reorder/defrag/delivery `maxsamples` -- recovered 19 kB to
     33 kB of heap, nowhere near enough.
  2. BEST_EFFORT readers -- a regression. Lossy plus no retransmit meant
     the board received nothing at all; its apparent survival was a no-load
     false positive.
  3. Rate-limiting the trajectory to ~5 Hz (throttle plus bridge remap) --
     bought 62 cycles instead of 51, then died identically.

The fix is to eliminate fragmentation rather than slow it down: emit a
trajectory small enough that the serialized sample fits in a single DDS
message. This node subscribes to the full trajectory and republishes a
downsampled copy on a distinct topic; the bridge carries the downsampled
topic into domain 2 remapped back to the real name, so nothing on the board
side knows the difference.

How the downsampling works, and why it is this and nothing else
---------------------------------------------------------------
Points are chosen at UNIFORM ARC LENGTH across a capped extent, and the
chosen points are REAL INPUT POINTS -- never interpolated ones. Two other
strategies were A/B tested on hardware and both are wrong:

  * `points[::2]`-style stride (170 -> 11 points spread over the full
    ~85 m, ~7.7 m apart): the vehicle drives but SWERVES, with lateral
    steering saturated at -0.700 rad, the vehicle maximum. Too coarse near
    the ego vehicle for the MPC to track.
  * `points[:N]` near-ego prefix: Autoware's trajectory is ultra-dense
    close to the ego vehicle (~0.09 m spacing), so a 13-point prefix spans
    only ~1.1 m. With no longitudinal lookahead the vehicle DOES NOT DRIVE
    AT ALL -- commanded velocity stays 0.

The insight those two failures encode, and the reason the constants below
are shaped the way they are: NEAR-FIELD DENSITY controls steering quality,
EXTENT controls whether the vehicle drives at all, and BOTH have to fit
inside one packet. Uniform arc length over a capped extent is the only one
of the three that spends the packet budget on both at once.

Subsampling rather than interpolating is what preserves the velocity
profile: each TrajectoryPoint carries longitudinal_velocity_mps,
acceleration_mps2 and the rest, and those travel with the point. An
interpolated pose would need every one of those fields synthesised too, and
a synthesised velocity profile is a new controller input, not a smaller
one.

Hardware result with the settings below: 966 MPC cycles, control_cmd
sustained at ~6.6 Hz, board alive past 4.5 minutes with no death, steering
-0.029 rad while driving and 0.000 at a dead-straight stop.

Running it
----------
Runs from the staged universe image with this file mounted in; it needs
only rclpy and autoware_planning_msgs, both present there. The ROS imports
are deferred into main() on purpose so that the resampling functions in
this module can be imported and unit-tested on a machine with no ROS
installation (see test_traj_relay.py beside this file).
"""
import bisect
import math

# Extent cap: how far ahead of the ego vehicle the downsampled trajectory
# reaches, in metres of arc length. This is the "does the vehicle drive at
# all" knob. Too small and the near-ego prefix failure returns -- at ~1.1 m
# of lookahead the longitudinal controller commands zero velocity and the
# vehicle never moves. Too large and, at a fixed point budget, the spacing
# grows until the stride failure returns -- at ~7.7 m the MPC saturates
# steering at -0.700 rad and the vehicle swerves. 25 m is the
# hardware-validated setting: with TARGET_POINT_COUNT points it gives
# ~2.1 m spacing, roughly 3.7x denser than the stride that swerved, while
# still reaching far enough ahead to drive.
EXTENT_CAP_M = 25.0

# Point budget. 13 points serialize to 1172 B (measured, see
# serialized_size_bytes below), 172 B clear of the fragmentation threshold
# and 28 B inside SERIALIZED_BYTE_BUDGET, which is the tighter of the two.
# 13 is both the hardware-validated count and, with frame_id "map", exactly
# the most the budget admits -- the budget binds first, so this number
# cannot silently drift upward.
TARGET_POINT_COUNT = 13

# The two DDS limits that actually govern this node. Both are recorded here
# so the budget below is a derivation rather than a magic number, and so a
# change to either shows up as a diff against a stated value.
#
# CYCLONEDDS_FRAGMENT_SIZE_B is the BINDING one. CycloneDDS fragments a
# sample when its serialized size -- inclusive of the CDR encapsulation
# header, which is what serialized_size_bytes() returns and what
# rclpy.serialize_message() produces -- exceeds General/FragmentSize:
#
#   sz = ddsi_serdata_size (serdata);
#   if (sz > gv->config.fragment_size || ...)      /* -> DATA_FRAG path */
#
# (cyclonedds releases/0.10.x, src/core/ddsi/src/q_transmit.c:836; Humble
# ships cyclonedds 0.10.5.) Domain 2 in cyclonedds-x5h.xml pins it to the
# CycloneDDS default of 1344 B. Exceed it and the sample goes out as a
# DATA_FRAG train, the CR52's reliable receive path holds every fragment
# for defragmentation, and the heap death this whole node exists to prevent
# comes straight back.
#
# CYCLONEDDS_MAX_MESSAGE_SIZE_B is General/MaxMessageSize, set to 1400 B on
# both domains. It is NOT the fragmentation trigger -- it bounds the whole
# RTPS message, headers and INFO_TS and inline QoS included, so the payload
# it leaves room for is some 60-100 B less than 1400 B. Calibrating against
# 1400 B, as this constant originally did, was doubly wrong: it ignored the
# tighter FragmentSize AND it spent the RTPS overhead as if it were payload.
CYCLONEDDS_FRAGMENT_SIZE_B = 1344
CYCLONEDDS_MAX_MESSAGE_SIZE_B = 1400

# The hard ceiling on the serialized sample. Not a hint: downsample_indices()
# drops points rather than exceed it, and on_trajectory() re-checks and
# refuses to publish rather than exceed it.
#
# 1200 B is the empirically validated budget, not a safety factor picked to
# look comfortable: it is the budget the hardware-validated original
# downsampler ran under, and the arc-length version that survived 966 MPC
# cycles came in at 1172 B beneath it. It clears CYCLONEDDS_FRAGMENT_SIZE_B
# by 144 B and leaves ample room for RTPS overhead under
# CYCLONEDDS_MAX_MESSAGE_SIZE_B. With frame_id "map" it admits 13 points
# (1172 B) and rejects 14 (1260 B).
SERIALIZED_BYTE_BUDGET = 1200

# CDR wire-format constants for autoware_planning_msgs/msg/Trajectory,
# used by serialized_size_bytes(). Verified against rclpy's own
# serialize_message() on the staged arm64 image: 24 B for an empty
# trajectory with frame_id "map", 116 B at one point, 1172 B at 13.
CDR_ENCAPSULATION_BYTES = 4  # the 4-byte encapsulation header
CDR_TIME_BYTES = 8  # builtin_interfaces/Time: int32 + uint32
CDR_UINT32_BYTES = 4  # string length prefix, sequence length prefix
CDR_STRING_ALIGNMENT = 4
# TrajectoryPoint: Duration(8) + Pose(3+4 float64 = 56) + 6 float32 (24).
CDR_TRAJECTORY_POINT_BYTES = 88
# The widest member of TrajectoryPoint is a float64, so every element is
# aligned to 8 relative to the start of the CDR body.
CDR_TRAJECTORY_POINT_ALIGNMENT = 8

DEFAULT_INPUT_TOPIC = "/planning/scenario_planning/trajectory"
DEFAULT_OUTPUT_TOPIC = "/planning/scenario_planning/trajectory_ds"


def _align_up(offset, alignment):
    """Round a CDR stream offset up to the next multiple of `alignment`."""
    return (offset + alignment - 1) // alignment * alignment


def serialized_size_bytes(frame_id_length, point_count):
    """Exact CDR size of a Trajectory with this frame_id length and point count.

    Offsets are tracked from the start of the CDR body, because that is
    where CDR alignment restarts -- the 4-byte encapsulation header sits in
    front of it and is added back at the end.
    """
    offset = CDR_TIME_BYTES  # header.stamp
    offset += CDR_UINT32_BYTES  # header.frame_id length prefix
    # frame_id characters plus the NUL terminator, padded out to the
    # alignment of whatever follows.
    offset += _align_up(frame_id_length + 1, CDR_STRING_ALIGNMENT)
    offset += CDR_UINT32_BYTES  # points sequence length prefix
    if point_count > 0:
        offset = _align_up(offset, CDR_TRAJECTORY_POINT_ALIGNMENT)
        offset += CDR_TRAJECTORY_POINT_BYTES * point_count
    return CDR_ENCAPSULATION_BYTES + offset


def max_points_within(frame_id_length, byte_budget):
    """Largest point count whose serialized Trajectory still fits the budget.

    Returns 0 when even a single point does not fit, which is the honest
    answer rather than a clamp to 1: publishing an oversized sample is the
    one thing this node must never do.
    """
    count = 0
    while serialized_size_bytes(frame_id_length, count + 1) <= byte_budget:
        count += 1
    return count


def cumulative_arc_lengths(positions):
    """Cumulative 2D arc length along a sequence of (x, y) positions.

    Planar length, matching how Autoware measures trajectory arc length:
    the z component of a driving trajectory contributes noise, not
    distance. The result is non-decreasing, starts at 0.0, and has one
    entry per input position.
    """
    lengths = [0.0] * len(positions)
    for i in range(1, len(positions)):
        previous_x, previous_y = positions[i - 1]
        current_x, current_y = positions[i]
        lengths[i] = lengths[i - 1] + math.hypot(
            current_x - previous_x, current_y - previous_y
        )
    return lengths


def _nearest_index(arc_lengths, target):
    """Index of the point whose arc length is closest to `target`."""
    position = bisect.bisect_left(arc_lengths, target)
    if position == 0:
        return 0
    if position >= len(arc_lengths):
        return len(arc_lengths) - 1
    after = arc_lengths[position] - target
    before = target - arc_lengths[position - 1]
    return position if after < before else position - 1


def select_indices(arc_lengths, extent_cap_m, max_points):
    """Indices of real points at uniform arc-length spacing over the extent.

    The extent is min(extent_cap_m, total length), so a trajectory shorter
    than the cap is spread over its whole length instead of being padded or
    clipped. Indices come back strictly increasing and never longer than
    `max_points`; coincident points collapse to one entry, so the result can
    legitimately be shorter than requested.
    """
    count = len(arc_lengths)
    if count == 0:
        return []
    if count == 1 or max_points <= 1:
        return [0]
    extent = min(extent_cap_m, arc_lengths[-1])
    if extent <= 0.0:
        # Every point coincides: there is exactly one distinct place to be.
        return [0]
    wanted = min(max_points, count)
    if wanted < 2:
        return [0]
    indices = []
    for step in range(wanted):
        target = extent * step / (wanted - 1)
        index = _nearest_index(arc_lengths, target)
        if not indices or index > indices[-1]:
            indices.append(index)
    return indices


def downsample_indices(
    positions,
    frame_id_length,
    extent_cap_m=EXTENT_CAP_M,
    target_point_count=TARGET_POINT_COUNT,
    byte_budget=SERIALIZED_BYTE_BUDGET,
):
    """Full point-selection decision for one trajectory.

    Combines the point budget (whichever of the target count and the byte
    budget is tighter) with uniform arc-length selection over the capped
    extent.
    """
    budget = min(
        target_point_count, max_points_within(frame_id_length, byte_budget)
    )
    if budget <= 0:
        return []
    return select_indices(cumulative_arc_lengths(positions), extent_cap_m, budget)


def main(args=None):
    # Deferred so the pure functions above stay importable without ROS.
    import rclpy
    from autoware_planning_msgs.msg import Trajectory
    from rclpy.qos import (
        QoSDurabilityPolicy,
        QoSHistoryPolicy,
        QoSProfile,
        QoSReliabilityPolicy,
    )

    rclpy.init(args=args)
    node = rclpy.create_node("trajectory_downsample_relay")

    input_topic = node.declare_parameter("input_topic", DEFAULT_INPUT_TOPIC).value
    output_topic = node.declare_parameter("output_topic", DEFAULT_OUTPUT_TOPIC).value
    extent_cap_m = node.declare_parameter("extent_cap_m", EXTENT_CAP_M).value
    target_point_count = node.declare_parameter(
        "target_point_count", TARGET_POINT_COUNT
    ).value
    byte_budget = node.declare_parameter(
        "byte_budget", SERIALIZED_BYTE_BUDGET
    ).value

    # Matches the QoS Autoware's planning stack publishes the trajectory
    # with (reliable, volatile, keep_last depth 1). The output profile is
    # the same, because the bridge's domain-1 subscription is what reads it
    # and the bridge is configured reliable for the domain-2 side. Reliable
    # is safe HERE: this hop is loopback inside the application cluster,
    # and it is only the CR52's reliable reader on the rpmsg-eth link that
    # cannot afford fragments.
    qos = QoSProfile(
        depth=1,
        history=QoSHistoryPolicy.KEEP_LAST,
        reliability=QoSReliabilityPolicy.RELIABLE,
        durability=QoSDurabilityPolicy.VOLATILE,
    )
    publisher = node.create_publisher(Trajectory, output_topic, qos)

    def on_trajectory(msg):
        positions = [(p.pose.position.x, p.pose.position.y) for p in msg.points]
        indices = downsample_indices(
            positions,
            len(msg.header.frame_id),
            extent_cap_m=extent_cap_m,
            target_point_count=target_point_count,
            byte_budget=byte_budget,
        )
        downsampled = Trajectory()
        downsampled.header = msg.header
        downsampled.points = [msg.points[i] for i in indices]
        size = serialized_size_bytes(len(msg.header.frame_id), len(indices))
        if size > byte_budget:
            # Unreachable by construction -- downsample_indices() derives
            # the count from the same arithmetic. Kept as a guard because
            # the consequence of being wrong is a dead safety island, not a
            # dropped message.
            node.get_logger().error(
                f"refusing to publish {size} B (> {byte_budget} B budget)"
            )
            return
        publisher.publish(downsampled)
        node.get_logger().info(
            f"{len(msg.points)} -> {len(indices)} points, {size} B",
            throttle_duration_sec=5.0,
        )

    node.create_subscription(Trajectory, input_topic, on_trajectory, qos)
    node.get_logger().info(
        f"relaying {input_topic} -> {output_topic} "
        f"(extent cap {extent_cap_m} m, up to {target_point_count} points, "
        f"under {byte_budget} B)"
    )
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
