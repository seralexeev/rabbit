import asyncio
import json
from types import SimpleNamespace

from sim import Clock, Event, Robot, Sim, apartment, block, nav_module, room_grid

from lib.observability import EventLimiter
from lib.trip import Target


def events(node, name: str) -> list[dict]:
    return [event for event in node.event_queue if event["name"] == name]


def test_a_wall_ahead_records_why_nav_held_and_why_it_gave_up():
    grid = room_grid(4.0, 2.0)
    block(grid, 2.5, 0.0, 2.6, 2.0)
    sim = Sim(grid, grid, Robot(1.0, 1.0, 0.0))

    sim.run_mission([{"type": "move", "forward": 3.0}], 25.0)

    [started] = events(sim.nav, "nav.mission_started")
    [hold] = events(sim.nav, "nav.hold")
    [stop] = events(sim.nav, "nav.safety_stop")
    assert started["ids"]["mission_id"] == hold["ids"]["mission_id"] == stop["ids"]["mission_id"] == "m"
    assert hold["reason"] == "obstacle ahead" and hold["values"]["free_distance_m"] < hold["values"]["stop_m"]
    assert stop["reason"] == "blocked" and stop["severity"] == "warning"
    assert stop["values"]["blocked_s"] >= nav_module.Node.BLOCKED_TIMEOUT
    assert stop["labels"]["hold"] == "obstacle ahead"


async def ignore(subject: str, payload: dict):
    pass


def drive(node, clock: Clock):
    node.publish_json = ignore
    node.mode, node.speed, node.speed_changed_at, node.ground_speed, node.pose_at = "driving", 0.25, clock.now - 5.0, 0.0, clock.now
    node.mission_id = "m"
    node.set_log_context(mission_id="m")


def test_every_safety_stop_records_its_fault_and_the_measurement_behind_it():
    clock = Clock()
    nav_module.time = clock
    try:
        loop = asyncio.new_event_loop()
        stuck = nav_module.Node()
        drive(stuck, clock)
        for _ in range(200):
            stuck.pose_at = clock.now
            loop.run_until_complete(stuck.on_roboclaw(SimpleNamespace(data=json.dumps({"left": {"current": 0.6}, "right": {"current": 0.6}}).encode())))
            clock.now += 0.02
        bumped = nav_module.Node()
        drive(bumped, clock)
        for _ in range(6):
            imu = {"acceleration": [8.0, 9.81, 0.0], "orientation": [0.0, 0.0, 0.0, 1.0]}
            loop.run_until_complete(bumped.on_imu(SimpleNamespace(data=json.dumps(imu).encode())))
            clock.now += 0.01
        loop.close()
    finally:
        nav_module.time = __import__("time")

    [stuck_stop] = events(stuck, "nav.safety_stop")
    [bump_stop] = events(bumped, "nav.safety_stop")
    assert stuck_stop["reason"] == "stuck" and stuck_stop["ids"]["mission_id"] == "m"
    assert stuck_stop["values"]["motor_current_a"] == 0.6 and stuck_stop["values"]["stuck_s"] > nav_module.Node.STUCK_TIME
    assert bump_stop["reason"] == "collision" and bump_stop["values"]["accel_mps2"] > nav_module.Node.BUMP_ACCELERATION


def test_a_trip_that_loses_its_route_records_each_plan_and_why_it_failed():
    def close_every_door(s: Sim):
        s.world = apartment(door_b_to_c=False)
        s.set_known(s.world)

    sim = Sim(apartment(), apartment(), Robot(5.5, 1.5, 0.0))
    sim.events.append(Event(10.0, close_every_door))

    state = sim.run(Target("point", 6.4, 5.0), 120)

    records = sim.navigator.drain_records()
    finished = [fields | {"reason": reason, "severity": severity} for name, reason, severity, fields in records if name == "planner.trip_finished"]
    failed_plans = [fields for name, _, _, fields in records if name == "planner.plan" and fields["outcome"] == "no route"]
    assert state["phase"] == "failed"
    assert finished == [finished[0]] and finished[0]["reason"] == state["message"] and finished[0]["severity"] == "warning"
    assert finished[0]["trip_id"] == "trip" and finished[0]["outcome"] == "failed"
    assert failed_plans and all(plan["trip_id"] == "trip" for plan in failed_plans)


def test_rate_limited_events_report_how_many_were_skipped():
    now = [0.0]
    limiter = EventLimiter(rate=1000.0, burst=5.0, clock=lambda: now[0])

    admitted = [limiter.admit("nav.hold|obstacle ahead", every_s=2.0)]
    for _ in range(3):
        now[0] += 0.5
        admitted.append(limiter.admit("nav.hold|obstacle ahead", every_s=2.0))
    now[0] += 1.0
    admitted.append(limiter.admit("nav.hold|obstacle ahead", every_s=2.0))

    assert admitted == [0, None, None, None, 3]
    flood = [limiter.admit(f"other-{i}") for i in range(10)]
    assert flood.count(None) == limiter.dropped > 0
