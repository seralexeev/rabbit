"""Shared geometry for the Rabbit 2.0 printed mounts.

Frame: model/chassis.step, millimetres. Forward is -Y, the robot's left is +X, up is +Z.
All chassis numbers below were measured from model/chassis.step (see measure_chassis.py).
Heights "above floor" are z - FLOOR_Z, with the floor where the front tyres touch, as in
docs/reports/2026-10-03-body-pcb.md (deck 1 top 24.8 mm).

Stack (owner, 2026-10-03): deck 1 = lower kit plate; 45 mm brass standoffs; deck 2 = the body PCB
(pcb/rabbit-body/, 1.6 mm); 45 mm standoffs; deck 3 = upper kit plate with the V-mount plate,
the ZED, the lidar mast and the rear camera.
"""

import math
from pathlib import Path

from build123d import (
    Align,
    Axis,
    Box,
    Cylinder,
    Mesher,
    Pos,
    Rot,
    export_step,
    import_brep,
    import_step,
    export_brep,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RENDERS = HERE / "renders"
CACHE = REPO / "data" / "cad" / "chassis"
CHASSIS_STEP = REPO / "model" / "chassis.step"

CX = 2.48
PLATE_T = 2.0
BOTTOM_PLATE_TOP = 29.12
FLOOR_Z = BOTTOM_PLATE_TOP - 24.8
PLATE_FRONT_Y = -138.40
PLATE_REAR_Y = 131.54
TOP_PLATE_TOP_MODEL = 81.12
STANDOFF_1_2 = 45.0
STANDOFF_2_3 = 45.0
PCB_T = 1.6
DECK2_BOTTOM = BOTTOM_PLATE_TOP + STANDOFF_1_2
DECK3_BOTTOM = DECK2_BOTTOM + PCB_T + STANDOFF_2_3
TOP_PLATE_TOP = DECK3_BOTTOM + PLATE_T
TOP_PLATE_TOP_H = TOP_PLATE_TOP - FLOOR_Z
TOP_LIFT = TOP_PLATE_TOP - TOP_PLATE_TOP_MODEL
PCB_STEP = REPO / "pcb" / "rabbit-body" / "rabbit-body.step"
PCB_ORIGIN = (2.482, -3.427)
PCB_PIN_DEPTH = 1.81

KINGPINS = ((57.74, -88.38), (-52.78, -88.38))
KINGPIN_TO_WHEEL = 29.27
WHEEL_R = 37.45
WHEEL_W = 29.2
FRONT_WHEEL_Z = 41.85
REAR_AXLE_Y = 83.15
STEER_LOCK_DESIGN = 35.0
STEER_LOCK_CHECK = 40.0

ZED_SIZE = (175.3, 43.1, 30.3)
ZED_BACK_Y = -115.0
ZED_HFOV, ZED_VFOV = 110.0, 70.0
BATTERY_SIZE = (73.0, 111.0, 56.7)
VPLATE_SIZE = (90.0, 154.0, 17.0)
VPLATE_Y = (-48.0, 106.0)
BATTERY_CENTER_Y = sum(VPLATE_Y) / 2

M3_CLEAR = 3.4
M3_HEAD_D, M3_HEAD_H = 6.2, 3.4
M3_INSERT_D, M3_INSERT_DEPTH = 4.0, 6.0
M2_PILOT = 1.7
M25_CLEAR = 2.9
M25_PILOT = 2.2
FIT = 0.2

TOF_BOARD = (12.7, 22.86, 1.6)
TOF_HOLES = ((3.81, 8.89), (3.81, -8.89))
TOF_HFOV = TOF_VFOV = 45.0

D2F_BODY = (12.7, 6.5, 5.8)
D2F_HOLES_X = (3.1, 9.6)
D2F_HOLE_TO_TOP = 5.0
D2F_HOLE_TO_BOTTOM = 1.5
D2F_FP_MAX = 10.0
D2F_OP = (5.3, 8.3)
D2F_LEVER_TIP_X = 14.4

C1_BASE = 55.6
C1_HOLE_SQUARE = 43.0
C1_HEIGHT = 41.3
C1_BASE_H = 23.1
C1_LASER_H = 29.8
C1_DOME_D = 50.0
C1_SCREW_DEPTH_MAX = 4.0

CAM3_BOARD = (25.0, 23.862, 1.12)
CAM3_HOLES = ((-10.5, -9.931), (10.5, -9.931), (-10.5, 2.569), (10.5, 2.569))
CAM3_LENS = (0.0, 2.469)
CAM3_HFOV, CAM3_VFOV = 102.0, 67.0

BUTTON_HOLE = 16.2
BUTTON_NUT_ACROSS = 21.0
BUTTON_DEPTH = 32.0
LED_HOLE = 5.1


def h(z):
    return z - FLOOR_Z


def z_at(height):
    return height + FLOOR_Z


def cyl(d, length, x=0.0, y=0.0, z=0.0, axis="Z", centered=False):
    align = (Align.CENTER, Align.CENTER, Align.CENTER if centered else Align.MIN)
    c = Cylinder(d / 2, length, align=align)
    if axis == "X":
        c = Rot(0, 90, 0) * c
    elif axis == "Y":
        c = Rot(-90, 0, 0) * c
    return Pos(x, y, z) * c


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def insert_hole(x, y):
    """Heat-set insert hole (M3 x 5.7) entering the bed face z = 0, 6 mm deep."""
    return cyl(M3_INSERT_D, M3_INSERT_DEPTH + 0.5, x, y, -0.5)


def gable(width, length, axis="Y"):
    """45 deg roof prism over a slot of the given width, apex up, base centred on z = 0."""
    s = width / math.sqrt(2)
    roof = Rot(0, 45, 0) * Box(s, length, s) if axis == "Y" else Rot(45, 0, 0) * Box(length, s, s)
    return roof


def counterbored(x, y, z_bottom, z_top, head_depth=M3_HEAD_H):
    return cyl(M3_CLEAR, z_top - z_bottom + 0.2, x, y, z_bottom - 0.1) + cyl(M3_HEAD_D, head_depth + 0.1, x, y, z_top - head_depth)


def load_chassis():
    """Chassis solids as {name: solid}, cached as BREP under data/cad/chassis/."""
    CACHE.mkdir(parents=True, exist_ok=True)
    files = sorted(CACHE.glob("s*.brep"))
    if not files:
        for i, solid in enumerate(import_step(str(CHASSIS_STEP)).solids()):
            export_brep(solid, str(CACHE / f"s{i:03d}.brep"))
        files = sorted(CACHE.glob("s*.brep"))
    return {f.stem: import_brep(str(f)) for f in files}


def plate_holes(plate):
    """Round holes and slots of a plate's top face: [(x, y, sx, sy)]."""
    top = plate.faces().sort_by(Axis.Z)[-1]
    out = []
    for w in top.inner_wires():
        b = w.bounding_box()
        out.append((b.center().X, b.center().Y, b.size.X, b.size.Y))
    return out


def wheel_envelope(center, angle_deg=0.0, pivot=None):
    """Tyre envelope cylinder (axis along X), optionally steered about a vertical kingpin."""
    w = Pos(*center) * (Rot(0, 90, 0) * Cylinder(WHEEL_R, WHEEL_W))
    if pivot is not None and angle_deg:
        w = Pos(pivot[0], pivot[1], 0) * (Rot(0, 0, angle_deg) * (Pos(-pivot[0], -pivot[1], 0) * w))
    return w


def frustum(apex, direction_yaw, pitch, hfov, vfov, length):
    """Rectangular view frustum as a solid: apex point, yaw from -Y toward +X, pitch up, degrees."""
    from build123d import Solid, Vector, Wire, Face, Shell

    hw = length * math.tan(math.radians(hfov / 2))
    hh = length * math.tan(math.radians(vfov / 2))
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    pts = [Vector(u, -length, v) for u, v in corners]
    o = Vector(0, 0, 0)
    faces = [Face(Wire.make_polygon([o, pts[i], pts[(i + 1) % 4]], close=True)) for i in range(4)]
    faces.append(Face(Wire.make_polygon(pts, close=True)))
    solid = Solid(Shell(faces))
    loc = Pos(*apex) * Rot(0, 0, direction_yaw) * Rot(-pitch, 0, 0)
    return loc * solid


def export_part(name, installed, printed):
    """installed: part in the chassis frame; printed: part in its print pose (on z=0)."""
    export_step(installed, str(HERE / f"{name}.step"))
    mesher = Mesher()
    mesher.add_shape(printed, linear_deflection=0.02, angular_deflection=0.2)
    mesher.write(str(HERE / f"{name}.3mf"))


def on_bed(part):
    bb = part.bounding_box()
    return Pos(-bb.center().X, -bb.center().Y, -bb.min.Z) * part


def render(items, out, views=("iso",), size=(1400, 1000), zoom=1.2, focus=None, edges=False):
    """items: [(shape, colour)]. Writes <out>_<view>.png."""
    import numpy as np
    import pyvista as pv

    view_dirs = {
        "iso": ((1.0, -1.2, 0.9), (0, 0, 1)),
        "iso_rear": ((-1.0, 1.2, 0.8), (0, 0, 1)),
        "top": ((0, 0, 1), (0, -1, 0)),
        "side": ((1, 0, 0), (0, 0, 1)),
        "front": ((0, -1, 0), (0, 0, 1)),
        "rear": ((0, 1, 0), (0, 0, 1)),
    }

    def mesh(shape, tol=0.15):
        polys = []
        for solid in shape.solids() or [shape]:
            try:
                verts, tris = solid.tessellate(tol, 0.3)
            except Exception:
                continue
            if not tris:
                continue
            pts = np.array([(v.X, v.Y, v.Z) for v in verts])
            faces = np.hstack([np.full((len(tris), 1), 3), np.array(tris)]).ravel()
            polys.append(pv.PolyData(pts, faces))
        return pv.merge(polys) if polys else None

    meshes = [(m, c) for s, c in items if (m := mesh(s)) is not None]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for view in views:
        direction, up = view_dirs[view]
        pl = pv.Plotter(off_screen=True, window_size=size)
        pl.set_background("white")
        for m, c in meshes:
            pl.add_mesh(m, color=c, smooth_shading=False, specular=0.2, show_edges=edges, edge_color="#555555")
        pl.view_vector(direction, viewup=up)
        if focus is not None:
            pl.reset_camera(bounds=focus)
        else:
            pl.reset_camera()
        pl.camera.zoom(zoom)
        p = out.with_name(f"{out.name}_{view}.png")
        pl.screenshot(str(p))
        pl.close()
        paths.append(p)
    return paths


def label_png(path, title, lines=()):
    """Burn an English title and notes onto a rendered PNG."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(path).convert("RGB")
    d = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 34)
        small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    except OSError:
        big = small = ImageFont.load_default()
    d.rectangle((0, 0, img.width, 66 + 28 * len(lines) + 8), fill="white")
    d.text((24, 18), title, fill="#111111", font=big)
    for i, line in enumerate(lines):
        d.text((24, 66 + 28 * i), line, fill="#333333", font=small)
    img.save(path)


PART_COLOURS = {
    "tof": "#e07b39",
    "bumper": "#3f7fbf",
    "mast": "#4caf50",
    "camera": "#9c27b0",
    "button": "#d32f2f",
    "clip": "#795548",
    "deck": "#c9a227",
    "hardware": "#222222",
    "envelope": "#9e9e9e",
}


def board_to_model(x, y):
    """Body PCB frame (pcb/rabbit-body: +X robot right, +Y forward) to the chassis frame."""
    return PCB_ORIGIN[0] - x, PCB_ORIGIN[1] - y


def pcb_location():
    """Places pcb/rabbit-body/rabbit-body.step (board bottom at z = 0) as deck 2."""
    return Pos(PCB_ORIGIN[0], PCB_ORIGIN[1], DECK2_BOTTOM) * Rot(0, 0, 180)


EDGE_SLOT = PCB_T
EDGE_WALL = 2.0
EDGE_UNDER = 3.5
EDGE_OVER = 1.0
EDGE_FLANGE_T = 1.2


def edge_clip(length):
    """C-clip over a PCB edge. Local frame: edge along X, the board inward at +y,
    board bottom at z = 0. Grips EDGE_UNDER mm under the board (clear of THT pins 4.5 mm in)
    and EDGE_OVER mm on top (clear of edge connectors)."""
    under = box(-length / 2, length / 2, -EDGE_WALL, EDGE_UNDER, -EDGE_FLANGE_T, 0)
    over = box(-length / 2, length / 2, -EDGE_WALL, EDGE_OVER, EDGE_SLOT, EDGE_SLOT + EDGE_FLANGE_T)
    back = box(-length / 2, length / 2, -EDGE_WALL, 0, -EDGE_FLANGE_T, EDGE_SLOT + EDGE_FLANGE_T)
    return under + over + back


def tie_slots(xs, y, z0, z1, width=4.0, gap=1.8):
    """Slots for 3.6 mm cable ties through a flat flange: one per x, long side along x."""
    cuts = None
    for x in xs:
        c = box(x - width / 2, x + width / 2, y - gap / 2, y + gap / 2, z0, z1)
        cuts = c if cuts is None else cuts + c
    return cuts
