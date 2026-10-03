# 2026-10-03 BLDC drive: final motor, bracket and wheel coupling

Offline, no robot. The owner chose BLDC and accepted new brackets (Q39). Report section: `reports/2026-10-03-bldc-drive.md` §13 (Russian). CAD: `cad/drive/` (README with the BOM, machining and print notes). Nothing in robot code or `pcb/` changed.

## Motor choice

Datasheet numbers at 14 V, per wheel (Ø75 mm):

| | maxon ECX FLAT 22 L 18 V + GPX 22 LN 16:1 + ENX 22 MILE 1024 | Faulhaber 3216W012BXTH + 22GPT 11:1 + IEF3-4096 |
|---|---|---|
| No-load / at 0.2 N·m | 2.35 / 2.08 m/s | 2.62 / 2.41 m/s |
| Current at 0.2 / 0.6 N·m | 1.22 / 3.46 A | 1.37 / 3.86 A |
| Gearhead continuous / intermittent | 0.55 / 0.70 N·m, plastic planets, −5 dB(A) | 0.8 / 1.1 N·m, stainless |
| Output shaft | Ø4 × 14.85 mm | Ø6 × 16.3 mm |
| Encoder | 4,096 counts/motor rev, A/B line driver, no index | 16,384 counts/motor rev, A/B/I |
| Length behind the flange, diameter | 46.3 mm, Ø22 | 49.2 mm, Ø22 + Ø32 motor |
| Price | €429.78 per drive (config B845D2FFA4A0), ≈ A$770 ex GST | on request (ERNTEC, AU/NZ partner), est. €500–700 |

- **Chosen: maxon.** With the motor coaxial to the wheel, the axis is only 15.3 mm above deck 1. The Faulhaber's Ø32 motor body goes 0.67 mm into the deck (32 mm³ per side in the fit check), which would mean filing windows into deck 1. The maxon is Ø22 and clears the deck by 4.3 mm.
- **Noise:** the LN gearhead is the only option with a stated reduction (−5 dB(A)). At 0.5 m/s the motor turns ~2,000 rpm, against 8,900 on the 37D 70:1.
- **Limits, handled in firmware:**
  - the 0.6 N·m peak fits the LN's 0.70 N·m intermittent rating with an Iq cap of 3.7 A;
  - the LN input is limited to 10,000 rpm, so motor speed is capped there (2.52 m/s).
- **Fallback:** the Faulhaber. It is faster and stronger and the drive set is the same; only the flange and the Oldham hub change, plus the windows in deck 1.
- **Rejected:**
  - GPX 22 HP: its 8,000 rpm input limit gives 2.0 m/s;
  - ECX TORQUE 22 L: ~90 mm long;
  - Faulhaber 2232/2214: too weak; 2250: 78 mm long.
- **Not checked:** Portescap returned 403, and the web search quota ran out for Nidec and Moons.

## Mount

- **The bracket carries the wheel.** Hanging the wheel on the gearhead would put its centre ~37 mm from a flange rated at 100 N 10 mm away (LN: 40 N axial), against ~61 N on a 5 g bump plus cornering moments. So the bracket holds a hollow stainless stub axle on two SKF 61803-2RS1 (17 × 26 × 5) either side of a 2 mm shoulder. The stub's outer end is the kit hub's 12 mm hex with the M3 axial screw, so the wheel goes on as before. Bearing loads: static 44 N; 0.7 g cornering 89 N; 5 g bump + cornering 265 N (s0 = 3.9).
- **The gearhead shaft only turns the wheel.** It sits inside the hollow stub: hub A with a set screw on the flat, a PEEK Oldham disc (±0.3 mm float), and a cross slot in the stub bore. Nesting the coupling inside the bearings saved ~10 mm of length. The first, stacked layout left the Faulhaber 1 mm past the centreline; the nested one leaves 22.9 mm between the maxon motors.
- **Bracket shape:** an L in 6061-T6.
  - The 4 mm foot sits under deck 1 on the kit's two M4 holes, slotted ±1 mm fore-aft. No drilling.
  - The housing sits outboard of the deck edge. The 10.7 mm per side widening freed that space.
  - The gearhead bolts to a 3 mm flange plate that spigots into the bracket (Ø30 g6/H7) with 3 × M3, so the motor comes out without touching the wheel.
  - Drawings with the fits: `cad/drive/drawings/*.pdf`.
- **Print variant** for a test fit on the P2S: PA-CF, outboard face down. Bores are +0.1 mm and heat-set inserts replace the threads. The printability check shows only the 2 mm bearing shoulder ledge.

## Fit check (`cad/drive/assembly.py`)

The chassis model is the kit with the rear brackets at 142 mm and the wheels moved out 10.7 mm per side. It includes the 3-deck stack, the body PCB STEP and the printed mounts.

| Check | maxon | Faulhaber |
|---|---|---|
| Interference with the chassis, PCB, printed mounts or between drive parts | none | motor into deck 1 |
| Gap between the motors' rear ends | 22.9 mm | 17.1 mm |
| Motor to deck 1 | 4.3 mm | −0.67 mm |
| Bracket / motor to the PCB | 7.9 / 12.7 mm | 7.9 / 8.7 mm |
| Bracket to the wheel | 1.0 mm | 1.0 mm |

Other results, the same for both motors:
- The foot slots match all four deck holes.
- The lowest point is the M4 nuts, 11.1 mm above the floor and inside the tyre silhouette.

Measurements taken from the kit model:
- deck 1 plate z 27.12–29.12;
- wheel axis z 44.455, rear wheel bottom at z 7.0 (the model is 2.7 mm higher at the rear than at the front tyres);
- bracket inner face 60.3 mm from the centreline, now 71 mm;
- wheel inner rim face 8.8 mm outboard of it, kit hex socket 17.9–23.9 mm;
- the kit "Ø15 centre hole" is really a 15 × 22.5 slot at the output shaft, 7 mm below the Ø31 circle centre.

## Electrical

- **Rev B needs no board change.** The phases (KK 396), Halls (PH 5) and encoder (GH 7) connect through adapter pigtails; pinouts are in report §13.6 and `cad/drive/README.md`.
- **Encoder:** ENX 22 MILE has no index, and its outputs are a 5 V CMOS line driver; only A and B are used.
- **Current:** the winding's short-circuit current at 16.8 V is 11.7 A, so the DRV8316 current limit and the lower OCP level must be on, along with the 3.7 A Iq cap.

## Open

On-robot measurements M13–M18 and the questions in `open-issues.md`:
- how the widened brackets are fixed now;
- axle height over deck 1;
- the wheel recess;
- space under the deck;
- the maxon Hall-board outline from its STEP (needs the configurator);
- the wider rear track vs the bumpers.

The maxon STEP was not downloaded; its "Create CAD data" may need a login. The motor is modelled as an envelope from the catalogue drawing. Faulhaber STEPs are in `data/cad/makers/faulhaber/`: their licence forbids redistributing modified files.
