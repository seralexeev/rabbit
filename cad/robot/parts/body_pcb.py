"""The body board (pcb/rabbit-body) as deck 2: its outline from gen/outline.json, the six deck standoff holes,
and the Raspberry Pi 4 on its M2.5 x 6 standoffs at the rev B position.

Board frame (pcb/rabbit-body): origin at the deck centre, +X robot right, +Y robot front, top view.
Chassis frame: x = 2.482 - X, y = -3.427 - Y, i.e. a 180 degree turn about Z.
"""

import json
from pathlib import Path

from build123d import Cylinder, Edge, Face, Pos, Rot, Vector, Wire, extrude, import_step

REPO = Path(__file__).resolve().parents[3]
PCB = REPO / "pcb" / "rabbit-body"
OUTLINE = REPO / "pcb" / "rabbit-body-c" / "gen" / "outline.json"
THICKNESS = 2.0
PI_AT = (13.0, -4.0)
PI_STANDOFF = 6.0


def to_chassis(z_bottom):
    """Location that maps the board frame (z = 0 on the board's bottom face) into the chassis frame."""
    return Pos(2.482, -3.427, z_bottom) * Rot(0, 0, 180)


def board():
    o = json.loads(OUTLINE.read_text())
    edges = []
    for s in o["segments"]:
        a, b = Vector(*s["start"], 0), Vector(*s["end"], 0)
        edges.append(Edge.make_three_point_arc(a, Vector(*s["mid"], 0), b) if s["type"] == "arc" else Edge.make_line(a, b))
    plate = extrude(Face(Wire(edges)), THICKNESS)
    for h in o["mounting_holes"]:
        plate -= Pos(h["x"], h["y"], THICKNESS / 2) * Cylinder(h["d"] / 2, THICKNESS + 1)
    for x, y in ((3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)):
        plate -= Pos(PI_AT[0] + x - 42.5, PI_AT[1] + 28.0 - y, THICKNESS / 2) * Cylinder(1.35, THICKNESS + 1)
    return plate


def raspberry_pi():
    """Pi 4 model from pcb/rabbit-body/3d (its origin is the Pi board centre, bottom face), on 6 mm standoffs."""
    pi = import_step(str(PCB / "3d" / "rpi4.step"))
    return Pos(PI_AT[0], PI_AT[1], THICKNESS + PI_STANDOFF) * pi
