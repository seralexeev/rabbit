# Roadmap

What to do next, in order. Update it when an item is done or priorities change; details and evidence live in `docs/log/` and `docs/reports/`.

## When the robot is back on (needs the owner)

Run these with `scripts/bringup.py` (`check`, `deploy`, `diet`, `forge-cutover`, `motion --motion`, `loc-shadow`; see the rabbit-robot skill); it writes a report to `data/bringup/`.

1. **Deploy and verify today's offline work** (only named services until the Forge cutover):
   - `scripts/deploy.sh rabbit-zed rabbit-nav rabbit-planner rabbit-explore rabbit-roboclaw rabbit-ina rabbit-telemetry rabbit-web`;
   - power: `power.calibrated` arrives from rabbit-ina with 10 mΩ / SHUNT_CAL 512 on both channels, `roboclaw.duty_max` = 1 on the 12 V buck, `battery_clipped` is set on hard starts above 7.37 A (`log/2026-10-03-phase-0-tools.md`);
   - run the nvblox tests in the container (`docker exec rabbit-zed sh -c "cd /rabbit && uv run -q --with pytest python -m pytest tests/test_nvblox_mapper.py -q"`);
   - a camera restart during a mission ends it with `odometry reset`;
   - `odom_rejected` and `held_poses` stay ~0 while driving;
   - explore 8–15 m on a fresh map with `MAX_INTEGRATION_DISTANCE` 5 m: the clearance grid shows no phantom obstacles on open floor;
   - a chat "drive to the fridge" with approval after ~60 s still runs (2 min window);
   - the new path tracker (curvature feedforward + lateral/heading feedback; pure pursuit removed) on a few trips, then cruise duty 0.35 (0.16 m/s); 0.45–0.5 only after checking pose confidence at speed;
   - exploration with the information-gain planner (`lib/exploration.py`) from a fresh map in another room;
   - `bash workspaces/jetson/diet.sh --dry-run`, then for real; recreate rabbit-telemetry (debugfs mount for the throttling counters);
   - observability (needs the Forge cutover for the new tables): every node sends `node.start` with the deployed `git_rev`; rabbit-zed events (`camera.opened`, `camera.relocalized` with its duration, `map.saved`, `camera.restart` on a map reset) arrive, since that code was only compiled on the Mac; `nats_server` rows and `jetson.ram_shared_bytes` appear; `node_health` shows the probe and metrics cost per node on the Jetson (expected ≈ 0.3 % of a core) and `events_dropped = 0`; a gamepad takeover gives `drive.owner_changed` and a stopped sender `motors.command_timeout`; run the evals `why_nav_stopped`, `camera_restarts_per_boot`, `exploration_decisions`.
2. **Forge cutover** to Parquet + chDB following `reports/2026-10-03-forge-cutover-runbook.md` (eval before, history import, switch, eval after, Jetson RSS/latency). Remove ClickHouse only with the owner's OK.
3. **Recordings for the localization benchmark** (`workspaces/bench/README.md`, "Recording sessions"): tape markers, an ~8 min mapping drive, wake sessions per marker in two lighting conditions; every recording ≥ 14 fps.
4. **rabbit-loc shadow mode** (RTAB-Map global localization over ZED VIO odometry) for a day, then switch and delete the GEN_3 area machinery.

## Next development (offline-capable)

- **Localization**: finish rabbit-loc (map←odom, multi-session DB, wake-anywhere), nvblox in the map frame with block rebuilds on corrections; then cuVSLAM as the odometry candidate (2.5 ms/frame on the Jetson) once its IMU parameters are tuned.
- **Observability follow-ups** (`reports/2026-10-03-observability.md`): events in rabbit-loc once it leaves shadow mode; a metric-graph node for event-loop stalls; an `investigate` focus on `events`.
- **Python 3.12** for the robot image: staged as `reports/2026-10-03-python312.patch` (apply together with an image rebuild; rabbit-loc's Dockerfile too).
- Done offline on 2026-10-03, waiting for the robot: exploration finishes the current room before leaving (tail after 90% −52%), full-stack simulator (`scripts/sim.sh`), scans anchored at capture time, reverse penalty outside the driven corridor, recovery rework, new tracker, faster cruise, exploration planner, chat evals 39/39 (local times, trip and exploration slabs, find_object routing), throttling telemetry, Jetson diet script, deploy prunes dangling images.
- **Detector recall**: the fridge needed several passes to collect detections. The detector now reads results every 2nd frame while moving (was every 4th); next, evaluate classes and thresholds on dumped frames (needs `data/detector/detector.onnx` from the robot).

## Hardware and environment

- **Rabbit 2.0 proposal** (`reports/2026-10-03-architecture-2.0.md`): Raspberry Pi 4 as the body (motors, servo, power, independent safety loop, lidar/ToF, rear camera, Forge, HUD, H.264 video), Jetson as the brain (perception, localization, planning), a direct Jetson–Pi cable and home Wi-Fi via a USB adapter with an external antenna (4G via the Teltonika TRB246 postponed by the owner), 2D lidar + ToF + bumpers, the existing wheel encoders wired to the RoboClaw, separate DC-DC and a soft power button.
- **Rabbit 2.0, buildable** (2026-10-03; BOM, wiring, body software and a per-phase plan with acceptance checks in `reports/2026-10-03-architecture-2.0*.md`, diagrams `reports/media/wiring-2.0-*.svg`). Next steps, in order:
  1. Phase 0, no purchases (procedure: rabbit-robot skill, "Phase 0 on the robot"; tools and checks: `log/2026-10-03-phase-0-tools.md`):
     - read the INA4235EVM shunt markings; if one isn't R010, set `INA_SHUNT_OHMS` for rabbit-ina (history rules out a battery shunt above ~20 mΩ, not a smaller one);
     - RoboClaw max current 3 A/channel saved to NVM: `workspaces/rabbit/tools/roboclaw_config.py plan`, `apply --yes`, power-cycle, `read` shows 3.00 A;
     - rewire the encoders, then `tools/roboclaw_encoders.py --distance 1.0` while rolling the robot 1 m by hand (19,014 counts/m ± 3%, forward counts up);
     - find what feeds the Jetson.
  2. Owner answers the open questions in the report (Pi RAM, plate output, UART vs USB for the RoboClaw, button, how `jetson.rabbit` resolves).
  3. Body PCB (`reports/2026-10-03-body-pcb.md`, `pcb/rabbit-body/`): designed, reviewed and fixed (`reports/2026-10-03-body-pcb-review.md`), DRC clean, Gerbers/BOM/CPL in `pcb/rabbit-body/fab/`. Before ordering: source PCA9685 (0 at LCSC) and INA4235 (1 pc) — P15; owner answers §12 (deck 1 standoffs 45 mm, Pi cooler ≤ 35 mm, ribbon 5 V) and Q24–Q27; check CPL rotations in JLC's preview; redo the ZED grommet for the 11.1 × 18 mm cut-out.
  4. Order the parts (~A$825); print the mounts (`cad/brackets/README.md`: 13 parts, ~7.5 h PETG + TPU grommets; brass 45 mm standoffs bought) after measuring the M-items in `docs/open-issues.md`; decide where the USB hub goes (the §10 place does not fit the real hub). Then phase 1: the Pi with NATS hub + leaf, moving ina/steering/roboclaw one at a time, `rabbit-safety` in shadow.
  5. Later code changes (per-channel shunts, the `clipped` flag and the duty cap 12 V / V_supply are done offline, see the phase 0 log):
     - ALERT registers and channels 3–4 in `ina.py`;
     - `roboclaw_config.py apply --yes --battery --estop` once the RoboClaw is on the pack and the E-stop line is wired (phase 2);
     - `rabbit.safety.drive` as the command subject for roboclaw and steering;
     - new nodes: safety, lidar, tof, power, video, odom;
     - with the bumpers on, the footprint grows to front 0.2452 m, rear 0.072 m, half width 0.102 m (`lib/safety.py` `Footprint`, `lib/planner.py` `front_overhang`); sensor poses for `T_base_lidar` / ToF in `cad/brackets/README.md`;
     - `deploy.sh` targets `body` and `brain`.
- **BLDC drive** (study 2026-10-03: `reports/2026-10-03-bldc-drive.md`, log `log/2026-10-03-bldc-drive.md`). The current 70:1 tops out at 0.59 m/s with 8× more torque than traction allows. In order:
  1. Measure: which 37D is fitted and the free length between the motor ends (open-issues M5), plus phone dB(A) and spectrum at 30 cm at 0.16 / 0.3 / 0.5 m/s.
  2. Owner decision (open-issues): first step Pololu 37D 19:1 #4751 on the RoboClaw (drop-in, ~1.57 m/s, US$140, speed mode with a 4 A limit), and/or straight to BLDC.
  3. Ask sellers (ASLONG, Chihai, NFP) for a bare JGB37 BLDC (3-phase + Hall, 12 V, 18.8:1, 6 mm D, 7 mm offset, double shaft); order 3 samples, plus 2× SimpleFOC Mini, an STM32G474 board and 2× MT6701.
  4. Bench one motor, then both on the robot via modules. The firmware speaks the RoboClaw packet-serial subset, so `roboclaw.py` and `rabbit.roboclaw` stay unchanged. Acceptance tests are in report §10, including ≥ 6 dB(A) quieter at 0.5 m/s.
  5. Body PCB rev B: STM32G474 + 2× DRV8316CR in the RoboClaw spot, BKIN/nSLEEP hardware E-stop, a 17.6 V brake chopper, solder jumpers to fall back to the RoboClaw (report §8).
- Wi-Fi in the far room (−74 dBm, AP disassociations with reason 34): external antennas or an AX210 card, or a second access point.
- Power (see "Силовая часть" in `reports/2026-10-03-architecture-2.0.md`, diagram `reports/media/power-2.0.svg`): check whether the Jetson barrel shares the motors' 12 V buck (it hits its ~4.5 A limit, 11.3 V, and may explain the mid-manoeuvre reboot on 1 Oct); set RoboClaw current limit 3 A/channel (phase 0 tool) before ever feeding it straight from the battery (max duty 0.71 is now applied in `roboclaw.py` from the supply voltage); battery shunt 10 mΩ caps at 8.19 A (peak seen 7.64 A; `power.battery_clipped` flags readings from 7.37 A): use an external 2 mΩ on ch1 and 5 mΩ on ch3 (motors); wire INA channel 4 to the Jetson's 12 V side (channel plan in `reports/2026-10-03-architecture-2.0-wiring.md`); the Pi's DS3231 keeps time (the dev kit has no RTC connector fitted).
- Encoders read 0 (speed comes from the pose); magnetometer uncalibrated.

## Decided, don't revisit without new evidence

- Keep our own Hybrid A* (Ackermann with asymmetric turning) instead of Nav2; keep nvblox as a library.
- No JetPack 7 before 2027 (UART for the RoboClaw broken on L4T ≥ 36.5 and JP7, little gain for us); `nvidia-l4t-*` packages are held.
- NEURAL_LIGHT depth (NEURAL FP16 is slightly cleaner but takes 3× the GPU memory; INT8 is noisier).
- The HUD is a viewer: nothing on the robot depends on it.
