import math
from dataclasses import dataclass

DEFAULT_SHUNT_OHMS = 0.01
SHUNT_RANGE_V = 0.08192
SHUNT_LSB_V = 2.5e-6
CAL_SCALE = 0.00512
SHUNT_CAL_MAX = 0x7FFF
CURRENT_STEPS = 2**15
CLIP_FRACTION = 0.9


@dataclass(frozen=True)
class Calibration:
    shunt_ohms: float
    max_current_a: float
    current_lsb_a: float
    shunt_cal: int

    @property
    def full_scale_a(self) -> float:
        return SHUNT_RANGE_V / self.shunt_ohms

    @property
    def clip_a(self) -> float:
        return CLIP_FRACTION * min(self.full_scale_a, self.current_lsb_a * CURRENT_STEPS)


def minimum_current_lsb(max_current_a: float) -> float:
    return max_current_a / CURRENT_STEPS


def current_lsb(max_current_a: float) -> float:
    minimum = minimum_current_lsb(max_current_a)
    step = 10 ** math.floor(math.log10(4 * minimum))
    return math.ceil(minimum / step - 1e-9) * step


def shunt_cal(current_lsb_a: float, shunt_ohms: float) -> int:
    return round(CAL_SCALE / (current_lsb_a * shunt_ohms))


def calibrate(shunt_ohms: float, max_current_a: float | None = None) -> Calibration:
    if shunt_ohms <= 0:
        raise ValueError(f"Shunt must be positive, got {shunt_ohms} ohm")
    expected = SHUNT_RANGE_V / shunt_ohms if max_current_a is None else max_current_a
    lsb = current_lsb(expected)
    cal = shunt_cal(lsb, shunt_ohms)
    if not 0 < cal <= SHUNT_CAL_MAX:
        raise ValueError(f"SHUNT_CAL {cal} for {shunt_ohms} ohm and {expected} A does not fit in 15 bits")
    return Calibration(shunt_ohms, expected, lsb, cal)


def per_channel(text: str | None) -> dict[int, float]:
    values = {}
    for item in (text or "").replace(" ", "").split(","):
        if item:
            ch, value = item.split("=")
            values[int(ch)] = float(value)
    return values


def channel_calibrations(channels: dict[int, str], shunts: str | None, max_currents: str | None) -> dict[int, Calibration]:
    ohms, amps = per_channel(shunts), per_channel(max_currents)
    unknown = (set(ohms) | set(amps)) - set(channels)
    if unknown:
        raise ValueError(f"No active INA channel {sorted(unknown)}; active: {sorted(channels)}")
    return {ch: calibrate(ohms.get(ch, DEFAULT_SHUNT_OHMS), amps.get(ch)) for ch in channels}


def is_clipped(shunt_raw: int, current_raw: int) -> bool:
    return abs(shunt_raw) * SHUNT_LSB_V >= CLIP_FRACTION * SHUNT_RANGE_V or abs(current_raw) >= CLIP_FRACTION * CURRENT_STEPS
