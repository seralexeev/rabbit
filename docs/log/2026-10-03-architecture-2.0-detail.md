# 2026-10-03 Rabbit 2.0 made buildable

Offline (the robot was off). This entry turns the Rabbit 2.0 proposal (`reports/2026-10-03-architecture-2.0.md`) into something to buy and wire. The proposal: a Raspberry Pi 4 as the body, the Jetson as the brain. Parts were checked on manufacturer and retailer pages on 2026-10-03; the INA4235, RoboClaw, Jetson carrier and Pololu 37D facts come from the datasheets in `datasheet/`. No robot or Forge code changed.

Where things are:
- Reports (Russian), next to the proposal:
  - `-bom.md`: what to buy;
  - `-wiring.md`: Pi pins, buses, connectors, INA4235;
  - `-body.md`: Pi software, safety loop, NATS, time, power state machine, migration, EKF.
- Diagrams, English labels:
  - `reports/media/wiring-2.0.py` generates `wiring-2.0-overview.svg`, `wiring-2.0-signals.svg` and `wiring-2.0-power.svg`;
  - `power-2.0.py` now draws the INA4235 as one block with four channels.

## Decisions and why

| Decision | Why |
|---|---|
| **Lidar: RPLIDAR C1**, not LD19 | The LD19 (Waveshare D300) is discontinued. The C1 is in stock at Core Electronics for A$129.95 and specced better: ±30 mm vs ±45 mm, 0.72° vs ~1°, 6 m on black. Costs: 460800 baud, a start command, no device timestamps, 0.8 A at start. The STL-19P is the choice if per-packet device time matters |
| **ToF: 4× VL53L8CX on Pololu #3419, one I2C bus each** (i2c3–i2c6), all at 0x29 | In 5 klux it ranges 1.4–1.7× further than the L5CX. Separate buses avoid re-addressing after every boot (the L8CX Python driver can't change addresses), load the ~86 KB firmware in parallel (~2.2 s per sensor at 400 kHz), and keep one stuck bus from taking all four sensors. A full 8×8 frame is ~1440 B, so four sensors at 15 Hz exceed one 400 kHz bus. The board's I/O follows VIN, so it runs on a 3.3 V regulator switched by the Pi, not on 5 V |
| **RoboClaw on Pi UART0** (GPIO14/15, `disable-bt`), USB kept for Motion Studio | The RoboClaw 2x30A datasheet says USB "will likely disconnect and not automatically recover" in electrically noisy environments, and recommends TTL serial for control. The owner had chosen USB; left as an open question |
| **Fail-safe E-stop on S3** | S3 is active low with an internal pull-up. In serial modes its default is a *latching* E-stop, and no serial command clears that. The design: S3 set to non-latching E-stop, 1 kΩ to GND in the S3 connector, and the Pi drives the line high only while `rabbit-safety` runs. A dead process, a booting Pi or a broken wire all stop the motors. Bumpers stay off this line, or a robot pressed against a wall couldn't back away |
| **Fail-safe outputs on GPIO9–27** | Those pins are pulled down at boot, so a booting Pi means E-stop on, Jetson on, switch on. The regulator EN pins (100 kΩ pull-up to VIN) are driven through N-MOSFETs, never straight from a GPIO |
| **NATS: hub on the Pi, leaf on the Jetson**, not a 2-node cluster | A 2-node JetStream cluster has no quorum when one node is down, which would take the KV and LOGS away on both sides. With a leaf, the Jetson's internal traffic (pose → nav) stays local, and its JetStream API calls go to the hub |
| **Main switch: Pololu Big Pushbutton HP #2813**; OFF from `dtoverlay=gpio-poweroff`; 2-pole button (one pole on the switch's A input, which is on-only; the other on GPIO26) | It is Pololu's biggest power switch: 16 A is a thermal limit (MOSFETs at 150 °C), 6 A continuous at a 55 °C board. The robot averages 2–3 A with peaks up to ~10 A |
| **`rabbit-power` runs as a host systemd service** | It orchestrates `docker stop` and the final poweroff, so it can't live in a container |
| **5 V body rail: the owned D24V90F5** (5–38 V in, 4–8 A); Pi branch fuse 5 A, not 3 A | At 12.4 V in, a 5 V × 5 A load draws ~2.3 A on the battery side |
| **USB hub: Waveshare USB3.2-Gen1-HUB-4U**, 7–36 V terminal on its own fuse | Pi 4 USB ports supply 1.1–1.2 A in total; only the flash drive runs from the Pi |
| **Storage: Raspberry Pi Flash Drive 256 GB** (UAS, SMART); no SD card | The Samsung T7 has an unresolved Pi 4 boot issue (firmware#1799) |
| **Wi-Fi: Alfa AWUS036ACM** (MT7612U), 5 GHz | Mature in-kernel driver. MT7921 adapters have an open MCU-timeout bug on Pi 4 with kernel 6.18 (mt76#1141) |
| **HUD video: H.264 over the NATS websocket, decoded with WebCodecs** | The Cloudflare tunnel carries only HTTP/websocket over TCP; WebRTC media is UDP and would need a TURN server |
| **No Jetson RTC battery** | On the dev kit, J3 and R560 are not fitted (NVIDIA forum), so it means SMD rework. The Jetson takes time from the Pi (DS3231 + chrony) and waits for sync before Docker |
| **Jetson keeps its D36V50F12** | The jack takes 9–20 V, so direct battery would work. But the buck gives EN control and isolates the Jetson from motor transients. It drops out below 13.3 V in, roughly the bottom 15% of charge, where the Jetson still runs |

## INA4235: datasheet facts and the new channel plan

**Datasheet facts:**
- Shunt range ±81.92 mV (2.5 µV LSB) or ±20.48 mV, per channel.
- Common mode −0.3 to 48 V, so a 16.8 V bus is fine. Bus voltage is read on each IN− (1.6 mV LSB).
- 16 addresses via A0/A1 (GND/VS/SDA/SCL). The EVM is at 0x41 today.
- ALERT is open drain; four alert slots (SOL/SUL/BOL/BUL/POL) can be assigned to any channel, compared per conversion, and latched until FLAGS (0x22) is read.
- Minimum CURRENT_LSB = I_max/2¹⁵.
- On the EVM the shunts are optional 2512 pads (R12, R1, R13, R9), and J1/J5 are limited to **10 A**.

**Channel plan** (it differs from `plans/pcb-rabbit-board.md` so the already-wired 6 V channel keeps its number):

| Channel | What | Shunt | Range | Note |
|---|---|---|---|---|
| ch1 | battery | 2 mΩ external Kelvin shunt | 41 A | CURRENT_LSB 1.25 mA; 0.39 W at 14 A |
| ch2 | servo 6 V | 10 mΩ on the EVM, unchanged | 8.19 A | |
| ch3 | motors | 5 mΩ external | 16.4 A | 0.5 W at 10 A |
| ch4 | Jetson 12 V side | 10 mΩ on the EVM | 8.19 A | |

- ch1 and ch3 are external because the worst-case battery sum (~10.4 A) and the 14 A plate limit exceed the EVM's 10 A.
- ALERT goes to GPIO24, set for: ch1 under 12.8 V, ch1 over 13 A, ch3 over 8 A, ch4 under 11 V.

**Open risk in the recorded data:** `node/ina.py` uses `R_SHUNT = 0.01` for every channel. The owner soldered some EVM shunts himself, and if one isn't 10 mΩ, that channel's current in Forge since 1 Oct is off by R_actual / 0.01.

**Later code change** (not made: other agents own the node code): per-channel `R_SHUNT` / `CURRENT_LSB` / `SHUNT_CAL`, channel names, all four channels active, ALERT registers, a clipped flag.

## Pi 4 limits checked

- **Bluetooth** takes UART0, so `disable-bt` is needed to get the PL011 on GPIO14/15. uart4 (GPIO8/9) and uart5 (GPIO12/13) are free because SPI isn't used.
- **Hardware PWM:** only 2 independent channels; not needed.
- **GPIO current:** 16 mA per pin, ~50 mA in total. The largest load is the 1 kΩ E-stop pull-down: 3.3 mA.
- **3V3 budget:** not specified officially, so the ToF boards get their own regulator.
- **I2C:** i2c1 has 1.8 kΩ pull-ups; i2c3–6 have none (the Pololu boards provide them). Clock stretching on BCM2711 is still unreliable.
- **Power:** feeding through the 5 V pins bypasses input protection, so USB-C must never be connected at the same time. Undervoltage is flagged below 4.63 V.
- **Thermal:** throttling from 80 °C.
- **Watchdog:** the hardware maximum is ~16 s, so `RuntimeWatchdogSec=15`.
- **OS:** Raspberry Pi OS is now Trixie (kernel 6.18).

## Prices and BOM

- **To buy: ~A$825 (~US$550).** About A$460 of that is verified prices; the rest is marked as estimates in `-bom.md`.
- **The Pi 4 8 GB now costs US$165 / A$267.63.** Raspberry Pi raised the price three times since Dec 2025 because of memory costs. A 4 GB board would likely do if the owner's Pi isn't 8 GB.

## Not verified

- Whether the E-stop also blocks USB motor commands.
- Encoder output type.
- Whether the D24V10F3-class 3.3 V regulator has an EN pin.
- AUD prices for the Wi-Fi adapter, the camera and the USB hub.
- The plate's actual output connector.
- Auto-MDIX on the Pi 4 PHY (irrelevant for gigabit).
