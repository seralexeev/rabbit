"""Wheel coupling: hollow stub axle on two bearings, and an Oldham coupling from the gearhead shaft.

Load path: wheel -> 12 mm hex -> stub axle -> 2 x SKF 61803-2RS1 -> bracket. The gearhead shaft sits
inside the hollow stub and only turns it, through hub A (on the shaft), a PEEK Oldham disc and the
cross slot at the bottom of the stub bore. The disc floats +-0.3 mm radially, so the bracket bearings
and the gearhead bearings never fight each other.

    uv run --project ../../model python coupling.py    # STEP of each part
"""

from build123d import Align, Box, Cylinder, Pos, RegularPolygon, Rot, export_step, extrude

from bracket import xcyl
from geometry import (
    BEARING,
    BORE_BOTTOM,
    BRG1_IN,
    BRG1_OUT,
    BRG2_IN,
    BRG2_OUT,
    CIRCLIP,
    GEAR_FACE,
    HERE,
    HEX_AF,
    HEX_FACE,
    HEX_LEN,
    HUB_NECK_D,
    KIT_COLLAR_D,
    MOTOR,
    MOTORS,
    OLDHAM_BODY_T,
    OLDHAM_D,
    OLDHAM_GAP,
    OLDHAM_SLOT_W,
    OLDHAM_TONGUE_H,
    SHOULDER_W,
    STUB_END,
    STUB_SHOULDER_D,
    TUBE_ID,
    box,
)

SHOULDER_LEN = 0.7
M3_TAP = 2.5
M3_TAP_DEPTH = 10.0
SLOT_DEPTH = OLDHAM_TONGUE_H + 0.3
DISC_HOLE = 7.0
SET_SCREW = 3.0
HUB_GAP = 0.3

DISC_OUT = BORE_BOTTOM - OLDHAM_GAP
DISC_IN = DISC_OUT - OLDHAM_BODY_T
HUB_FACE = DISC_IN - OLDHAM_GAP


def hub_inner(key=MOTOR):
    m = MOTORS[key]
    return GEAR_FACE + m["pilot_h"] + m["shoulder_h"] + HUB_GAP


def hex_prism(af, x0, x1):
    poly = RegularPolygon(af / 2, 6, major_radius=False)
    return Pos(x0, 0, 0) * (Rot(0, 90, 0) * Rot(0, 0, 30) * extrude(poly, x1 - x0))


def stub_axle():
    """Stainless 303. Hex end into the wheel as the kit hub, bearing seat 17 k5, DIN 471 groove, Oldham slot."""
    shoulder_out = BRG2_OUT + SHOULDER_LEN
    hex_end = HEX_FACE + HEX_LEN
    s = xcyl(BEARING["d"], STUB_END, BRG2_OUT)
    s += xcyl(STUB_SHOULDER_D, BRG2_OUT, shoulder_out)
    s += xcyl(KIT_COLLAR_D, shoulder_out, HEX_FACE)
    s += hex_prism(HEX_AF, HEX_FACE, hex_end).intersect(xcyl(HEX_AF / 0.866 - 0.6, HEX_FACE, hex_end))
    s -= xcyl(BEARING["d"] + 2, BRG1_IN - CIRCLIP["groove_m"], BRG1_IN) - xcyl(CIRCLIP["groove_d"], BRG1_IN - 2, BRG1_IN + 1)
    s -= xcyl(TUBE_ID, STUB_END - 1, BORE_BOTTOM)
    s -= box(BORE_BOTTOM - 0.5, BORE_BOTTOM + SLOT_DEPTH, -OLDHAM_SLOT_W / 2, OLDHAM_SLOT_W / 2, -TUBE_ID / 2, TUBE_ID / 2)
    s -= xcyl(M3_TAP, hex_end - M3_TAP_DEPTH, hex_end + 1)
    return s


def inner_spacer():
    """Between the two inner rings; its width matches the housing shoulder so the rings are not preloaded."""
    return xcyl(20.0, BRG2_IN - SHOULDER_W, BRG2_IN) - xcyl(BEARING["d"] + 0.1, BRG2_IN - SHOULDER_W - 1, BRG2_IN + 1)


def oldham_hub(key=MOTOR):
    """Hub A on the gearhead shaft: bore 6 H7, M3 set screw on the flat, cross slot (along Y) for the disc."""
    m = MOTORS[key]
    x0, x1 = hub_inner(key), HUB_FACE
    neck_end = STUB_END - OLDHAM_GAP
    h = xcyl(HUB_NECK_D, x0, neck_end) + xcyl(OLDHAM_D, neck_end, x1)
    h -= xcyl(m["shaft_d"], x0 - 1, x1 + 1)
    h -= box(x1 - SLOT_DEPTH, x1 + 1, -OLDHAM_D, OLDHAM_D, -OLDHAM_SLOT_W / 2, OLDHAM_SLOT_W / 2)
    xs = set_screw_x(key)
    h -= Pos(xs, 0, 0) * Cylinder(SET_SCREW * 0.42, OLDHAM_D, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return h


def set_screw_x(key=MOTOR):
    """On the shaft flat: the flat runs from the shaft end back over its last 10 mm."""
    m = MOTORS[key]
    shaft_end = GEAR_FACE + m["shaft_len"]
    flat_start = shaft_end - m["flat_len"]
    return min(max(flat_start + 2.5, hub_inner(key) + 2.5), shaft_end - 2.0)


def oldham_disc():
    """PEEK. Tongue along Y toward hub A, tongue along Z toward the stub, central hole for the shaft end."""
    d = xcyl(OLDHAM_D, DISC_IN, DISC_OUT)
    w = OLDHAM_SLOT_W - 0.02
    d += box(DISC_IN - OLDHAM_TONGUE_H, DISC_IN, -OLDHAM_D / 2, OLDHAM_D / 2, -w / 2, w / 2).intersect(xcyl(OLDHAM_D, DISC_IN - 3, DISC_IN))
    d += box(DISC_OUT, DISC_OUT + OLDHAM_TONGUE_H, -w / 2, w / 2, -OLDHAM_D / 2, OLDHAM_D / 2).intersect(xcyl(OLDHAM_D, DISC_OUT, DISC_OUT + 3))
    d -= xcyl(DISC_HOLE, DISC_IN - 3, DISC_OUT + 3)
    return d


def parts(key=MOTOR):
    return {
        "stub_axle": stub_axle(),
        "inner_spacer": inner_spacer(),
        "oldham_hub": oldham_hub(key),
        "oldham_disc": oldham_disc(),
    }


def export():
    out = {}
    for name, p in parts().items():
        if name == "oldham_hub":
            continue
        export_step(p, str(HERE / f"{name}.step"))
        out[name] = round(p.volume / 1000, 3)
    for key in MOTORS:
        p = oldham_hub(key)
        export_step(p, str(HERE / f"oldham_hub_{key}.step"))
        out[f"oldham_hub_{key}"] = round(p.volume / 1000, 3)
    return out


if __name__ == "__main__":
    print(export())
