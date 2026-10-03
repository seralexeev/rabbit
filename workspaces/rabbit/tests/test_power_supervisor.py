import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.power_supervisor import ESTOP_SUBJECT, JETSON_SUBJECT, MAP_SAVE_SUBJECT, NAV_CANCEL_SUBJECT, PowerSupervisor

TICK = 0.1


class Rig:
    def __init__(self):
        self.power = PowerSupervisor()
        self.now = 0.0
        self.brain = True
        self.jetson_a = 1.0
        self.battery_v = 15.5
        self.actions: list[tuple] = []
        self.events: list[tuple] = []
        self.power.on_button(False, self.now)

    def run(self, seconds: float):
        for _ in range(round(seconds / TICK)):
            if self.brain:
                self.power.on_brain(self.now)
            channels = [{"name": "battery", "voltage": self.battery_v, "current": 2.0}]
            if self.jetson_a is not None:
                channels.append({"name": "jetson_12v", "voltage": 12.0, "current": self.jetson_a})
            self.power.on_ina({"channels": channels, "battery_charge_pct": 63.0}, self.now)
            self.power.on_safety({"self_test": "passed"}, self.now)
            self.power.tick(self.now)
            actions, events = self.power.drain()
            self.actions += actions
            self.events += events
            self.now += TICK
        return self.power.state

    def press(self, seconds: float):
        self.power.on_button(True, self.now)
        self.run(seconds)
        self.power.on_button(False, self.now)

    def published(self) -> list[str]:
        return [action[1] for action in self.actions if action[0] == "publish"]


def running() -> Rig:
    rig = Rig()
    assert rig.run(0.5) == "running"
    return rig


def test_a_long_press_shuts_down_in_order_stop_motors_save_map_halt_jetson_cut_power():
    rig = running()
    rig.press(2.1)
    assert rig.power.state == "stopping"
    assert rig.published() == [ESTOP_SUBJECT, NAV_CANCEL_SUBJECT, MAP_SAVE_SUBJECT]
    rig.run(1.0)
    rig.power.on_map_event("map.saved", rig.now)
    rig.run(0.2)
    assert rig.power.state == "jetson_halt" and rig.actions[-1] == ("publish", JETSON_SUBJECT, {"action": "poweroff", "source": "power"})
    rig.brain = False
    rig.jetson_a = 0.1
    rig.run(2.0)
    assert rig.power.state == "jetson_halt"
    rig.run(1.5)
    assert rig.power.state == "pi_halt"
    assert [action for action in rig.actions if action[0] != "publish"] == [("jetson_power", False), ("poweroff",)]
    states = [fields["state"] for name, _, _, fields in rig.events if name == "power.state_changed"]
    assert states == ["body_ready", "running", "stopping", "jetson_halt", "jetson_off", "pi_halt"]


def test_without_a_brain_the_map_save_is_skipped_and_a_hung_jetson_is_cut_after_45_s():
    rig = running()
    rig.brain = False
    rig.run(1.5)
    assert rig.power.request("shutdown", "forge", rig.now) == (True, "shutting down")
    assert MAP_SAVE_SUBJECT not in rig.published()
    rig.run(0.2)
    assert rig.power.state == "jetson_halt"
    rig.run(44.5)
    assert rig.power.state == "jetson_halt"
    rig.run(1.0)
    assert rig.power.state == "pi_halt"
    [cut] = [event for event in rig.events if event[0] == "power.state_changed" and event[3]["state"] == "jetson_off"]
    assert cut[2] == "error" and "without a clean halt" in cut[3]["cause"]


def test_without_a_jetson_current_channel_the_halt_waits_for_the_heartbeat_to_stop():
    rig = running()
    rig.jetson_a = None
    rig.power.jetson_a = None
    rig.press(2.1)
    rig.power.on_map_event("map.save_skipped", rig.now)
    rig.run(0.2)
    rig.brain = False
    rig.run(14.0)
    assert rig.power.state == "jetson_halt"
    rig.run(2.0)
    assert rig.power.state == "pi_halt"


def test_a_short_press_blinks_the_charge_and_a_press_held_since_boot_is_ignored():
    rig = Rig()
    rig.power = PowerSupervisor()
    rig.power.on_button(True, 0.0)
    rig.run(3.0)
    assert rig.power.state == "running"
    rig.power.on_button(False, rig.now)
    rig.press(0.3)
    rig.run(0.1)
    [blink] = [event for event in rig.events if event[0] == "power.button_short"]
    assert blink[3]["blinks"] == 4 and rig.power.state == "running"


def test_a_critical_battery_for_10_s_starts_the_shutdown():
    rig = running()
    rig.battery_v = 12.7
    rig.run(9.5)
    assert rig.power.state == "running"
    rig.run(1.0)
    assert rig.power.state == "stopping" and "battery below 12.8 V" in rig.power.reason
    assert any(name == "power.battery_low" for name, *_ in rig.events)


def test_a_silent_brain_with_a_powered_jetson_is_power_cycled_at_most_twice_an_hour():
    rig = running()
    rig.brain = False
    for cycle in range(2):
        rig.run(120.5)
        assert rig.power.state == "jetson_cycle"
        rig.run(5.1)
        assert rig.power.state == "body_ready"
        rig.brain = True
        rig.run(0.2)
        rig.brain = False
    rig.run(121.0)
    assert rig.power.state == "running"
    assert [a for a in rig.actions if a[0] == "jetson_power"] == [("jetson_power", False), ("jetson_power", True)] * 2
    assert sum(1 for name, *_ in rig.events if name == "power.jetson_cycle_skipped") == 1


def test_requests_are_refused_once_shutting_down():
    rig = running()
    assert rig.power.request("reboot_jetson", "hud", rig.now)[0]
    assert rig.power.actions[-1] == ("publish", JETSON_SUBJECT, {"action": "reboot", "source": "hud"})
    assert rig.power.request("power_cycle_jetson", "hud", rig.now)[0] and rig.power.state == "jetson_cycle"
    rig.run(5.2)
    rig.power.request("shutdown", "hud", rig.now)
    assert rig.power.request("shutdown", "hud", rig.now) == (False, "already shutting down (stopping)")
    assert running().power.request("bogus", "hud", 0.0) == (False, "unknown action bogus")
