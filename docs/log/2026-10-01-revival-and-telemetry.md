# Revival after five months and the telemetry rewrite

Date: 2026-10-01, 08:58–10:32 UTC (18:58–20:32 Sydney). Robot on a stand, no motion.

## Goal

Bring the robot back after about five months off, fix what was broken, and publish every signal the hardware can give at useful rates, so that a recorder (later Forge, see `2026-10-01-forge.md`) can store it in ClickHouse.

## What was done

**Nodes (`workspaces/rabbit/src`)**

- `lib/node.py` (`RabbitNode` base): `publish_json` stamps every payload with `ts` in nanoseconds of the robot's NTP-synced wall clock; `set_interval` no longer blocks `init()` (it was awaited and never returned, so nodes never reached `stop.wait()`); shutdown order is now cancel tasks → drain NATS → stop motors.
- A bare `except:` in the watcher and task wrappers caught `CancelledError`, so nodes never shut down cleanly and the ZED map was never saved on stop. Changed to `except Exception:`.
- `node/roboclaw.py` / `lib/roboclaw.py`:
  - `read_status` (command 90) expected 1 byte, firmware 4.x returns 4 bytes + CRC, so it always failed with "CRC mismatch". Fixed.
  - USB (`/dev/ttyACM0`) gave 376.6 reads/s with 0 errors against 119 reads/s with occasional CRC errors on the UART `/dev/ttyTHS1`. The port is chosen by `ROBOCLAW_PORT`, else the stable `/dev/serial/by-id/usb-Basicmicro_Inc._USB_Roboclaw_2x30A-if00`, else the UART. (Later the USB cable was unplugged and the robot runs on the UART again.)
  - Serial I/O moved to a thread; the node publishes at 50 Hz (per side command, PWM, current, speed, encoder; supply voltage, temperature, status). Later the same day the driver was rewritten as a compact module (about 2900 generated lines replaced): one I/O thread owns the port, the last command is resent every 100 ms, CRC errors are retried, reconnect after repeated errors, and the RoboClaw's own 0.5 s serial timeout is enabled as a hardware failsafe. `termios.error` was added to the serial error tuple, because a vanished USB port raises it.
  - Motor current zero offset is tracked while PWM is 0 (idle current went from −0.42/−0.18 A to 0 ± 0.05 A).
- `node/ina.py`: 1 Hz → 50 Hz; CONFIG1 written for hardware averaging; channels 3–4 disabled; 4S charge estimate `battery_charge_pct` from a 3.30–4.20 V per-cell curve. The RoboClaw's "battery voltage" (11.9 V) turned out to be the 12 V buck output and was renamed `supply_voltage`; battery voltage comes from the INA.
- `node/steering.py`: publishes `rabbit.steering` at 20 Hz.
- `node/zed.py`: `grab()` ran on the asyncio loop and starved timers; capture moved to a thread. New streams: `rabbit.zed.imu` (~110 Hz, the 400 Hz IMU averaged over ~10 ms), `rabbit.zed.magnetometer` (~50 Hz, not calibrated), `rabbit.zed.barometer` (~25 Hz; SDK altitude is garbage at 9263 m and is not published), richer pose and health.
- Camera settings bug: the node wrote the camera's current values into KV on first start, which pinned white balance at 4000 K with auto off (and `HUE=7`), so the picture was yellow. Defaults now come from the `CameraSettings()` model.
- ZED timestamps: after an NTP step at boot the camera clock kept its old base and rows were stamped up to 5.7 min in the past. `ts` is now the camera timestamp plus `clock_offset_ns` recomputed about once a second.
- NaN in JSON: Python writes `NaN`, which browsers reject; `publish_json` uses a `finite()` helper and `allow_nan=False`.
- `node/telemetry.py`: per-core clocks, GPU clock, rail power from jtop; later Wi-Fi (`WifiCollector`: signal, bitrates, gateway RTT, errors), host networking.

**Jetson clocks**

jtop showed the CPU at 729.6 of 1728 MHz (governor schedutil) and the GPU at 306 of 1020 MHz, which kept the ZED below 30 Hz (capture 34 ms per frame against 14.4 ms after). `jetson_clocks` fixed it; persistence came later with the `rabbit-performance` service (`2026-10-02-jetson-performance.md`).

**Rates before and after (2026-10-01 ~09:16 UTC)**

| Subject | Before | After |
|---|---|---|
| `rabbit.roboclaw` | 9.2 Hz | 49.9 Hz |
| `rabbit.ina` | 1 Hz | 50 Hz |
| `rabbit.steering` | — | 20 Hz |
| `rabbit.zed.pose` | not measured | 29.6 Hz |
| costmap (JSON → raw uint8 + NATS headers) | 235 KB/s | 74 KB/s |

**Web HUD access**

- `cert/` held a mkcert certificate from another machine's CA; it was reissued with the local CA for `jetson.rabbit`, `dev.rabbit` and `localhost`, and `scripts/ssl.sh` fixed to write `key.pem`/`cert.pem`.
- The HUD hung at "Connecting to NATS…" although `curl` worked. Tailscale was suspected and ruled out; the cause was Chrome's macOS local-network access permission.

## Open questions left that day

- The encoders read 0 in every mode, even with wheels turned by hand (RoboClaw in quadrature mode, connectors re-plugged). Suspected missing 5 V or wiring; unresolved. Navigation uses ZED odometry only.
- INA reads 25–31 W on the bench while the loads should sum to about 15–20 W. Not resolved.

## Files

`workspaces/rabbit/src/lib/node.py`, `lib/roboclaw.py`, `node/roboclaw.py`, `node/ina.py`, `node/steering.py`, `node/zed.py`, `node/telemetry.py`, `scripts/ssl.sh`. These changes were first committed in `ac133e3` (2026-10-01 14:17 UTC).
