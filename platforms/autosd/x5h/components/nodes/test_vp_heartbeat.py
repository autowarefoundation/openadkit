"""Pure part of vp_heartbeat.py. Run from this directory: python3 -m pytest test_vp_heartbeat.py"""
import vp_heartbeat as h


def test_heartbeat_carries_the_node_stamp_and_the_command():
    m = h.make_heartbeat(1700000000, 250000000, -1.25)
    assert m == {"stamp": {"sec": 1700000000, "nanosec": 250000000}, "data": -1.25}


def test_non_finite_command_is_still_a_heartbeat():
    m = h.make_heartbeat(1, 2, float("nan"))
    assert m["data"] == 0.0
