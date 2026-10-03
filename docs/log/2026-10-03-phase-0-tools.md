# Rabbit 2.0 phase 0: INA shunts, RoboClaw configuration, encoder check

Date: 2026-10-03, offline (robot off). Uncommitted, not deployed, verified on the Mac only: unit tests, a RoboClaw emulator on a pseudo-terminal, and the full-stack simulator with a Forge writer. Phase 0 is defined in `reports/2026-10-03-architecture-2.0.md` ("План по этапам"); the numbers behind it are in [2026-10-03 power rails](2026-10-03-power-rails.md).

## INA4235: per-channel shunts and a clipped flag

- **Calibration per channel.** `lib/ina4235.py` has the datasheet math (SBOSAB5 §8.1.2): `CURRENT_LSB ≥ I_max / 2^15` (at most 8× that), `SHUNT_CAL = 0.00512 / (CURRENT_LSB × R_shunt)`, 15 bits. The expected maximum current defaults to the shunt's full scale, 81.92 mV / R. The LSB is the smallest multiple of the decade step that is at least the minimum, so it stays within 1–5× the minimum:

  | Shunt | Full scale | CURRENT_LSB | SHUNT_CAL |
  |---|---|---|---|
  | 10 mΩ (today, all channels) | 8.19 A | 1 mA | 512, as before |
  | 5 mΩ (2.0 motors) | 16.4 A | 1 mA | 1024 |
  | 2 mΩ (2.0 battery) | 41.0 A | 2 mA | 1280 |

  The wiring report proposed 1.25 mA / 2048 for 2 mΩ. Both are valid; the ADC's 2.5 µV step (1.25 mA on 2 mΩ) sets the real resolution either way.
- **Configuration** through the environment of `rabbit-ina`: `INA_SHUNT_OHMS=1=0.002,2=0.01` and optionally `INA_MAX_CURRENT_A=1=20`. Unset channels keep 10 mΩ. A channel that isn't active (today only 1 and 2) is refused at start. `INA_` is now one of the environment prefixes in `lib/observability.py`, so `node_starts.env` shows the override.
- **Startup record.** `node/ina.py` writes CONFIG1 and each active channel's SHUNT_CAL, then emits `power.calibrated` with these values per channel: `chN_shunt_ohms`, `chN_max_current_a`, `chN_full_scale_a`, `chN_clip_a`, `chN_current_lsb_a`, `chN_shunt_cal`, plus the label `chN_name`. The event replaces the old `Written CONFIG1=... and SHUNT_CAL=...` log line.
- **Clipped.** The node now also reads each channel's shunt-voltage register (0x00/0x08/…, 2.5 µV/LSB). `clipped` is true when |V_shunt| ≥ 90% of 81.92 mV, or when the current register is at 90% of ±2^15. With averaging over 4 conversions (CONFIG1), single conversions can exceed the averaged value. The threshold is 90%, not the 95% of the wiring report, because the 7.64 A peak of 1 Oct is 93% of the 10 mΩ range and has to be flagged.
- **What the history says about the shunts.** In the Forge mirror (52,082 seconds with both `power` and `jetson`), battery power is at least 1.96× the Jetson module's own VDD_IN in 99% of seconds (median 21.7 W vs 9.8 W), and at least 8.75 W above it in 99.9%. A channel 1 shunt above ~20 mΩ (readings ≥ 2× too high) is therefore ruled out. A smaller shunt (readings too low) is not, so the marking still has to be read. Only 2 seconds of history reach the new 7.37 A clip threshold.
- **Forge:** `power.battery_clipped` and `power.rail_6v_clipped` (`Nullable(Bool)`, NULL for older rows), zod `clipped` nullish in `src/streams.ts`, `power.calibrated` in the `events.name` comment, README table and data note, eval case `battery_clipped` (skipped until clipped rows exist).

## Duty cap for 12 V motors on a 16.8 V pack

The RoboClaw has no max-duty setting in packet serial mode: Fwd/Rev limits apply only to RC and analog. So `node/roboclaw.py` scales every command by `duty_max = min(1, 12 V / V_supply)` (`lib/drive.py` `duty_limit`), where `V_supply` is the highest valid RoboClaw main-battery reading (6–34 V) of the last 50 I/O ticks (1 s). The highest is used so that sag under load doesn't raise the cap. Until there is a valid reading the cap assumes a full pack, 12 / 16.8 = 0.714.

- **Scaling rather than clipping.** On the pack a command of 0.5 still puts 6 V on the motor, as it does today, so nav's speed calibration (0.464 m/s per duty) and creep speeds don't change when the RoboClaw moves to the battery.
- **Today nothing changes.** On the 12 V buck (11.3–12.0 V) `duty_max` is 1.
- **Telemetry.** `duty_max` is published in `rabbit.roboclaw` and stored in `roboclaw.duty_max`. `pwm` is now command × `duty_max` after the slew.
- **Tests:** `tests/test_power.py` (buck → 1.0, full pack → 0.714, glitches ignored, no reading → full-pack cap).

## RoboClaw configuration tool

`workspaces/rabbit/tools/roboclaw_config.py read | plan | apply --yes [--estop] [--battery]` runs in the `rabbit` image while `rabbit-roboclaw` is stopped (the procedure is in its `--help` and in the rabbit-robot skill, "Phase 0 on the robot"). It refuses to start while `rabbit-roboclaw` runs; the check uses the Docker socket, which the printed `docker run` mounts.

| Setting | Command (manual rev 5.7) | Target |
|---|---|---|
| M1/M2 max current | 133/134 set `[max u32, min u32 = 0]` in 10 mA; 135/136 read | 3.00 A |
| serial timeout | 14 set, 15 read, 100 ms units | 0.5 s (`Node.HARDWARE_TIMEOUT`; the node also sets it at every connect) |
| main battery limits | 57 set `[min u16, max u16]` in 0.1 V; 59 read | 12.4 .. 17.4 V, only with `--battery` |
| S3/S4/S5 modes | 74 set, 75 read | S3 = 0x01 non-latching E-stop, only with `--estop`; S4/S5 kept |
| shown only | 21 firmware, 24 main battery, 90 status, 91 encoder modes, 99 standard config, 149 PWM mode | unchanged |
| save | 94 | after every `apply` |

- **`--battery` is refused while the RoboClaw reads a voltage outside the limits.** Today it is fed by the 12 V buck (11.9 V), and a 12.4 V minimum would make it freewheel the motors. 12.4 V is 3.1 V/cell. 17.4 V leaves 0.6 V above a full 4S pack for regeneration. The manual's "±2 V" rule is for power supplies; with a battery the regenerated energy goes into the pack. Above the maximum the RoboClaw brakes, below the minimum it freewheels. If "main voltage high" warnings appear when braking on a full pack, raise the maximum.
- **`--estop` waits for the 2.0 wiring.** The default S3 mode in packet serial is a latching E-stop, cleared only by power-cycling. Non-latching E-stop is safe only with the 1 kΩ pull-down at the connector and the Pi holding the line high (wiring report).
- **Command 94** is documented in the manual as `[address, 94, CRC]`, but Basicmicro's `roboclaw_3.py` sends the key `0xE22EAB7A` with it. The tool tries the library form first and falls back to the manual form, then prints which one the RoboClaw acknowledged (firmware on the robot: v4.3.6). `apply` reads every setting back before saving and doesn't save if anything didn't take or anything was refused.
- **Checked against an emulator** of the packet protocol (CRC16, ack 0xFF) on a pty. Factory 30 A / 0 s → 3 A / 0.5 s saved; `--battery` on 11.9 V refused with nothing written; on 16.5 V the limits and S3 were applied; command 94 worked in both forms; an unreachable port printed the procedure.

## Encoder check

`tools/roboclaw_encoders.py [--distance 1.0] [--seconds N]` is read-only: no drive commands, no reset. It streams commands 78 (counts), 79 (instantaneous speed) and 108 (1 s average speed) at 10 Hz with counts, counts since start, wheel turns, metres and direction. At the end it prints a verdict per side: no counts (check 5 V on blue/green, a square wave on yellow/white), counting down while rolling forward (swap A/B or set "reverse encoder", bit 6 of commands 92/93), or PASS/FAIL against 19,014 counts/m ± 3% (64 CPR × 70 = 4480 per wheel turn, 75 mm wheel).

## Still needs the robot

- Deploy `rabbit-ina` and `rabbit-roboclaw` (with the rest of the roadmap's list), check `power.calibrated` and `roboclaw.duty_max = 1` in Forge, and see whether `battery_clipped` appears on hard starts.
- Run the phase 0 procedure: read the shunt markings, and set `INA_SHUNT_OHMS` if one isn't R010; `roboclaw_config.py plan` and `apply --yes`; power-cycle the RoboClaw and `read` (3.00 A); the encoder check after rewiring.
- After `apply`, watch motor starts in Forge: the 3 A limit is below the 3.3–4.7 A start peaks seen so far, so acceleration from standstill may be slightly softer.
