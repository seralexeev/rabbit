# NATS and Docker latency audit

Date: 2026-10-02, 22:55–23:20 UTC. Read-only audit by an agent, plus probes on `bench.latency.*`. Robot on the floor, not moving (camera at 1–5 fps idle), with a benchmark container at about 88 % CPU and two full deploys during the window. Report: `docs/reports/2026-10-03-nats-docker-latency.md`.

## Question

Do NATS and Docker networking add latency that matters for control?

## Findings

- **Traffic:** about 320 msg/s, 180–330 KiB/s in total. `rabbit-zed` publishes 184 msg/s (267 KB/s); the largest messages are `rabbit.map.chunks` (up to 590 KB) and `rabbit.map.grid` (up to 243 KB). forge-writer and the HUD each receive about 315 msg/s. 0 slow consumers, 0 pending bytes.
- **On-robot transport:** p50 0.5–0.9 ms, p99 1–3.5 ms, mostly asyncio wake-up. Bridge vs host networking within ±0.3 ms; docker-proxy via 127.0.0.1 adds about 0.2 ms; a 2 MB message on the same connection raises small-message p99 from 1.7 to 3.6 ms. JSON costs 46 µs to encode and 16 µs to parse a pose.
- **Pose, camera frame → subscriber:** p50 46.6 ms, p99 about 77 ms; NATS is under 1 ms of it, the rest is exposure, USB, grab and tracking.
- **IMU/magnetometer/barometer:** p50 26–33 ms, p99 55–62 ms, caused by 50 ms batching in the camera process (`SENSOR_PUBLISH_S`); this also delays bump detection in nav.
- **Mac over Wi-Fi:** request-reply p50 11–14 ms, p99 about 340 ms with 2 s timeouts; after a Wi-Fi stall the server delivered pose data seconds late (p90 2.5 s), because it buffers up to 10 s / 64 MB per client. Signal −75 dBm, 6 disconnects in 10 minutes.
- **Docker:** no CPU limits on `rabbit-*`; forge-clickhouse throttled by its low CPU weight as intended and at its memory limit (10,419 events) without affecting the control path; no OOM kills.

## Applied

- `SENSOR_PUBLISH_S` 0.05 → 0.01 s in `zed.py` (expected −25 ms on IMU latency; not measured yet).
- `nats-server.conf`: `write_deadline` 10 s → 5 s, `ping_interval: 20s`, `ping_max: 3`. The suggested 2 s deadline was rejected: camera-process pauses of 1–2 s would make NATS drop its connection.

## Not applied

nav taking pose time from the message `ts` (would remove 37–80 ms of jitter from ground speed), a separate connection for bulk messages, websocket compression (measure first). Host networking and larger pending limits would not help.

## Conclusion

The robot's Wi-Fi adds one to three orders of magnitude more latency than NATS or Docker.

## History of NATS settings

- 2026-10-01 21:38 UTC: `write_deadline` 2 s → 10 s after the server dropped the Mac's clients as slow consumers during a Wi-Fi roam; long-lived clients (Forge writer and chat) ping every 5 s × 2 so dead links are noticed in 10 s instead of 4–6 minutes; `publish` drops and counts messages while reconnecting instead of raising (a NATS restart during a deploy had crashed `rabbit-zed`).
- 2026-10-01 20:07 UTC: nodes wait for NATS at startup instead of crash-looping at boot (`816c953`).
- Open: corrupted UTF-8 in some `rabbit.zed.obstacle` messages on 2026-10-01 and 2026-10-02 morning (124 messages, attributed to a race in the old obstacle worker; not repeated); a `MaxPayloadError` on the map grid on 2026-10-02 11:18 UTC before the grid was windowed.
