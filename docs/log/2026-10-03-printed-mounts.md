# 2026-10-03 Printed mounts for Rabbit 2.0

Offline (the robot was off). Parametric build123d parts for the Rabbit 2.0 sensors, to be printed on a Bambu Lab P2S, with a fit check against the chassis model. Everything is in `cad/brackets/`; the print sheet is `cad/brackets/README.md`; the Russian summary is `reports/2026-10-03-mounts.md`. No robot or Forge code changed.

## Parts

| Part | Holds | Mounts on |
|---|---|---|
| `tof_pair` ×2 | two VL53L8CX on Pololu #3419, yaw ±22°, pitch +15°, 60 mm above the floor | the bumper backbone, 3× M3 from below into inserts |
| `bumper_front`, `bumper_rear` | a compliant bar and two Omron D2F-01L, struck by M3 grub screws | bottom plate edge, 3× M3 into inserts |
| `lidar_mast` | RPLIDAR C1, scan plane 220 mm above the floor | top plate between the ZED and the battery, 2× M3 + 2× M2.5 |
| `power_button_panel` | 16 mm 2NO lit button + 5 mm status LED | the mast's left side |
| `rear_camera_mount` | Camera Module 3 Wide, 142 mm high, 15° down | top plate rear slot, 2× M3 |
| `cable_clip` ×6 | bundles up to 6.5 mm | any 3.2 mm plate hole |

All PETG and support-free, ~6 h of printing in total; the build123d MCP printability analysis leaves only small bridges.

Vendor dimensions used:
- Slamtec C1 datasheet v1.0, fig. 4-1: 55.6 mm base, M2.5 at 43 mm, ≤ 4 mm deep, laser 29.8 mm above the base.
- Pololu #3419 dimension drawing: 12.7 × 22.86 mm, M2 holes 17.78 mm apart.
- Omron D2F datasheet: hinge lever OP 6.8 ± 1.5 mm from the hole line, FP ≤ 10, OT ≥ 0.55, M2 holes 6.5 mm apart.
- Raspberry Pi Camera Module 3 Wide mechanical drawing: M2 holes 21 × 12.5 mm.
- NEEWER PS099E: 111 × 73 × 56.7 mm.
- Alfa AWUS036ACM: 62 × 85.3 × 24 mm.

The PDFs were read from the vendors' sites and not kept in the repo.

## Chassis measurements (from `model/chassis.step`)

- **Plates.** The two kit plates are the same 2 mm part, 120.5 × 269.9 mm, centreline x = 2.48. Their holes are 3.2 mm (M3), 4.3 mm (the M4 corner standoffs), 2.7 mm and 2.5 mm, plus slots.
- **Wheels.** Wheelbase 171.5 mm and rear track 167.4 mm, which match `lib/geometry.py`. Tyres Ø74.9 × 29.2 mm.
- **Steering.** Kingpins at (57.74, −88.38) and (−52.78, −88.38); the wheel centre is 29.27 mm outboard of the kingpin. Steered 40° inward, a front tyre reaches 145.3 mm ahead of the kingpin line (y −145.3), 7 mm beyond the plate's front edge. Anything in front of the plate has to clear that.
- **Floor.** The model is not level: the front tyres touch at z 4.4, the rear ones at 7.0.
- **Frame.** Forward is −Y and the robot's left is +X. The PCB agent's board frame (`pcb/rabbit-body/gen/outline.json`) mirrors X and Y.

## The robot is not the kit

The kit's standoffs are 50 mm, which puts the top plate 75 mm above the floor. The robot's top plate is at ~122 mm: the ZED's optical centre is at 137 mm (`CAMERA_HEIGHT`) and the camera is 30.3 mm tall and sits on the plate; blog photos #142–144 agree. So `assembly.py` lifts the top plate by 46.6 mm. It adds boxes for:
- the ZED (tripod screw in the plate's 9 mm hole 45.9 mm behind the front edge);
- the V-mount plate (estimate);
- the battery.

Placing the ZED that way puts its lens about 10 mm ahead of `CAMERA_TO_REAR_AXLE` (0.1845 m). The ZED field-of-view check also sees the top plate's own front tab at the bottom of the ZED image. The ZED's real position on the plate should be measured; it affects the mast's front clearance (1 mm assumed).

## Decisions

- **ToF pitched 15° up.** At 60 mm the lowest of the 45° rows reaches a flat floor at 0.46 m. The 0–0.4 m zone the ToFs are for has no floor returns, and the safety loop needs no per-zone floor model. Low objects close in (below ~47 mm at 0.1 m) are left to the bumper and, further out, the ZED.
- **Two sensors per holder.** Four single holders did not fit next to the switches and the rear standoffs, so there is one twin holder per end. The rear one is the same print turned 180°.
- **Bumper as one compliant print.**
  - Two guided 40 × 1.25 × 6 mm PETG leaves from a central stub give ~0.7 N/mm; with the D2F's 0.78 N lever a switch trips at ~2 N.
  - Hard stops at 3.5 mm keep the lever from being crushed and the bar off the steered tyres.
  - The leaves stand vertical in the print so the layers run along the bending direction.
  - The switches stand upright on posts with the lever toward the bar. An M3 grub screw in the bar is the adjustable striker, because the lever's operating point varies ±1.5 mm between switches.
- **Scan plane at 220 mm.** The battery top is ~188.7 mm. Over the ~0.19 m to the battery's far corner the C1's scan-field flatness (0–1.5°) drops the plane by up to 5 mm, and the beam has a few mm of height, so ≥ 200 mm is needed. At 220 mm the whole lidar is above the battery (it can slide out), still within the report's 18–22 cm. The robot becomes 231.5 mm tall.
- **Power button on the mast.** There are no two free plate holes beside the mast for a separate box, and the rear strip is needed by the camera. Only the button's wires and the lidar lead go into the plate slots next to the mast foot.
- **No antenna mount.** The Alfa's 19 cm antennas would cross the scan plane (~3° shadow each). Keep the tips below 205 mm or mask the sectors.

## Checks (`cad/brackets/assembly.py`, ~10 min)

The results are in `cad/brackets/renders/fit_report.json`.
- **Screws.** All 12 plate screws land in a measured hole or slot of the right size.
- **Overlaps.** No part or hardware overlaps anything: 7 printed parts, sensors, switches, lidar, button and camera, against each other, the 134 chassis solids and the envelopes. The threshold is 0.5 mm³.
- **Steering.** Tyre envelopes swept about the kingpins in 2.5° steps:
  - to ±35°: the smallest gap to the bumper is 6.8 mm;
  - to ±40°: 4.5 mm, and 7.2 mm for the bar pushed to its stops.
- **Fields of view.** Nothing new in any of them:
  - 4 ToF frustums;
  - the lidar band, ±(3 mm + r·tan 1.5°) over 31–500 mm;
  - the ZED frustum, level and pitched 10° down;
  - the rear camera frustum.

## Footprint change

With the bumpers on, the footprint grows:
- front: 0.2452 m from the rear axle (was 0.2245);
- rear: 0.072 m (was 0.07);
- half width: 0.102 m (was 0.10).

`Footprint` in `lib/safety.py` and `front_overhang` in `lib/planner.py` have to follow when the bumpers are fitted.

## Pitfalls met

- **3MF export.** build123d's `Mesher` refused to write a 3MF ("mesh is invalid") for solids that were valid B-reps but had 0.01 mm sliver faces. These came from unions overlapping by 0.01 mm, or a hole tangent to a face. Overlap by ≥ 0.5 mm inside another solid, or not at all.
- **Insert depth.** The mast foot is 5 mm and an M3 × 5.7 insert needs 6: the first version would have pushed the inserts through the foot. The foot now has bosses there.

## Open

- **PCB-dependent parts.** Done in the update below, except the USB hub bracket.
- **Measurements on the robot.** The list is in the README, "Measure before printing": top plate and battery heights, the ZED and V-mount positions, free plate edges, the button's size.

## Update: the 3-deck stack and the body PCB (same day)

The owner confirmed a 3-deck stack, and the body PCB was finished (`reports/2026-10-03-body-pcb.md`):
- deck 1 is the lower kit plate;
- 45 mm brass standoffs;
- deck 2 is the PCB (bottom 69.8 mm above the floor);
- another 45 mm;
- deck 3 is the upper kit plate (top 118.4 mm).

Heights now use the PCB report's floor (front tyres, deck 1 top 24.8 mm). The assembly rebuilds the stack:
- deck 3 is lifted 41.6 mm from the kit;
- the steering posts are cut to 18 mm under the PCB;
- `pcb/rabbit-body/rabbit-body.step` is the board, all 266 solids, in every check.

What changed and why:
- **V-mount plate is long.** The 2026-10-03 side photo shows the owner's plate from ~26 to ~180 mm from deck 3's rear edge, about 17 mm thick. Its front end sat where the mast foot was (y −70…−33).
  - The mast moved forward into the strip between the ZED and the plate: foot at y −98…−57, screws in the 3.2 mm holes at y −92.55 and the 2.7 mm holes at y −65.96.
  - The battery top is now ~192 mm, so the scan plane went up to **230 mm**: lidar base at 200.2 mm, robot 241.5 mm tall.
  - The ZED is modelled from the same photo, with its back face 23 mm behind deck 3's front edge. That puts the lens ~0.24 m ahead of the rear axle; `CAMERA_TO_REAR_AXLE` says 0.1845, so the ZED position is still a measurement to make.
- **ToF heads under the PCB.** The PCB's nose and tail pass over the ToF pairs, and its edge connectors' pins reach 1.81 mm below the board. The first-run heads came up to ~80 mm above the floor (model), through the board.
  - The boards now lie landscape (head 10 mm lower) and the sensors moved from 60 to 57.8 mm above the floor.
  - The heads moved to ±19 mm and the bumper switches 2 mm outward to make room.
  - Gap to the lowest PCB feature: 3.5 mm front, 2.7 mm rear. The zone grid is turned 90°, so `T_base_tof` needs a 90° roll.
- **New parts from PCB report §10**, all clip-on or glued, since the board has no holes for them:
  - front and rear edge combs for the cables going over the edge to deck 1 (items 8–9);
  - an XT60 strain-relief post at the right edge (item 7);
  - a collar for the 1000 µF C1 (item 6);
  - a TPU grommet for the PCB's ZED cutout (item 11);
  - two TPU grommets for deck 3's 10.3 × 23.9 mm slots, the cable passthroughs between decks: ZED and lidar on the left, the button wires on the right inside the mast foot.
- **Brass, not printed:** 8 × M3 F-F 45 mm, 2 × M3 18 mm for the steering bracket, the Pi and RoboClaw standoffs. They are in the README's "Buy" table.
- **USB hub bracket (§10 item 12) not made.** Waveshare's drawing gives 72.2 × 47.8 × 27.6 mm (86 mm with ears), with ports on both long sides. Under deck 3 that leaves 17.4 mm above the PCB against the ≥ 20 mm §10 asks for. In the suggested place the hub would also cover both deck 3 cable slots and touch the front deck columns, and its plugs need ~35 mm on each long side. It needs a new place; the question is in `docs/open-issues.md`.
- **Camera ribbon.** The PCB report sends it up through deck 3's long slot at y 51, but the V-mount plate covers that slot, so the ribbon goes over deck 3's rear edge.

**Checks after the change:**
- all 12 plate screws match;
- no overlap above 0.5 mm³ among the 13 printed parts, their hardware, the chassis, the PCB and the envelopes;
- steering gaps unchanged (4.5 mm at 40°, 7.2 mm with the bar pushed);
- the ToF, lidar, ZED and rear camera fields are clear.

The first run showed the slot grommets inside the hub bracket; that was one of the reasons to drop the bracket.
