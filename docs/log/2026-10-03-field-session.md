# 2026-10-03 field session: boot, recordings, safety and map quality

Date: 2026-10-03, 21:45 UTC (2 Oct) – 02:05 UTC. Robot on the floor, owner present, motion allowed. Everything below is deployed unless noted; nothing committed.

## Boot after the overnight shutdown

- `docker compose stop` before `shutdown` left every container stopped after boot (restart policy `unless-stopped`). Shut down with plain `shutdown -h now` instead: Docker stops containers gracefully (zed saves its map on SIGTERM) and they start again on boot.
- The robot had been carried to another room. GEN_3 stayed `INITIALIZING` for 10+ minutes, through restarts, a full-rate wake and 1.3 m of driving. Both the current `room.area` and the 23:15 backup had been saved after the camera went `LOST` near the fridge (68 MB vs 74 MB); neither relocalized. Fix: area files are exported only in mapping mode while the memory status is localized (`_save_map`); in localization mode the area is never rewritten.
- With no HUD open the camera idles at 1 fps; relocalizing against a fresh area took 64 s. The first 60 s of a relocalization now run at full rate (16–22 s observed). Explore and the planner publish `rabbit.zed.wake` before they need poses (they used to fail with "no pose" because poses arrived 1 s apart).
- Relocalization now gives up after 45 s without a localized status and starts a new map (archiving the old one), unless a localized status was seen in the last 20 s (the SDK re-initialises once after the first KNOWN_MAP). Driving 3 m without relocalizing still gives up too.
- A static robot never integrated depth (the integration skipped `STATIC` frames), so a fresh map stayed empty and explore failed with "no map from the camera". Static frames are now integrated every 2 s.

## Pose gating

- The millimetre-pose glitch also hit a robot near the map origin: (70, −0.27, 114) passed the absolute bound (|x|, |z| < 200 m, |y − floor| < 3 m). `lib/pose_gate.JumpGate` holds any pose that jumps further than 0.5 m + 1.5 m/s × min(dt, 1 s) from the last accepted one; a jump that holds for 4 s is accepted (a real correction), one that comes back is dropped. Health counts `held_poses`.
- Odometry for nav (`odom` in the pose message) chains `get_position(CAMERA)` deltas, updated on every SDK-OK frame before the gates, with a step guard of 5 cm + 1.5 m/s × dt. On a 2.8 m drive with a 90° turn it stayed within 3 mm of the map pose.

## Recording the mapping drive

- First manual drive: the camera process died after ~70 s with `cudaMallocAsync … out of memory` in nvblox (RAM was at 6.2–6.5 of 7.4 GB). Then 3 m of driving without relocalization started a new map.
- `uv run` wrappers (one per node, 8–38 MB each, ~135 MB total) were replaced by `sh -c 'uv sync --quiet && exec .venv/bin/python …'`; RAM after deploy 3.8 GB (was 4.4).
- Second drive: 7.8 min, 2.6 GB, but only ~4.5 fps (2098 frames, gaps up to 1 s). LOSSLESS SVO compression runs on the CPU (no NVENC on Orin Nano) and competed with tracking, nvblox and the detector. Recording now pauses the detector and nvblox integration and logs frames/fps on stop. Not yet re-recorded.
- Mid-drive the router disassociated the robot (`reason=34`, poor channel; −74 to −75 dBm in the far room). The HUD lost NATS and the robot stopped receiving gamepad commands; the recording continued. The Cloudflare tunnel stayed down after the reconnect (QUIC retries); switched to `--protocol http2`.

## Driving feel and safety

- Gamepad driving was jerky: commands arrive in bursts over Wi-Fi and rabbit-roboclaw zeroed the motors 250 ms after the last one. Now: slew limiter (accelerate 1.5/s, brake 5/s) and a 0.4 s timeout.
- The operator heartbeat stop was removed entirely: autonomous trips faulted with "operator link lost" whenever the HUD tab was hidden. The HUD is a viewer.
- `SENSOR_PUBLISH_S` 0.05 → 0.01 (IMU latency −25 ms per the latency audit) left ~1 sample per message; floor vibration reached 8–10 m/s² and tripped `collision` (threshold 5) on open floor. Nav now averages 50 ms.
- A planner recovery ("backing up along its trail") reversed into an unseen wall for 70 s: duty 17%, current 0.5–0.7 A, below the 1.8 A stall threshold, pose static. Nav now trips `stuck` when it commands motion and the pose hasn't moved for 2.5 s.
- Explore asked for an in-place turnaround; the planner produced a loop ending 7 cm from its start and nav declared it finished at once (the end was within lookahead and "behind"), forever. A path now finishes only when less than the lookahead remains along it.

## Map quality

- Raising `MAX_INTEGRATION_DISTANCE` from 3.5 to 5 m (so the kitchen island at 4.3 m appears) filled the clearance grid with phantom obstacles: the planner reported "obstacles where the robot stands" on open floor and the fridge trip failed. A 1° pose pitch error lifts the floor 7 cm at 4 m, above the 4 cm obstacle band. The depth kernel now drops near-floor points beyond 2 m (band 3 cm + 2 cm per metre of range); a regression test integrates a floor through a 1° pitch error and a wall at 4.5 m. Back at 5 m.

## Other

- The chat answered "never seen" for the fridge: after a map reset it had 6 detections at 61% and Forge required 10. Now 3 detections suffice at ≥ 55% confidence.
- Chat motion approvals expired after ~30 s (handed to the Forge agent: ~2 min).
- HUD object boxes: ZED re-IDs the same object constantly (~480 IDs in 10 min); the HUD now merges same-label overlaps, draws only labelled boxes and forgets objects that should be visible but aren't. The detector publishes a track after 3 hits, with per-class confidence thresholds and per-class box depths.
