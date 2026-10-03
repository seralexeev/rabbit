# Hardware and software stack history (May 2025 – October 2026)

Period: 2025-05-18 to 2026-10-01. Sources: the public build log at https://rabbit0.dev (posts 1–163, 18-05-2025 to 30-08-2025), the git history of this repo, and what the agent sessions found on the robot on 2026-10-01.

## Context

Rabbit is a small rover on an RC car kit with Ackermann steering. The goal from the start was a robot driven over the internet, and then autonomous navigation.

## Hardware as of October 2026

| Part | What |
|---|---|
| Chassis | RC car kit with Ackermann steering; aluminium steering hubs and metal ball links replaced the plastic parts (blog #101, #93) |
| Compute | NVIDIA Jetson Orin Nano Super developer kit, 8 GB (7.4 GB usable), 6 cores, NVMe 915 GB, L4T R36.4.4 (JetPack 6), power mode MAXN_SUPER |
| Camera | ZED 2i, 2.1 mm lenses (serial 31819002, firmware 1523), on USB. Depth from about 0.3 m only, so there is a blind zone in front of the bumper |
| Drive | 2 × Pololu 37D 70:1 12 V gear motors at the rear, 37Dx70L with 64 CPR encoders, helical pinion (#4754, 4480 counts per wheel revolution; confirmed by the owner 2026-10-03; the old whiteboard says 37Dx54L, which is wrong), RoboClaw 2x30A (firmware USB Roboclaw 2x30a v4.3.6). The wheel encoders do not count (always 0), so speed comes from the camera pose |
| Steering | brushless servo (A50BHL) on a PCA9685 (I2C bus 7, address 0x40), 1000–2000 µs, centre trimmed to 1532 µs |
| Power | 99 Wh V-mount 4S Li-ion pack (16.8 V full, 14.8 V nominal) with its own BMS; buck converters for 12 V (RoboClaw), 6 V (servo) and the Jetson input; INA4235 4-channel monitor at I2C 0x41 with 10 mΩ shunts (channel 1 battery, channel 2 the 6 V rail; channels 3–4 unwired) |
| Network | Wi-Fi only: Realtek rtl88x2ce PCIe card (`wlP1p1s0`) |
| Geometry | wheelbase 0.1715 m, rear track 0.1674 m, 75 mm wheels; camera 0.137 m above the floor, 0.1845 m ahead of the rear axle and 0.06 m off the centreline; mass about 3.5 kg |

Not installed: the robot arm, the 4G/5G gateway and a lidar (all mentioned in the blog as plans). `model/` holds a CAD model of the chassis and `pcb/rabbit-board` a KiCad power/I-O board that exists only as a design (commit `b88c33b`, pushed 2026-10-01).

## Timeline

| Date | Change | Source |
|---|---|---|
| 2025-05-18 | Project start on a Raspberry Pi 4 with a PCA9685 for the servo | blog #1–4 |
| 2025-05-21 | RoboClaw does not stop when the controlling script dies; RC timeout and a command loop are needed | blog #6 |
| 2025-05-22 | Motors run over UART; a TXB0104 level shifter did not work for the 5 V RoboClaw RX | blog #7–8 |
| 2025-05-25 | First drive; Python script with joystick and RoboClaw threads; Docker Compose + uv | blog #29, #37, #40 |
| 2025-06-04 | Jetson Orin Nano Super chosen; flashing L4T to NVMe took several attempts with the SDK Manager | blog #70–75 |
| 2025-06-17 | WebRTC streaming and data channel control | blog #82 |
| 2025-07-03 – 07-07 | About a week on ROS 2 (git: `ros2_ws`, `rabbit-ros2`, foxglove bridge), then removed in favour of NATS (`cd31f6d nats`, `35794ec drop ros2`, 2025-07-04) | blog #115–121 |
| 2025-07-16 | ZED 2i arrives; streamed over NATS | blog #123 |
| 2025-07-18 | Jetson reports "System throttled due to over-current"; suspected voltage drop on a thin AWG22 barrel lead | blog #132 |
| 2025-07-21 | Drives on battery with remote control and 720p30 video | blog #148 |
| 2025-07-22 | No hardware H.264 encoder on the Orin Nano; camera work collapsed into one process | blog #150–152 |
| 2025-08-08 | NATS JetStream KV for camera settings | blog #158 |
| 2025-08-16 | First nvblox integration (nvblox_torch, torch 2.3.0 built for the Jetson, separate `rabbit-nvblox` container fed RGB+depth over NATS) | blog #160–162, git `abaf00c`…`abb35ef` |
| 2025-08-30 | Electronic differential calibrated | blog #163 |
| 2026-01-31 – 2026-04-09 | "wip" commits; the robot copy gained `node/perception.py`, `lib/occupancy.py` and `node/telemetry.py` | git |
| ~2026-05 | All containers stopped; the robot stayed off for about five months | `docker ps` on 2026-10-01 |
| 2026-10-01 | `b88c33b` pushes the chassis model, the PCB design and the robot-side perception node; the agent sessions start (see the following log entries) | git |

## Stack decisions that still hold

- **NATS instead of ROS 2.** Every node is a container running one Python file; messages are JSON or small binary formats on NATS subjects, with JetStream for the KV bucket `rabbit` and the `LOGS` stream. The reasons given in the blog (#117–119): ROS 2 build tooling (colcon, ament, CMake, package.xml) was too heavy for a one-person project, and a plain bus lets nodes be written in any language.
- **One camera process.** Only one process can open the ZED, and the Orin Nano has no hardware video encoder, so `rabbit-zed` owns the camera and does tracking, depth, mapping, obstacle scan, detection and preview.
- **Docker Compose on the robot** (`workspaces/compose.yaml`), code bind-mounted, deployed from the Mac with `scripts/deploy.sh`.

## State found on 2026-10-01

- `/root/rabbit` on the robot is not a git checkout; code arrives by rsync. Until the push of `b88c33b` the robot was ahead of GitHub.
- Published topics were few and slow: `rabbit.roboclaw` 10 Hz (speed and encoder only), `rabbit.ina` 1 Hz, `rabbit.telemetry` 1 Hz, `rabbit.sensor.bundle` (RGB+depth, 13.5 Hz, about 5.5 MB/s), a JSON costmap at 2 Hz (235 KB/s).
- About 75 GB of old Docker images (nvblox, WebRTC, test images) were left on the NVMe.

See `2026-10-01-revival-and-telemetry.md` for what changed next.
