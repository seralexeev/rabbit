"""Rev C copper before the autorouter: planes and power pours (8 layers).

Stack: F.Cu signals + local pours | In1.Cu GND plane | In2.Cu signals | In3.Cu signals | In4.Cu VBUS plane |
In5.Cu signals + the MOT_BUS pour | In6.Cu GND plane | B.Cu signals + local pours (6 layers left ~350 connections
unrouted on 3 signal layers). In1 and In6 carry the GND_MOT island under the motor block (DRV8243
thermal pads and straps, PH motor connectors, bulk polymers, brake chopper, freewheel diode), which joins GND only at
the star net tie NT1 next to the battery connector. In4 is one VBUS plane over the whole board: every VBUS load
(fuses F2-F5, TPS16630 x2, bucks, TVS) drops a via into it, so the 9 A to the front bucks and the 3.5 A to the Jetson
never run in a track. The current paths that stay local (battery chain, motor outputs, buck switch nodes, eFuse
inputs and outputs) get pours on the side of their pads: the convex hull of the net's pads, POUR_MARGIN wider.
Outer layers are filled with GND (GND_FILL_*). The fills, the MOT_BUS pour and the local pours (POSTFILL_*) are
removed while the router runs (as planes they walled whole areas off from the signals: 243 connections stayed
unrouted) and filled around the finished tracks; the router lays every power net as a track of its class width.
"""
import json
import math
from pathlib import Path

import pcbnew

import design

F, IN1, IN4, IN5, IN6, B = pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In4_Cu, pcbnew.In5_Cu, pcbnew.In6_Cu, pcbnew.B_Cu

BOARD_POLY = [(-70, -158), (70, -158), (70, 157), (-70, 157)]

GND_MOT_ISLAND = [(-38.0, -77.0), (-12.0, -77.0), (-12.0, -98.0), (12.0, -98.0), (12.0, -77.0), (38.0, -77.0),
                  (38.0, -100.5), (44.8, -100.5), (44.8, -114.5), (17.5, -114.5), (17.5, -122.0), (5.0, -122.0),
                  (5.0, -117.0), (-38.0, -117.0)]
MOT_BUS_POUR = [(-38.0, -36.0), (34.0, -36.0), (34.0, -121.0), (-38.0, -121.0)]


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# In5: split power plane, a power layer for the router (vias only). MOT_BUS over the drive, SERVO_RAW over the servo
# buck output, the arm eFuse and a strip to the steering eFuse, SERVO_PWR over the servo ports, +5V_PI_USBC from U87
# to the Pi's USB-C J53, +5V everywhere else (adjacent +5V rectangles overlap the main one by 0.5-1 mm). The +5V bands
# beside SERVO_RAW reach the lidar eFuse inputs U80-U82 and the buzzer; deeproute could not reach them through the
# 0.6 mm class width on the outer layers (2026-10-11); the right band runs up past SERVO_PWR into the nose +5V so the
# nose LEDs and the ToF mux are on the same copper.
SERVO_RAW_POUR = [(0.0, 52.0), (29.5, 52.0), (29.5, 96.0), (-62.0, 96.0), (-62.0, 90.5), (0.0, 90.5)]
PI_USBC = [(-70.0, -13.0), (18.0, -13.0), (18.0, -5.5), (-45.0, -5.5), (-45.0, 1.5), (-70.0, 1.5)]
# +5V_AUX (U86, 2 A) to J58 / TP32 and down the left side to J51 in the tail: deeproute could not run 0.5 mm that far
AUX_5V = [(-70.0, -158.0), (-40.5, -158.0), (-40.5, -36.9), (-49.0, -36.9), (-49.0, -19.5), (10.0, -19.5),
          (10.0, -13.8), (-70.0, -13.8)]
MAIN_5V = [(-48.6, -36.5), (70.0, -36.5), (70.0, 51.5), (-70.0, 51.5), (-70.0, 1.9), (-44.6, 1.9), (-44.6, -5.1),
           (18.4, -5.1), (18.4, -13.4), (10.4, -13.4), (10.4, -19.9), (-48.6, -19.9)]
# (net, outline, priority): same-net zones that overlap need different priorities (zones_intersect)
IN5_REGIONS = [("MOT_BUS", MOT_BUS_POUR, 0), ("SERVO_RAW", SERVO_RAW_POUR, 0),
               ("SERVO_PWR", rect(-62.0, 96.5, 24.0, 122.0), 0),
               ("+5V", MAIN_5V, 0), ("+5V", rect(34.5, -158.0, 70.0, -35.5), 1),
               ("+5V", rect(12.5, -158.0, 35.5, -121.5), 2),
               ("+3V3_MCU", rect(-40.0, -158.0, 12.0, -121.5), 0),
               ("+5V", rect(-62.0, 122.5, 62.0, 157.0), 0),
               ("+5V", rect(-62.0, 51.0, -0.5, 90.0), 1), ("+5V", rect(30.0, 51.0, 62.0, 123.0), 1),
               ("+5V_PI_USBC", PI_USBC, 0), ("+5V_AUX", AUX_5V, 0)]

# (net, priority): local pours on the outer layers where the net's pads are
POURS = [("BAT_IN", 30), ("BAT_F", 30), ("SW_MID", 30), ("VBUS_RAW", 30), ("MOT_F", 30), ("MOT_SNS_D", 30),
         ("ML_OUT1", 30), ("ML_OUT2", 30), ("MR_OUT1", 30), ("MR_OUT2", 30), ("BRK_D", 30),
         ("SW4", 30), ("SW6", 30), ("SW_TOF", 30), ("BODY_IN", 25), ("STEER_IN", 25), ("+5V_BUCK", 25),
         ("SERVO_BUCK", 25), ("ARM_PWR", 25)]
POUR_MARGIN = 0.6


def hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def pad_corners(bl, net):
    """Pad bounding-box corners of `net` per outer layer, in the board frame, grown by POUR_MARGIN."""
    out = {F: [], B: []}
    for fp in bl.b.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() != net:
                continue
            bb = pad.GetBoundingBox()
            x0, x1 = pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())
            y0, y1 = pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())
            corners = [(x - 150.0, 150.0 - y) for x in (x0 - POUR_MARGIN, x1 + POUR_MARGIN)
                       for y in (y0 - POUR_MARGIN, y1 + POUR_MARGIN)]
            layers = [F, B] if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH else \
                [F] if pad.IsOnLayer(F) else [B]
            for layer in layers:
                out[layer] += corners
    return out


def inside(pt, poly):
    x, y = pt
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def foreign_pads(bl, net, layer, poly):
    n = 0
    for fp in bl.b.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() in (net, "") or not pad.IsOnLayer(layer):
                continue
            p = pad.GetPosition()
            if inside((pcbnew.ToMM(p.x) - 150.0, 150.0 - pcbnew.ToMM(p.y)), poly):
                n += 1
    return n


EDGE_STITCH, EDGE_INSET, EDGE_VIA = 5.0, 0.8, (0.6, 0.3)


def outline_samples(step):
    """Points along the outer outline (gen/outline.json) every `step` mm, with the inward unit normal."""
    segs = json.loads((Path(__file__).resolve().parent / "outline.json").read_text())["segments"]
    pts = []
    for sg in segs:
        a, c = sg["start"], sg["end"]
        if sg["type"] == "line":
            n = max(1, round(math.hypot(c[0] - a[0], c[1] - a[1]) / step))
            for i in range(n):
                t = i / n
                pts.append((a[0] + t * (c[0] - a[0]), a[1] + t * (c[1] - a[1])))
        else:
            m = sg["mid"]
            ax, ay, bx_, by, cx, cy = a[0], a[1], m[0], m[1], c[0], c[1]
            d = 2 * (ax * (by - cy) + bx_ * (cy - ay) + cx * (ay - by))
            ux = ((ax * ax + ay * ay) * (by - cy) + (bx_ * bx_ + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
            uy = ((ax * ax + ay * ay) * (cx - bx_) + (bx_ * bx_ + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx_ - ax)) / d
            r = math.hypot(ax - ux, ay - uy)
            t0, t1, tm = (math.atan2(q[1] - uy, q[0] - ux) for q in (a, c, m))
            sweep = (t1 - t0) % (2 * math.pi)
            if not 0 < (tm - t0) % (2 * math.pi) < sweep:
                sweep -= 2 * math.pi
            n = max(1, round(abs(sweep) * r / step))
            for i in range(n):
                t = t0 + sweep * i / n
                pts.append((ux + r * math.cos(t), uy + r * math.sin(t)))
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1.0
        nx, ny = (-dy / L, dx / L) if area > 0 else (dy / L, -dx / L)
        out.append(((x0 + x1) / 2, (y0 + y1) / 2, nx, ny))
    return out


def edge_plating(bl):
    """Plated board edge tied to GND (owner, 2026-10-11): the GND fills and planes reach the edge (edge_clearance 0 for
    GND in rabbit-body-c.kicad_dru; every other net stays 1.5 mm back = 1 mm ring + 0.5 mm), GND stitching vias every
    EDGE_STITCH mm EDGE_INSET inside the outline (none within 1 mm of a mounting or bracket hole), and the plated edge
    marked for the fab on User.1 (outline copy) with a note on User.Drawings."""
    holes = []
    for fp in bl.b.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                p = pad.GetPosition()
                holes.append((pcbnew.ToMM(p.x) - 150.0, 150.0 - pcbnew.ToMM(p.y), pcbnew.ToMM(pad.GetDrillSize().x) / 2))
    fine = [(x, y) for x, y, _, _ in outline_samples(0.25)]
    n = 0
    for x, y, nx, ny in outline_samples(EDGE_STITCH):
        vx, vy = x + nx * EDGE_INSET, y + ny * EDGE_INSET
        # a point inset from one segment can fall outside the next one at a convex corner: check against the whole edge
        if not inside((vx, vy), fine) or min(math.hypot(vx - px, vy - py) for px, py in fine) < EDGE_INSET - 0.1:
            continue
        if any(math.hypot(vx - hx, vy - hy) < hr + 1.0 + EDGE_VIA[0] / 2 for hx, hy, hr in holes):
            continue
        bl.via("GND", (vx, vy), *EDGE_VIA)
        n += 1
    segs = json.loads((Path(__file__).resolve().parent / "outline.json").read_text())["segments"]
    for sg in segs:
        sh = pcbnew.PCB_SHAPE(bl.b)
        sh.SetLayer(pcbnew.User_1)
        sh.SetWidth(pcbnew.FromMM(0.3))
        if sg["type"] == "line":
            sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
            sh.SetStart(bl.kp(*sg["start"])); sh.SetEnd(bl.kp(*sg["end"]))
        else:
            sh.SetShape(pcbnew.SHAPE_T_ARC)
            sh.SetArcGeometry(bl.kp(*sg["start"]), bl.kp(*sg["mid"]), bl.kp(*sg["end"]))
        bl.b.Add(sh)
    bl.text("PLATED EDGE: all outer edges (User.1), GND; no plating in the cutout", 0.0, -8.0, 1.5, pcbnew.Dwgs_User)
    print("edge plating: GND stitching vias", n)


def apply(bl):
    for layer in (IN1, IN6):
        bl.zone("GND", layer, BOARD_POLY, priority=0, clearance=0.3, thermal=True, name=f"GND_{bl.b.GetLayerName(layer)[:3]}")
        bl.zone("GND_MOT", layer, GND_MOT_ISLAND, priority=10, clearance=0.5, name=f"GND_MOT_{bl.b.GetLayerName(layer)[:3]}")
    bl.zone("VBUS", IN4, BOARD_POLY, priority=0, clearance=0.3, name="VBUS_IN4")
    for net, poly, prio in IN5_REGIONS:
        bl.zone(net, IN5, poly, priority=prio, clearance=0.4, name=f"{net}_IN5")
    kept = []
    for net, prio in POURS:
        for layer, pts in pad_corners(bl, net).items():
            if len(pts) < 3:
                continue
            h = hull(pts)
            pre = foreign_pads(bl, net, layer, h) <= 1   # a pour that traps other nets' pads would wall them off
            tag = "F" if layer == F else "B"
            bl.zone(net, layer, h, priority=prio, clearance=0.3, name=f"{'PRE' if pre else 'POSTFILL'}_{net}_{tag}")
            kept.append((net, tag, pre))
    for poly in getattr(design, "CUTOUTS", []):   # the router's edge clearance covers the outline, not the cutouts
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        # the cutout edge is not plated: the DRU's 1.5 mm plated-edge rule skips items inside this named area, which
        # restricts nothing itself; the router keeps 0.5 mm off the cutout (R190 / R192 sit 0.4 mm from it)
        bl.keepout(rect(min(xs) - 1.5, min(ys) - 1.5, max(xs) + 1.5, max(ys) + 1.5), pours=False, tracks=False,
                   vias=False, layers=("F.Cu", "In2.Cu", "In3.Cu", "B.Cu"), name="zed_cutout")
        bl.keepout(rect(min(xs) - 0.5, min(ys) - 0.5, max(xs) + 0.5, max(ys) + 0.5), pours=False,
                   layers=("F.Cu", "In2.Cu", "In3.Cu", "B.Cu"), name="cutout_keepout")
    for layer, tag in ((F, "F"), (B, "B")):
        bl.zone("GND", layer, BOARD_POLY, priority=0, clearance=0.3, thermal=True, name=f"GND_FILL_{tag}")
    edge_plating(bl)
    assert set(n for n, _ in POURS) <= set(design.nets())
    print("pours before routing:", [f"{n}/{t}" for n, t, p in kept if p])
    print("pours after routing:", [f"{n}/{t}" for n, t, p in kept if not p])
