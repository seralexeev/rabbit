"""2D manufacturing drawings (PDF + PNG) for the CNC parts: hidden-line views from build123d,
dimensions and the fit table drawn with matplotlib.

    uv run --project ../../model python drawing.py
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

from build123d import Plane  # noqa: E402

import bracket  # noqa: E402
import coupling  # noqa: E402
from geometry import (  # noqa: E402
    BEARING,
    BORE_BOTTOM,
    BRACKET_FACE,
    BRG1_IN,
    BRG1_OUT,
    BRG2_IN,
    BRG2_OUT,
    CAVITY_D,
    CIRCLIP,
    FLANGE_D,
    FLANGE_SCREW_R,
    FLANGE_T,
    FOOT_BOTTOM,
    FOOT_HOLES,
    FOOT_IN,
    GEAR_FACE,
    HERE,
    HEX_FACE,
    HEX_LEN,
    HOUSING_OUT,
    MOTOR,
    MOTORS,
    OLDHAM_D,
    OLDHAM_SLOT_W,
    PLATE_BOTTOM,
    SHOULDER_D,
    SPIGOT_D,
    SPIGOT_DEPTH,
    STUB_END,
    TUBE_ID,
    WIDTH,
    box,
)

DRAWINGS = HERE / "drawings"
CAMERAS = {
    "front": ((0, -300, 0), (0, 0, 1), lambda p: (p[0], p[2])),
    "inboard": ((-300, 0, 0), (0, 0, 1), lambda p: (-p[1], p[2])),
    "outboard": ((300, 0, 0), (0, 0, 1), lambda p: (p[1], p[2])),
    "top": ((0, 0, 300), (0, 1, 0), lambda p: (p[0], p[1])),
}


def edge_points(e, n=24):
    if e.geom_type.name == "LINE":
        return [e.start_point(), e.end_point()]
    return [e.position_at(i / n) for i in range(n + 1)]


def draw_view(ax, part, cam, section=False, title=""):
    origin, up, _ = CAMERAS[cam]
    shape = part
    if section:
        shape = part & box(-500, 500, 0, 500, -500, 500)
    vis, hid = shape.project_to_viewport(origin, up, (0, 0, 0))
    for e in hid:
        pts = edge_points(e)
        ax.plot([p.X for p in pts], [p.Y for p in pts], color="#9a9a9a", lw=0.5, ls=(0, (3, 2)))
    for e in vis:
        pts = edge_points(e)
        ax.plot([p.X for p in pts], [p.Y for p in pts], color="#111111", lw=0.9)
    if section:
        for f in shape.faces().filter_by(Plane.XZ):
            if abs(f.center().Y) > 1e-3:
                continue
            verts, tris = f.tessellate(0.05)
            for t in tris:
                ax.add_patch(Polygon([(verts[i].X, verts[i].Z) for i in t], closed=True, facecolor="none",
                                     edgecolor="#7a7a7a", hatch="////", lw=0))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=9, loc="left")


def dim(ax, cam, p1, p2, offset, text, vertical=False):
    """Linear dimension between two 3D points in the given view; offset moves the dimension line."""
    f = CAMERAS[cam][2]
    (x1, y1), (x2, y2) = f(p1), f(p2)
    if vertical:
        xd = max(x1, x2) + offset if offset > 0 else min(x1, x2) + offset
        ax.plot([x1, xd], [y1, y1], color="#1f5fa8", lw=0.4)
        ax.plot([x2, xd], [y2, y2], color="#1f5fa8", lw=0.4)
        ax.annotate("", (xd, y1), (xd, y2), arrowprops=dict(arrowstyle="<->", color="#1f5fa8", lw=0.6))
        ax.text(xd + (0.6 if offset > 0 else -0.6), (y1 + y2) / 2, text, fontsize=6.5, color="#1f5fa8", rotation=90,
                ha="left" if offset > 0 else "right", va="center")
    else:
        yd = max(y1, y2) + offset if offset > 0 else min(y1, y2) + offset
        ax.plot([x1, x1], [y1, yd], color="#1f5fa8", lw=0.4)
        ax.plot([x2, x2], [y2, yd], color="#1f5fa8", lw=0.4)
        ax.annotate("", (x1, yd), (x2, yd), arrowprops=dict(arrowstyle="<->", color="#1f5fa8", lw=0.6))
        ax.text((x1 + x2) / 2, yd + (0.5 if offset > 0 else -0.5), text, fontsize=6.5, color="#1f5fa8", ha="center",
                va="bottom" if offset > 0 else "top")


def callout(ax, cam, p, text, dx, dy):
    x, y = CAMERAS[cam][2](p)
    ax.annotate(text, (x, y), (x + dx, y + dy), fontsize=6.5, color="#a83232",
                arrowprops=dict(arrowstyle="-", color="#a83232", lw=0.5))


def sheet(name, title, panels, notes, table):
    fig = plt.figure(figsize=(16.5, 11.7))
    gs = fig.add_gridspec(2, 3, width_ratios=[1.2, 1.0, 1.0], height_ratios=[1.0, 0.85], wspace=0.08, hspace=0.12)
    slots = [gs[0, 0], gs[0, 1], gs[0, 2], gs[1, 0]]
    for slot, panel in zip(slots, panels):
        ax = fig.add_subplot(slot)
        panel(ax)
    ax = fig.add_subplot(gs[1, 1:])
    ax.axis("off")
    y = 1.0
    ax.text(0, y, title, fontsize=13, weight="bold", va="top")
    y -= 0.07
    for line in notes:
        ax.text(0, y, line, fontsize=8, va="top")
        y -= 0.042
    y -= 0.02
    if table:
        t = ax.table(cellText=[r[1:] for r in table], rowLabels=[r[0] for r in table], colLabels=["Feature", "Size / fit", "Tolerance / check"],
                     loc="bottom", cellLoc="left", bbox=[0.0, 0.0, 1.0, max(0.05, y - 0.02)])
        t.auto_set_font_size(False)
        t.set_fontsize(7.2)
    DRAWINGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(DRAWINGS / f"{name}.pdf")
    fig.savefig(DRAWINGS / f"{name}.png", dpi=110)
    plt.close(fig)
    return DRAWINGS / f"{name}.png"


def bracket_sheet():
    b = bracket.bracket("cnc")
    r = WIDTH / 2

    def section(ax):
        draw_view(ax, b, "front", section=True, title="Section A-A (y = 0), from the front; outboard to the right")
        dim(ax, "front", (BRACKET_FACE, 0, -r), (HOUSING_OUT, 0, -r), -8, f"{HOUSING_OUT - BRACKET_FACE:.2f}")
        dim(ax, "front", (FOOT_IN, 0, FOOT_BOTTOM), (BRACKET_FACE, 0, FOOT_BOTTOM), -4, f"{BRACKET_FACE - FOOT_IN:.2f}")
        dim(ax, "front", (FOOT_IN, 0, FOOT_BOTTOM), (FOOT_HOLES[0][0], 0, FOOT_BOTTOM), -9, f"{FOOT_HOLES[0][0] - FOOT_IN:.2f}")
        dim(ax, "front", (BRG2_IN, 0, 13), (HOUSING_OUT, 0, 13), 9, f"{HOUSING_OUT - BRG2_IN:.2f}")
        dim(ax, "front", (BRG1_IN, 0, 13), (BRG1_OUT, 0, 13), 14, f"{BRG1_OUT - BRG1_IN:.2f}")
        dim(ax, "front", (BRG1_OUT, 0, 11), (BRG2_IN, 0, 11), 4, "2.00 +0.02/0")
        dim(ax, "front", (BRACKET_FACE, 0, 15), (BRACKET_FACE + SPIGOT_DEPTH + 0.2, 0, 15), 13, f"{SPIGOT_DEPTH + 0.2:.1f}")
        dim(ax, "front", (HOUSING_OUT, 0, 0), (HOUSING_OUT, 0, FOOT_BOTTOM), 6, f"axis {-FOOT_BOTTOM:.2f}", vertical=True)
        dim(ax, "front", (HOUSING_OUT, 0, PLATE_BOTTOM), (HOUSING_OUT, 0, FOOT_BOTTOM), 14, "4.00", vertical=True)
        callout(ax, "front", (BRG2_IN + 2, 0, BEARING["D"] / 2), "Ø26 J7 (B)", 6, 10)
        callout(ax, "front", (BRG1_IN + 2, 0, BEARING["D"] / 2), "Ø26 J7 (B)", -6, 12)
        callout(ax, "front", (BRG1_OUT + 1, 0, SHOULDER_D / 2), "Ø22", 2, 6)
        callout(ax, "front", (BRACKET_FACE + 1, 0, -SPIGOT_D / 2), "Ø30 H7 (A)", -14, -6)
        callout(ax, "front", (BRACKET_FACE + 4, 0, -CAVITY_D / 2), "Ø28", 4, -6)

    def inboard(ax):
        draw_view(ax, b, "inboard", title="View from inboard (motor side)")
        dim(ax, "inboard", (0, -r, FOOT_BOTTOM), (0, r, FOOT_BOTTOM), -4, f"{WIDTH:.0f}")
        callout(ax, "inboard", (0, -FLANGE_SCREW_R * 0.866, -FLANGE_SCREW_R * 0.5), f"3x M3-6H x 8 (drill 2.5 x 9)\non R{FLANGE_SCREW_R}, 90/210/330 deg", -26, -14)
        callout(ax, "inboard", (0, 0, r), f"R{r:.0f} about axis", 8, 4)

    def top(ax):
        draw_view(ax, b, "top", title="Top view")
        hx, hy0 = FOOT_HOLES[0]
        hy1 = FOOT_HOLES[1][1]
        dim(ax, "top", (hx, hy0, 0), (hx, hy1, 0), -10, f"{hy1 - hy0:.2f}", vertical=True)
        callout(ax, "top", (hx, hy0, 0), "2x slot 4.5 x 6.5 (M4), through", -20, -8)

    def iso_note(ax):
        draw_view(ax, b, "outboard", title="View from outboard (wheel side)")
        callout(ax, "outboard", (0, 0, BEARING["D"] / 2), "bearing seat B, Ø26 J7", 10, 10)

    notes = [
        "Material: aluminium 6061-T6. Finish: bead blast + clear or black anodise (Type II). Break sharp edges 0.2-0.3.",
        "General tolerances ISO 2768-mK. Units mm. One part per side: the right-hand part is the mirror image (STEP: bracket.step is the robot-left part).",
        "Datum A: spigot seat Ø30 H7. Machine Ø30 H7, Ø28 and the inboard bearing seat in one setup; flip and bore the outboard seat to the same axis.",
        "Both bearing seats Ø26 J7 (-0.009/+0.012), coaxial to A within Ø0.02; shoulder width 2.00 +0.02/0 (inner-ring spacer is 2.00 0/-0.02).",
        "Inboard face perpendicular to A within 0.02. Bearings: SKF 61803-2RS1, Loctite 641 on the outer rings.",
        f"Axis height: {-FOOT_BOTTOM:.2f} above the foot bottom ({-PLATE_BOTTOM:.2f} above the foot top, which bears on the underside of deck 1).",
        "Print variant (bracket_print.3mf): same shape, bores +0.10, M3 heat-set inserts Ø4.0 x 6 instead of the tapped holes.",
    ]
    table = [
        ["A", "Spigot seat", "Ø30 H7 (0/+0.021) x 2.2 deep", "datum A"],
        ["B", "Bearing seats x2", "Ø26 J7 (-0.009/+0.012) x 5.0", "coaxial Ø0.02 to A"],
        ["C", "Shoulder", "Ø22, width 2.00 +0.02/0", "faces parallel 0.01"],
        ["D", "Cavity", "Ø28 x to bearing seat", "ISO 2768-m"],
        ["E", "Flange screws", f"3x M3-6H, 8 deep, R{FLANGE_SCREW_R}", "position Ø0.1 to A"],
        ["F", "Foot slots", "2x 4.5 x 6.5, 2 mm travel along y", "26.90 pitch = deck 1 M4 holes"],
        ["G", "Foot top", "flat 0.05", "bears on deck 1"],
    ]
    return sheet("bracket", "Rear drive bracket (6061-T6, CNC) - robot-left part", [section, inboard, top, iso_note], notes, table)


def flange_sheet(key=MOTOR):
    f = bracket.motor_flange(key)
    m = MOTORS[key]
    s = m["screws"]

    def section(ax):
        draw_view(ax, f, "front", section=True, title="Section A-A (y = 0)")
        dim(ax, "front", (GEAR_FACE, 0, 18), (BRACKET_FACE, 0, 18), 5, f"{FLANGE_T:.1f}")
        dim(ax, "front", (BRACKET_FACE, 0, 15), (BRACKET_FACE + SPIGOT_DEPTH, 0, 15), 9, f"{SPIGOT_DEPTH:.1f}")
        callout(ax, "front", (BRACKET_FACE + 1, 0, SPIGOT_D / 2), "Ø30 g6 (A)", 6, 6)
        callout(ax, "front", (GEAR_FACE + 0.5, 0, m["pilot_d"] / 2), f"Ø{m['pilot_d']:.0f} H7 x {m['pilot_h'] + 0.1:.1f} deep (gearhead pilot)", -18, 10)

    def inboard(ax):
        draw_view(ax, f, "inboard", title="View from the gearhead side")
        callout(ax, "inboard", (GEAR_FACE, 0, s["pcd"] / 2), f"{s['n']}x Ø{s['clear']} on Ø{s['pcd']:.0f} ({s['thread']} gearhead screws)", 8, 14)
        callout(ax, "inboard", (GEAR_FACE, -FLANGE_SCREW_R * 0.866, -FLANGE_SCREW_R * 0.5), f"3x Ø3.4 on R{FLANGE_SCREW_R} (M3 to bracket)", -24, -8)
        dim(ax, "inboard", (0, -FLANGE_D / 2, 0), (0, FLANGE_D / 2, 0), 25, f"Ø{FLANGE_D:.0f}")

    def top(ax):
        draw_view(ax, f, "top", title="Top view")

    def blank(ax):
        ax.axis("off")

    notes = [
        f"Motor flange for the {m['label']}.",
        "Material: aluminium 6061-T6, turned + drilled. General tolerances ISO 2768-mK. Break edges 0.2.",
        "Spigot Ø30 g6 (-0.007/-0.020) and pilot pocket coaxial within Ø0.02 (one setup). Flat bottom 0.5 mm above deck 1.",
        f"Gearhead screws: {s['n']}x {s['thread']} DIN 7984 (low head) from the spigot side, Loctite 243.",
        "The other motor's flange: motor_flange_<maker>.step (same outline, different pilot and screw circle).",
    ]
    table = [
        ["A", "Spigot", "Ø30 g6 x 2.0, bore Ø25", "datum A"],
        ["B", "Gearhead pilot pocket", f"Ø{m['pilot_d']:.0f} H7 x {m['pilot_h'] + 0.1:.1f}", "coaxial Ø0.02 to A"],
        ["C", "Gearhead screws", f"{s['n']}x Ø{s['clear']} on Ø{s['pcd']:.0f}", "position Ø0.05 to B"],
        ["D", "Bracket screws", f"3x Ø3.4 on R{FLANGE_SCREW_R} at 90/210/330", "position Ø0.1 to A"],
        ["E", "Faces", "parallel 0.02", "gearhead face perpendicular to A 0.02"],
    ]
    return sheet(f"motor_flange_{key}", f"Motor flange - {key}", [section, inboard, top, blank], notes, table)


def coupling_sheet(key=MOTOR):
    parts = coupling.parts(key)
    m = MOTORS[key]

    def stub(ax):
        draw_view(ax, parts["stub_axle"], "front", section=True, title="Stub axle, section (stainless 303)")
        s = parts["stub_axle"]
        dim(ax, "front", (STUB_END, 0, -8.5), (HEX_FACE + HEX_LEN, 0, -8.5), -6, f"{HEX_FACE + HEX_LEN - STUB_END:.2f}")
        dim(ax, "front", (STUB_END, 0, 8.5), (BRG2_OUT, 0, 8.5), 4, f"{BRG2_OUT - STUB_END:.2f}")
        dim(ax, "front", (BRG1_IN - CIRCLIP["groove_m"], 0, 8.5), (BRG2_OUT, 0, 8.5), 9, f"{BRG2_OUT - BRG1_IN + CIRCLIP['groove_m']:.2f} (groove to shoulder)")
        callout(ax, "front", (BRG2_IN, 0, BEARING["d"] / 2), "Ø17 k5", 2, 8)
        callout(ax, "front", (BRG1_IN - 0.5, 0, CIRCLIP["groove_d"] / 2), "groove Ø16.2 h11 x 1.1 H13 (DIN 471-17)", -16, 12)
        callout(ax, "front", (BORE_BOTTOM + 1, 0, 0), "cross slot 3.5 F7 x 2.3, along z", 6, 12)
        callout(ax, "front", (STUB_END + 2, 0, -TUBE_ID / 2), "bore Ø13 H9", -8, -8)
        callout(ax, "front", (HEX_FACE + 3, 0, -6), "hex 12 h11 A/F x 6, M3-6H x 10 axial", 2, -10)
        return s

    def hub(ax):
        draw_view(ax, parts["oldham_hub"], "front", section=True, title=f"Oldham hub A (stainless 303), bore Ø{m['shaft_d']:.0f} H7")
        callout(ax, "front", (coupling.HUB_FACE - 1, 0, 0), "slot 3.5 F7 x 2.3, along y", 3, 6)
        callout(ax, "front", (coupling.set_screw_x(key), 0, OLDHAM_D / 2), "M3-6H set screw on the flat", 2, 4)

    def disc(ax):
        draw_view(ax, parts["oldham_disc"], "outboard", title="Oldham disc (PEEK), from outboard")
        callout(ax, "outboard", (0, 0, OLDHAM_D / 2 - 1), "tongues 3.48 h7 x 2.0, at 90 deg", 4, 4)

    def spacer(ax):
        draw_view(ax, parts["inner_spacer"], "front", section=True, title="Inner-ring spacer (stainless), 2.00 0/-0.02")

    notes = [
        "Stub axle: stainless 303 (or 17-4PH H1150), turned + milled. Ø17 k5 (+0.001/+0.009) bearing seat, Ra 0.8.",
        "Hex 12 A/F x 6 and the M3 axial thread take the kit wheel exactly as the kit hub did (wheel screw M3 x 8 + washer).",
        "Oldham: hub A on the gearhead shaft, PEEK disc, cross slot in the stub bore; radial float 0.3 mm, slots F7 / tongues h7.",
        f"Hub A: bore Ø{m['shaft_d']:.0f} H7, M3 x 3 cup-point set screw on the shaft flat (Loctite 243), set before the motor goes in.",
        "General tolerances ISO 2768-mK. Coaxiality of Ø17 k5, Ø12 collar and hex within Ø0.02.",
    ]
    table = [
        ["A", "Bearing seat", "Ø17 k5", "datum A, Ra 0.8"],
        ["B", "Shoulder", "Ø19.5 x 0.7", "perpendicular 0.01 to A"],
        ["C", "Circlip groove", "Ø16.2 h11 x 1.1 H13", "outboard flank 12.00 +0.05/0 from B"],
        ["D", "Bore", "Ø13 H9, blind", "coaxial Ø0.05"],
        ["E", "Oldham slot", "3.5 F7 x 2.3", "symmetric 0.02 to A"],
        ["F", "Hex", "12 h11 A/F x 6, M3-6H x 10", "kit wheel"],
        ["G", "Hub A bore", f"Ø{m['shaft_d']:.0f} H7", "slot 3.5 F7, symmetric 0.02"],
    ]
    return sheet(f"coupling_{key}", "Stub axle and Oldham coupling", [stub, hub, disc, spacer], notes, table)


if __name__ == "__main__":
    for p in (bracket_sheet(), flange_sheet("maxon"), flange_sheet("faulhaber"), coupling_sheet()):
        print(p)
