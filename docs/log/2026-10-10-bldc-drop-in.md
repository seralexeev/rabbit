# 2026-10-10 BLDC drop-in for the existing 37D bracket

Offline research, no robot. Full report (Russian): `reports/2026-10-10-bldc-drop-in.md`. Datasheets: `datasheet/Pololu 37D/` (drawing, datasheet, 9 Pololu STEP files) and `datasheet/BLDC 37D drop-in/`. Nothing in code, CAD or `pcb/` changed.

## Question

A BLDC that bolts into the current bracket and takes the current wheel hub, fast (2–2.5 m/s on Ø75 wheels at 14.5 V), reliable, price secondary. The 2026-10-03 findings were treated as hypotheses and re-checked against maker drawings.

## Reference (Pololu drawing + STEP)

- 6×M3, 3 mm deep, on Ø31; output offset 7.0 mm; Ø12 × 6 boss; Ø6 shaft, 5.4 flat, 22 mm from the face.
- #4754 is 70.1 mm behind the face (STEP: 36.9 × 92.1 mm overall). The chassis has 71 mm per side.

## Findings

- **No quality maker sells a literal bolt-on BLDC.** Pololu has no BLDC 37D and does not sell the gearbox alone. maxon GS 38 A is the only branded offset spur head (7 mm, Ø6/5.5 shaft) but has a 4-hole square flange, ≤ 5,000 rpm input (≤ 1.1 m/s) and is being discontinued.
- **The JGB37/GM37 face matches Pololu** on three independent drawings (Chihai, Leison, Kechen). Shaft is 21 mm with the flat only on the outer 12 mm.
- **Bare (external-driver) 37 mm BLDC exists:** Chihai CHB-BLDC3650 (3 phase + 5 Hall leads, by drawing; winding too weak: 80 g·cm rated) and Kechen ABL3650-37GM-12HH1 (554 rpm/V, 39 mN·m rated, ~8 leads in photos, wiring undocumented). No 37 mm BLDC gearmotor with a quadrature encoder was found.
- **Adapter-plate route:** the bracket window is a 15 × 22.5 slot on the output axis, so a Ø22 planetary with a Ø15 pilot sits on the wheel axis via a ~3 mm plate (6×M3 on Ø31 to the bracket, 6×M2 on Ø19 to the gearhead). maxon GPX 22 and Faulhaber 22GPT share the Ø19/M2/Ø15 pattern. Both give a Ø6 output shaft (Faulhaber flat 5.4, maxon 5.5) that takes the current hub, but ~4 mm shorter past the bracket unless a longer shaft is ordered.

## Candidates at 14.5 V, 0.2 N·m per wheel (estimates from datasheets)

| Drive | Fit | Speed | Encoder |
|---|---|---|---|
| Faulhaber 3216W012BXTH + 22GPT 11:1 KS5 + IEF3-4096 | plate; Ø32 motor 0.7 mm into deck 1 | ~2.4–2.6 m/s | 4096 lines A/B/I |
| maxon ECX FLAT 22 L 18 V + GPX 22 UP 16:1 + ENX 22 MILE | plate | 2.0 m/s continuous, 2.5 short-term (8,000/10,000 rpm input limit) | 1024 lines A/B |
| Kechen ABL3650-37GM-12HH1 10:1 | direct; ~72.5 mm long vs 71 available | ~2.6 m/s | Halls only |

GPX 22 UP vs the LN in Q40: steel gears, 2.9/3.6 N·m vs 0.55/0.70, Ø6 shaft vs Ø4, no −5 dB(A).

## Open

- Q41: which route (supersedes or complements Q40).
- M19: gap between the two motor rear ends, hub set-screw distance from the shaft tip.
- Kechen RFQ: wiring, pole pairs, length, R/L, rear shaft stub.

## Update: stock Hiwonder motor and a 1.25 m/s target (same day)

- The chassis is the Hiwonder Ackermann Steering Chassis; its stock motor is the Hiwonder JGB37-520R30-12 (brushed, 30:1, 12 V, 320 rpm). Hiwonder drawing: 6×M3 on Ø31, 7 mm offset, Ø6 shaft with 5.48 flat, 19.8 mm from the face, **56.7 mm behind the face** (Pololu: 70.1). Encoder: Hall + 11-pole magnet ring, A/B, 3.3–5 V, PH2.0-6, pin order M2 · VCC · H1 · H2 · GND · M1 (owner's photo matches Hiwonder's M+ VCC A B GND M−); 1,320 counts per wheel turn. Files: `datasheet/JGB37-520R30-12/`.
- Hiwonder sells no BLDC for any of its cars. No ready-made JGB37-format BLDC with an A/B encoder for an external driver was found; Kechen and Chihai offer Halls only, encoders are custom orders.
- The owner set the speed target to ~1.25 m/s (research rover). With it the recommendation moves to maxon ECX FLAT 22 L + GPX 22 UP **21:1** + ENX 22 MILE on an adapter plate: 1.5 m/s (8,000 rpm input limit), 0.55 N·m continuous at the wheel, ~0.8 A at 0.2 N·m. Faulhaber 3216 + 22GPT 16:1 is the fallback (~1.7 m/s). Kechen 3650 at 18.75:1 is ~75 mm long, so two do not fit in 142 mm without a shorter motor.

## Update: bare and integrated JGB37 BLDC (same day)

- Bare (3 phase + Halls) JGB37 BLDC is buyable: TT Motor GM37-TEC3650 (datasheet in `datasheet/BLDC 37D drop-in/JGB37 BLDC/`): 12 V winding TEC3650-1265, 6,500 rpm no-load, rated 19.6 mN·m at 1.4 A, stall 4 A; gearbox rated 0.78 N·m, 1.47 N·m momentary; sold with a separate driver board, bare harness 2×4 Molex per photos; ~US$20. Encoder only as a custom option. At 19:1 and 14.5 V: ~1.4 m/s under 0.2 N·m (estimate).
- Length is the blocker for every 3650: 71.5 mm behind the face at 19/30:1 plus a rear connector, vs 71 mm per side. M19 decides.
- No JGB37-format BLDC with an integrated bus (RS485/CAN/UART) or encoder output was found; integrated drivers give only PWM/DIR/FG (6 pulses per motor turn), some with a brake input. Q42: RFQ to TT Motor and Kechen.

## Update: full maxon catalogue sweep (same day)

- Downloaded maxon Product Range 2026/27 (506 pages) to `data/datasheets/maxon/`; extracted 181 motor windings (Ø ≤ 32), 152 gearhead variants and 34 encoders to JSON; selection script `docs/reports/media/maxon-select.py`.
- 28,677 motor × gearhead × ratio combos; 1,039 meet speed (≥ 1.25 m/s at 13.2 V, 0.2 N·m), torque and current limits; 238 also fit 67 mm behind the adapter plate. Length rules out every cylindrical 22 mm motor (ECX SPEED/PRIME/TORQUE 22 are 44.5–82 mm long).
- Best fit across the catalogue: ECX FLAT 22 L High Torque 18 V + GPX 22 UP 21:1 + ENX 22 MILE (50.2 mm, Ø22, 1.45–1.5 m/s, 0.56 N·m continuous at the wheel, Ø6 shaft). GPX 22 A/C/LN/LZ have a Ø4 shaft; only UP/HP give Ø6. ECX FLAT 32 + GPX 32 is twice as strong but Ø32, Ø8 shaft and a Ø19 pilot.
- Maxon-quality integrated option: ECX FLAT 22 L with integrated 4-Q speed controller (8–28 V, 4 I/O, min 300 motor rpm).
