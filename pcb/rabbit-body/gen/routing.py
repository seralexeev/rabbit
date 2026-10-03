"""Hand routing of the power paths, ground planes, keepouts and stitching.

High-current chain (battery -> F1 -> switch -> 2 mOhm shunt -> VBUS -> fuses -> motor shunt -> RoboClaw)
is copper pours on F.Cu and B.Cu (motor return GND_MOT on B.Cu only, tied to GND at the XT60 by NT1).
Branch feeds and regulated outputs are wide tracks. Signals are left to Freerouting.
Widths follow IPC-2152 for 1 oz outer copper and a 10-20 C rise (see docs/reports/2026-10-03-body-pcb.md).
"""
import math

import pcbnew

F, B, IN1, IN2 = pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu

BOARD_POLY = [(-61, -136), (61, -136), (61, 136), (-61, 136)]

# pours: (net, layers, polygon, priority)
POURS = [
    ("BAT_IN", (F, B), [(45.5, -103.0), (54.6, -103.0), (54.6, -86.4), (45.5, -86.4)], 20),
    ("BAT_FUSED", (F, B), [(37.8, -46.1), (43.9, -46.1), (43.9, -72.2), (54.6, -72.2), (54.6, -78.2),
                           (43.9, -78.2), (43.9, -81.0), (40.3, -81.0), (40.3, -54.0), (37.8, -54.0)], 20),
    ("SW_OUT", (F, B), [(50.0, -37.0), (53.7, -37.0), (53.7, -39.6), (57.8, -39.6), (57.8, -53.9),
                        (53.2, -53.9), (53.2, -45.0), (47.4, -45.0), (47.4, -40.0), (50.0, -40.0)], 20),
    ("VBUS", (F, B), [(29.0, -106.6), (36.6, -106.6), (36.6, -45.6), (44.4, -45.6), (44.4, -40.1),
                      (29.0, -40.1)], 20),
    ("MOT_FUSED", (F, B), [(10.4, -106.6), (18.9, -106.6), (18.9, -99.6), (13.3, -99.6), (13.3, -102.45),
                           (10.4, -102.45)], 20),
    ("MOT_BAT", (F,), [(-37.0, -121.4), (7.2, -121.4), (7.2, -102.45), (0.5, -102.45), (0.5, -110.0),
                       (-37.0, -110.0)], 20),
    ("GND_MOT", (B,), [(-28.8, -110.6), (37.0, -110.6), (37.0, -104.0), (43.6, -104.0), (43.6, -116.2),
                       (32.4, -116.2), (32.4, -121.4), (-28.8, -121.4)], 20),
    ("SERVO_6V", (B,), [(33.9, 48.0), (39.8, 48.0), (39.8, 81.5), (20.5, 103.0), (20.5, 111.2), (-8.4, 111.2),
                        (-8.4, 108.2), (14.8, 108.2), (14.8, 101.0), (33.9, 79.0)], 20),
]

# hand tracks: (net, layer, width mm, points)
TRACKS = [
    # branch feeds from the fuse bank, B.Cu lanes under the RoboClaw and the Pi (left to right: body, brain, servo)
    ("BODY_IN", B, 1.5, [(17.25, -93.0), (-18.0, -93.0), (-18.0, -24.0), (-41.48, -24.0), (-41.48, -21.8)]),
    ("BODY_IN", B, 1.0, [(-41.48, -21.8), (-42.74, -19.26)]),
    ("BODY_IN", B, 1.0, [(-41.48, -21.8), (-40.2, -19.26)]),
    ("BRAIN_IN", B, 1.5, [(17.25, -83.0), (-15.5, -83.0), (-15.5, 24.4), (-33.0, 24.4), (-33.0, 36.2),
                          (-15.73, 36.2), (-15.73, 39.07)]),
    ("STEER_IN", B, 1.5, [(17.25, -73.0), (-13.0, -73.0), (-13.0, 24.4), (34.6, 24.4), (34.6, 36.2),
                          (18.27, 36.2), (18.27, 39.07)]),
    ("HUB_PWR", F, 1.2, [(17.25, -61.3), (5.0, -61.3), (5.0, -58.0)]),
    ("RES_PWR", F, 1.5, [(17.25, -51.3), (4.0, -51.3), (4.0, -48.0)]),
    # 5 V to the Pi header pins 2 and 4 (Pi ~2 A)
    ("+5V", F, 2.0, [(-41.48, 13.8), (-41.48, 19.0), (-31.0, 29.5), (-31.0, 33.9), (-18.59, 33.9),
                     (-18.59, 31.27)]),
    ("+5V", F, 1.2, [(-21.13, 33.9), (-21.13, 31.27)]),
    ("+5V", F, 1.0, [(-41.48, 13.8), (-42.74, 11.26)]),
    ("+5V", F, 1.0, [(-41.48, 13.8), (-40.2, 11.26)]),
    # Jetson 12 V: regulator -> 10 mOhm shunt -> XT30
    ("12V_RAW", F, 1.5, [(-23.35, 39.07), (-23.35, 37.0), (-32.0, 37.0), (-35.95, 41.2), (-35.95, 43.95)]),
    ("12V_RAW", F, 1.0, [(-23.35, 39.07), (-23.35, 41.61)]),
    ("JET_12V", F, 1.5, [(-35.95, 50.05), (-35.95, 72.0), (-27.5, 72.0)]),
    # servo 6 V: regulator -> 10 mOhm shunt (then the B.Cu pour)
    ("6V_RAW", F, 2.0, [(10.65, 39.07), (10.65, 36.7), (32.0, 36.7), (35.05, 39.8), (35.05, 43.95)]),
    ("6V_RAW", F, 1.0, [(10.65, 39.07), (10.65, 41.61)]),
    # star: motor return joins GND at the battery connector
    ("GND_MOT", F, 3.5, [(39.5, -106.5), (39.5, -112.0)]),
    ("SERVO_6V", F, 2.0, [(35.05, 50.05), (35.05, 52.4)]),
    ("GND", F, 3.5, [(43.5, -106.5), (47.0, -106.5)]),
]

VIAS = [
    ("GND_MOT", [(x, y) for x in (38.1, 39.5, 40.9) for y in (-108.9, -110.3, -111.7)], 0.8, 0.4),
    ("SERVO_6V", [(34.0, 51.6), (35.6, 51.6), (34.0, 53.2), (35.6, 53.2)], 0.8, 0.4),
]

# copper keepouts around the deck standoffs (washers / nuts) and the Pi / RoboClaw screws
STANDOFF_KEEPOUT = 4.6


def circle(x, y, r, n=20):
    return [(x + r * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def inside(poly, x, y):
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def obstacles(bl):
    out = []
    for fp in bl.b.GetFootprints():
        for p in fp.Pads():
            x = pcbnew.ToMM(p.GetPosition().x) - 150
            y = 150 - pcbnew.ToMM(p.GetPosition().y)
            r = max(pcbnew.ToMM(p.GetSize().x), pcbnew.ToMM(p.GetSize().y)) / 2
            out.append((x, y, r, p.GetNetname()))
    return out


def stitch(bl, net, poly, pitch=3.0, margin=1.6):
    obs = obstacles(bl)
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    x = min(xs) + 1.2
    n = 0
    while x < max(xs) - 1.0:
        y = min(ys) + 1.2
        while y < max(ys) - 1.0:
            ok = inside(poly, x, y) and all(
                inside(poly, x + dx, y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            if ok:
                for ox, oy, r, onet in obs:
                    lim = r + (0.9 if onet == net else margin)
                    if (ox - x) ** 2 + (oy - y) ** 2 < lim * lim:
                        ok = False
                        break
            if ok:
                for tnet, layer, w, pts in TRACKS:
                    if tnet == net:
                        continue
                    for (ax, ay), (cx, cy) in zip(pts, pts[1:]):
                        if seg_dist(x, y, ax, ay, cx, cy) < w / 2 + 0.4 + 0.4:
                            ok = False
                            break
                    if not ok:
                        break
            if ok:
                bl.via(net, (x, y), 0.8, 0.4)
                n += 1
            y += pitch
        x += pitch
    return n


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


# INA4235 (U3, rot 0): fan-out of the 0.4 mm DSBGA. Outer balls escape on 0.1 mm stubs to vias,
# inner balls join neighbours of the same net diagonally (EN B3 -> VS A4, A0 C2 -> B3, A1 C3 -> GND B4);
# ALERT (B2) stays unconnected: it cannot escape without via-in-pad.
INA_AT = (22.0, -41.5)
INA_FANOUT = {"A1": (-1.6, -1.6), "A2": (-0.55, -2.3), "A3": (0.55, -2.3), "A4": (1.6, -1.6),
              "B1": (-2.3, -0.55), "C1": (-2.3, 0.55), "B4": (2.3, -0.55), "C4": (2.3, 0.55),
              "D1": (-1.6, 1.6), "D2": (-0.55, 2.3), "D3": (0.55, 2.3), "D4": (1.6, 1.6)}
INA_DIAG = [("B3", "A4"), ("C2", "B3"), ("C3", "B4")]


def ina_ball(name):
    r = "ABCD".index(name[0]); c = int(name[1]) - 1
    return (-0.6 + 0.4 * c, -0.6 + 0.4 * r)


def ina_fanout(bl):
    import design
    pins = next(p for p in design.PARTS if p["ref"] == "U3")["pins"]
    ax, ay = INA_AT
    to_board = lambda lx, ly: (ax + lx, ay - ly)
    for ball, (vx, vy) in INA_FANOUT.items():
        net = pins[ball]
        bx, by = ina_ball(ball)
        bl.track(net, [to_board(bx, by), to_board(vx, vy)], 0.1, F)
        bl.via(net, to_board(vx, vy), 0.6, 0.3)
    for a, c in INA_DIAG:
        bl.track(pins[a], [to_board(*ina_ball(a)), to_board(*ina_ball(c))], 0.1, F)


def link_duplicate_pads(bl):
    """Join pads that share a number and a power net (fuse clip pairs, regulator pin pairs) with a short track."""
    import design
    nets = set(design.POWER_HI + design.POWER_MID) - {p[0] for p in POURS}
    n = 0
    for ref, fp in bl.fps.items():
        groups = {}
        for p in fp.Pads():
            if p.GetNetname() in nets and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                groups.setdefault((p.GetNumber(), p.GetNetname()), []).append(
                    (pcbnew.ToMM(p.GetPosition().x) - 150, 150 - pcbnew.ToMM(p.GetPosition().y)))
        for (num, net), pts in groups.items():
            pts.sort()
            for a, c in zip(pts, pts[1:]):
                if math.dist(a, c) < 3.6:
                    bl.track(net, [a, c], 1.0, F)
                    n += 1
    return n


def gnd_fanout(bl):
    """Via to the In1 ground plane next to every SMD ground pad."""
    n = 0
    for ref, fp in bl.fps.items():
        cx = pcbnew.ToMM(fp.GetPosition().x) - 150
        cy = 150 - pcbnew.ToMM(fp.GetPosition().y)
        for p in fp.Pads():
            if p.GetNetname() != "GND" or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or ref in ("U3", "NT1"):
                continue
            if ref == "BT1":   # CR1220 contact pad: two vias inside the pad
                x = pcbnew.ToMM(p.GetPosition().x) - 150
                y = 150 - pcbnew.ToMM(p.GetPosition().y)
                for ox in (-2.0, 2.0):
                    bl.via("GND", (x + ox, y), 0.6, 0.3)
                continue
            x = pcbnew.ToMM(p.GetPosition().x) - 150
            y = 150 - pcbnew.ToMM(p.GetPosition().y)
            bb = p.GetBoundingBox()
            w = pcbnew.ToMM(bb.GetWidth()); h = pcbnew.ToMM(bb.GetHeight())
            dx, dy = x - cx, y - cy
            if w > 1.3 * h or (h <= 1.3 * w and abs(dx) * h >= abs(dy) * w):   # leave along the pad's long axis
                vx, vy = x + math.copysign(w / 2 + 0.55, dx or 1), y
            else:
                vx, vy = x, y + math.copysign(h / 2 + 0.55, dy or 1)
            bl.track("GND", [(x, y), (vx, vy)], 0.4, F)
            bl.via("GND", (vx, vy), 0.6, 0.3)
            n += 1
    return n


def apply(bl):
    import design
    # ground: solid In1, GND fill on the other layers at the lowest priority
    bl.zone("GND", IN1, BOARD_POLY, 0, 0.35, 0.25, thermal=True, name="GND_IN1")
    for layer, nm in ((F, "F"), (B, "B"), (IN2, "In2")):
        bl.zone("GND", layer, BOARD_POLY, 0, 0.35, 0.3, thermal=True, name=f"GND_FILL_{nm}")
    ina_fanout(bl)
    print("duplicate pad links", link_duplicate_pads(bl), "GND fan-out vias", gnd_fanout(bl))
    for net, layers, poly, pri in POURS:
        for layer in layers:
            bl.zone(net, layer, poly, pri, 0.35, 0.3, thermal=False, name=f"{net}_{layer}")
    for net, layer, w, pts in TRACKS:
        bl.track(net, pts, w, layer)
    for net, pts, d, drill in VIAS:
        for at in pts:
            bl.via(net, at, d, drill)
    total = 0
    for net, layers, poly, pri in POURS:
        if len(layers) > 1:
            total += stitch(bl, net, poly)
    # keep signal tracks out of the single-layer power pours so they stay in one piece
    for net, layers, poly, pri in POURS:
        bl.keepout(poly, tuple(bl.b.GetLayerName(l) for l in layers), tracks=True, vias=False, pours=False)
    # the cable cut-outs are holes in the board: keep everything (incl. the autorouter) out with a margin
    for poly in design.CUTOUTS:
        xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
        m = 0.35
        bl.keepout([(min(xs) - m, min(ys) - m), (max(xs) + m, min(ys) - m), (max(xs) + m, max(ys) + m),
                    (min(xs) - m, max(ys) + m)])
    # keepouts
    for p in design.PARTS:
        if p["ref"].startswith("H"):
            x, y = p["at"]
            bl.keepout(circle(x, y, STANDOFF_KEEPOUT), ("F.Cu", "B.Cu"))
    pi = bl.fps["MOD1"]
    for pad in pi.Pads():
        x = pcbnew.ToMM(pad.GetPosition().x) - 150; y = 150 - pcbnew.ToMM(pad.GetPosition().y)
        bl.keepout(circle(x, y, 2.9), ("F.Cu", "B.Cu"))
    for pad in bl.fps["U1"].Pads():
        x = pcbnew.ToMM(pad.GetPosition().x) - 150; y = 150 - pcbnew.ToMM(pad.GetPosition().y)
        bl.keepout(circle(x, y, 3.4), ("F.Cu", "B.Cu"))
    print("stitching vias", total)
