# pcb-audit: net-by-net electrical audit of the body board

`audit.py` reads the netlist straight from `pcb/rabbit-body-c/gen/design.py` (imported read-only, no bytecode
written) and checks every net and every IC pin. Standard library only; one run takes under a second.

```
python3 workspaces/bench/pcb-audit/audit.py                       # report to stdout
python3 workspaces/bench/pcb-audit/audit.py --md data/pcb-revc/review/round2-audit-script.md
python3 workspaces/bench/pcb-audit/audit.py --net ARM_SIG_B       # one net in every scenario
```

## Method

| Step | What |
|---|---|
| Rails | `RAILS`: every power net with its maximum voltage and its power domain (battery 16.8 V, servo 7.45 V, +5V 5.3 V, ...). `NEEDS` says which domains a domain depends on (e.g. a ToF port needs the Pi, because its EN comes from the Pi's expander) |
| Scenarios | `SCENARIOS`: all on; Pi off with the battery latch on; USB only; arm, servo buck, ToF, one ToF port, encoder, lidar, fan, motor bus, AUX off; servo buck failed high (HS short); arm off with C887 charged, then the buck off; MCU transmitting a low while the arm bus is high |
| DC solve | Exact nodal analysis (Gaussian elimination per connected component) over resistors, resistor arrays, Kelvin shunts, fuses/inductors (shorts), piecewise-linear diodes (forward drop, zener/TVS breakdown, BAT54S halves, ESD arrays), N-FETs as switches (symmetric, with body diode). IC outputs are 25 ohm drivers at their supply (or low, `DRIVE_LOW`), internal pulls are resistors, and pins of unpowered parts clamp to their dead rail through a 0.5 V diode. Nets driven by an IC function the solver does not model (charge pumps, IMON/ILM, timers) are set by `FORCE`, each with the reason |
| Pin tables | `PINS`: per IC value, every pin's name, kind (supply, input, push-pull, open drain, I2C, analog, power terminal), abs-max expression and datasheet page. `ext_pins()`: the device on the far side of each connector (Pi GPIO, VL53L8CX carrier, RPLIDAR C1, Hall encoder, servos, xArm bus, fans) |
| Checks | abs max per pin; back-powering (current into the clamp of an unpowered pin); current into a rail that is off; floating CMOS inputs; open-drain nets without a pull-up; two push-pull drivers on a net; output pin current above the pin rating; single-pin nets and nets with fewer than two fitted pins; capacitor rating < 1.5 x the voltage across it (rating from the JLC description in `fab/stock.json` and `data/pcb-revc/review/audit-lcsc-extra.json`); polymer polarity; diodes conducting in the static solution; FET/BJT Vgs/Vds/VEB; resistor power (solved, and with a connector pin shorted to GND) |
| Claims | `CLAIMS`: every numeric claim in the design.py comments recomputed from the part values; the report also lists all numbers with units found in the comments for a manual coverage pass |

## Limits

- DC only. Transients (inrush, ringing after a buck HS short, the eFuse blanking intervals) are in
  `workspaces/bench/pcb-sim` (ngspice) or need one.
- An unpowered pin's clamp is a generic 0.5 V diode; pins marked `ioff` (datasheet says the input tolerates voltage
  above its supply) get none.
- The script flags; it does not judge. The judgement for each flag of a review round is in that round's report
  (`data/pcb-revc/review/round2-audit.md`).
