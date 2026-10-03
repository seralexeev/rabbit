# Jetson performance tuning, the clock-floor incident and the upgrade assessment

Dates: 2026-10-01 09:10 UTC – 2026-10-02 22:45 UTC. Board: Jetson Orin Nano Super developer kit (p3767-0003), L4T R36.4.4 (JetPack 6.2.1), CUDA 12.6, TensorRT 10.3, Docker 27.5.1.

## Boot-time tuning (`workspaces/jetson/rabbit-performance`, `rabbit-performance.service`)

| When (UTC) | Change | Why |
|---|---|---|
| 2026-10-01 09:10 | `jetson_clocks`: CPU 1728 MHz × 6, GPU 1020 MHz, EMC 3199 MHz | under schedutil the CPU sat at 729.6 MHz and the ZED could not hold 30 fps (capture 34 ms vs 14.4 ms) |
| 2026-10-01 11:17 | oneshot service at boot: clocks, USB autosuspend off, Wi-Fi power save off | USB autosuspend (2 s) suspected in RoboClaw USB drop-outs; power save caused 1.5 s ping |
| 2026-10-01 11:17 | a first version ran `nvpmodel -m 0` assuming 0 = MAXN; on this board 0 is 15 W (2 = MAXN_SUPER). Reverted immediately | mode ids are board-specific: read `/etc/nvpmodel.conf` |
| 2026-10-02 00:02 | interrupts pinned: camera USB (xhci) → CPU2, RoboClaw UART → CPU4, I2C → CPU5 | every IRQ landed on CPU0, which ran at 100 %; after the change CPU0 32–59 %. The Wi-Fi interrupt (PCIe MSI) cannot be moved |
| 2026-10-02 00:02 | PCIe ASPM `performance`, `vm.swappiness=10` | Wi-Fi card on PCIe could sleep (unverified effect); about 1 GB was in swap |
| 2026-10-02 00:05 | headless: `multi-user.target`, GNOME and x11vnc off | about 300 MB RAM freed, swap 1005 → 551 MB |
| 2026-10-02 06:00 | UART IRQ pinned by device-tree hwirq | pinning by name in `/proc/interrupts` silently failed after every boot, because the serial port is not listed until it is opened |
| 2026-10-02 22:45 | `nvpmodel.service` drop-in (`workspaces/jetson/nvpmodel-rabbit.conf`: `RemainAfterExit=yes`, `ExecStartPost=/usr/bin/jetson_clocks`) | see the incident below |

Commit: `0b91121` (IRQs, ASPM, versioned script), `fd61834` (headless). The hwirq pinning and the drop-in are uncommitted at the time of writing.

## Incident: 85 minutes of low clocks (2026-10-02 00:06–01:30 UTC)

- Symptom in Forge: CPU at 730–1574 MHz, GPU 306–714 MHz for about 85 minutes; ZED capture fell from 29.6–30.0 to 26.5–28.5 fps. First attributed to over-current throttling.
- Root cause (power-throttling investigation, 2026-10-02 22:45 UTC): switching to headless ran `systemctl isolate multi-user.target` at 00:06:06. `nvpmodel.service` is a oneshot without `RemainAfterExit`, so `isolate` re-ran it and it restored the MAXN_SUPER default floors (CPU min 729.6 MHz, GPU min 306 MHz). `rabbit-performance` has `RemainAfterExit=yes`, stayed "active" and did not re-run. Evidence: Tj ≤ 58 °C, battery 15.6–16.7 V, power lower than before, and the floors exactly equal to the nvpmodel defaults. It ended with the next reboot.
- Fix: the drop-in above. Rule: never run `systemctl isolate` or `nvpmodel -m` on the live robot.

## OC3 events

`soctherm_oc` hwmon counts OC3 events: about 355,000 in 7.4 h of uptime at one point; 1–2/s typically, up to 28/s in another sample. OC3 is NVIDIA's throttle on instantaneous VDD_IN power (25 W threshold in MAXN_SUPER). Each event halves CPU/GPU clocks for about 1 ms; in total about 0.9 % of the time at half clock, about 0.5 % of performance. OC1 (under-voltage) and OC2 (average power) are 0; VDD_IN never below 4.936 V; no correlation with motor current (−0.03). NVIDIA describes OC in MAXN as expected and not to be disabled. Forge records the requested frequency, not the actual one, so it cannot see these dips (actual clocks and OC counters in telemetry are recommended, not done).

## Load picture

- Average power 10–12 W, peak 17.1 W; Tj max 60.6 °C; no thermal throttling.
- `rabbit-zed` dominates: p50 1977 MB / max 4651 MB RSS over 1–2 Oct before nvblox; 20–45 % CPU standing in localization mode, about 175 % driving, up to about 280 % exploring in mapping mode.
- The `uv run` wrappers of the nine Python nodes cost about 240 MB PSS; on 2026-10-02 23:09 UTC the compose commands became `uv sync --quiet && exec .venv/bin/python …`, and used RAM after a full deploy was 3.8 GB (was 4.4–6.4 GB).
- NVMe: 93 unsafe shutdowns out of 104 power cycles. The RTC does not keep time (likely no battery): the robot boots with a wrong clock and containers start before NTP, so Forge records the first seconds hours off. The journal is not persistent.

## JetPack upgrade assessment (2026-10-02 22:21–22:32 UTC)

- Don't upgrade now. The GPU is 20–25 % loaded; the bottlenecks are RAM and CPU, and none of the current problems (camera USB errors, SDK stalls, OC3, Wi-Fi) would be fixed.
- The apt cache held L4T 36.4.7 with a known CUDA regression; the `nvidia-l4t-*` packages were put on hold (50 packages held).
- From r36.5 UEFI enables DMA on `serial@3100000` (`/dev/ttyTHS1`, the RoboClaw UART) and zeroes the first bytes of each receive; on JetPack 7 / R39.2 on the Orin Nano Super the UART TX pin does not drive. Motor control would break without a device-tree overlay.
- Worth doing: Python 3.12 (with nvblox v0.0.10) on the current JetPack, estimated 1–3 days and 10–25 % less CPU for the Python nodes (Python 3.10 reaches end of life on 31 October 2026); JetPack 6.2.3 later for a boot-hang fix relevant to hard power-offs, after the UART workaround is tested on a stand; JetPack 7 not before 2027.

## Not done (recommended by the audit)

Remove snaps that update themselves on the live robot; prune about 77 GB of old Docker images (each `--build` deploy leaves an ~11 GB image); persistent journal; RTC battery; actual clocks and OC counters in Forge.

Reports: `docs/reports/2026-10-03-jetson-audit.md`, `docs/reports/2026-10-03-power-throttling.md`.
