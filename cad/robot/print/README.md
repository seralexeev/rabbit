# Printed parts for the JLC order

Ordered from JLC3DP with the PCB order, so one account and one shipment.

| File | Part | Qty | Process | Notes |
|---|---|---|---|---|
| `tof_bracket.step` / `.stl` | ToF bracket (`parts/tof_mount.py`) | 8 (6 + 2 spare) | MJF, PA12-HP nylon, dyed black | 26 × 9.5 × 25.7 mm, ~2.4 cm³; connector window 12.5 × 7.5 mm for the carrier's GH-6 (11.5 × 6.5). The flange lies under the body board; the face hangs below the board edge, tilted 10° down. STL is exported flange-down. No supports, no inserts. |

## Why MJF PA12

- **Accuracy and walls:** the nut pockets (5.1 mm across flats) and the M2 pilot holes (Ø1.8 mm) need about ±0.2 mm. The thinnest wall is 1.6 mm under the nut pocket, and MJF handles both. FDM is too coarse for the pockets; SLA resin is brittle at the self-tapping screws.
- **Heat:** PA12 holds its shape next to warm electronics, about 90 °C under load. PLA does not.

## How the bracket mounts

1. Put two M2.5 hex nuts into the pockets under the flange.
2. Hold the flange against the bottom of the body board, square to the board's edge. The two holes in the board (footprint `ToF_Bracket_M2.5`, H20–H25) set its heading.
3. Fit two M2.5 × 6 screws from the top of the board. A drop of glue under the flange is optional: the board has no parts under it.
4. Screw the VL53L8CX carrier (`pcb/rabbit-tof`) to the face with two M2 × 5 self-tapping screws for plastics. Its GH-6 plug goes through the window behind it.
5. Run a 100 mm GH-6 cable (pin 1 to pin 1) up to the board's port J60–J65 next to the bracket.

## Hardware (not available at JLC: LCSC, or any AU fastener shop)

| Item | Qty for 6 + spares | Spec |
|---|---|---|
| Screw M2.5 × 6 | 14 | ISO 7380 button head or DIN 912, A2 stainless |
| Hex nut M2.5 | 14 | DIN 934, A2 |
| Self-tapping screw M2 × 5 for plastics | 14 | PT/WN1412 type, pan head |
| JST GH 6-pin cable, 100 mm, same-end (1→1) | 8 | GHR-06V-S housings both ends, 28 AWG |

Poses and the field-of-view check: `pcb/rabbit-body-c/gen/tof.json` and `cad/robot/tof_fov.py`.
