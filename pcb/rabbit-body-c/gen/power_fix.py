"""Post-route power reinforcement for the routed board (review round 3, data/pcb-revc/review/round3-power-si.md):
wherever a pad or pour meets a plane through one via, add vias of the net's size around the pad, each landing inside
that net's plane region, and tie pad and vias with a small solid local pour on the pad's layer. GND pads of the
battery return and the bucks' power stages get a solid zone connection and extra GND vias.

Idempotent like gen/fixups.py (existing vias are kept, local pours replaced). Run after fixups, then gen/fill.sh:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 gen/power_fix.py [board]
"""
import math
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixups as F  # noqa: E402
import routing as R  # noqa: E402

BIG, MID, SMALL = (1.0, 0.5), (0.8, 0.4), (0.6, 0.3)


def plane_of(net):
    polys = [poly for n, poly, _ in R.IN5_REGIONS if n == net]
    if net == "VBUS":
        return lambda p: True
    if net == "GND_MOT":
        return lambda p: R.inside(p, R.GND_MOT_ISLAND)
    if net == "GND":
        return lambda p: not R.inside(p, R.GND_MOT_ISLAND)
    if not polys:
        return lambda p: True
    return lambda p: any(R.inside(p, poly) for poly in polys)


def pad(B, ref, num):
    fp = B.b.FindFootprintByReference(ref)
    return next(p for p in fp.Pads() if p.GetNumber() == num)


def add_vias(B, net, centre, n, size, radius=3.0, step=0.25, keep=()):
    """Up to n vias of `size` nearest to `centre` (plane check, no conflicts, ≥ 0.25 mm hole-to-hole)."""
    ok = plane_of(net)
    d, drill = size
    got = []
    k = int(radius / step)
    cand = sorted(((i * step) ** 2 + (j * step) ** 2, (round(centre[0] + i * step, 3), round(centre[1] + j * step, 3)))
                  for i in range(-k, k + 1) for j in range(-k, k + 1))
    for _, p in cand:
        if len(got) >= n:
            break
        if math.hypot(p[0] - centre[0], p[1] - centre[1]) > radius or not ok(p):
            continue
        if any(math.hypot(p[0] - q[0], p[1] - q[1]) < d + 0.25 for q in got + list(keep)):
            continue
        if any(math.hypot(p[0] - x[0], p[1] - x[1]) < (d + vd) / 2 + 0.2 for x, vd in existing_vias(B, net)):
            continue
        n0 = len(B.skipped)
        B.add_via(net, p, d, drill)
        if len(B.skipped) > n0:
            B.skipped.pop()
            continue
        got.append(p)
    B.log.append(f"{net} @{centre}: +{len(got)} vias {d}/{drill}")
    return got


def existing_vias(B, net):
    return [(F.bx(t.GetPosition()), pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu))) for t in B.b.GetTracks()
            if t.GetClass() == "PCB_VIA" and t.GetNetname() == net]


def local_pour(B, name, net, layer, pts, margin=0.9, priority=60):
    for z in list(B.b.Zones()):
        if z.GetZoneName() == name:
            B.b.Remove(z)
            B.removed.append(z)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    z = pcbnew.ZONE(B.b)
    z.SetLayer(B.layer(layer))
    z.SetNet(B.b.FindNet(net))
    ol = z.Outline()
    ol.NewOutline()
    for x, y in ((min(xs) - margin, min(ys) - margin), (max(xs) + margin, min(ys) - margin),
                 (max(xs) + margin, max(ys) + margin), (min(xs) - margin, max(ys) + margin)):
        ol.Append(F.kp(x, y))
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(pcbnew.FromMM(0.25))
    z.SetMinThickness(pcbnew.FromMM(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetZoneName(name)
    B.b.Add(z)
    B.log.append(f"pour {name} {net} {layer}")


def reinforce(B, name, net, ref, num, n, size, layer="F.Cu", radius=3.0):
    p = pad(B, ref, num)
    c = F.bx(p.GetPosition())
    vias = add_vias(B, net, c, n, size, radius)
    near = [x for x, _ in existing_vias(B, net) if math.hypot(x[0] - c[0], x[1] - c[1]) <= radius]
    local_pour(B, name, net, layer, [c] + near)
    return vias


def solid(B, refs_pads):
    for ref, num in refs_pads:
        fp = B.b.FindFootprintByReference(ref)
        if fp is None:
            continue
        for p in fp.Pads():
            if p.GetNumber() == num:
                p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    B.log.append(f"solid zone connection: {len(refs_pads)} pads")


def main():
    B = F.Board(F.BOARD)
    # battery current into the VBUS plane and the three fused taps (M-1, M-2)
    reinforce(B, "PF_VBUS_R1", "VBUS", "R1", "2", 8, BIG, radius=4.0)
    reinforce(B, "PF_VBUS_F2", "VBUS", "F2", "1", 5, BIG, radius=3.5)
    reinforce(B, "PF_VBUS_F4", "VBUS", "F4", "1", 4, BIG, radius=3.5)
    reinforce(B, "PF_VBUS_F3", "VBUS", "F3", "1", 3, BIG, radius=3.5)
    # LM5069 FET into the In5 motor bus (M-3): Q30 source pins 1-3
    reinforce(B, "PF_MOT_BUS_Q30", "MOT_BUS", "Q30", "2", 5, BIG, radius=3.5)
    # motor return: island to NT1, battery minus and the net tie solid (M-4)
    add_vias(B, "GND_MOT", F.bx(pad(B, "NT1", "1").GetPosition()), 6, BIG, radius=1.3)
    solid(B, [("J1", "1"), ("NT1", "1"), ("NT1", "2")])
    # servo rail: buck shunt into In5, In5 into the steering and arm eFuses, steering out (M-5, M-6)
    reinforce(B, "PF_SERVO_RAW_R2", "SERVO_RAW", "R2", "2", 5, BIG, radius=3.5)
    # U83 sits over SERVO_PWR: its input vias go into the SERVO_RAW strip (Y < 96) under one pour with the pin
    c = F.bx(pad(B, "U83", "5").GetPosition())
    v = add_vias(B, "SERVO_RAW", (-32.0, 94.8), 3, BIG, radius=2.5)
    local_pour(B, "PF_SERVO_RAW_U83", "SERVO_RAW", "F.Cu", [c, (-31.62, 95.36)] + v, margin=0.7)
    reinforce(B, "PF_SERVO_RAW_U88", "SERVO_RAW", "U88", "5", 3, BIG, radius=3.0)
    reinforce(B, "PF_SERVO_PWR_U83", "SERVO_PWR", "U83", "6", 3, BIG, radius=3.5)
    # arm rail: the B.Cu jumper between the two halves of the F pour (M-7)
    a, c = (11.17, 71.66), (12.11, 77.22)
    L = math.hypot(c[0] - a[0], c[1] - a[1])
    for t in (1.3 / L, 2.6 / L, 1 - 2.6 / L, 1 - 1.3 / L):     # on the B.Cu jumper itself, so B is joined too
        add_vias(B, "ARM_PWR", (round(a[0] + (c[0] - a[0]) * t, 3), round(a[1] + (c[1] - a[1]) * t, 3)), 1, BIG,
                 radius=0.5)
    # +5V buck shunt into In5 and the Pi eFuse input (M-8, S-9)
    reinforce(B, "PF_5V_R6", "+5V", "R6", "2", 6, MID, radius=3.5)
    reinforce(B, "PF_5V_U87", "+5V", "U87", "5", 3, MID, layer="B.Cu", radius=2.5)
    # LM61495 power-stage grounds (M-9)
    gnd = [(u, n) for u in ("U4", "U6") for n in ("1", "8", "11", "12", "15")]
    gnd += [(f"C{b + i}", "2") for b in (400, 600) for i in (1, 2, 3, 4, 10, 11, 12, 13, 14)]
    solid(B, gnd)
    for ref in ("C401", "C402", "C403", "C404", "C601", "C602", "C603", "C604"):
        add_vias(B, "GND", F.bx(pad(B, ref, "2").GetPosition()), 2, SMALL, radius=1.8)
    for ref in ("C410", "C412", "C414", "C610", "C612", "C614"):
        add_vias(B, "GND", F.bx(pad(B, ref, "2").GetPosition()), 2, SMALL, radius=1.8)
    B.save(F.BOARD)
    print("\n".join(B.log))
    if B.skipped:
        print("skipped:", len(B.skipped))


if __name__ == "__main__":
    main()
