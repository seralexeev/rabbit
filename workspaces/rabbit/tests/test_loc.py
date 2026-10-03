import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.loc import GROW, LOCALIZED, LOST, RELOCALIZING, STOP, GrowthPolicy, KeyframePolicy, LocalizationFilter, planar, decode_keyframe, difference, encode_keyframe, from_rtabmap, to_rtabmap


def pose(x=0.0, y=0.0, z=0.0, yaw_deg=0.0) -> np.ndarray:
    """Y-up pose with a rotation about +y (yaw 0 looks along -z)."""
    a = math.radians(yaw_deg)
    m = np.eye(4)
    m[:3, :3] = [[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]
    m[:3, 3] = [x, y, z]
    return m


def test_the_camera_looking_along_minus_z_is_rtabmaps_forward_x_with_up_kept():
    base = to_rtabmap(pose(1.0, 0.137, -2.0))
    np.testing.assert_allclose(base[:3, 3], [2.0, -1.0, 0.137])
    np.testing.assert_allclose(base[:3, :3], np.eye(3), atol=1e-12)


def test_a_left_turn_stays_a_left_turn():
    base = to_rtabmap(pose(yaw_deg=30.0))
    forward = base[:3, :3] @ np.array([1.0, 0.0, 0.0])
    assert forward[1] > 0
    assert math.isclose(math.degrees(math.atan2(forward[1], forward[0])), 30.0, abs_tol=1e-9)


def test_round_trip_and_correction_composition():
    odom = pose(0.4, 0.137, -1.2, 25.0)
    map_from_odom = pose(3.0, 0.0, 1.5, -170.0)
    np.testing.assert_allclose(from_rtabmap(to_rtabmap(odom)), odom, atol=1e-12)
    in_rtabmap = to_rtabmap(map_from_odom) @ to_rtabmap(odom)
    np.testing.assert_allclose(from_rtabmap(in_rtabmap), map_from_odom @ odom, atol=1e-12)


def test_keyframe_wire_format_round_trip():
    payload, headers = encode_keyframe(123, "s1", pose(1, 2, 3, 40), (267.1, 267.1, 317.5, 181.5), b"jpeg", b"png16")
    frame = decode_keyframe(payload, headers)
    assert (frame.ts, frame.session, frame.rgb, frame.depth) == (123, "s1", b"jpeg", b"png16")
    np.testing.assert_allclose(frame.odom, pose(1, 2, 3, 40), atol=1e-6)
    assert frame.intrinsics == (267.1, 267.1, 317.5, 181.5)


def same(a, b) -> bool:
    metres, degrees = difference(a, b)
    return metres < 1e-9 and degrees < 1e-6


def run(filter_: LocalizationFilter, events):
    for t, candidate, is_global in events:
        filter_.update(t, [0.0, 0.0, 0.0], candidate, is_global)
    return filter_


def test_a_single_global_match_is_not_a_fix():
    f = run(LocalizationFilter(), [(0.0, pose(1, 0, 1, 10), True), (1.0, None, False)])
    assert f.status == RELOCALIZING and f.map_from_odom is None


def test_two_agreeing_global_matches_fix_the_map():
    f = run(LocalizationFilter(), [(0.0, pose(1, 0, 1, 10), True), (0.5, pose(1.1, 0, 1, 12), True)])
    assert f.status == LOCALIZED
    assert same(f.map_from_odom, pose(1.1, 0, 1, 12))


def test_disagreeing_or_stale_matches_do_not_fix_the_map():
    f = run(LocalizationFilter(), [(0.0, pose(1, 0, 1, 10), True), (0.5, pose(1.9, 0, 1, 10), True), (1.0, pose(1, 0, 1, 30), True)])
    assert f.status == RELOCALIZING
    f = run(LocalizationFilter(window_s=10.0), [(0.0, pose(1, 0, 1), True), (11.0, pose(1, 0, 1), True)])
    assert f.status == RELOCALIZING


def test_proximity_matches_cannot_fix_the_map():
    f = run(LocalizationFilter(), [(0.0, pose(1, 0, 1), False), (0.5, pose(1, 0, 1), False), (1.0, pose(1, 0, 1), True)])
    assert f.status == RELOCALIZING


def test_a_lone_jump_is_ignored_and_a_confirmed_one_is_taken():
    f = LocalizationFilter()
    f.seed(0.0, pose(0, 0, 0))
    run(f, [(1.0, pose(0.1, 0, 0, 2), False)])
    assert same(f.map_from_odom, pose(0.1, 0, 0, 2))
    run(f, [(2.0, pose(0.9, 0, 0, 20), True)])
    assert same(f.map_from_odom, pose(0.1, 0, 0, 2))
    run(f, [(3.0, pose(0.95, 0, 0, 21), True)])
    assert f.corrections == 1
    assert same(f.map_from_odom, pose(0.95, 0, 0, 21))


def test_lost_needs_both_time_and_travel_and_an_agreeing_match_recovers():
    f = LocalizationFilter(lost_s=30.0, lost_m=3.0)
    f.seed(0.0, pose())
    for t in range(1, 60):
        f.update(float(t), [0.0, 0.0, 0.0])
    assert f.status == LOCALIZED
    for t in range(60, 70):
        f.update(float(t), [0.5 * (t - 59), 0.0, 0.0])
    assert f.status == LOST
    f.update(70.0, [5.5, 0.0, 0.0], pose(0.05, 0, 0), False)
    assert f.status == LOCALIZED


def test_keyframes_follow_motion_and_keep_coming_while_unlocalized():
    p = KeyframePolicy()
    assert p.due(0.0, pose(), localized=True)
    p.sent(0.0, pose())
    assert not p.due(0.3, pose(0.5), localized=True)
    assert not p.due(5.0, pose(0.05), localized=True)
    assert p.due(5.0, pose(0.05), localized=False)
    assert p.due(0.6, pose(0.0, 0.0, 0.0, 6.0), localized=True)


def test_planar_offset_of_a_y_up_transform():
    x, z, yaw = planar(pose(1.0, 0.2, -3.0, 135.0))
    assert (round(x, 9), round(z, 9), round(yaw, 9)) == (1.0, -3.0, 135.0)


def localized_at(t: float, travel: float) -> LocalizationFilter:
    f = LocalizationFilter()
    f.seed(t, pose())
    f.travel_m = travel
    return f


def test_growth_starts_after_a_recent_fix_and_a_run_of_new_views():
    g = GrowthPolicy()
    fix = localized_at(0.0, 0.8)
    assert [g.update(t, fix, False) for t in (1.0, 1.5, 2.0)] == [None, None, None]
    assert g.update(2.5, fix, False) == GROW


def test_no_growth_on_a_stale_or_drifted_or_doubtful_fix():
    for fix, now in ((localized_at(0.0, 0.8), 20.0), (localized_at(0.0, 2.5), 2.0), (localized_at(0.0, 0.2), 2.0)):
        g = GrowthPolicy()
        assert all(g.update(now + i, fix, False) is None for i in range(6))
    lost = localized_at(0.0, 0.8)
    lost.status = LOST
    g = GrowthPolicy()
    assert all(g.update(1.0 + i, lost, False) is None for i in range(6))


def test_a_known_view_resets_the_run_of_misses():
    g = GrowthPolicy()
    fix = localized_at(0.0, 0.8)
    for t, known in ((1.0, False), (1.5, False), (2.0, False), (2.5, True), (3.0, False)):
        assert g.update(t, fix, known) is None


def test_growth_stops_when_the_old_map_matches_again_or_the_fix_is_lost():
    g = GrowthPolicy(growing=True)
    fix = localized_at(0.0, 0.8)
    assert g.update(1.0, fix, True) is None
    assert g.update(1.5, fix, False) is None
    assert g.update(2.0, fix, True) is None
    assert g.update(2.5, fix, True) == STOP and not g.growing
    g = GrowthPolicy(growing=True)
    fix.status = LOST
    assert g.update(3.0, fix, False) == STOP
