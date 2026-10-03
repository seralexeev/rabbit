# Lag hunt and the Wi-Fi investigation

Dates: 2026-10-01 13:50–14:12 UTC (lag hunt), 2026-10-02 11:16–12:31 UTC (Wi-Fi changes), 2026-10-02 23:02 – 2026-10-03 00:01 UTC (drops during manual driving). The robot is connected only by Wi-Fi, by the owner's decision: no separate control link.

## Symptom

"Лаги реально огромные": control and video lagged by up to seconds. From the Mac on 2026-10-01 13:51 UTC: preview latency p95 917 ms, max 6021 ms; IMU max 5551 ms; roboclaw p95 500 ms.

## Root causes (2026-10-01)

1. **The mesh filter held the GIL** in the camera process for 0.5–2 s (pose fell to 6.6/s) and made the whole map resend every 3 s (870 KB/s, 85 % of the traffic). Removed from the live loop; map work capped at 5 % of the time.
2. **The telemetry node blocked its event loop** with `jtop.ok()`: that connection's NATS RTT was 2.36 s. Moved to `asyncio.to_thread`.
3. **The router dropped the robot every 10–30 s** (45 disconnects per hour, `CTRL-EVENT-DISCONNECTED reason=34`, "excessive frame losses / poor channel conditions"), although the signal was −40 to −50 dBm. The Realtek driver re-enabled power save after every reconnect; a global NetworkManager setting did not stick. Fixed by pinning power save off in the connection itself and setting the regulatory domain to AU (was `00`). Result: 0 disconnects in 10 minutes. Earlier the same evening Wi-Fi power save had pushed ping to 1.25–1.79 s.

Inside the robot after the fixes: NATS RTT p50 0.4 ms; pose 30/s p95 65 ms; preview p50 62 / p95 82 ms. Control round trip from the Mac (drive command to its echo in `rabbit.roboclaw`): p50 15 ms, max 48 ms (was 0.5–1 s).

**Dead end:** forcing 2.4 GHz gave −74 dBm and ping max 1582 ms; reverted (done with an automatic revert timer, since Wi-Fi is the only link).

Rare 300–600 ms stalls remained (2–5 % of packets). Measuring on the robot and from the Mac separately showed the robot side at 1–60 ms p50 and the rest on the link.

## Second round (2026-10-02)

A Wi-Fi subagent found the problem on the **transmit** side: the router heard the robot at −78 dBm, 13–23 dB worse than any other device, and had dropped it 28 times that boot. The `rtl88x2ce` driver ignores the country code (module parameter and `/proc` both leave `alpha2:00`, channel plan 0x7F) and transmitted at about 10–12 dBm.

Changes, with the owner's approval:
- Router 5 GHz fixed to channel 48, 80 MHz (160 MHz briefly lost SSH and was worse).
- Driver `rtw_tx_pwr_lmt_enable=0` in `/etc/modprobe.d/rabbit-wifi.conf`: TX power 12 → 25 dBm. The owner accepted that this exceeds the Australian limit. Module reloads were done by a script that rolls back if the gateway stops answering.
- Uplink right after the change about 70–75 Mbit/s; minutes later only 16–19 Mbit/s at the same signal (−71/−72 dBm). Not explained.

## Third round (2026-10-02 23:02 – 2026-10-03 00:01 UTC)

During manual mapping drives in the far part of the flat: signal −74/−75 dBm, ping avg 104 ms (max 334 ms), joystick messages arriving in bursts (432–606 per 20 s), the robot stopping when the HUD connection dropped, and at 23:54:54 UTC another `reason=34` kick (three reconnects). The robot looked hung but was fine; near the router it was −57 dBm / 351 Mbit/s. The Cloudflare tunnel's QUIC connections did not recover after the drop (`2026-10-01-public-access.md`). A motor slew limiter was added so bursts don't jerk the robot (`2026-10-03-motor-slew-limit.md`).

## Open

- Minimum-RSSI / band-steering settings on the router; antennas outside the metal plates; or a different card (Intel AX210) or a second access point.
- The NATS/Docker audit (`2026-10-02-nats-docker-latency.md`) concluded that Wi-Fi adds 1–3 orders of magnitude more latency than NATS or Docker.

## Diagnostics

`journalctl -b | grep CTRL-EVENT-DISCONNECTED`, `iw dev wlP1p1s0 link`, `ping -c 300 -i 0.1 192.168.1.1`; Wi-Fi telemetry is in `rabbit.telemetry` and the Forge `wifi` table (slab `wifi_health`).
