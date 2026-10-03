from __future__ import annotations

import math
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from lib.drive import DRIVE_SUBJECT, JOY_SUBJECT, METRES_PER_SECOND_PER_DUTY, CommandArbiter
from lib.geometry import curvature_for_steer
from lib.lidar import to_safety_frame
from lib.safety import Footprint, free_distance

STATE_SUBJECT = "rabbit.safety.state"
ESTOP_SUBJECT = "rabbit.safety.estop"
RESET_SUBJECT = "rabbit.safety.reset"
ROBOCLAW_ESTOP_FLAG = 0x1
STOPPING_STATES = frozenset({"stopping", "jetson_halt", "jetson_off", "pi_halt"})
TOF_ENDS = {"FL": "front", "FR": "front", "RL": "rear", "RR": "rear"}
DIRECTIONS = {"front": 1, "rear": -1}
BODY_2_0 = Footprint(front=0.2452, rear=0.072, half_width=0.102, margin=0.02)


def sensors_from_env(name: str, default: str) -> frozenset[str]:
    return frozenset(item for item in (os.environ.get(name, default) or "").replace(" ", "").split(",") if item)


@dataclass(frozen=True)
class SafetyConfig:
    command_timeout_s: float = 0.3
    brain_timeout_s: float = 0.5
    lidar_timeout_s: float = 0.3
    tof_timeout_s: float = 0.25
    roboclaw_timeout_s: float = 0.3
    roboclaw_recovery_s: float = 1.0
    ina_timeout_s: float = 1.0
    stale_cap_mps: float = 0.1
    tof_stale_cap_mps: float = 0.08
    bump_release_s: float = 1.0
    bump_crawl_mps: float = 0.1
    bump_crawl_m: float = 0.5
    min_speed_mps: float = 0.03
    stop_margin_m: float = 0.05
    reaction_s: float = 0.25
    deceleration_mps2: float = 1.0
    lookahead_m: float = 1.0
    battery_low_v: float = 13.2
    battery_clear_v: float = 13.6
    battery_window_s: float = 5.0
    battery_low_scale: float = 0.5
    battery_critical_v: float = 12.8
    battery_critical_s: float = 10.0
    battery_overcurrent_a: float = 13.0
    motor_overcurrent_a: float = 8.0
    overcurrent_release_s: float = 2.0
    self_test_timeout_s: float = 3.0
    footprint: Footprint = BODY_2_0
    sensors: frozenset[str] = frozenset({"lidar", "tof", "bumpers"})
    tof_sensors: tuple[str, ...] = ("FL", "FR", "RL", "RR")
    nav_sources: frozenset[str] = frozenset({"nav"})
    self_test: bool = True
    ina_alert: bool = False
    shadow: bool = False

    @classmethod
    def from_env(cls) -> "SafetyConfig":
        return cls(
            sensors=sensors_from_env("SAFETY_SENSORS", "lidar,tof,bumpers"),
            tof_sensors=tuple(sorted(sensors_from_env("SAFETY_TOF", "FL,FR,RL,RR"))),
            self_test=os.environ.get("SAFETY_SELF_TEST", "1") == "1",
            ina_alert=os.environ.get("SAFETY_INA_ALERT", "0") == "1",
            shadow=os.environ.get("SAFETY_MODE", "active") == "shadow",
        )


def speed_for_clearance(clearance: float, config: SafetyConfig) -> float:
    room = clearance - config.stop_margin_m
    if room <= 0:
        return 0.0
    a, t = config.deceleration_mps2, config.reaction_s
    return a * (-t + math.sqrt(t * t + 2.0 * room / a))


def stopping_distance(speed: float, config: SafetyConfig) -> float:
    return config.stop_margin_m + speed * config.reaction_s + speed * speed / (2.0 * config.deceleration_mps2)


@dataclass
class Bump:
    pressed: bool = False
    pressed_at: float = -math.inf
    released_at: float = -math.inf
    crawled_m: float = 0.0


@dataclass
class Decision:
    speed: float
    steer: float
    source: str
    cap_fwd: float
    cap_rev: float
    reason: str
    line: bool
    mode: str
    reasons: list[str]
    clearance_fwd: float | None
    clearance_rev: float | None
    requested: tuple[float, float]


@dataclass
class Limit:
    mps: float
    reason: str


@dataclass
class SafetyLoop:
    config: SafetyConfig = field(default_factory=SafetyConfig)

    def __post_init__(self):
        self.arbiter = CommandArbiter()
        self.command: tuple[float, float, str, float] | None = None
        self.seen: dict[str, float] = {}
        self.lidar_points = np.empty((0, 2))
        self.tof_points: dict[str, np.ndarray] = {}
        self.bumps = {"front": Bump(), "rear": Bump()}
        self.roboclaw: dict[str, Any] = {}
        self.roboclaw_fresh_since: float | None = None
        self.roboclaw_lost = True
        self.battery: deque[tuple[float, float]] = deque()
        self.battery_low = False
        self.battery_critical = False
        self.critical_since: float | None = None
        self.overcurrent_until = -math.inf
        self.alert = False
        self.power_state = ""
        self.estop: tuple[str, str] | None = None
        self.self_test = "skipped" if self.config.shadow or not self.config.self_test else "waiting"
        self.self_test_at = 0.0
        self.line = False
        self.stale: set[str] = set()
        self.brain_lost = False
        self.limit_reason = ""
        self.output = (0.0, 0.0)
        self.stepped_at: float | None = None
        self.outbox: list[tuple[str, str, str, float, dict[str, Any]]] = []

    def record(self, name: str, reason: str, severity: str = "info", every_s: float = 0.0, **fields: Any) -> None:
        self.outbox.append((name, reason, severity, every_s, fields))

    def drain(self) -> list[tuple[str, str, str, float, dict[str, Any]]]:
        events, self.outbox = self.outbox, []
        return events

    def enabled(self, sensor: str) -> bool:
        return sensor in self.config.sensors

    def fresh(self, name: str, timeout: float, now: float) -> bool:
        return now - self.seen.get(name, -math.inf) <= timeout

    def on_drive(self, data: dict, now: float) -> None:
        if self.arbiter.decide(DRIVE_SUBJECT, data, now) is None:
            return
        speed, steer = (float(data.get(key) or 0.0) for key in ("speed", "steer"))
        self.command = (max(-1.0, min(1.0, speed)), max(-1.0, min(1.0, steer)), str(data.get("source") or ""), now)

    def on_joy(self, data: dict, now: float) -> None:
        resolved = self.arbiter.decide(JOY_SUBJECT, data, now)
        if resolved is not None:
            self.command = (resolved[0], resolved[1], "joystick", now)

    def on_brain(self, now: float) -> None:
        self.seen["brain"] = now

    def on_lidar(self, points: np.ndarray, now: float) -> None:
        self.lidar_points = self.outside_body(points)
        self.seen["lidar"] = now

    def on_tof(self, sensor: str, points: np.ndarray, now: float) -> None:
        self.tof_points[sensor] = self.outside_body(points)
        self.seen[f"tof_{sensor}"] = now

    def outside_body(self, points: np.ndarray) -> np.ndarray:
        if len(points) == 0:
            return np.empty((0, 2))
        f = self.config.footprint
        inside = (points[:, 0] <= f.front) & (points[:, 0] >= -f.rear) & (np.abs(points[:, 1]) <= f.half_width)
        return points[~inside]

    def on_bumper(self, end: str, pressed: bool, now: float) -> None:
        bump = self.bumps[end]
        if pressed == bump.pressed:
            return
        bump.pressed = pressed
        if pressed:
            bump.pressed_at, bump.crawled_m = now, 0.0
            speed, steer = self.output
            self.record("safety.bump", f"{end} bumper pressed", "warning", end=end, speed=speed, steer=steer, source=self.command[2] if self.command else "")
        else:
            bump.released_at = now
            self.record("safety.bump_released", f"{end} bumper released", end=end, pressed_s=now - bump.pressed_at, crawled_m=bump.crawled_m)

    def on_roboclaw(self, data: dict, now: float) -> None:
        self.roboclaw = data
        if self.roboclaw_fresh_since is None:
            self.roboclaw_fresh_since = now
        self.seen["roboclaw"] = now

    def on_ina(self, data: dict, now: float) -> None:
        self.seen["ina"] = now
        channels = {str(channel.get("name")): channel for channel in data.get("channels", [])}
        battery = channels.get("battery")
        if battery is None:
            return
        voltage, current = float(battery.get("voltage", 0.0)), float(battery.get("current", 0.0))
        self.battery.append((now, voltage))
        while self.battery and now - self.battery[0][0] > self.config.battery_window_s:
            self.battery.popleft()
        mean = sum(v for _, v in self.battery) / len(self.battery)
        if not self.battery_low and mean <= self.config.battery_low_v and now - self.battery[0][0] >= self.config.battery_window_s * 0.9:
            self.battery_low = True
            self.record("safety.battery_low", f"battery {mean:.2f} V over {self.config.battery_window_s:.0f} s", "warning", battery_v=mean, threshold_v=self.config.battery_low_v)
        elif self.battery_low and mean >= self.config.battery_clear_v:
            self.battery_low = False
            self.record("safety.battery_ok", f"battery {mean:.2f} V", battery_v=mean)
        if voltage <= self.config.battery_critical_v:
            self.critical_since = now if self.critical_since is None else self.critical_since
            if not self.battery_critical and now - self.critical_since >= self.config.battery_critical_s:
                self.battery_critical = True
                self.record("safety.battery_critical", f"battery below {self.config.battery_critical_v} V for {self.config.battery_critical_s:.0f} s", "critical", battery_v=voltage)
        else:
            self.critical_since = None
            if self.battery_critical and mean >= self.config.battery_clear_v:
                self.battery_critical = False
        motors = channels.get("motors")
        motor_current = abs(float(motors.get("current", 0.0))) if motors else 0.0
        if abs(current) >= self.config.battery_overcurrent_a or motor_current >= self.config.motor_overcurrent_a:
            if now >= self.overcurrent_until:
                self.record("safety.overcurrent", f"battery {current:.1f} A, motors {motor_current:.1f} A", "error", battery_a=current, motors_a=motor_current)
            self.overcurrent_until = now + self.config.overcurrent_release_s

    def on_alert(self, active: bool, now: float) -> None:
        if not self.config.ina_alert or active == self.alert:
            return
        self.alert = active
        if active:
            self.record("safety.overcurrent", "INA ALERT asserted", "error", source="alert")
        else:
            self.overcurrent_until = max(self.overcurrent_until, now + self.config.overcurrent_release_s)

    def on_power(self, state: str, now: float) -> None:
        self.power_state = state

    def on_estop(self, data: dict, now: float) -> None:
        source, reason = str(data.get("source") or "unknown"), str(data.get("reason") or "")
        if self.estop is None:
            self.record("safety.estop", f"latched by {source}" + (f": {reason}" if reason else ""), "warning", source=source)
        self.estop = (source, reason)

    def on_reset(self, data: dict, now: float) -> None:
        if self.estop is not None:
            source = str(data.get("source") or "unknown")
            self.record("safety.reset", f"released by {source}", source=source, latched_by=self.estop[0])
        self.estop = None

    def inputs(self) -> dict[str, float]:
        inputs = {"roboclaw": self.config.roboclaw_timeout_s, "ina": self.config.ina_timeout_s}
        if self.enabled("lidar"):
            inputs["lidar"] = self.config.lidar_timeout_s
        if self.enabled("tof"):
            inputs |= {f"tof_{sensor}": self.config.tof_timeout_s for sensor in self.config.tof_sensors}
        return inputs

    def watch_inputs(self, now: float) -> None:
        for name, timeout in self.inputs().items():
            stale = not self.fresh(name, timeout, now)
            if stale and name in self.seen and name not in self.stale:
                self.stale.add(name)
                self.record("safety.input_stale", f"{name} silent for {now - self.seen[name]:.2f} s", "warning", input=name, age_s=now - self.seen[name], timeout_s=timeout)
            elif not stale and name in self.stale:
                self.stale.discard(name)
                self.record("safety.input_restored", f"{name} fresh again", input=name)
        brain_lost = not self.fresh("brain", self.config.brain_timeout_s, now)
        if brain_lost != self.brain_lost and (not brain_lost or "brain" in self.seen):
            self.record("safety.brain_lost" if brain_lost else "safety.brain_restored", "rabbit.nav.state silent" if brain_lost else "rabbit.nav.state fresh again", "warning" if brain_lost else "info")
        self.brain_lost = brain_lost

    def watch_roboclaw(self, now: float) -> None:
        if not self.fresh("roboclaw", self.config.roboclaw_timeout_s, now):
            if not self.roboclaw_lost:
                self.record("safety.roboclaw_lost", f"no telemetry for {now - self.seen['roboclaw']:.2f} s", "error", age_s=now - self.seen["roboclaw"])
            self.roboclaw_lost = True
            self.roboclaw_fresh_since = None
            return
        idle = all(abs(float((self.roboclaw.get(side) or {}).get("pwm", 0.0))) < 1e-3 for side in ("left", "right"))
        if not idle:
            self.roboclaw_fresh_since = now
        if self.roboclaw_lost and self.roboclaw_fresh_since is not None and now - self.roboclaw_fresh_since >= self.config.roboclaw_recovery_s:
            self.roboclaw_lost = False
            self.record("safety.roboclaw_ready", f"fresh idle telemetry for {self.config.roboclaw_recovery_s:.0f} s")

    def run_self_test(self, now: float) -> None:
        if self.self_test in ("passed", "failed", "skipped"):
            return
        status = int(self.roboclaw.get("status", 0) or 0)
        fresh = self.fresh("roboclaw", self.config.roboclaw_timeout_s, now)
        if self.self_test == "waiting":
            if all(self.fresh(name, timeout, now) for name, timeout in self.inputs().items() if name != "ina"):
                self.self_test, self.self_test_at = "line_low", now
        elif self.self_test == "line_low":
            if fresh and status & ROBOCLAW_ESTOP_FLAG:
                self.self_test, self.self_test_at = "line_high", now
            elif now - self.self_test_at > self.config.self_test_timeout_s:
                self.fail_self_test("RoboClaw reports no E-stop while the line is low", status)
        elif self.self_test == "line_high":
            if fresh and not status & ROBOCLAW_ESTOP_FLAG and self.roboclaw_fresh_since is not None and self.seen["roboclaw"] > self.self_test_at:
                self.self_test = "passed"
                self.record("safety.self_test", "E-stop line checked: low stops, high releases", status=status)
            elif now - self.self_test_at > self.config.self_test_timeout_s:
                self.fail_self_test("RoboClaw still reports E-stop after the line went high", status)

    def fail_self_test(self, reason: str, status: int) -> None:
        self.self_test = "failed"
        self.record("safety.self_test", f"estop_line_fault: {reason}", "critical", status=status)

    def hard_stops(self, now: float) -> list[str]:
        reasons = []
        if self.estop is not None:
            reasons.append(f"estop by {self.estop[0]}")
        if self.power_state in STOPPING_STATES:
            reasons.append(f"power {self.power_state}")
        if self.roboclaw_lost:
            reasons.append("roboclaw lost")
        if now < self.overcurrent_until or self.alert:
            reasons.append("overcurrent")
        if self.self_test == "failed":
            reasons.append("estop_line_fault")
        elif self.self_test not in ("passed", "skipped"):
            reasons.append(f"self test {self.self_test}")
        return reasons

    def clearance(self, steer: float, direction: int, now: float) -> float | None:
        sources = []
        if self.enabled("lidar") and self.fresh("lidar", self.config.lidar_timeout_s, now):
            sources.append(self.lidar_points)
        if self.enabled("tof"):
            sources += [points for sensor, points in self.tof_points.items() if self.fresh(f"tof_{sensor}", self.config.tof_timeout_s, now)]
        if not sources:
            return None
        return free_distance(to_safety_frame(np.concatenate(sources)), curvature_for_steer(steer), self.config.lookahead_m, direction=direction, footprint=self.config.footprint)

    def limits(self, end: str, clearance: float | None, now: float) -> list[Limit]:
        found = []
        lidar_fresh = self.enabled("lidar") and self.fresh("lidar", self.config.lidar_timeout_s, now)
        if clearance is not None:
            found.append(Limit(speed_for_clearance(clearance, self.config), f"obstacle {'ahead' if end == 'front' else 'behind'} {clearance:.2f} m"))
        if self.enabled("lidar") and not lidar_fresh:
            found.append(Limit(self.config.stale_cap_mps, "lidar stale"))
        if self.enabled("tof"):
            for sensor in self.config.tof_sensors:
                if TOF_ENDS.get(sensor) == end and not self.fresh(f"tof_{sensor}", self.config.tof_timeout_s, now):
                    found.append(Limit(self.config.tof_stale_cap_mps if lidar_fresh else 0.0, f"tof {sensor} stale" + ("" if lidar_fresh else " without lidar")))
        if self.enabled("bumpers"):
            mine, other = self.bumps[end], self.bumps["rear" if end == "front" else "front"]
            if mine.pressed or now - mine.released_at < self.config.bump_release_s:
                found.append(Limit(0.0, f"{end} bumper"))
            if other.pressed or now - other.released_at < self.config.bump_release_s:
                if other.crawled_m >= self.config.bump_crawl_m:
                    found.append(Limit(0.0, f"crawled {self.config.bump_crawl_m:.1f} m off the {'rear' if end == 'front' else 'front'} bumper"))
                else:
                    found.append(Limit(self.config.bump_crawl_mps, f"crawling off the {'rear' if end == 'front' else 'front'} bumper"))
        if not self.fresh("ina", self.config.ina_timeout_s, now):
            found.append(Limit(self.config.stale_cap_mps, "ina stale"))
        if self.battery_critical:
            found.append(Limit(0.0, "battery critical"))
        return found

    def step(self, now: float) -> Decision:
        dt = 0.0 if self.stepped_at is None else min(max(now - self.stepped_at, 0.0), 0.1)
        self.stepped_at = now
        self.watch_inputs(now)
        self.watch_roboclaw(now)
        self.run_self_test(now)
        hard = self.hard_stops(now)
        self.line = not self.config.shadow and all(reason == "self test line_high" for reason in hard)

        speed, steer, source = 0.0, 0.0, "none"
        reasons = list(hard)
        if self.command is not None and now - self.command[3] <= self.config.command_timeout_s:
            speed, steer, source = self.command[0], self.command[1], self.command[2]
            if source in self.config.nav_sources and self.brain_lost:
                reasons.append("brain lost")
                speed, steer, source = 0.0, 0.0, f"{source} rejected"
        requested = (speed, steer)

        clearance_fwd = self.clearance(steer, 1, now)
        clearance_rev = self.clearance(steer, -1, now)
        caps = {}
        binding = {}
        for end, clearance in (("front", clearance_fwd), ("rear", clearance_rev)):
            found = self.limits(end, clearance, now)
            tightest = min(found, key=lambda limit: limit.mps, default=Limit(math.inf, ""))
            cap = 0.0 if tightest.mps < self.config.min_speed_mps else tightest.mps
            caps[end] = min(1.0, cap / METRES_PER_SECOND_PER_DUTY)
            binding[end] = tightest.reason
            reasons += [limit.reason for limit in found if limit.mps < math.inf and limit.reason not in reasons and not limit.reason.startswith("obstacle")]
        if self.battery_low:
            reasons.append("battery low")

        scaled = speed * (self.config.battery_low_scale if self.battery_low else 1.0)
        allowed = 0.0 if hard else max(-caps["rear"], min(caps["front"], scaled))
        reason = ""
        if hard and speed != 0.0:
            reason = hard[0]
        elif abs(allowed) < abs(scaled) - 1e-6:
            reason = binding["front" if speed > 0 else "rear"]
            if reason.startswith("obstacle"):
                reasons.append(reason)
        elif abs(allowed) < abs(speed) - 1e-6:
            reason = "battery low"
        self.report_limit(reason, speed, allowed, source, clearance_fwd if speed > 0 else clearance_rev)
        if allowed != 0.0:
            moving = "front" if allowed > 0 else "rear"
            away = self.bumps["rear" if moving == "front" else "front"]
            if away.pressed or now - away.released_at < self.config.bump_release_s:
                away.crawled_m += abs(allowed) * METRES_PER_SECOND_PER_DUTY * dt
        self.output = (allowed, steer if source != "none" else 0.0)
        mode = "estop" if hard else "ok" if not reason else "stopped" if allowed == 0.0 else "limited"
        return Decision(
            allowed, self.output[1], source, caps["front"], caps["rear"], reason, self.line, mode, reasons, clearance_fwd, clearance_rev, requested
        )

    def report_limit(self, reason: str, requested: float, allowed: float, source: str, clearance: float | None) -> None:
        if reason and reason != self.limit_reason:
            self.record(
                "safety.limit",
                reason,
                "warning" if source in self.config.nav_sources or allowed == 0.0 else "info",
                every_s=2.0,
                requested_speed=requested,
                allowed_speed=allowed,
                clearance_m=clearance,
                source=source,
                direction="forward" if requested > 0 else "reverse",
            )
        self.limit_reason = reason

    def snapshot(self, decision: Decision, now: float) -> dict[str, Any]:
        def age(name: str) -> float | None:
            return round(now - self.seen[name], 3) if name in self.seen else None

        inputs = ["command", "brain", "roboclaw", "ina", "lidar"] + [f"tof_{sensor}" for sensor in self.config.tof_sensors]
        ages = {name: age(name) for name in inputs}
        ages["command"] = None if self.command is None else round(now - self.command[3], 3)
        return {
            "mode": decision.mode,
            "reason": decision.reason,
            "reasons": decision.reasons,
            "shadow": self.config.shadow,
            "estop_line": decision.line,
            "estop_latched": self.estop is not None,
            "estop_source": None if self.estop is None else self.estop[0],
            "self_test": self.self_test,
            "speed": round(decision.speed, 4),
            "steer": round(decision.steer, 4),
            "requested_speed": round(decision.requested[0], 4),
            "requested_steer": round(decision.requested[1], 4),
            "source": decision.source,
            "owner": self.arbiter.owner(now),
            "cap_fwd": round(decision.cap_fwd, 4),
            "cap_rev": round(decision.cap_rev, 4),
            "clearance_fwd_m": None if decision.clearance_fwd is None else round(decision.clearance_fwd, 3),
            "clearance_rev_m": None if decision.clearance_rev is None else round(decision.clearance_rev, 3),
            "brain_ok": not self.brain_lost,
            "bumper_front": self.bumps["front"].pressed,
            "bumper_rear": self.bumps["rear"].pressed,
            "battery_low": self.battery_low,
            "battery_critical": self.battery_critical,
            "power_state": self.power_state,
            "input_age_s": ages,
            "sensors": sorted(self.config.sensors),
        }
