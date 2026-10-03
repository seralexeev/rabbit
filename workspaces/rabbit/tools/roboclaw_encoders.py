import argparse
import math
import sys
import time

from roboclaw_config import PROCEDURE, connect, describe_encoder

COUNTS_PER_WHEEL_REV = 64 * 70
WHEEL_DIAMETER_M = 0.075
COUNTS_PER_M = COUNTS_PER_WHEEL_REV / (math.pi * WHEEL_DIAMETER_M)
RATE_HZ = 10.0
TOLERANCE = 0.03
SIDES = (("left", "M1"), ("right", "M2"))


def wrap32(value: int) -> int:
    return (value + 2**31) % 2**32 - 2**31


def arrow(rate: float) -> str:
    return "  ." if abs(rate) < 1 else (" ->" if rate > 0 else "<- ")


def verdict(delta: int, distance_m: float | None) -> str:
    if delta == 0:
        return "no counts: check 5 V between blue (+) and green (-), and a square wave on yellow (A) and white (B) while turning slowly"
    reversed_hint = "counts down while rolling forward: swap A/B or set 'reverse encoder' (bit 6, commands 92/93)"
    if distance_m is None:
        return "counts up (forward)" if delta > 0 else reversed_hint
    expected = distance_m * COUNTS_PER_M
    if delta * expected < 0:
        return f"FAIL: {reversed_hint}"
    error = delta / expected - 1
    ok = abs(error) <= TOLERANCE
    return f"{'PASS' if ok else 'FAIL'}: {delta:+d} counts for {distance_m:g} m, expected {expected:+.0f} ±{TOLERANCE:.0%} ({error:+.1%})"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Stream RoboClaw encoder counts and speeds at {RATE_HZ:g} Hz while the wheels are turned by hand. Read-only: it never drives or resets anything.",
        epilog=PROCEDURE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port", help="serial port (default: ROBOCLAW_PORT, else the USB port if present, else /dev/ttyTHS1)")
    parser.add_argument("--seconds", type=float, default=0.0, help="stop after this many seconds (default: until Ctrl-C)")
    parser.add_argument("--distance", type=float, help="metres the robot was rolled forward by hand; the summary checks each side against it")
    args = parser.parse_args()

    rc, firmware = connect(args.port)
    try:
        modes = rc.read_encoder_modes()
        print(f"{firmware} on {rc.port}")
        print(f"encoder modes: M1 {describe_encoder(modes[0])}, M2 {describe_encoder(modes[1])}")
        print(f"{COUNTS_PER_WHEEL_REV} counts per wheel turn, {COUNTS_PER_M:.0f} per metre (75 mm wheel). Forward should count up on both sides. Ctrl-C to stop.\n")
        print(f"{'t, s':>6}  " + "  |  ".join(f"{side:<5} {'count':>11} {'Δ':>8} {'turns':>6} {'m':>7} {'counts/s':>9} {'rc avg/s':>8}" for side, _ in SIDES))
        start = rc.read_encoders()
        previous, previous_at = start, time.monotonic()
        began = previous_at
        try:
            while not args.seconds or time.monotonic() - began < args.seconds:
                time.sleep(max(0.0, previous_at + 1 / RATE_HZ - time.monotonic()))
                now = time.monotonic()
                reading = rc.read_encoders()
                cells = []
                for side, _ in SIDES:
                    count = reading[side]["count"]
                    delta = wrap32(count - start[side]["count"])
                    rate = wrap32(count - previous[side]["count"]) / (now - previous_at)
                    cells.append(
                        f"{side:<5} {count:>11d} {delta:>+8d} {delta / COUNTS_PER_WHEEL_REV:>+6.2f} {delta / COUNTS_PER_M:>+7.3f} {rate:>+9.0f} {reading[side]['average_speed']:>+8d} {arrow(rate)}"
                    )
                print(f"{now - began:>6.1f}  " + "  |  ".join(cells), flush=True)
                previous, previous_at = reading, now
        except KeyboardInterrupt:
            pass
        print()
        for side, motor in SIDES:
            delta = wrap32(previous[side]["count"] - start[side]["count"])
            print(f"{side} ({motor}): {delta:+d} counts, {delta / COUNTS_PER_WHEEL_REV:+.2f} wheel turns, {delta / COUNTS_PER_M:+.3f} m; {verdict(delta, args.distance)}")
    finally:
        rc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
