"""Rev C board outline: the kit plate (gen/kit_outline.json, from extract_outline.py) with its four corner chamfers
turned so each ToF bracket sits square in the middle of its own edge (gen/tof.json): front chamfers face 50 deg off
the heading, rear chamfers 135 deg. Each chamfer is pushed out until the bracket flange (9 mm deep) clears the M4
deck standoff behind it by MARGIN. Writes gen/outline.json and the four corner sensor poses into gen/tof.json.

Run with any Python 3: python3 gen/outline_revc.py
"""
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
# the nose grows so the ZED 2i (43.1 mm deep, on 5 mm standoffs, front face on the edge) clears the front M4
# standoffs to deck 3 (their front faces at Y 111.10) by 2 mm (owner, 2026-10-11)
CAMERA_DEPTH, CAMERA_GAP, STANDOFF_FRONT = 43.1, 2.0, 111.10
# more room for the routing (owner, 2026-10-11): the tail grows to Y -158 and the board widens to +-70 from the
# tail to Y 30 (rear wheels' inner faces at +-79.8: 9.8 mm left), then narrows back to the kit's waist before the
# front wheels' steering sweep; rear chamfers 30 mm long (the 26 mm brackets fit like the front ones)
FRONT_Y, REAR_Y = round(STANDOFF_FRONT + CAMERA_GAP + CAMERA_DEPTH, 2), -158.0
SIDE_X, SIDE_TOP, REAR_CHAMFER = 70.0, 30.0, 30.0
WAIST = (42.6534, 46.7348)          # start of the kit's waist arc (segment 24 / end of 10)
FRONT_YAW, REAR_YAW = 50.0, 135.0
FRONT_HALF = 34.1502   # the nose keeps the rev C front-edge width; the chamfers move out with it
FLANGE, STANDOFF_R, MARGIN = 9.0, 4.05, 1.5
FRONT_STANDOFF, REAR_STANDOFF = (38.0916, 107.636), (38.0916, -121.8873)
EAR_FRONT = (52.2474, 94.6374)      # start of the kit's line towards the front ear (segment 4 / 30)
SIDE_REAR = (59.3646, -116.5367)    # end of the kit's side line (segment 13 / 21)


def chamfer(yaw, edge_y, standoff, x_end):
    """Right-hand chamfer with outward normal at `yaw`: from (x0, edge_y) to (x_end, y1), placed so the standoff is
    FLANGE + STANDOFF_R + MARGIN inside it."""
    a = math.radians(yaw)
    n = (math.sin(a), math.cos(a))
    d = FLANGE + STANDOFF_R + MARGIN
    c = n[0] * standoff[0] + n[1] * standoff[1] + d          # line: n . p = c
    x0 = (c - n[1] * edge_y) / n[0]
    y1 = (c - n[0] * x_end) / n[1]
    return (round(x0, 4), edge_y), (round(x_end, 4), round(y1, 4))


def main():
    kit = json.loads((HERE / "kit_outline.json").read_text())
    fa = (FRONT_HALF, FRONT_Y)
    fb = (51.7168, round(FRONT_Y - (51.7168 - FRONT_HALF) * math.tan(math.radians(FRONT_YAW)), 4))
    d = REAR_CHAMFER / math.sqrt(2)
    ra, rb = (round(SIDE_X - d, 4), REAR_Y), (SIDE_X, round(REAR_Y + d, 4))
    n = (math.sin(math.radians(REAR_YAW)), math.cos(math.radians(REAR_YAW)))
    clear = (n[0] * ra[0] + n[1] * ra[1]) - (n[0] * REAR_STANDOFF[0] + n[1] * REAR_STANDOFF[1])
    assert clear >= FLANGE + STANDOFF_R + MARGIN, clear     # bracket flange still clears the rear standoff
    assert fb[1] > EAR_FRONT[1], fb
    S = kit["segments"]

    def line(p, q):
        return {"type": "line", "start": list(p), "end": list(q)}

    def mx(p):
        return (-p[0], p[1])
    segs = [line(fa, mx(fa)), line(mx(fa), mx(fb)), line(mx(fb), mx(EAR_FRONT))]
    top = (SIDE_X, SIDE_TOP)
    segs += S[4:11]                                             # left ear and waist down to WAIST
    segs += [line(mx(WAIST), mx(top)), line(mx(top), mx(rb)), line(mx(rb), mx(ra)), line(mx(ra), ra), line(ra, rb),
             line(rb, top), line(top, WAIST)]
    segs += S[24:31]                                            # right waist and ear, up to EAR_FRONT
    segs += [line(EAR_FRONT, fb), line(fb, fa)]
    out = dict(kit)
    out["segments"] = segs
    out["note"] = "rev C: kit plate grown (nose for the ZED, wider and longer tail) with the chamfers squared to the ToF brackets (gen/outline_revc.py)"
    (HERE / "outline.json").write_text(json.dumps(out, indent=1))
    tof = json.loads((HERE / "tof.json").read_text())
    mid_f = ((fa[0] + fb[0]) / 2, (fa[1] + fb[1]) / 2)
    mid_r = ((ra[0] + rb[0]) / 2, (ra[1] + rb[1]) / 2)
    for s in tof["sensors"]:
        if s["name"] == "front":
            s.update(Y=FRONT_Y)
        if s["name"] == "rear":
            s.update(Y=REAR_Y)
        if s["name"] in ("front_l", "front_r"):
            sg = -1 if s["name"] == "front_l" else 1
            s.update(X=round(sg * mid_f[0], 3), Y=round(mid_f[1], 3), yaw=sg * FRONT_YAW)
        if s["name"] in ("rear_l", "rear_r"):
            sg = -1 if s["name"] == "rear_l" else 1
            s.update(X=round(sg * mid_r[0], 3), Y=round(mid_r[1], 3), yaw=sg * REAR_YAW)
    (HERE / "tof.json").write_text(json.dumps(tof, indent=1))
    print("front chamfer", fa, fb, "mid", mid_f, "| rear chamfer", ra, rb, "mid", mid_r)


if __name__ == "__main__":
    main()
