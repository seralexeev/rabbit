"""Cable combs that clip onto the front and rear edges of the body PCB (deck 2), PCB report §10 items 8 and 9.

Front: ToF FL/FR (J8, J9) and the front bumper (J13) cables go over the nose edge and down to the
bumper backbone. Rear: encoders (J6, J7), ToF RR (J11), rear bumper (J14) go over the rear edge.
Each comb is a C-clip (3.5 mm under the board, clear of the THT pins 4.5 mm in; 1 mm on top,
clear of the edge connectors) with a 7 mm flange outside the edge carrying cable-tie slots.
The flange is at board level, 2.9 mm above the ToF heads below it.
Print lying on the under-board flange, no supports. Push onto the edge; a drop of CA if loose.

Local frame: edge along X, board inward at +y, board bottom at z = 0.
"""

from build123d import Pos, Rot

from common import (
    CX,
    DECK2_BOTTOM,
    EDGE_FLANGE_T,
    EDGE_SLOT,
    EDGE_WALL,
    PCB_ORIGIN,
    PLATE_FRONT_Y,
    PLATE_REAR_Y,
    box,
    edge_clip,
    export_part,
    on_bed,
    tie_slots,
)

FLANGE = 7.0
COMBS = {
    "front": {"length": 50.0, "ties": (-18.0, -6.0, 6.0, 18.0), "edge_y": PLATE_FRONT_Y, "turn": 0},
    "rear": {"length": 92.0, "ties": (-40.0, -28.0, -16.0, -4.0, 8.0, 20.0, 32.0, 42.0), "edge_y": PLATE_REAR_Y, "turn": 180},
}


def build(end):
    c = COMBS[end]
    half = c["length"] / 2
    part = edge_clip(c["length"])
    part += box(-half, half, -EDGE_WALL - FLANGE, -EDGE_WALL + 0.5, -EDGE_FLANGE_T, EDGE_SLOT + EDGE_FLANGE_T)
    part -= tie_slots(c["ties"], -EDGE_WALL - FLANGE / 2, -EDGE_FLANGE_T - 1, EDGE_SLOT + EDGE_FLANGE_T + 1)
    return part


def installed(end, shape):
    c = COMBS[end]
    return Pos(PCB_ORIGIN[0], c["edge_y"], DECK2_BOTTOM) * Rot(0, 0, c["turn"]) * shape


def main(end):
    p = build(end)
    export_part(f"pcb_comb_{end}", installed(end, p), on_bed(p))
    print(f"pcb_comb_{end}", round(p.volume, 1), p.bounding_box().size, p.is_valid)


if __name__ == "__main__":
    main("front")
    main("rear")
