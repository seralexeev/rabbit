"""Deterministic post-route fixups for rabbit-body-c.kicad_pcb (after fastroute, before the final fill).

Each fix_* function repairs one DRC item of the routed board (data/pcb-route/routed-8L-C3, the 0.15 / 0.15 mm route
of 2026-10-11) by deleting, moving or adding tracks, vias and zone outlines at fixed coordinates in the board frame
(mm, origin at the deck centre, +X right, +Y front). Every function is idempotent: deletions match by net, layer, end
points (and width) and do nothing when the item is already gone; additions skip items that already exist, and copper
that would collide with another net (KiCad shape collision, 0.15 mm) is skipped and reported, never forced.
sync_fields() carries value / LCSC / MPN / BOM changes made in design.py after the route onto the routed board.

Run with KiCad's Python, then gen/fill.sh and gen/drc_summary.py:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 gen/fixups.py [board]
"""
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402

PRJ = Path(__file__).resolve().parents[1]
BOARD = Path(sys.argv[1]) if len(sys.argv) > 1 else PRJ / "rabbit-body-c.kicad_pcb"
OX = OY = 150.0
CLR = 0.15
TOL = 0.02


def kp(X, Y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(OX + X), pcbnew.FromMM(OY - Y))


def bx(v):
    return pcbnew.ToMM(v.x) - OX, OY - pcbnew.ToMM(v.y)


def near(p, X, Y, tol=TOL):
    x, y = bx(p)
    return abs(x - X) <= tol and abs(y - Y) <= tol


class Board:
    def __init__(self, path):
        self.b = pcbnew.LoadBoard(str(path))
        self.log = []
        self.skipped = []
        self.removed = []
        self.cell = pcbnew.FromMM(4.0)
        self.grid = {}
        self.reindex()

    def reindex(self):
        self.grid = {}
        for fp in self.b.GetFootprints():
            for p in fp.Pads():
                self._index(("pad", p, fp.GetReference() + "." + p.GetNumber()), p.GetBoundingBox())
        for t in self.b.GetTracks():
            self._index(("via" if t.GetClass() == "PCB_VIA" else "trk", t, t.GetNetname()), t.GetBoundingBox())

    # ------------------------------------------------------------ spatial index for clearance checks
    def _index(self, item, bb):
        for cx in range(bb.GetLeft() // self.cell, bb.GetRight() // self.cell + 1):
            for cy in range(bb.GetTop() // self.cell, bb.GetBottom() // self.cell + 1):
                self.grid.setdefault((cx, cy), []).append(item)

    def _near(self, bb):
        seen, out = set(), []
        for cx in range(bb.GetLeft() // self.cell, bb.GetRight() // self.cell + 1):
            for cy in range(bb.GetTop() // self.cell, bb.GetBottom() // self.cell + 1):
                for it in self.grid.get((cx, cy), ()):
                    if id(it) not in seen:
                        seen.add(id(it)); out.append(it)
        return out

    def layer(self, name):
        return self.b.GetLayerID(name)

    def conflicts(self, cand, layers, net):
        hits = []
        for lname in layers:
            lid = self.layer(lname)
            cs = cand.GetEffectiveShape()
            cbb = cs.BBox(); cbb.Inflate(pcbnew.FromMM(CLR + 0.05))
            for kind, it, descr in self._near(cbb):
                if it.GetNetname() == net or (kind != "pad" and it.GetNetname() == ""):
                    continue
                if kind == "pad":
                    if not it.IsOnLayer(lid):
                        continue
                    s = it.GetEffectiveShape(lid)
                elif kind == "via":
                    if not it.IsOnLayer(lid):
                        continue
                    s = it.GetEffectiveShape()
                else:
                    if it.GetLayer() != lid:
                        continue
                    s = it.GetEffectiveShape()
                if s.BBox().Intersects(cbb) and s.Collide(cs, pcbnew.FromMM(CLR)):
                    hits.append((lname, descr if kind == "pad" else f"{kind} {it.GetNetname()}", bx(it.GetPosition())))
        return hits

    # ------------------------------------------------------------ queries
    def tracks(self, net, layer=None):
        lid = self.layer(layer) if layer else None
        for t in self.b.GetTracks():
            if t.GetClass() == "PCB_TRACK" and t.GetNetname() == net and (lid is None or t.GetLayer() == lid):
                yield t

    def find_track(self, net, layer, a, c, w=None):
        for t in self.tracks(net, layer):
            if w is not None and abs(pcbnew.ToMM(t.GetWidth()) - w) > 0.01:
                continue
            if (near(t.GetStart(), *a) and near(t.GetEnd(), *c)) or (near(t.GetStart(), *c) and near(t.GetEnd(), *a)):
                return t
        return None

    def find_via(self, net, at):
        for t in self.b.GetTracks():
            if t.GetClass() == "PCB_VIA" and t.GetNetname() == net and near(t.GetPosition(), *at):
                return t
        return None

    # ------------------------------------------------------------ edits
    def remove(self, item, what):
        """Removed C++ objects must leave the index at once (a stale SWIG proxy segfaults in GetEffectiveShape)."""
        if item is not None:
            uid = item.m_Uuid.AsString()
            for cell in self.grid.values():
                cell[:] = [it for it in cell if it[1].m_Uuid.AsString() != uid]
            self.b.Remove(item)
            self.removed.append(item)   # a removed item's proxy must outlive the board, else SWIG's type table breaks
            self.log.append("del " + what)

    def del_track(self, net, layer, a, c, w=None):
        self.remove(self.find_track(net, layer, a, c, w), f"track {net} {layer} {a}->{c}")

    def del_tracks_in(self, net, layer, box):
        x0, y0, x1, y1 = box
        for t in list(self.tracks(net, layer)):
            sx, sy = bx(t.GetStart()); ex, ey = bx(t.GetEnd())
            if x0 <= sx <= x1 and y0 <= sy <= y1 and x0 <= ex <= x1 and y0 <= ey <= y1:
                self.remove(t, f"track {net} {layer} ({sx:.2f},{sy:.2f})->({ex:.2f},{ey:.2f})")

    def del_via(self, net, at):
        self.remove(self.find_via(net, at), f"via {net} {at}")

    def set_width(self, net, layer, a, c, w):
        t = self.find_track(net, layer, a, c)
        if t is not None and abs(pcbnew.ToMM(t.GetWidth()) - w) > 0.001:
            t.SetWidth(pcbnew.FromMM(w))
            self.log.append(f"width {net} {layer} {a}->{c} = {w}")

    def add_track(self, net, layer, a, c, w, check=True):
        if self.find_track(net, layer, a, c) is not None:
            return
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(kp(*a)); t.SetEnd(kp(*c)); t.SetWidth(pcbnew.FromMM(w)); t.SetLayer(self.layer(layer))
        t.SetNet(self.b.FindNet(net))
        if check:
            hits = self.conflicts(t, (layer,), net)
            if hits:
                self.skipped.append(f"track {net} {layer} {a}->{c}: {hits}")
                return
        self.b.Add(t)
        self._index(("trk", t, net), t.GetBoundingBox())
        self.log.append(f"add track {net} {layer} {a}->{c} w{w}")

    def add_path(self, net, layer, pts, w, check=True):
        for a, c in zip(pts, pts[1:]):
            self.add_track(net, layer, a, c, w, check)

    def add_via(self, net, at, d=0.45, drill=0.2, check=True):
        if self.find_via(net, at) is not None:
            return
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(kp(*at)); v.SetDrill(pcbnew.FromMM(drill)); v.SetWidth(pcbnew.FromMM(d))
        v.SetNet(self.b.FindNet(net))
        if check:
            hits = self.conflicts(v, ALL_CU, net)
            if hits:
                self.skipped.append(f"via {net} {at}: {hits}")
                return
        self.b.Add(v)
        self._index(("via", v, net), v.GetBoundingBox())
        self.log.append(f"add via {net} {at} d{d}")

    def zone_rect(self, name, net, old_box, new_box, priority=1):
        """Re-outline the zone `name` of `net` whose bounding box is old_box (x0, y0, x1, y1) to new_box. The zone
        gets `priority` (KiCad reports same-net zones of equal priority that overlap as zones_intersect)."""
        for z in self.b.Zones():
            if z.GetZoneName() != name or z.GetNetname() != net:
                continue
            bb = z.GetBoundingBox()
            cur = (pcbnew.ToMM(bb.GetLeft()) - OX, OY - pcbnew.ToMM(bb.GetBottom()),
                   pcbnew.ToMM(bb.GetRight()) - OX, OY - pcbnew.ToMM(bb.GetTop()))
            if all(abs(a - c) < 0.3 for a, c in zip(cur, new_box)):
                if z.GetAssignedPriority() != priority:
                    z.SetAssignedPriority(priority)
                    self.log.append(f"zone {name} {new_box} priority {priority}")
                return
            if not all(abs(a - c) < 0.3 for a, c in zip(cur, old_box)):
                continue
            z.SetAssignedPriority(priority)
            x0, y0, x1, y1 = new_box
            ol = z.Outline()
            ol.RemoveAllContours()
            ol.NewOutline()
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                ol.Append(kp(x, y))
            z.HatchBorder()
            self.log.append(f"zone {name} {old_box} -> {new_box}")
            return
        raise SystemExit(f"zone {name} {old_box} not found")

    def save(self, path):
        self.b.BuildConnectivity()
        pcbnew.SaveBoard(str(path), self.b)


ALL_CU = ("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu")


# ---------------------------------------------------------------- fixes

def sync_fields(B):
    """Values and part numbers changed in design.py after the route (F1 20 A, R45 220k, lidar R_ILM 1.65k, ...):
    update the footprint fields and the silk labels that carry a value, without rebuilding the board."""
    parts = {p["ref"]: p for p in design.PARTS}
    n = 0
    for fp in B.b.GetFootprints():
        p = parts.get(fp.GetReference())
        if p is None:
            continue
        if fp.GetValue() != p["value"]:
            fp.SetValue(p["value"]); n += 1
        for key, val in (("LCSC", p["lcsc"]), ("MPN", p["mpn"]), ("BOM", p["bom"])):
            if val and fp.HasField(key) and fp.GetFieldByName(key).GetText() != val:
                fp.GetFieldByName(key).SetText(val); n += 1
    labels = {}
    for p in design.PARTS:
        if p.get("label") and p["label"].startswith(p["ref"]):
            labels[p["ref"]] = p["label"]
    for t in B.b.Drawings():
        if t.GetClass() != "PCB_TEXT":
            continue
        txt = t.GetText()
        ref = txt.split(" ")[0]
        if ref in labels and txt != labels[ref] and txt.startswith(ref + " "):
            t.SetText(labels[ref]); n += 1
    if n:
        B.log.append(f"sync_fields: {n} fields / labels updated")


def check_fiducials(B):
    """FID1-FID6 (gen/design.py): no copper of another net within 1.5 mm of the mark on its own layer."""
    for fp in B.b.GetFootprints():
        if not fp.GetReference().startswith("FID"):
            continue
        lid = B.layer("B.Cu" if fp.IsFlipped() else "F.Cu")
        pad = list(fp.Pads())[0]
        ring = pad.GetEffectiveShape(lid)
        rbb = ring.BBox(); rbb.Inflate(pcbnew.FromMM(1.6))
        for kind, it, descr in B._near(rbb):
            if kind == "pad" and it.GetParentFootprint().GetReference() == fp.GetReference():
                continue
            on = it.IsOnLayer(lid) if kind != "trk" else it.GetLayer() == lid
            if on and (it.GetEffectiveShape(lid) if kind == "pad" else it.GetEffectiveShape()).Collide(ring, pcbnew.FromMM(1.5)):
                B.skipped.append(f"fiducial {fp.GetReference()} ring: {kind} {descr} at {bx(it.GetPosition())}")


def fix_5v_nose(B):
    """The nose +5V In5 region (Y > 122.5) is an island behind the SERVO regions; the C2 router left it fed by nothing.
    Keep the link from the right ear: it is skipped when the route already connects the nose or the path is taken."""
    B.add_path("+5V", "In2.Cu", [(42.5, 90.0), (45.5, 93.0), (45.5, 123.5), (45.0, 124.0)], 0.6)
    B.add_via("+5V", (45.0, 124.0), 0.8, 0.4)


FIXES = [sync_fields, fix_5v_nose, check_fiducials]


def main():
    B = Board(BOARD)
    for fix in FIXES:
        n = len(B.log)
        fix(B)
        print(f"{fix.__name__}: {len(B.log) - n} edits")
    B.save(BOARD)
    print("saved", BOARD, "edits", len(B.log), "skipped", len(B.skipped))
    for line in B.log:
        print("  ", line)
    for line in B.skipped:
        print("  SKIPPED", line)


if __name__ == "__main__":
    main()
