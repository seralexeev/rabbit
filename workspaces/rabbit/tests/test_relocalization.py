import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.relocalization import Relocalization


def run(statuses, positions=None):
    relocalization = Relocalization(stable_s=10.0, give_up_m=3.0, max_step_m=1.0, give_up_s=45.0)
    outcomes = []
    for i, (t, memory) in enumerate(statuses):
        position = None if positions is None else positions[i]
        outcomes.append((t, relocalization.update(memory, t, position)))
    return [t for t, outcome in outcomes if outcome == "relocalized"][:1], [t for t, outcome in outcomes if outcome == "give_up"][:1]


def test_the_sdks_second_initialisation_after_the_first_known_map_is_waited_out():
    statuses = [(t, "INITIALIZING") for t in range(0, 3)]
    statuses += [(t, "KNOWN_MAP") for t in range(3, 9)]
    statuses += [(t, "INITIALIZING") for t in range(9, 12)]
    statuses += [(t, "KNOWN_MAP") for t in range(12, 30)]
    relocalized, _ = run(statuses)
    assert relocalized == [22]


def test_lost_right_after_start_is_not_relocalized():
    relocalized, _ = run([(t, "INITIALIZING") for t in range(15)] + [(t, "LOST") for t in range(15, 40)])
    assert relocalized == []


def test_a_robot_carried_somewhere_unrecognisable_gives_up_on_the_old_map_after_45_s():
    relocalization = Relocalization(stable_s=10.0, give_up_m=3.0, max_step_m=1.0, give_up_s=45.0)
    outcomes = [relocalization.update("INITIALIZING", float(t), None) for t in range(60)]
    assert outcomes.index("timeout") == 45


def test_relocalizing_just_before_the_timeout_still_succeeds():
    relocalization = Relocalization(stable_s=10.0, give_up_m=3.0, max_step_m=1.0, give_up_s=45.0)
    statuses = ["INITIALIZING"] * 40 + ["KNOWN_MAP"] * 20
    outcomes = [relocalization.update(memory, float(t), None) for t, memory in enumerate(statuses)]
    assert "timeout" not in outcomes and outcomes.index("relocalized") == 50


def test_the_jump_into_the_map_frame_does_not_count_as_driving():
    statuses = [(0, "SEARCHING"), (1, "SEARCHING"), (2, "SEARCHING"), (3, "SEARCHING")]
    positions = [np.array([0.0, 0.0]), np.array([0.1, 0.0]), np.array([-2.8, -3.3]), np.array([-2.7, -3.3])]
    _, give_up = run(statuses, positions)
    assert give_up == []


def test_driving_three_metres_without_relocalizing_gives_up():
    statuses = [(t, "SEARCHING") for t in range(40)]
    positions = [np.array([0.1 * t, 0.0]) for t in range(40)]
    _, give_up = run(statuses, positions)
    assert give_up == [30]


def test_the_sdks_second_initialisation_past_the_timeout_does_not_discard_the_map():
    relocalization = Relocalization(stable_s=10.0, give_up_m=3.0, max_step_m=1.0, give_up_s=45.0)
    statuses = ["INITIALIZING"] * 40 + ["KNOWN_MAP"] * 6 + ["INITIALIZING"] * 4 + ["KNOWN_MAP"] * 20
    outcomes = [relocalization.update(memory, float(t), None) for t, memory in enumerate(statuses)]
    assert "timeout" not in outcomes and outcomes.index("relocalized") == 60
