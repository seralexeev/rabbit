# Rabbit 2.0 printed mounts

Brackets and holders for the Rabbit 2.0 sensors (`docs/reports/2026-10-03-architecture-2.0*.md`), designed for a Bambu Lab P2S (256 × 256 × 256 mm, enclosed). Every part is a build123d script with its parameters at the top; the STEP is the part as installed on the robot (chassis frame), the 3MF is the part in its print orientation, ready for Bambu Studio.

```bash
cd cad/brackets
uv run --project ../../model python tof_pair.py        # any part: writes <part>.step and <part>.3mf
uv run --project ../../model python assembly.py        # fit checks, renders/, rabbit-2.0-mounts.step
```

`assembly.py` imports `model/chassis.step` once (~1 min) and caches it under `data/cad/chassis/` (gitignored). A full run takes ~15 min; `--no-render --no-step` gives the checks alone, `--step-only` just the combined STEP. The checks land in `renders/fit_report.json`. The combined STEP (~19 MB) leaves out the kit's fasteners (their modelled threads are ~1 MB each) and shows the tyres as envelopes.

Frame: `model/chassis.step`, mm. Forward is −Y, the robot's left is +X, up is +Z, plate centreline x = 2.48, rear axle y = 83.15, floor z ≈ 5.7.

![assembly](renders/assembly_iso.png)

## Parts

| Part | Qty | Material | Orientation on the plate | Walls / infill | Supports | Est. time, filament |
|---|---|---|---|---|---|---|
| `tof_pair` (front and rear are the same print) | 2 | PETG | foot down, as exported | 4 walls, 30% gyroid | no | ~45 min, ~14 g each |
| `bumper_front` | 1 | PETG | plate side down, as exported (leaves stand vertical) | 3 walls, 25% gyroid | no | ~1 h 15, ~30 g |
| `bumper_rear` | 1 | PETG | as `bumper_front` | 3 walls, 25% gyroid | no | ~1 h 20, ~32 g |
| `lidar_mast` | 1 | PETG (ASA if the robot works in sun) | foot down | 4 walls, 30% gyroid | no | ~1 h 30, ~35 g |
| `power_button_panel` | 1 | PETG | button face down, as exported | 3 walls, 20% | no | ~30 min, ~9 g |
| `rear_camera_mount` | 1 | PETG | foot down | 4 walls, 30% | no | ~20 min, ~5 g |
| `cable_clip` | 6 | PETG | on its side, as exported | 3 walls, 100% | no | ~3 min, 0.5 g each |

Times and weights are estimates from the part volumes; slice for real numbers. Common settings: 0.4 mm nozzle, 0.2 mm layers, Bambu PETG HF profile, textured PEI plate (or glue stick on smooth PEI), no brim needed.

**The bumper leaves are the springs.** They are 1.25 mm thick, which is exactly three 0.42 mm lines: keep wall loops at 3 so each leaf is solid perimeters with no infill or gap fill. The leaves stand vertical in the print, so the layers run along the bending direction and do not split. Don't print the bumpers in PLA: the springs creep.

Slicer checks (build123d MCP `analyze_printability`, 45° support angle): no part needs supports. The remaining findings are small bridges: the 4 mm insert holes and the horizontal M2 pilots, the 6 mm screw bores under the lidar platform, and a 5 mm ledge inside each ToF board pocket (hidden behind the board).

### P2S plates

Everything fits one plate (tallest part 68 mm, widest 204 mm), ~6 h. Two plates are better, so the small parts can be test-fitted first:

| Plate | Parts | Time |
|---|---|---|
| A, test fit | 2× `tof_pair`, `rear_camera_mount`, `power_button_panel`, 6× `cable_clip` | ~2 h 30 |
| B | `bumper_front` and `bumper_rear` side by side along X (204 × 35 mm each), `lidar_mast` | ~4 h |

## Hardware

Heat-set inserts: M3 × 5.7 mm (Ruthex-type, hole 4.0 mm, 6 mm deep). Press them in at 220–230 °C. Screw lengths assume the kit's 2 mm plates.

| Where | Screws | Inserts / nuts |
|---|---|---|
| bumper → bottom plate, per bumper | 3× M3 × 8 from under the plate; washer on the one in the 5.4 mm slot (rear) | 3 inserts in the pad |
| ToF pair → bumper backbone, per pair | 3× M3 × 12 from under the backbone | 3 inserts in the foot |
| VL53L8CX board → ToF pair | 2× M2 × 6 self-tapping per board (8 total) | 1.7 mm pilots |
| D2F-01L → bumper switch post | 2× M2 × 10 + M2 washers per switch (8 total) | 1.7 mm pilots |
| bumper striker (one per switch) | M3 × 12 grub screw (4 total) | M3 hex nut in the slot in the bar |
| lidar mast → top plate | 2× M3 × 8 (3.2 mm holes) + 2× M2.5 × 10 self-tapping (2.7 mm holes), from under the top plate | 2 inserts in the foot bosses |
| RPLIDAR C1 → mast | 4× M2.5 × 8 from below; **no more than 4 mm into the lidar** (Slamtec) | — |
| power button pod → mast | 2× M3 × 8, through the access holes in the pod's outer wall | 2 inserts in the mast wall |
| rear camera mount → top plate | 2× M3 × 8 + washers, from under the top plate through the rear slot | 2 inserts in the foot |
| Camera Module 3 Wide → mount | 4× M2 × 6 self-tapping | 1.7 mm pilots |
| cable clip | M3 × 8 + nut each | — |

Totals: 18 M3 inserts (+ spares), 4 M3 × 12 grub screws and 4 M3 nuts, M2 × 6 ×12, M2 × 10 ×8.

## How each part works

### ToF pair (`tof_pair.py`)

Two VL53L8CX on Pololu #3419 carriers (12.7 × 22.86 mm, M2 holes 17.78 mm apart, from Pololu's dimension drawing), one pair per end, on the bumper backbone. Each board is yawed 22° outward (the 2.0 design), so the two 45° × 45° fields cover −44.5…+44.5° around the robot axis, and pitched **15° up**. The sensors are 60 mm above the floor, so the lowest zone row meets a flat floor only ~0.46 m away: the 0–0.4 m blind zone the ToFs exist for is free of floor returns, which was open question 9 in the report. The price is that low things right in front are not seen (at 0.1 m only above ~47 mm, at 0.3 m above ~20 mm); the bumper bar covers 23–47 mm.

Boards face out in a pocket sized for wires soldered straight to the pads (no straight headers): the pocket behind the board is 4.5 mm deep. Wires (VIN, GND, SDA, SCL; tie SPI/I2C to GND on the board) drop through the column and leave at the back of the foot; run them as twisted pairs with ground, ≤ 40 cm (`-wiring.md`).

Poses for `T_base_tof` (from the rear axle, robot frame x forward, y left): front sensors 224.6 mm ahead, ±16 mm off the centreline, yaw ±22°; rear sensors 51.4 mm behind, ±16 mm, yaw 180 ∓ 22°; all 60 mm high, pitch +15°.

### Bumpers (`bumper.py`, `bumper_front.py`, `bumper_rear.py`)

One PETG print per end. A pad bolts to the bottom plate; in front of the plate edge a backbone carries a central stub, from which a 1.25 mm leaf runs 40 mm to each side. The leaf tips carry the bar (204 × 6 × 24 mm, 23–47 mm above the floor) on two posts. A push anywhere on the bar moves it back; an off-centre hit also turns it, which drives the nearer switch further. Spring rate ~0.7 N/mm for the bar (two guided 40 × 1.25 × 6 mm PETG leaves), so a switch trips at ~2 N; at the stops a leaf sees ~16 MPa, a third of PETG's yield.

Each Omron D2F-01L stands upright on a post on the backbone, lever toward the bar, and is struck by an M3 grub screw threaded through a nut trapped in the bar. Hard stops on the backbone end the travel at **3.5 mm**: the lever's operating point is 6.8 ± 1.5 mm and overtravel ≥ 0.55 mm (Omron datasheet), so set each grub screw so its switch clicks after ~1.5 mm of bar travel; the remaining 2 mm is taken by the springy lever. Wire the two NC contacts in series (`-wiring.md`).

The bar is set so that, pushed to the stops, it stays clear of the front tyres at full steering lock (see Checks). It sits below the ToF fields of view and far below the ZED's.

**The footprint grows:** front 0.2452 m from the rear axle (was 0.2245), rear 0.072 m (was 0.07), half width 0.102 m (was 0.10). `Footprint` in `workspaces/rabbit/src/lib/safety.py` and `front_overhang` in `lib/planner.py` must change when the bumpers go on.

### Lidar mast (`lidar_mast.py`)

RPLIDAR C1 (Slamtec datasheet v1.0, fig. 4-1: 55.6 mm square base, 41.3 mm tall, laser plane 29.8 mm above the base, 4× M2.5 in a 43 mm square, ≤ 4 mm deep). The mast stands on the top plate between the ZED and the battery, lidar centre on the centreline 134.2 mm ahead of the rear axle.

**Scan plane: 220 mm above the floor** (lidar base 190.2 mm, robot top 231.5 mm). Why: the highest thing on the robot is the battery at ~188.7 mm (top plate 122 + V-mount plate ~10 + PS099E 56.7). Over the ~0.19 m to the far corner of the battery the C1's scan-field flatness (0–1.5°) can drop the plane by 5 mm, and the beam has a few mm of height, so the plane needs ≥ ~200 mm. 220 mm also puts the whole lidar above the battery, so the pack can slide out under it, and is at the top of the 18–22 cm range in the report. The check sweeps a band of ±(3 mm + r·tan 1.5°) from 31 to 500 mm around the lidar against every solid of the model: nothing is in it.

The tube is hollow; a 45° flare carries the platform. Screw the C1 on with M2.5 × 8 from below through the 6 mm bores in the flare. Cable: mount the C1 with its cable/arrow side forward (then `T_base_lidar` yaw is 0; check the sign on the first scan), run the lead into the window under the flare at the front, down inside the tube and out through the window at the −X foot into the plate slot at (−25.7, −70.3).

### Power button pod (`power_button_panel.py`)

A pod on the +X (robot-left) side of the mast, on the mast's foot, for a 16 mm two-pole (2NO) momentary metal button with a 5 V ring LED (BOM item 6) and a 5 mm status LED (GPIO19). The button face is 168 mm above the floor and just outboard of the lidar base, so a finger reaches it from above; the pod overhangs the plate edge by ~10 mm (it hangs on the mast, nothing is under it but air). The pod is open toward the mast and the foot: fit the button and its nut first, then screw the pod to the mast through the access holes in its outer wall. Wires drop through the hole in the mast foot into the plate slot at (30.5, −70.3). For a 19 mm button, set `BUTTON_HOLE = 19.2` and widen the pod (`X1`).

### Rear camera mount (`rear_camera_mount.py`)

Camera Module 3 Wide (official mechanical drawing: board 25 × 23.862 mm, M2 holes 21 × 12.5 mm apart, 2 mm from the edges, lens 14.4 mm above the bottom edge, 102° × 67°). On the rear edge of the top plate, lens 142 mm above the floor and pitched 15° down: the floor is visible from ~0.13 m behind the lens, and neither the plate, the bumper nor the ToF pair is in view (checked with the frustum). A window behind the board leaves room for the FPC connector; the 300 mm ribbon runs down behind the plate and over the rear edge of the top plate to the Pi.

### Cable clip (`cable_clip.py`)

Snap-in clip for bundles up to 6.5 mm on any 3.2 mm plate hole, M3 screw and nut. For the ToF pairs, the switch wires, the lidar lead and the camera ribbon.

### Not made

- **Wi-Fi antenna mount.** The Alfa AWUS036ACM is 62 × 85.3 × 24 mm with its two RP-SMA jacks on the body (Alfa's spec page), and the 5 dBi antennas are ~19 cm long: mounted upright they would cross the scan plane and shadow ~3° of the lidar each. Where the adapter goes depends on the deck layout; keep the antenna tips below 205 mm (stubby antennas, or tilt them) or mask their sectors in `rabbit-lidar`.
- **Inter-deck spacers and other board-specific parts.** The body PCB (`pcb/rabbit-body/`) was still in progress: its outline uses the plate shape and the kit's six standoff holes (four corners M4, two at the kingpins M3), but `rabbit-body.step` and its list of mounting parts did not exist yet.

## Checks (`assembly.py`)

The real robot differs from `model/chassis.step` in one way that matters: its standoffs are longer, so the top plate sits at 122 mm above the floor (the ZED's optical centre is at 137 mm, half its 30.3 mm height below that), not 75 mm. `assembly.py` lifts the top plate by 46.6 mm and adds boxes for the ZED 2i (175.3 × 43.1 × 30.3 mm, tripod screw in the plate's 9 mm hole 45.9 mm from the front edge), the V-mount plate (90 × 120 × 10, estimate) and the battery (73 × 111 × 56.7 mm, NEEWER spec).

| Check | Result |
|---|---|
| Every plate screw lands in a measured plate hole or slot of the right size (12 screws) | all 12 match |
| Overlap of every printed part and every piece of hardware with each other, with the 134 chassis solids and with the envelopes | none above 0.5 mm³ |
| Front tyres (Ø74.9 × 29.2 mm envelopes) steered about the measured kingpins to ±35° and ±40°, against the bumper (bar at rest and pushed 3.5 mm), switches and ToF pair | smallest gap 4.5 mm (bumper at 40°), 7.2 mm for the pushed bar; the bar pushed to the stops never reaches the tyre (front-most tyre point y −145.3 at 40°) |
| ToF fields (45° × 45°, 0.6 m) against all solids | clear for all four |
| Lidar band (above) | clear |
| ZED 2i field (110° × 70°, 1.5 m, level and pitched 10° down) | none of the new parts; only the top plate's own front tab, as today |
| Rear camera field (102° × 67°, 1 m) | clear |

Renders: `renders/assembly_{iso,iso_rear,top,side,front,rear}.png`, details `renders/detail_{front,rear,mast}_*.png`, fields of view `renders/fields_of_view_{iso,side,top}.png`, each part alone `renders/part_*_{iso,iso_rear}.png`.

## Measure before printing

The model is the kit, not this robot. Measure these on the robot; each names the parameter to change.

1. **Top plate height** above the floor (assumed 122 mm): sets the lidar plane. `TOP_PLATE_TOP_H` in `common.py`; the mast height follows.
2. **Battery top** above the floor with the V-mount plate (assumed 188.7 mm): must stay ≥ 10 mm below the lidar base (190.2 mm), else raise `LIDAR_PLANE_H`.
3. **Free strip on the top plate between the ZED and the battery**: the mast foot covers 68–105 mm behind the top plate's front edge, ±25 mm of the centre plus the pod side to +42 mm. Measure the ZED's back face (incl. the USB plug) and the V-mount plate's front edge from the plate's front edge. Assumed: ZED back at 67 mm, V-mount front at 119 mm.
4. **Rear end of the top plate**: the camera foot needs the last 15.5 mm, ±16 mm of the centre, and the 5.4 mm slot there free. Check the V-mount plate or battery doesn't reach it and that the pack still slides out.
5. **Bottom plate front strip**: the 14 mm in front of the steering-servo bracket must be free (slot 4.6 mm and hole 10.85 mm from the front edge). **Rear strip**: free behind the rear corner standoffs (holes 7 mm from the rear edge). The rear pad has notches for the standoffs at their kit positions.
6. **Steering lock**: checked to ±40° about the kit's kingpins. If the real lock is larger, re-run `assembly.py` with `STEER_LOCK_CHECK` raised.
7. **Your power button**: body behind the panel ≤ 37 mm, nut ≤ 21 mm across corners, panel ≥ 2.5 mm allowed.
8. **ToF wiring**: the pocket assumes wires soldered to the pads; straight header pins (6 mm) will not fit.
9. **Camera FPC connector**: the window behind the board is 14 × 16 mm at its centre; check against your module.
10. **Floor height**: in the model the front tyres touch 2.6 mm lower than the rear ones (z 4.4 vs 7.0); heights here use the mean.
