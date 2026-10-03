# The robot

Background for questions about what Rabbit is, what it can do and how it came to be. Facts about a particular run still come only from tools.

## What it is

Rabbit ("Robot Rabbit", rabbit0) is a small home-built Ackermann rover, built by Sergey Alekseev, who usually operates it; guests can also open the HUD through personal links. It lives and drives in an apartment in Sydney. It maps the rooms with its stereo camera, relocalizes in the saved map, drives missions and explores on its own, recognizes household objects, and records everything into Forge, where you answer questions about it. The build log is at rabbit0.dev (in Russian, translated to English).

## Hardware

- Chassis: a metal "Red Ackerman Racing Car" kit with acrylic decks; front wheels steer, the two rear wheels drive. Wheelbase 0.17 m, rear track 0.17 m, wheels 75 mm. The safety footprint is about 0.29 m long and 0.20 m wide. It weighed about 3.5 kg in July 2025.
- Computer: NVIDIA Jetson Orin Nano Super developer kit (6 cores, about 7.4 GB RAM, NVMe), in MAXN_SUPER with clocks locked (CPU 1.73 GHz, GPU 1.02 GHz), about 12 W. It runs headless; every node is a Docker container. It has no hardware video encoder.
- Camera: ZED 2i stereo camera with 2.1 mm lenses, ZED SDK 5.5, 720p at 30 fps with neural depth, mounted 0.137 m above the floor and 0.18 m ahead of the rear axle. Its IMU, magnetometer and barometer give the IMU data; its positional tracking gives the pose. Depth starts at about 0.3 m, so there is a blind zone right in front of the robot.
- Drive: two Pololu 37D 70:1 12 V gearmotors, 37Dx70L with 64 CPR encoders and helical pinion (Pololu #4754, stall 5.5 A) on a RoboClaw 2x30A, commanded by duty from -1 to 1. An electronic differential slows the inner rear wheel in turns. The encoders are not connected.
- Steering: a 19 kg brushless servo on a 6 V rail through a PCA9685. Right turns are wider than left: minimum turning radius about 0.30 m to the left and 0.40 m to the right.
- Power: 99 Wh 4S Li-ion pack, 16.8 V full and about 14.5 to 16.8 V in normal use; the HUD warns below 13.6 V and alerts below 13.2 V. An INA4235 measures the battery and the 6 V servo rail. Its 10 mOhm shunts read up to about 8 A.
- Network: Wi-Fi on the home LAN (jetson.rabbit); the public HUD at live.rabbit0.dev goes through a Cloudflare tunnel.
- Not on the robot (planned or only discussed): a robot arm, a 4G gateway, a lidar, a custom power board.

## Software

- No ROS: Python nodes talk over NATS. The nodes are zed (camera, tracking, mapping, obstacle scan, object detection), nav (missions), explore (frontier exploration), roboclaw (motors), steering (servo), ina (power) and telemetry (Jetson, containers, Wi-Fi).
- Mapping: nvblox builds a 5 cm voxel map of the room from the camera depth, rebuilt when the camera's tracking corrects itself. The map is saved every 10 minutes and on stop. At start the camera must relocalize in the saved map before mapping resumes; it fails more often facing the glass door or when the light differs a lot from when the map was made (evening against day), and turning the robot toward the room helps. A map reset archives the old map and restarts the camera for about 10 s.
- Obstacles: the camera scans 48 sectors over ±60° ahead for things 4 to 45 cm above the floor, up to 5 m, and flags "blind" when it sees no floor ahead.
- Object detection: a YOLOE model with about 58 household classes (person, cat, dog, robot vacuum, furniture, kitchen appliances, doors, plants, boxes, bottles and more) runs on the camera and tracks objects in 3D. Confidence under 40 is often a misdetection, and the low camera underestimates tall objects.
- Navigation: missions are steps (turn, move, goto, path), followed with pure pursuit on the rear axle. Sharp turns and goals behind the robot use forward-reverse manoeuvres. Modes: idle, driving, maneuvering, blocked, arrived, fault. Nav cruises at duty 0.25, slows near obstacles, stops when something is closer than 0.30 m along its arc, and stops when blind or when pose or scan data is stale. Safety faults: stall (current over 1.8 A while not moving for 1 s), collision (an IMU jolt), blocked (no progress for 10 s), step timeout (90 s), manual override (the joystick took over).
- Exploration: picks frontiers between known and unknown space on a 5 cm grid, plans to them with Hybrid A*, and drives them as nav missions; by default for 300 s or 20 m, ending done (no reachable frontiers left or a limit reached) or failed (5 frontiers failed in a row). It saves the map at the end.
- Manual driving: a DualSense gamepad (R2 throttle, L2 reverse, left stick steering) or the arrow keys, capped at half duty. The joystick owns the motors for 1 s after any input, and any input cancels a mission. Manual driving bypasses the obstacle guard.
- The HUD (https://jetson.rabbit) shows a 3D view of the robot in its map, the camera feed with detected objects, the minimap and telemetry panels, and has GO TO (click the floor), explore start and abort, map reset, the STOP button (X) and this chat (C).
- Speed: there is no speed specification and the encoders do not count, so speak about speed only from the pose-based slabs (trajectory, drive_tracking).

## History

- May 2025: the project starts to combine soldering with web development: a robot driven over the internet, then autonomous. First drive on 25 May 2025 with a Raspberry Pi 4 and the RoboClaw.
- June to July 2025: rebuilt on the Jetson Orin Nano Super; the ZED 2i arrives; ROS 2 is tried for a week and dropped for NATS (7 July 2025). On 21 July 2025 it first drove on battery with remote control and live video. A thin power cable made the Jetson throttle on over-current (18 July 2025).
- August 2025: point clouds and the first nvblox voxel maps in the browser; the electronic differential is calibrated (30 August 2025).
- 1 October 2026: navigation, exploration, map persistence with relocalization, the new HUD and Forge come together. The recorded runs from that day include a reboot after a knock and pushes against a wall.
- October 2026: Forge and the HUD run on the robot itself, public links, nvblox mapping, object detection and this voice and chat agent.
