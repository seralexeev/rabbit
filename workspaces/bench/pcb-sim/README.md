# Body board rev C: circuit simulations

ngspice decks and a runner that check the circuits of `pcb/rabbit-body-c/gen/design.py` whose behaviour is not
obvious from arithmetic, plus a table of the rail and threshold arithmetic. Results, raw waveforms and plots go to
the gitignored `data/pcb-revc/sim/`; the review summary is `data/pcb-revc/review/round1-sim.md`.

## Run

```sh
brew install ngspice                                   # ngspice 47 was used
uv run --script workspaces/bench/pcb-sim/run.py        # all tests, about 2 minutes
uv run --script workspaces/bench/pcb-sim/run.py 1 6    # only tests 1 and 6
```

Output in `data/pcb-revc/sim/`:

| Path | What |
|---|---|
| `results.md`, `results.json` | every metric with value, limit and PASS / FAIL / INFO |
| `<n>-<test>/*.png` | waveforms of the representative cases |
| `<n>-<test>/raw/<case>.cir`, `.txt`, `.log` | the exact deck sent to ngspice, its `wrdata` output and log |
| `5-rails/rails.md` | the rail and threshold table |

The runner imports `design.py` and checks every `.param` whose name is a reference designator (`R43`, `C14A`,
`C883`, ...) against the value in `design.py`; a mismatch stops the run. When `design.py` changes, update the deck.
`design.py` value `1M` means 1 MOhm; SPICE `1M` is 1 mOhm, so the decks write `1Meg`.

## Tests

| # | Deck | Parts (design.py) | What it checks |
|---|---|---|---|
| 1 | `latch.cir` | J15 button, Q4, R43-R49, C24-C26, D8, Q5, D9, U10 EN/OV (R40/R41), C23/R42, Q2 | battery hot-plug with no press stays off; a press latches at 12.0 and 16.8 V; the shortest press that latches (typical and worst corner); the hold through D8 keeps EN above the LM74800 thresholds; OV pin margin; GPIO17 (gpio-poweroff) turns it off with no re-latch; brown-out dropout voltage; 20 ms battery dips |
| 2 | `watchdog.cir` | U1.11 MCU_ALIVE, C14A, D12, C14B, R14B, R16-R18, C18, U16, R19 | DRVOFF release vs toggle frequency 100 Hz-100 kHz at three corners; time to assert when MCU_ALIVE stops high or low; E-stop open to DRVOFF; power-up state |
| 3 | `xarm.cir` | U1.62 PB9, R887, Q88, R888, U89 (ARM_5V), R889, D89, cable | 115200 Bd both directions with push-pull 5 V, push-pull 3.3 V and open-drain servos: levels, edges, duty distortion, PB9 range and negative injection; 8.4 V forced on the signal pin with the arm on and off; bus collision current |
| 4 | `i2c.cir` | J3 (Pi 1.8k pull-ups), the 18 devices on I2C1 (counted from `netlist.json`), U40 channel 1, R900, D60 | 30-70 % rise time and VOL on I2C1 for 230 / 280 / 400 pF; a ToF port through the TCA9548A pass gate in both directions |
| 5 | (arithmetic) | U4/U6 FB and EN, U31 FB, U10 OV, U5/U7 UVLO/OVP/ILIM, U30 UVLO/OVLO/CL, every TPS259470L ILIM/ITIMER/OVLO, U88 ILIM/ITIMER/IMON/EN, U90, U32 | value, min-max from datasheet tolerances, against the `design.py` comments |
| 6 | `servo.cir` | U6 + L6 + C610-C614, R2, C881, U88 (C883, R881), C885-C887, U83 (R831, C834, R166/R167), C835/C836 | an arm stall or overload on the shared 10 A servo buck: does only the arm eFuse act, does the steering rail stay within 90 % of its setpoint, does U83 stay on (fast trip, ITIMER, OVLO) |

## Models

Behavioural where the IC is too complex or no free model exists; every threshold is from the datasheet in
`data/datasheets/`.

- **LM74800** (`ti/lm74800-q1`, SNOSDD8 p.5-6): EN/UVLO comparator 1.231 V rising / 1.132 V falling (worst corner
  1.267 / 1.159), OV 1.231 / 1.13 V through R(SW) 19.5 ohm, HGATE 55 uA source (39-75) clamped at OUT + 11.1 V,
  260 mA sink when disabled, ~0.25 ms charge-pump start. Q1 (ideal diode) is a low-drop diode, Q2 a level-1 FET
  (Vth 1.7 V, 1 mOhm, Ciss ~7 nF).
- **Pi and 5 V buck** in test 1: the LM61495 EN divider R404/R405 with 1.263 V rising and 0.888 V falling, the Pi
  alive above 5.4 V, a constant-power load (10 W on, 1 W after poweroff, 30 W in the dip test), 470 uF on VBUS.
- **D8 BZT52C8V2**: Bv 8.2 V at 5 mA with a soft knee (Nbv 4, about -0.5 V at 50 uA); corners 7.7 V soft and
  8.7 V hard knee (Diodes BZT52C, 7.7-8.7 V at 5 mA).
- **SN74LVC1G132** (`body-rev-b/sn74lvc1g132`, p.6): Schmitt inputs interpolated to 3.3 V, VT+ 1.63-2.04 V
  (typ 1.83), VT- 0.95-1.27 V (typ 1.10); input leakage up to 5 uA in the worst corner. MCU_ALIVE: 3.3 V push-pull
  with 40 ohm, VOH 2.9 V in the worst corner. BAT54: standard SPICE diode.
- **BSS138** (onsemi BSS138LT1G, datasheet not downloadable from this machine): level-1, Vth 1.3 V, 1.5 ohm at
  4.5 V; weak corner Vth 1.5 V, 3.5 ohm [from memory]. TPD1E10B09: two 10.5 V zeners back to back, 10 pF.
  Cable + 6 servos: 150 pF and 0.9 uH in three LC sections, 0.3 ohm. Servo driver: 5 V push-pull 50 ohm, 3.3 V
  push-pull 50 ohm or open drain 30 ohm, 15 ns edges. TLV76050 OUT can only source; its OUT->IN body diode is a
  1N4148.
- **TCA9548A** channel: NMOS pass gate (Vth 0.9 V, body effect, ~15 ohm). 10 pF per device plus 50 pF of trace on
  I2C1 as specified; downstream 35 pF (mux pin, ESD, 100 mm cable, sensor).
- **LM61495** (SNVSBZ4A p.7): averaged current-mode buck with a 35 kHz voltage loop; average current limit =
  low-side valley limit (9.8 / 11.5 A min / typ) + half the ripple, capped by the 14 A peak limit; hiccup flagged
  below 40 % of the setpoint. Output caps derated for DC bias (22 uF 1206 x 0.55, 10 uF 1210 x 0.8).
- **TPS25982 (TPS259824ON)** (`ti/tps25982`, SLVSEI3D p.9, 23-26): circuit breaker; ILIM from table 6.5
  (300 ohm: 4.36 / 4.98 / 5.66 A); fast trip at 2.1 x ILIM, after which it restarts current-limited at ILIM;
  ITIMER 2.1 uA (1.4-2.8) discharge over 0.98 V (0.7-1.3) from 2.5 V; latch-off.
- **TPS259470L** (`ti/tps25947`, SLVSFC9C p.9-10): RON 28 mOhm, ILIM 3334 / R_ILM (5.4-6.6 A at 549 ohm), fast
  trip 2.01 x ILIM, ITIMER 1.51 V / 1.8 uA, OVLO 1.20 / 1.09 V, true reverse current blocking.

Limits of the models: no thermal shutdown, no PCB parasitics, the buck is averaged (no switching ripple in the
waveforms), the servo electrical interface and the arm's real current profile are unmeasured
(`data/pcb-revc/ics/xarm_bus.md`).
