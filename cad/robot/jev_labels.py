"""Second opinion on the kit part names: TypeSafe Jev labels every chassis solid from its geometry.

Reads cad/robot/chassis_parts.json (written by chassis.py), asks Jev one Choice per solid,
writes cad/robot/chassis_jev.json and prints where Jev and the rules in chassis.py disagree.
Needs TYPESAFEAI_API_KEY in the environment.
"""

import json
import os
import sys
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "chassis_parts.json"
OUT = HERE / "chassis_jev.json"
URL = "https://api.typesafe.ai/v1/systemone"

CX, FRONT_AXLE_Y, REAR_AXLE_Y, DECK1_TOP = 2.48, -88.4, 83.15, 29.12

CONTEXT = (
    "A small 4-wheel Ackermann robot car kit (Hiwonder metal chassis), 270 x 120 mm aluminium plates. "
    "Front wheels steer through a servo, knuckles and tie rods; the rear wheels are each driven by a "
    "37 mm offset-gearbox DC motor with a magnetic encoder, held in an L bracket under the lower plate. "
    "Wheels are 75 mm diameter, 29 mm wide. Plates are joined by 50 mm hex standoffs. "
    "Positions: x_from_centre is sideways from the centreline (mm), y is fore-aft with forward negative "
    "(front axle at y = -88, rear axle at y = +83), z_above_deck is height above the top of the lower plate."
)

CATEGORIES = {
    "deck": "A flat chassis plate, about 2 mm thick and over 100 mm long",
    "wheel": "A complete wheel with tyre, about 75 mm diameter",
    "drive_motor": "Part of a rear drive motor: motor can, gearbox, encoder cap or encoder board, near the rear axle",
    "motor_bracket": "Bracket that holds a drive motor to the plate",
    "servo": "The steering servo body or its horn",
    "steering": "Steering mechanism part: knuckle, tie rod, steering arm, linkage, kingpin post or its bracket",
    "hub_or_axle": "Wheel hub, hex coupling, axle, shaft or bearing",
    "standoff": "Spacer column or hex standoff between plates or parts",
    "screw": "Screw or bolt, long and thin",
    "nut_or_washer": "Nut, washer or thin ring",
    "other": "Anything else",
}


def state(row, copies):
    lo, hi = row["min"], row["max"]
    size = [round(h - l, 1) for l, h in zip(lo, hi)]
    c = [(h + l) / 2 for l, h in zip(lo, hi)]
    box = max(size[0] * size[1] * size[2], 1e-6)
    return {
        "size_xyz_mm": size,
        "x_from_centre_mm": round(c[0] - CX, 1),
        "y_mm": round(c[1], 1),
        "z_above_deck_mm": round(c[2] - DECK1_TOP, 1),
        "volume_mm3": row["volume_mm3"],
        "fill_of_bounding_box": round(row["volume_mm3"] / box, 2),
        "identical_copies_in_model": copies,
    }


def ask(row, copies, key):
    body = {
        "model": "jev-latest",
        "state": {"robot": CONTEXT, "solid": state(row, copies)},
        "questions": {
            "category": {
                "type": "choice",
                "instructions": "Which part of the robot kit is `solid`? Use its size, fill of its bounding box, position and number of identical copies.",
                "criteria": CATEGORIES,
            }
        },
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    key = os.environ["TYPESAFEAI_API_KEY"]
    rows = json.loads(MANIFEST.read_text())
    shape = lambda r: (round(r["volume_mm3"]), tuple(sorted(round(h - l) for l, h in zip(r["min"], r["max"]))))
    copies = Counter(shape(r) for r in rows)
    with ThreadPoolExecutor(8) as pool:
        replies = list(pool.map(lambda r: ask(r, copies[shape(r)], key), rows))
    out = []
    for r, rep in zip(rows, replies):
        a = rep["answers"]["category"]
        out.append({"name": r["name"], "group": r["group"], "jev": a.get("choice"), "confidence": a.get("confidence"),
                    "probabilities": a.get("probabilities")})
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(replies[0], indent=1)[:800], file=sys.stderr)
    for o in out:
        if not o["name"].startswith("fastener"):
            print(f'{o["name"]:32} rules={o["group"]:9} jev={o["jev"]:14} conf={o["confidence"]}', file=sys.stderr)


if __name__ == "__main__":
    main()
