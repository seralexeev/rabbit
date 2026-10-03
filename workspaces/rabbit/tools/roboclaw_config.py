import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import docker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lib.roboclaw import SERIAL_ERRORS, RoboClaw, RoboClawError
from node.roboclaw import Node, roboclaw_port

SERVICE = "rabbit-roboclaw"
DOCKER_SOCKET = "/var/run/docker.sock"
SERIAL_READ_TIMEOUT = 0.5

MAX_CURRENT_A = 3.0
BATTERY_LIMITS_V = (12.4, 17.4)
SERIAL_TIMEOUT_S = Node.HARDWARE_TIMEOUT
ESTOP_NON_LATCHING = 0x01

PIN_MODES = {
    0x00: "default",
    0x01: "E-stop (non-latching)",
    0x81: "E-stop (latching)",
    0x14: "voltage clamp",
    0x24: "RS485 direction",
    0x84: "encoder toggle",
    0x04: "brake",
    0xE2: "home (auto)",
    0x62: "home (user)",
    0xF2: "home (auto) / limit (fwd)",
    0x72: "home (user) / limit (fwd)",
    0x12: "limit (fwd)",
    0x22: "limit (rev)",
    0x32: "limit (both)",
}
PWM_MODES = {0: "locked antiphase", 1: "sign magnitude"}
CONTROL_MODES = {0: "RC", 1: "analog", 2: "simple serial", 3: "packet serial"}
BAUD_RATES = {0x00: 2400, 0x20: 9600, 0x40: 19200, 0x60: 38400, 0x80: 57600, 0xA0: 115200, 0xC0: 230400, 0xE0: 460800}
STATUS_BITS = {
    0x000001: "E-stop",
    0x000002: "temperature error",
    0x000004: "temperature 2 error",
    0x000008: "main voltage high error",
    0x000010: "logic voltage high error",
    0x000020: "logic voltage low error",
    0x000040: "M1 driver fault",
    0x000080: "M2 driver fault",
    0x000100: "M1 speed error",
    0x000200: "M2 speed error",
    0x000400: "M1 position error",
    0x000800: "M2 position error",
    0x001000: "M1 current error",
    0x002000: "M2 current error",
    0x010000: "M1 over current warning",
    0x020000: "M2 over current warning",
    0x040000: "main voltage high warning",
    0x080000: "main voltage low warning",
    0x100000: "temperature warning",
    0x200000: "temperature 2 warning",
    0x400000: "S4 triggered",
    0x800000: "S5 triggered",
    0x01000000: "speed error limit warning",
    0x02000000: "position error limit warning",
}

RUN = "docker run --rm --privileged -v /root/rabbit/workspaces/rabbit:/rabbit -v /dev:/dev -v /var/run/docker.sock:/var/run/docker.sock -w /rabbit --entrypoint /rabbit/.venv/bin/python rabbit"
PROCEDURE = f"""Procedure on the robot (ssh -i ~/.ssh/rabbit_id_rsa root@192.168.1.53). Only one process may own the RoboClaw port,
and with rabbit-roboclaw stopped nothing drives the motors:
  1. docker stop {SERVICE}
  2. {RUN} tools/roboclaw_config.py read
     {RUN} tools/roboclaw_config.py plan
     {RUN} tools/roboclaw_config.py apply --yes
     {RUN} tools/roboclaw_encoders.py
  3. docker start {SERVICE}
Add -e ROBOCLAW_PORT=/dev/ttyTHS1 (or the USB /dev/serial/by-id path) after --privileged to pick the port; by default it is the USB port if present, else the UART.
Ctrl-C stops the encoder stream and prints the summary."""


def describe_pin(mode: int, pin: str = "S3") -> str:
    if mode == 0x00:
        return f"{mode:#04x} default ({'latching E-stop in serial modes' if pin == 'S3' else 'disabled'})"
    return f"{mode:#04x} {PIN_MODES.get(mode, 'unknown')}"


def describe_encoder(mode: int) -> str:
    flags = ["absolute" if mode & 0x01 else "quadrature"]
    flags += [name for bit, name in ((0x20, "reverse motor"), (0x40, "reverse encoder"), (0x80, "RC/analog encoder")) if mode & bit]
    return f"{mode:#04x} {', '.join(flags)}"


def describe_config(config: int) -> str:
    mode = CONTROL_MODES[config & 0x03]
    if mode != "packet serial":
        return f"{config:#06x} {mode}"
    return f"{config:#06x} packet serial, {BAUD_RATES[config & 0xE0]} baud, address {0x80 + ((config >> 8) & 0x07):#04x}"


def describe_status(status: int) -> str:
    flags = [name for bit, name in STATUS_BITS.items() if status & bit]
    return f"{status:#010x} {', '.join(flags) or 'normal'}"


def service_running() -> bool | None:
    if not os.path.exists(DOCKER_SOCKET):
        return None
    try:
        return docker.from_env().containers.get(SERVICE).status == "running"
    except docker.errors.NotFound:
        return False


def connect(port: str | None) -> tuple[RoboClaw, str]:
    running = service_running()
    if running:
        sys.exit(f"{SERVICE} is running and owns the RoboClaw port.\n\n{PROCEDURE}")
    if running is None:
        print(f"warning: no {DOCKER_SOCKET}, cannot check that {SERVICE} is stopped", file=sys.stderr)
    rc = RoboClaw(port or roboclaw_port(), timeout=SERIAL_READ_TIMEOUT)
    try:
        firmware = rc.open()
    except (RoboClawError, *SERIAL_ERRORS) as e:
        rc.close()
        sys.exit(f"Cannot talk to the RoboClaw on {rc.port}: {e}\n\n{PROCEDURE}")
    return rc, firmware


def attempt(read: Callable[[], object]) -> object:
    try:
        return read()
    except RoboClawError as e:
        return e


def read_settings(rc: RoboClaw, firmware: str) -> dict:
    return {
        "firmware": firmware,
        "port": rc.port,
        "main_battery_v": attempt(rc.read_main_battery),
        "max_current_a": {motor: attempt(lambda motor=motor: rc.read_max_current(motor)) for motor in (1, 2)},
        "main_battery_limits_v": attempt(rc.read_main_battery_limits),
        "pin_modes": attempt(rc.read_pin_modes),
        "serial_timeout_s": attempt(rc.read_serial_timeout),
        "pwm_mode": attempt(rc.read_pwm_mode),
        "encoder_modes": attempt(rc.read_encoder_modes),
        "config": attempt(rc.read_config),
        "status": attempt(lambda: rc.read_board()["status"]),
    }


def text(value: object, describe: Callable[[object], str] = str) -> str:
    return f"unavailable ({value})" if isinstance(value, Exception) else describe(value)


def print_settings(settings: dict):
    pins = settings["pin_modes"]
    encoders = settings["encoder_modes"]
    limits = settings["main_battery_limits_v"]
    rows = [
        ("firmware", settings["firmware"]),
        ("port", settings["port"]),
        ("control mode", text(settings["config"], describe_config)),
        ("main battery now", text(settings["main_battery_v"], lambda v: f"{v:.1f} V")),
        ("main battery limits", text(limits, lambda v: f"{v[0]:.1f} .. {v[1]:.1f} V")),
        ("M1 (left) max current", text(settings["max_current_a"][1], lambda v: f"{v:.2f} A")),
        ("M2 (right) max current", text(settings["max_current_a"][2], lambda v: f"{v:.2f} A")),
        ("S3 mode", text(pins, lambda v: describe_pin(v[0]))),
        ("S4 mode", text(pins, lambda v: describe_pin(v[1], "S4"))),
        ("S5 mode", text(pins, lambda v: describe_pin(v[2], "S5"))),
        ("serial timeout", text(settings["serial_timeout_s"], lambda v: f"{v:.1f} s")),
        ("PWM mode", text(settings["pwm_mode"], lambda v: f"{v} {PWM_MODES.get(v, 'unknown')}")),
        ("M1 encoder mode", text(encoders, lambda v: describe_encoder(v[0]))),
        ("M2 encoder mode", text(encoders, lambda v: describe_encoder(v[1]))),
        ("status", text(settings["status"], describe_status)),
    ]
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        print(f"{name:<{width}}  {value}")


@dataclass
class Step:
    setting: str
    current: str
    target: str
    action: Callable[[], None] | None
    note: str = ""

    @property
    def state(self) -> str:
        if self.note:
            return self.note
        return "change" if self.action else "ok"


def plan(rc: RoboClaw, settings: dict, estop: bool, battery: bool) -> list[Step]:
    steps = []
    for motor, side in ((1, "left"), (2, "right")):
        current = settings["max_current_a"][motor]
        same = not isinstance(current, Exception) and abs(current - MAX_CURRENT_A) < 0.005
        action = None if same else (lambda motor=motor: rc.set_max_current(motor, MAX_CURRENT_A))
        steps.append(Step(f"M{motor} ({side}) max current", text(current, lambda v: f"{v:.2f} A"), f"{MAX_CURRENT_A:.2f} A", action))

    timeout = settings["serial_timeout_s"]
    same = not isinstance(timeout, Exception) and abs(timeout - SERIAL_TIMEOUT_S) < 0.05
    steps.append(Step("serial timeout", text(timeout, lambda v: f"{v:.1f} s"), f"{SERIAL_TIMEOUT_S:.1f} s", None if same else lambda: rc.set_serial_timeout(SERIAL_TIMEOUT_S)))

    limits = settings["main_battery_limits_v"]
    supply = settings["main_battery_v"]
    target = f"{BATTERY_LIMITS_V[0]:.1f} .. {BATTERY_LIMITS_V[1]:.1f} V"
    same = not isinstance(limits, Exception) and all(abs(a - b) < 0.05 for a, b in zip(limits, BATTERY_LIMITS_V))
    if same:
        steps.append(Step("main battery limits", text(limits, lambda v: f"{v[0]:.1f} .. {v[1]:.1f} V"), target, None))
    elif not battery:
        steps.append(Step("main battery limits", text(limits, lambda v: f"{v[0]:.1f} .. {v[1]:.1f} V"), target, None, "skipped: needs --battery once the RoboClaw is fed from the 4S pack"))
    elif isinstance(supply, Exception) or not BATTERY_LIMITS_V[0] <= supply <= BATTERY_LIMITS_V[1]:
        steps.append(Step("main battery limits", text(limits, lambda v: f"{v[0]:.1f} .. {v[1]:.1f} V"), target, None, f"refused: the RoboClaw reads {text(supply, lambda v: f'{v:.1f} V')}, outside the limits, so the motors would stop"))
    else:
        steps.append(Step("main battery limits", text(limits, lambda v: f"{v[0]:.1f} .. {v[1]:.1f} V"), target, lambda: rc.set_main_battery_limits(*BATTERY_LIMITS_V)))

    pins = settings["pin_modes"]
    current_s3 = text(pins, lambda v: describe_pin(v[0]))
    if isinstance(pins, Exception):
        steps.append(Step("S3 mode", current_s3, describe_pin(ESTOP_NON_LATCHING), None, "skipped: S3/S4/S5 modes unreadable"))
    elif pins[0] == ESTOP_NON_LATCHING:
        steps.append(Step("S3 mode", current_s3, describe_pin(ESTOP_NON_LATCHING), None))
    elif not estop:
        steps.append(Step("S3 mode", current_s3, describe_pin(ESTOP_NON_LATCHING), None, "skipped: needs --estop once the 2.0 E-stop line is wired (1 kOhm S3-GND, Pi holds it high)"))
    else:
        steps.append(Step("S3 mode", current_s3, describe_pin(ESTOP_NON_LATCHING), lambda: rc.set_pin_modes(ESTOP_NON_LATCHING, pins[1], pins[2])))
    return steps


def print_plan(steps: list[Step]):
    rows = [("setting", "now", "target", "")] + [(s.setting, s.current, s.target, s.state) for s in steps]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)) + "  " + row[3])


def apply(rc: RoboClaw, firmware: str, steps: list[Step], estop: bool, battery: bool) -> int:
    refused = [step for step in steps if step.note.startswith("refused")]
    if refused:
        print_plan(steps)
        print("\nNothing was written.", file=sys.stderr)
        return 1
    for step in steps:
        if step.action:
            step.action()
            print(f"set {step.setting} -> {step.target}")
    after = plan(rc, read_settings(rc, firmware), estop, battery)
    pending = [step for step in after if step.action]
    if pending:
        print_plan(after)
        print("\nSome settings did not take; nothing was saved to EEPROM.", file=sys.stderr)
        return 1
    form = rc.write_nvm()
    print(f"\nSaved to EEPROM (command 94, {form}).")
    print_plan(after)
    print("\nPower-cycle the RoboClaw (or the robot), then run `read`: max current must still be 3.00 A per channel.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read, plan and apply the Rabbit 2.0 phase-0 RoboClaw configuration (packet serial, RoboClaw user manual rev 5.7)",
        epilog=PROCEDURE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["read", "plan", "apply"])
    parser.add_argument("--port", help="serial port (default: ROBOCLAW_PORT, else the USB port if present, else /dev/ttyTHS1)")
    parser.add_argument("--yes", action="store_true", help="apply: actually write the settings and save them to EEPROM")
    parser.add_argument("--estop", action="store_true", help="also set S3 to non-latching E-stop (only once the 2.0 E-stop line is wired)")
    parser.add_argument("--battery", action="store_true", help=f"also set the main battery limits to {BATTERY_LIMITS_V[0]}..{BATTERY_LIMITS_V[1]} V (only once the RoboClaw is fed from the 4S pack)")
    args = parser.parse_args()
    if args.command == "apply" and not args.yes:
        parser.error("apply writes the RoboClaw's EEPROM: run `plan` first, then `apply --yes`")

    rc, firmware = connect(args.port)
    try:
        settings = read_settings(rc, firmware)
        if args.command == "read":
            print_settings(settings)
            return 0
        steps = plan(rc, settings, args.estop, args.battery)
        if args.command == "plan":
            print_plan(steps)
            return 0
        return apply(rc, firmware, steps, args.estop, args.battery)
    finally:
        rc.close()


if __name__ == "__main__":
    sys.exit(main())
