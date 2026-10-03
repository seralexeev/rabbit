from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

STATE_SUBJECT = "rabbit.power.state"
REQUEST_SUBJECT = "rabbit.power.request"
JETSON_SUBJECT = "rabbit.power.jetson"
ESTOP_SUBJECT = "rabbit.safety.estop"
NAV_CANCEL_SUBJECT = "rabbit.nav.cancel"
MAP_SAVE_SUBJECT = "rabbit.map.save"
MAP_SAVE_OUTCOMES = frozenset({"map.saved", "map.save_skipped", "map.save_failed"})
SHUTDOWN_STATES = ("stopping", "jetson_halt", "jetson_off", "pi_halt")
LED_PATTERNS = {
    "booting": (1.0, 0.5),
    "body_ready": (2.0, 0.25),
    "running": None,
    "jetson_cycle": (4.0, 0.5),
    "stopping": (4.0, 0.5),
    "jetson_halt": (4.0, 0.5),
    "jetson_off": (4.0, 0.5),
    "pi_halt": (4.0, 0.5),
}


@dataclass(frozen=True)
class PowerConfig:
    long_press_s: float = 2.0
    brain_timeout_s: float = 1.0
    brain_silent_cycle_s: float = 120.0
    jetson_on_current_a: float = 0.3
    jetson_cycle_off_s: float = 5.0
    jetson_cycles_per_hour: int = 2
    map_save_timeout_s: float = 10.0
    jetson_halt_timeout_s: float = 45.0
    jetson_off_hold_s: float = 3.0
    jetson_blind_halt_s: float = 15.0
    battery_low_v: float = 13.2
    battery_clear_v: float = 13.6
    battery_window_s: float = 5.0
    battery_critical_v: float = 12.8
    battery_critical_s: float = 10.0
    require_safety: bool = True
    blink_period_s: float = 0.4
    charge_per_blink_pct: float = 20.0


@dataclass
class PowerSupervisor:
    config: PowerConfig = field(default_factory=PowerConfig)

    def __post_init__(self):
        self.state = "booting"
        self.entered_at = 0.0
        self.reason = ""
        self.started = False
        self.button_pressed: bool | None = None
        self.pressed_at: float | None = None
        self.long_press_handled = False
        self.brain_at = -math.inf
        self.safety_ready = False
        self.battery: deque[tuple[float, float]] = deque()
        self.battery_v: float | None = None
        self.charge_pct: float | None = None
        self.battery_low = False
        self.critical_since: float | None = None
        self.jetson_a: float | None = None
        self.jetson_low_since: float | None = None
        self.cycles: deque[float] = deque()
        self.map_saved = False
        self.brain_reported = False
        self.cycle_refused = False
        self.blinks_until = -math.inf
        self.blink_started = 0.0
        self.actions: list[tuple[Any, ...]] = []
        self.outbox: list[tuple[str, str, str, dict[str, Any]]] = []

    def record(self, name: str, reason: str, severity: str = "info", **fields: Any) -> None:
        self.outbox.append((name, reason, severity, fields))

    def drain(self) -> tuple[list[tuple[Any, ...]], list[tuple[str, str, str, dict[str, Any]]]]:
        actions, events = self.actions, self.outbox
        self.actions, self.outbox = [], []
        return actions, events

    def enter(self, state: str, reason: str, now: float, severity: str = "info", **fields: Any) -> None:
        previous, self.state, self.entered_at, self.reason = self.state, state, now, reason
        self.record("power.state_changed", f"{previous} -> {state}: {reason}", severity, previous=previous, state=state, cause=reason, **fields)

    def in_shutdown(self) -> bool:
        return self.state in SHUTDOWN_STATES

    def brain_alive(self, now: float) -> bool:
        return now - self.brain_at <= self.config.brain_timeout_s

    def on_button(self, pressed: bool, now: float) -> None:
        if self.button_pressed is None:
            self.button_pressed = pressed
            self.long_press_handled = pressed
            return
        if pressed == self.button_pressed:
            return
        self.button_pressed = pressed
        if pressed:
            self.pressed_at, self.long_press_handled = now, False
            return
        held = now - (self.pressed_at or now)
        if not self.long_press_handled and held < self.config.long_press_s and not self.in_shutdown():
            blinks = 0 if self.charge_pct is None else max(1, math.ceil(self.charge_pct / self.config.charge_per_blink_pct))
            self.blink_started = now
            self.blinks_until = now + max(blinks, 1) * self.config.blink_period_s * 2
            self.record("power.button_short", f"showing charge: {blinks} blinks", charge_pct=self.charge_pct, blinks=blinks, held_s=held)
        self.pressed_at = None

    def on_brain(self, now: float) -> None:
        self.brain_at = now

    def on_safety(self, data: dict, now: float) -> None:
        self.safety_ready = str(data.get("self_test", "")) in ("passed", "skipped")

    def on_map_event(self, name: str, now: float) -> None:
        if name in MAP_SAVE_OUTCOMES and self.state == "stopping":
            self.map_saved = True
            self.record("power.map_saved", name)

    def on_ina(self, data: dict, now: float) -> None:
        channels = {str(channel.get("name")): channel for channel in data.get("channels", [])}
        if "jetson_12v" in channels:
            self.jetson_a = float(channels["jetson_12v"].get("current", 0.0))
        if data.get("battery_charge_pct") is not None:
            self.charge_pct = float(data["battery_charge_pct"])
        battery = channels.get("battery")
        if battery is None:
            return
        voltage = float(battery.get("voltage", 0.0))
        self.battery_v = voltage
        self.battery.append((now, voltage))
        while self.battery and now - self.battery[0][0] > self.config.battery_window_s:
            self.battery.popleft()
        mean = sum(v for _, v in self.battery) / len(self.battery)
        full_window = now - self.battery[0][0] >= 0.9 * self.config.battery_window_s
        if not self.battery_low and full_window and mean <= self.config.battery_low_v:
            self.battery_low = True
            self.record("power.battery_low", f"battery {mean:.2f} V over {self.config.battery_window_s:.0f} s", "warning", battery_v=mean)
        elif self.battery_low and mean >= self.config.battery_clear_v:
            self.battery_low = False
            self.record("power.battery_ok", f"battery {mean:.2f} V", battery_v=mean)
        if voltage <= self.config.battery_critical_v:
            self.critical_since = now if self.critical_since is None else self.critical_since
        else:
            self.critical_since = None

    def request(self, action: str, source: str, now: float) -> tuple[bool, str]:
        if self.in_shutdown():
            return False, f"already shutting down ({self.state})"
        if action == "shutdown":
            self.shutdown(f"requested by {source}", now)
            return True, "shutting down"
        if action == "reboot_jetson":
            self.actions.append(("publish", JETSON_SUBJECT, {"action": "reboot", "source": source}))
            self.record("power.jetson_reboot", f"requested by {source}", source=source)
            return True, "asked the Jetson to reboot"
        if action == "power_cycle_jetson":
            self.cycle_jetson(f"requested by {source}", now)
            return True, f"Jetson power off for {self.config.jetson_cycle_off_s:.0f} s"
        return False, f"unknown action {action}"

    def shutdown(self, reason: str, now: float) -> None:
        self.map_saved = False
        self.enter("stopping", reason, now, "warning")
        self.actions += [
            ("publish", ESTOP_SUBJECT, {"source": "power", "reason": reason}),
            ("publish", NAV_CANCEL_SUBJECT, {"source": "power"}),
        ]
        if self.brain_alive(now):
            self.actions.append(("publish", MAP_SAVE_SUBJECT, {"source": "power"}))

    def cycle_jetson(self, reason: str, now: float) -> None:
        self.cycles.append(now)
        self.enter("jetson_cycle", reason, now, "warning", jetson_a=self.jetson_a)
        self.actions.append(("jetson_power", False))

    def tick(self, now: float) -> None:
        if not self.started:
            self.started, self.entered_at = True, now
        if self.button_pressed and self.pressed_at is not None and not self.long_press_handled and now - self.pressed_at >= self.config.long_press_s:
            self.long_press_handled = True
            if not self.in_shutdown():
                self.shutdown(f"button held {self.config.long_press_s:.0f} s", now)
        if self.critical_since is not None and now - self.critical_since >= self.config.battery_critical_s and not self.in_shutdown():
            self.shutdown(f"battery below {self.config.battery_critical_v} V for {self.config.battery_critical_s:.0f} s", now)
        while self.cycles and now - self.cycles[0] > 3600.0:
            self.cycles.popleft()
        elapsed = now - self.entered_at
        if self.state == "booting" and (self.safety_ready or not self.config.require_safety):
            self.enter("body_ready", "safety ready" if self.safety_ready else "safety not required", now)
        elif self.state == "body_ready" and self.brain_alive(now):
            self.enter("running", "brain heartbeat", now)
        elif self.state == "running":
            silent = now - self.brain_at
            if self.brain_alive(now):
                self.brain_reported = self.cycle_refused = False
            elif not self.brain_reported:
                self.brain_reported = True
                self.record("power.brain_lost", "rabbit.nav.state silent", "warning")
            if silent >= self.config.brain_silent_cycle_s and (self.jetson_a or 0.0) > self.config.jetson_on_current_a:
                if len(self.cycles) < self.config.jetson_cycles_per_hour:
                    self.cycle_jetson(f"brain silent {silent:.0f} s while the Jetson draws {self.jetson_a:.2f} A", now)
                elif not self.cycle_refused:
                    self.cycle_refused = True
                    self.record("power.jetson_cycle_skipped", f"already {len(self.cycles)} power cycles in the last hour", "error")
        elif self.state == "jetson_cycle" and elapsed >= self.config.jetson_cycle_off_s:
            self.actions.append(("jetson_power", True))
            self.brain_at = -math.inf
            self.enter("body_ready", "Jetson powered on again", now)
        elif self.state == "stopping" and (self.map_saved or elapsed >= self.config.map_save_timeout_s or not self.brain_alive(now)):
            how = "map saved" if self.map_saved else "brain not running" if not self.brain_alive(now) else f"no map save reply in {self.config.map_save_timeout_s:.0f} s"
            self.actions.append(("publish", JETSON_SUBJECT, {"action": "poweroff", "source": "power"}))
            self.jetson_low_since = None
            self.enter("jetson_halt", how, now)
        elif self.state == "jetson_halt":
            how = self.jetson_halted(now, elapsed)
            if how is not None:
                self.actions.append(("jetson_power", False))
                self.enter("jetson_off", how, now, "error" if how.startswith("timeout") else "info", jetson_a=self.jetson_a)
        elif self.state == "jetson_off":
            self.actions.append(("poweroff",))
            self.enter("pi_halt", "Jetson off, powering off the Pi", now)

    def jetson_halted(self, now: float, elapsed: float) -> str | None:
        if self.jetson_a is not None:
            if self.jetson_a < self.config.jetson_on_current_a:
                self.jetson_low_since = now if self.jetson_low_since is None else self.jetson_low_since
                if now - self.jetson_low_since >= self.config.jetson_off_hold_s:
                    return f"Jetson current {self.jetson_a:.2f} A for {self.config.jetson_off_hold_s:.0f} s"
            else:
                self.jetson_low_since = None
        elif now - max(self.brain_at, self.entered_at) >= self.config.jetson_blind_halt_s:
            return f"brain silent {self.config.jetson_blind_halt_s:.0f} s (no Jetson current channel)"
        if elapsed >= self.config.jetson_halt_timeout_s:
            return f"timeout {self.config.jetson_halt_timeout_s:.0f} s, cutting power without a clean halt"
        return None

    def led(self, now: float) -> bool:
        if now < self.blinks_until:
            return (now - self.blink_started) % (2 * self.config.blink_period_s) < self.config.blink_period_s
        pattern = LED_PATTERNS.get(self.state)
        if pattern is None:
            return True
        hz, duty = pattern
        if self.battery_low and self.state == "running":
            hz, duty = 1.0, 0.9
        return (now * hz) % 1.0 < duty

    def snapshot(self, now: float) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "state_s": round(now - self.entered_at, 1),
            "battery_v": self.battery_v,
            "battery_low": self.battery_low,
            "charge_pct": self.charge_pct,
            "jetson_a": self.jetson_a,
            "brain_ok": self.brain_alive(now),
            "safety_ready": self.safety_ready,
            "button": bool(self.button_pressed),
            "jetson_cycles_last_hour": len(self.cycles),
        }
