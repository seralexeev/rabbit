# Rabbit 2.0 printed mounts

Brackets and holders for the Rabbit 2.0 sensors (`docs/reports/2026-10-03-architecture-2.0*.md`) and for the body PCB (`docs/reports/2026-10-03-body-pcb.md` §10), designed for a Bambu Lab P2S (256 × 256 × 256 mm, enclosed). Every part is a build123d script with its parameters at the top; the STEP is the part as installed on the robot (chassis frame), the 3MF is the part in its print orientation, ready for Bambu Studio.

```bash
cd cad/brackets
uv run --project ../../model python tof_pair.py        # any part: writes <part>.step and <part>.3mf
uv run --project ../../model python assembly.py        # fit checks, renders/, rabbit-2.0-mounts.step
```

`assembly.py` imports `model/chassis.step` once (~1 min) and caches it under `data/cad/chassis/` (gitignored); it also reads `pcb/rabbit-body/rabbit-body.step`. A full run takes ~20 min; `--no-render --no-step` gives the checks alone, `--step-only` just the combined STEP. The checks land in `renders/fit_report.json`. The combined STEP (~36 MB, the PCB included) leaves out the kit's fasteners (their modelled threads are ~1 MB each) and shows the tyres as envelopes.

Frame: `model/chassis.step`, mm. Forward is −Y, the robot's left is +X, up is +Z, plate centreline x = 2.48, rear axle y = 83.15. Heights "above the floor" use the floor of the PCB report (front tyres, deck 1 top at 24.8 mm). The PCB's own frame (+X right, +Y forward) maps as x = 2.482 − X, y = −3.427 − Y.

## The stack

| Deck | What | Height above the floor |
|---|---|---|
| 1 | lower kit plate: motors, servo, Jetson, bumpers, ToF pairs | top 24.8 |
| — | 4 × brass M3 F-F 45 mm | |
| 2 | body PCB (`pcb/rabbit-body`), 1.6 mm, all parts on top | bottom 69.8, top 71.4 |
| — | 4 × brass M3 F-F 45 mm on the same columns | |
| 3 | upper kit plate: V-mount plate + battery, ZED, lidar mast, button pod, rear camera | bottom 116.4, top 118.4 |

![assembly](renders/assembly_iso.png)

![deck 2](renders/deck2_iso.png)

## Parts

| Part | Qty | Material | Orientation on the plate | Walls / infill | Supports | Est. time, filament |
|---|---|---|---|---|---|---|
| `tof_pair` (front and rear are the same print) | 2 | PETG | foot down, as exported | 4 walls, 30% gyroid | no | ~50 min, ~15 g each |
| `bumper_front` | 1 | PETG | plate side down, as exported (leaves stand vertical) | 3 walls, 25% gyroid | no | ~1 h 15, ~30 g |
| `bumper_rear` | 1 | PETG | as `bumper_front` | 3 walls, 25% gyroid | no | ~1 h 20, ~32 g |
| `lidar_mast` | 1 | PETG (ASA if the robot works in sun) | foot down | 4 walls, 30% gyroid | no | ~1 h 45, ~38 g |
| `power_button_panel` | 1 | PETG | button face down, as exported | 3 walls, 20% | no | ~35 min, ~11 g |
| `rear_camera_mount` | 1 | PETG | foot down | 4 walls, 30% | no | ~20 min, ~5 g |
| `pcb_comb_front` | 1 | PETG | under-board flange down | 3 walls, 100% | no | ~10 min, 2.5 g |
| `pcb_comb_rear` | 1 | PETG | under-board flange down | 3 walls, 100% | no | ~15 min, 4.5 g |
| `xt60_strain_relief` | 1 | PETG | clip down, post up, as used | 3 walls, 100% | no | ~10 min, 2 g |
| `cap_clamp` | 1 | PETG | standing | 3 walls, 100% | no | ~5 min, 1 g |
| `zed_grommet` | 1 | TPU 95A | flange down | 100% | no | ~5 min |
| `slot_grommet` | 2 | TPU 95A | flange down | 100% | no | ~5 min each |
| `cable_clip` | 6 | PETG | on its side, as exported | 3 walls, 100% | no | ~3 min, 0.5 g each |

Times and weights are estimates from the part volumes; slice for real numbers. Common settings: 0.4 mm nozzle, 0.2 mm layers, Bambu PETG HF profile, textured PEI plate (or glue stick on smooth PEI), no brim needed. TPU: Bambu TPU 95A profile, slow.

**The bumper leaves are the springs.** They are 1.25 mm thick, which is exactly three 0.42 mm lines: keep wall loops at 3 so each leaf is solid perimeters with no infill or gap fill. The leaves stand vertical in the print, so the layers run along the bending direction and do not split. Don't print the bumpers in PLA: the springs creep.

Slicer checks (build123d MCP `analyze_printability`, 45° support angle): no part needs supports. The remaining findings are short bridges: the 4 mm insert holes and the horizontal M2 pilots, the 6 mm screw bores under the lidar platform, the 1 mm lips of the PCB clips, and a 13 mm tilted ceiling plus 5 mm ledges inside each ToF board pocket (hidden behind the board).

### P2S plates

| Plate | Parts | Time |
|---|---|---|
| A, PETG, test fit | 2× `tof_pair`, `rear_camera_mount`, `power_button_panel`, `pcb_comb_front`, `pcb_comb_rear`, `xt60_strain_relief`, `cap_clamp`, 6× `cable_clip` | ~3 h |
| B, PETG | `bumper_front` and `bumper_rear` side by side along X (204 × 35 mm each), `lidar_mast` | ~4 h 20 |
| C, TPU | `zed_grommet`, 2× `slot_grommet` | ~15 min |

## Hardware

### Buy (not printed)

| Item | Qty | Where |
|---|---|---|
| Brass standoff M3 F-F **45 mm**, hex | 8 | deck 1 → PCB and PCB → deck 3, on the four kit columns (PCB report §10, items 1–2); M3 × 6 screws + washers (the plate holes are 4.3 mm) |
| Standoff M3 **18 mm** | 2 | steering bracket to the PCB at the kingpins (§10 item 3; the kit's were 23 mm) |
| Standoff M2.5 × 6 mm + M2.5 × 6 screws | 4 | Raspberry Pi 4 on the PCB (§10 item 4) |
| Standoff M3 × 6 mm + M3 × 6 screws | 4 | RoboClaw on the PCB (§10 item 5) |
| Heat-set inserts M3 × 5.7 (hole 4.0 mm) | 18 + spares | the printed parts below; press at 220–230 °C |
| Cable ties 3.6 mm | ~20 | combs, strain relief, clips |

Screw lengths assume the kit's 2 mm plates.

| Where | Screws | Inserts / nuts |
|---|---|---|
| bumper → deck 1, per bumper | 3× M3 × 8 from under the plate; washer on the one in the 5.4 mm slot (rear) | 3 inserts in the pad |
| ToF pair → bumper backbone, per pair | 3× M3 × 12 from under the backbone | 3 inserts in the foot |
| VL53L8CX board → ToF pair | 2× M2 × 6 self-tapping per board (8 total) | 1.7 mm pilots |
| D2F-01L → bumper switch post | 2× M2 × 10 + M2 washers per switch (8 total) | 1.7 mm pilots |
| bumper striker (one per switch) | M3 × 12 grub screw (4 total) | M3 hex nut in the slot in the bar |
| lidar mast → deck 3 | 2× M3 × 8 (3.2 mm holes) + 2× M2.5 × 10 self-tapping (2.7 mm holes), from under deck 3 | 2 inserts in the foot bosses |
| RPLIDAR C1 → mast | 4× M2.5 × 8 from below; **no more than 4 mm into the lidar** (Slamtec) | — |
| power button pod → mast | 2× M3 × 8, through the access holes in the pod's outer wall | 2 inserts in the mast wall |
| rear camera mount → deck 3 | 2× M3 × 8 + washers, from under deck 3 through the rear slot | 2 inserts in the foot |
| Camera Module 3 Wide → mount | 4× M2 × 6 self-tapping | 1.7 mm pilots |
| cable clip | M3 × 8 + nut each | — |
| PCB combs, XT60 strain relief | push-on; a drop of CA if loose | — |
| C1 collar | CA or hot glue to the board and the capacitor (the board has no holes for it) | — |

## How each part works

### ToF pair (`tof_pair.py`)

Two VL53L8CX on Pololu #3419 carriers (12.7 × 22.86 mm, M2 holes 17.78 mm apart, from Pololu's dimension drawing), one pair per end, on the bumper backbone. Each board is yawed 22° outward (the 2.0 design), so the two 45° × 45° fields cover −44.5…+44.5° around the robot axis, and pitched **15° up**. The sensors are 57.8 mm above the floor, so the lowest zone row meets a flat floor only ~0.44 m away: the 0–0.4 m blind zone the ToFs exist for is free of floor returns. The price is that low things right in front are not seen (at 0.1 m only above ~45 mm, at 0.3 m above ~18 mm); the bumper bar covers 25–49 mm.

**The boards lie landscape** (long side horizontal, the 9-pin row at the bottom). The PCB nose and tail pass over the heads, and its connectors' THT pins reach 1.8 mm below it, so the heads had to come down: the gap from the head tops to the lowest PCB feature is 3.5 mm at the front and 2.7 mm at the rear. The sensor's zone grid is turned 90°, so `T_base_tof` needs that roll.

Boards face out in a pocket sized for wires soldered straight to the pads (no straight headers): the pocket behind the board is 4.5 mm deep. Wires (VIN, GND, SDA, SCL; tie SPI/I2C to GND on the board) drop through the column and leave at the back of the foot. From there they run forward along the foot, out past the PCB edge, up over the edge comb (tie them there) into J8/J9 (front) and J10/J11 (rear). Run them as twisted pairs with ground, ≤ 40 cm (`-wiring.md`).

Poses for `T_base_tof` (from the rear axle, robot frame x forward, y left): front sensors 224.6 mm ahead, ±19 mm off the centreline, yaw ±22°; rear sensors 51.4 mm behind, ±19 mm, yaw 180 ∓ 22°; all 57.8 mm high, pitch +15°, roll 90°.

### Bumpers (`bumper.py`, `bumper_front.py`, `bumper_rear.py`)

One PETG print per end. A pad bolts to deck 1; in front of the plate edge a backbone carries a central stub, from which a 1.25 mm leaf runs 40 mm to each side. The leaf tips carry the bar (204 × 6 × 24 mm, 25–49 mm above the floor) on two posts. A push anywhere on the bar moves it back; an off-centre hit also turns it, which drives the nearer switch further. Spring rate ~0.7 N/mm for the bar (two guided 40 × 1.25 × 6 mm PETG leaves), so a switch trips at ~2 N; at the stops a leaf sees ~16 MPa, a third of PETG's yield.

Each Omron D2F-01L stands upright on a post on the backbone, lever toward the bar, and is struck by an M3 grub screw threaded through a nut trapped in the bar. Hard stops on the backbone end the travel at **3.5 mm**: the lever's operating point is 6.8 ± 1.5 mm and overtravel ≥ 0.55 mm (Omron datasheet), so set each grub screw so its switch clicks after ~1.5 mm of bar travel; the remaining 2 mm is taken by the springy lever. Wire the two NC contacts in series to J13 (front) / J14 (rear).

The bar is set so that, pushed to the stops, it stays clear of the front tyres at full steering lock (see Checks). It sits below the ToF fields of view and far below the ZED's, and the whole bumper is below the PCB.

**The footprint grows:** front 0.2452 m from the rear axle (was 0.2245), rear 0.072 m (was 0.07), half width 0.102 m (was 0.10). `Footprint` in `workspaces/rabbit/src/lib/safety.py` and `front_overhang` in `lib/planner.py` must change when the bumpers go on.

### Lidar mast (`lidar_mast.py`)

RPLIDAR C1 (Slamtec datasheet v1.0, fig. 4-1: 55.6 mm square base, 41.3 mm tall, laser plane 29.8 mm above the base, 4× M2.5 in a 43 mm square, ≤ 4 mm deep). The mast stands on deck 3 in the strip between the ZED and the V-mount plate. The 2026-10-03 side photo shows the owner's V-mount plate running from ~26 mm to ~180 mm from the deck's rear edge, so the mast sits in front of it: lidar centre on the centreline 159.7 mm ahead of the rear axle, foot 40–81 mm behind deck 3's front edge.

**Scan plane: 230 mm above the floor** (lidar base 200.2 mm, mast 81.8 mm, robot top 241.5 mm). Why: deck 3 is at 118.4 mm, the V-mount plate is ~17 mm thick in the photo, and the PS099E is 56.7 mm, so the battery top is ~192 mm. The lidar base sits 8 mm above that, so the pack slides out under it. The plane then clears the battery by 38 mm, far more than the C1's scan-field flatness (0–1.5°, 5 mm at 0.2 m) needs. That is 1 cm above the report's 18–22 cm range, because the real battery stack is taller than the 2.0 report assumed. The check sweeps a band of ±(3 mm + r·tan 1.5°) from 31 to 500 mm around the lidar against every solid of the model, the PCB included: nothing is in it.

The tube is hollow; a 45° flare carries the platform. Screw the C1 on with M2.5 × 8 from below through the 6 mm bores in the flare. Cable: mount the C1 with its cable side forward. The C1's 0° points away from the cable (datasheet v1.0, fig. 2-4), so `T_base_lidar` yaw is 180°, the `rabbit-lidar` default; check the sign on the first scan. Run the lead into the window under the flare at the front, down inside the tube, out through the window at the −X foot and down through the left deck 3 slot (with the ZED cable) to J12 on the PCB nose.

### Power button pod (`power_button_panel.py`)

A pod on the +X (robot-left) side of the mast, on the mast's foot, for a 16 mm two-pole (2NO) momentary metal button with a 5 V ring LED (BOM item 6) and a 5 mm status LED (GPIO19). The button face is 164 mm above the floor and just outboard of the lidar base, so a finger reaches it from above. The pod is open toward the mast and the foot: fit the button and its nut first, then screw the pod to the mast through the access holes in its outer wall. Wires drop through the opening in the mast foot and the right deck 3 slot (with its grommet) to J15/J16 on the PCB nose. For a 19 mm button, set `BUTTON_HOLE = 19.2` and widen the pod (`X1`).

### Rear camera mount (`rear_camera_mount.py`)

Camera Module 3 Wide (official mechanical drawing: board 25 × 23.862 mm, M2 holes 21 × 12.5 mm apart, 2 mm from the edges, lens 14.4 mm above the bottom edge, 102° × 67°). On the rear edge of deck 3, 10 mm behind the V-mount plate. The lens is 138 mm above the floor, 59.6 mm behind the rear axle, pitched 15° down: the floor is visible from ~0.12 m behind the lens, and neither the plate, the bumper nor the ToF pair is in view (checked with the frustum). A window behind the board leaves room for the FPC connector.

The 300 mm ribbon runs down behind the plate, over deck 3's rear edge and down to the Pi's CSI connector. The PCB report routes it up through deck 3's long slot at y 51 instead, but that slot is under the V-mount plate.

### PCB edge combs (`pcb_edge_comb.py`, §10 items 8 and 9)

C-clips that push onto the PCB's front (nose, 50 mm) and rear (92 mm) edges. Each grips 3.5 mm under the board, clear of the edge connectors' THT pins 4.5 mm in, and 1 mm on top, clear of the connector bodies. A 7 mm flange outside the edge carries cable-tie slots for the ToF, bumper and encoder cables that go over the edge to deck 1. The flanges are 2.9 mm above the ToF heads.

### XT60 strain relief (`xt60_strain_relief.py`, §10 item 7)

A clip on the PCB's right edge at board Y −110 with a post outside the edge, rising to 4 mm under deck 3, with three tie slots. Tie the battery lead (from the V-mount plate, down past the right rear corner into J1 from above) to it so a pull never reaches the XT60. The post is 3.7 mm inboard of the rear right tyre.

### C1 collar (`cap_clamp.py`, §10 item 6)

A 10 mm ring around the 1000 µF capacitor (Ø12.5 × 25 mm, standing), open toward J7/J14. Glue it to the board and the can; it stops the can rocking on its leads on impacts.

### Grommets (`zed_grommet.py`, `slot_grommet.py`, §10 item 11 and the deck passthroughs)

TPU 95A, push-in with a snap lip.
- `zed_grommet` lines the PCB's 7.8 × 13.8 mm ZED cutout. It leaves 6.2 × 12.2 mm, enough for the USB-A plug straight through.
- Two `slot_grommet`s line deck 3's 10.3 × 23.9 mm slots at (∓25.7, −70.3), so the aluminium edges don't cut the cables. Left: ZED USB 3 and the lidar lead. Right, inside the mast foot: the button and LED wires.

### Cable clip (`cable_clip.py`)

Snap-in clip for bundles up to 6.5 mm on any 3.2 mm plate hole, M3 screw and nut.

### Not made

- **USB hub bracket (§10 item 12).** Waveshare's outline drawing gives the hub as 72.2 × 47.8 × 27.6 mm, 86 mm with its mounting ears, with ports on both long sides. Under deck 3 it would leave at most 17.4 mm above the PCB, where §10 asks for ≥ 20 mm and the parts below reach 14 mm. In the place §10 suggests (board X −20…20, Y 35…125) it also sits over both deck 3 cable slots and against the front deck columns, and its plugs need ~35 mm on each long side. The hub needs a new place (decision for the owner and the PCB design, `docs/open-issues.md`).
- **Wi-Fi antenna mount.** The Alfa AWUS036ACM is 62 × 85.3 × 24 mm with two RP-SMA jacks on the body, and its 5 dBi antennas are ~19 cm long: upright they would cross the scan plane and shadow ~3° each. Keep the tips below 220 mm (stubby antennas, or tilt them) or mask the sectors in `rabbit-lidar`.
- **Printed spacers between decks:** brass, see "Buy".

## Checks (`assembly.py`)

The model is the kit with the robot's stack rebuilt:
- deck 3 on 45 + 45 mm columns (lifted 41.6 mm from the kit);
- the PCB STEP as deck 2;
- the steering posts cut to 18 mm under the PCB;
- boxes for the ZED 2i (175.3 × 43.1 × 30.3 mm, back face 23 mm behind deck 3's front edge, from the photo), the V-mount plate (90 × 154 × 17 mm, from the photo) and the battery (73 × 111 × 56.7 mm, NEEWER spec).

| Check | Result |
|---|---|
| Every plate screw lands in a measured plate hole or slot of the right size (12 screws) | all 12 match |
| Overlap of every printed part and every piece of hardware with each other, with the 134 chassis solids, with the 266 solids of the PCB STEP and with the envelopes | none above 0.5 mm³ |
| Gap from the deck-1 parts to the PCB and its pins | ToF pairs 3.5 mm (front) / 2.7 mm (rear); ToF boards 5.9 / 4.6 mm; bumpers and switches nowhere near |
| Front tyres (Ø74.9 × 29.2 mm envelopes) steered about the measured kingpins to ±35° and ±40°, against the bumper (bar at rest and pushed 3.5 mm), switches and ToF pair | smallest gap 4.5 mm (bumper at 40°), 7.2 mm for the pushed bar |
| ToF fields (45° × 45°, 0.6 m) against all solids | clear for all four |
| Lidar band (above) | clear |
| ZED 2i field (110° × 70°, 1.5 m, level and pitched 10° down) | clear |
| Rear camera field (102° × 67°, 1 m) | clear |

Renders:
- `renders/assembly_{iso,iso_rear,top,side,front,rear}.png`;
- deck 2 with deck 3 removed: `renders/deck2_{iso,top,side}.png`;
- details: `renders/detail_{front,rear,mast}_*.png`;
- fields of view: `renders/fields_of_view_{iso,side,top}.png`;
- each part alone: `renders/part_*_{iso,iso_rear}.png`.

## Measure before printing

The tracker for these is `docs/open-issues.md` (M-items). Each names the parameter to change.

1. **Column lengths**: 45 + 45 mm, so deck 3 at 118.4 mm. `STANDOFF_1_2`, `STANDOFF_2_3` in `common.py`; the mast height follows.
2. **Battery top** above the floor with the V-mount plate (assumed ~192 mm): must stay below the lidar base (200.2 mm), else raise `LIDAR_PLANE_H`.
3. **Free strip on deck 3 between the ZED and the V-mount plate**: the mast foot covers 40–81 mm behind deck 3's front edge. Assumed from the photo: ZED back face (with the USB plug) at 23 mm, V-mount front at 90 mm.
4. **Rear end of deck 3**: the camera foot needs the last 15.5 mm, ±16 mm of the centre, and the 5.4 mm slot there free; the V-mount plate is assumed to end 25 mm before the rear edge.
5. **Deck 1 front strip**: the 14 mm in front of the steering-servo bracket must be free (slot 4.6 mm and hole 10.85 mm from the front edge). **Rear strip**: free behind the rear corner columns (holes 7 mm from the rear edge).
6. **THT leads under the PCB nose and tail** (J8, J9, J13, J6, J7, J11, J14): trim to ≤ 1.5 mm; the ToF heads are 2.7 mm below the longest ones.
7. **Steering lock**: checked to ±40° about the kit's kingpins. If the real lock is larger, re-run `assembly.py` with `STEER_LOCK_CHECK` raised.
8. **Your power button**: body behind the panel ≤ 37 mm, nut ≤ 21 mm across corners, panel ≥ 2.5 mm allowed.
9. **ToF wiring**: the pocket assumes wires soldered to the pads; straight header pins (6 mm) will not fit.
10. **Camera FPC connector**: the window behind the board is 14 × 16 mm at its centre; check against your module.
