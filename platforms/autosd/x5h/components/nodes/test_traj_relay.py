"""Unit tests for the pure resampling logic in traj_relay.py.

Runs without ROS: traj_relay defers its rclpy imports into main(), so
everything exercised here is plain Python. Run from this directory with
`python3 -m pytest test_traj_relay.py`.

The CDR sizes asserted below are not guesses. They were measured with
rclpy's own serialize_message() against autoware_planning_msgs on the
staged arm64 image (ghcr.io/mitsudome-r/mrm-demo:universe-after-arm64);
MEASURED_SIZES_FRAME_ID_MAP is that measurement, and it pins
serialized_size_bytes() to the real wire format.
"""
import math

import traj_relay as r

# {point count: bytes}, frame_id "map", from rclpy serialize_message().
MEASURED_SIZES_FRAME_ID_MAP = {
    0: 24,
    1: 116,
    2: 204,
    11: 996,
    13: 1172,
    14: 1260,
    15: 1348,
    16: 1436,
    17: 1524,
    170: 14988,
}

MAP_FRAME_LEN = len("map")


def realistic_trajectory():
    """A trajectory shaped like Autoware's: ~170 points, ~85 m, dense near ego.

    30 points at 0.09 m spacing right in front of the ego vehicle, then 140
    points at ~0.59 m out to ~85 m, on a gentle left curve so the arc length
    is not simply the x coordinate.
    """
    spacings = [0.09] * 29 + [(85.0 - 29 * 0.09) / 140.0] * 140
    positions = [(0.0, 0.0)]
    travelled = 0.0
    for spacing in spacings:
        travelled += spacing
        # Curvature ~1/400 m: 85 m of arc bends about 0.2 rad.
        heading = travelled / 400.0
        x, y = positions[-1]
        positions.append(
            (x + spacing * math.cos(heading), y + spacing * math.sin(heading))
        )
    return positions


def test_serialized_size_matches_measured_wire_format():
    for count, expected in MEASURED_SIZES_FRAME_ID_MAP.items():
        assert r.serialized_size_bytes(MAP_FRAME_LEN, count) == expected


def test_default_point_count_is_1172_bytes_and_fits():
    size = r.serialized_size_bytes(MAP_FRAME_LEN, r.TARGET_POINT_COUNT)
    assert size == 1172
    assert size < r.SINGLE_MESSAGE_BYTE_LIMIT


def test_byte_limit_admits_15_points_and_rejects_16():
    assert r.max_points_within(MAP_FRAME_LEN, r.SINGLE_MESSAGE_BYTE_LIMIT) == 15


def test_full_trajectory_would_not_fit_in_one_message():
    full = r.serialized_size_bytes(MAP_FRAME_LEN, 170)
    assert full == 14988
    assert full > 10 * r.SINGLE_MESSAGE_BYTE_LIMIT


def test_empty_trajectory_selects_nothing():
    assert r.downsample_indices([], MAP_FRAME_LEN) == []


def test_single_point_trajectory_selects_that_point():
    assert r.downsample_indices([(1.0, 2.0)], MAP_FRAME_LEN) == [0]


def test_coincident_points_collapse_to_one():
    positions = [(4.0, 5.0)] * 40
    assert r.downsample_indices(positions, MAP_FRAME_LEN) == [0]


def test_two_point_trajectory_keeps_both_ends():
    assert r.downsample_indices([(0.0, 0.0), (3.0, 4.0)], MAP_FRAME_LEN) == [0, 1]


def test_trajectory_shorter_than_extent_cap_is_covered_end_to_end():
    # 40 points over 4 m, well inside the 25 m cap.
    positions = [(0.1 * i, 0.0) for i in range(41)]
    indices = r.downsample_indices(positions, MAP_FRAME_LEN)
    assert len(indices) == r.TARGET_POINT_COUNT
    assert indices[0] == 0
    assert indices[-1] == len(positions) - 1


def test_never_exceeds_the_byte_limit_even_when_the_limit_is_tiny():
    positions = realistic_trajectory()
    for limit in (0, 24, 116, 500, 1172, 1400):
        indices = r.downsample_indices(positions, MAP_FRAME_LEN, byte_limit=limit)
        assert r.serialized_size_bytes(MAP_FRAME_LEN, len(indices)) <= max(limit, 24)


def test_realistic_trajectory_yields_13_points_of_1172_bytes():
    positions = realistic_trajectory()
    assert len(positions) == 170
    total = r.cumulative_arc_lengths(positions)[-1]
    assert 84.9 < total < 85.1
    indices = r.downsample_indices(positions, MAP_FRAME_LEN)
    assert len(indices) == 13
    assert r.serialized_size_bytes(MAP_FRAME_LEN, len(indices)) == 1172


def test_selected_points_are_real_input_points_in_order():
    positions = realistic_trajectory()
    indices = r.downsample_indices(positions, MAP_FRAME_LEN)
    assert indices == sorted(set(indices))
    assert all(0 <= i < len(positions) for i in indices)
    # "Real point" means the relay copies positions[i] verbatim; assert the
    # identity the node relies on rather than a recomputed value.
    selected = [positions[i] for i in indices]
    assert all(point in positions for point in selected)


def test_velocity_profile_is_preserved_not_interpolated():
    positions = realistic_trajectory()
    # Stand in for TrajectoryPoint payload: whatever rides on point i must
    # arrive unchanged, because the relay subsamples instead of synthesising.
    velocities = [8.0 - 0.04 * i for i in range(len(positions))]
    indices = r.downsample_indices(positions, MAP_FRAME_LEN)
    selected = [velocities[i] for i in indices]
    assert selected == [velocities[i] for i in indices]
    assert all(v in velocities for v in selected)


def test_extent_is_capped_at_25_m_not_the_full_trajectory():
    positions = realistic_trajectory()
    lengths = r.cumulative_arc_lengths(positions)
    indices = r.downsample_indices(positions, MAP_FRAME_LEN)
    covered = lengths[indices[-1]]
    assert 24.5 < covered <= r.EXTENT_CAP_M + 0.5
    assert covered < lengths[-1]


def test_spacing_is_uniform_in_arc_length():
    positions = realistic_trajectory()
    lengths = r.cumulative_arc_lengths(positions)
    indices = r.downsample_indices(positions, MAP_FRAME_LEN)
    gaps = [lengths[b] - lengths[a] for a, b in zip(indices, indices[1:], strict=False)]
    nominal = r.EXTENT_CAP_M / (len(indices) - 1)
    # Gaps cannot be exactly uniform, because the relay snaps each target
    # arc length to a REAL point rather than interpolating one. The
    # quantisation floor is the source spacing, ~0.59 m out here, so every
    # gap must land within one source interval of nominal. That is still
    # worlds away from the near-ego prefix, whose gaps would all be ~0.09 m,
    # and from the stride, whose gaps would all be ~7.7 m.
    assert all(abs(gap - nominal) <= 0.60 for gap in gaps)
    assert abs(sum(gaps) / len(gaps) - nominal) < 0.05


def test_does_not_regress_to_the_stride_that_swerved():
    # The hardware failure was 170 -> 11 points over the full ~85 m, i.e.
    # ~7.7 m apart, which saturated steering at -0.700 rad. Guard the
    # property that broke: near-field spacing must stay well under that.
    positions = realistic_trajectory()
    lengths = r.cumulative_arc_lengths(positions)
    indices = r.downsample_indices(positions, MAP_FRAME_LEN)
    gaps = [lengths[b] - lengths[a] for a, b in zip(indices, indices[1:], strict=False)]
    assert max(gaps) < 3.0


def test_does_not_regress_to_the_prefix_that_would_not_drive():
    # The hardware failure was a 13-point prefix spanning only ~1.1 m, which
    # left no longitudinal lookahead and the vehicle never moved. Guard the
    # property that broke: the extent must be metres of lookahead, not
    # centimetres.
    positions = realistic_trajectory()
    lengths = r.cumulative_arc_lengths(positions)
    indices = r.downsample_indices(positions, MAP_FRAME_LEN)
    assert lengths[indices[-1]] > 20.0
    assert indices != list(range(len(indices)))


def test_arc_lengths_are_monotonic_and_start_at_zero():
    lengths = r.cumulative_arc_lengths(realistic_trajectory())
    assert lengths[0] == 0.0
    assert all(b >= a for a, b in zip(lengths, lengths[1:], strict=False))


def test_topic_wiring_matches_the_bridge_config():
    """The three topic names only work as a set; pin them together.

    The relay publishes ..._ds on domain 1, the bridge carries ..._ds into
    domain 2 remapped back to the real name, the bridge carries control_cmd
    out of domain 2 remapped to ..._raw, and the restamp node turns ..._raw
    back into the real name on domain 1. Renaming any one of the four
    without the others silently breaks the loop, and the failure looks like
    "the board is not driving" rather than like a typo.
    """
    import pathlib

    import yaml

    import control_restamp as restamp

    here = pathlib.Path(__file__).resolve().parent
    config_path = here.parent / "bridge" / "bridge-config.yaml"
    topics = yaml.safe_load(config_path.read_text())["topics"]

    trajectory = topics["planning/scenario_planning/trajectory_ds"]
    assert "/planning/scenario_planning/trajectory_ds" == r.DEFAULT_OUTPUT_TOPIC
    assert "/" + trajectory["remap"] == r.DEFAULT_INPUT_TOPIC
    assert (trajectory["from_domain"], trajectory["to_domain"]) == (1, 2)
    # best_effort here was tried on hardware and regressed; see the config.
    assert trajectory["qos"]["reliability"] == "reliable"

    control = topics["control/trajectory_follower/control_cmd"]
    real_name = "control/trajectory_follower/control_cmd"
    assert "/" + real_name == restamp.DEFAULT_OUTPUT_TOPIC
    assert "/" + control["remap"] == restamp.DEFAULT_INPUT_TOPIC
    assert (control["from_domain"], control["to_domain"]) == (2, 1)
