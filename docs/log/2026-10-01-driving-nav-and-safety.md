# First autonomous driving: nav node, safety guard, steering calibration

Date: 2026-10-01, 10:34–21:55 UTC, with later changes on 2026-10-02/03 noted at the end. Robot on the floor with the owner's permission.

## Goal

Drive to a clicked point, including points behind the robot ("туда-сюда" multi-point turns), and never hit anything.

## Command path

- `lib/drive.py`: `rabbit.cmd.joy` (gamepad/keyboard from the HUD) and `rabbit.cmd.drive {speed, steer}` (autonomy). `CommandArbiter`: active joystick input outside the 0.08 deadzone owns the motors for 1 s (`JOY_HOLD`), joystick speed is capped at 50 %, manual input cancels a mission ("manual override").
- Kill switches: the roboclaw and steering nodes stop and centre after 0.25 s without a command; the RoboClaw's own serial timeout (0.5 s) stops the motors if the node or the link dies.
- `node/nav.py`: missions on `rabbit.nav.mission` `{id?, steps: [move | turn | goto | path], source}` (limits: 20 steps, 3 m per move, 8 m per goto), state on `rabbit.nav.state` at 10 Hz. The queue lives on the robot so it survives a closed browser and one cancel clears it.

## Calibration

| Test | Result |
|---|---|
| speed 0.20, 1.5 s | 0.138 m; deadband up to about 15 % duty |
| steer +0.5 / −1.0 | `steer > 0` turns right; first estimate of minimum radius 0.31 m |
| steering trim | heading change over 0.5 m: 3.75° untrimmed, 1.29° at +24 µs, 1.09° at +32 µs → `CENTER_TRIM_US = 32` |
| geometric differential (`wheel_speeds`, `REAR_TRACK = 0.1674`) | pure geometry reduced scrub but widened the minimum radius to 0.37–0.47 m; `DIFFERENTIAL_GAIN = 1.6` brought it back (R 0.40 m right, 0.30 m left at full lock) |

Right turns are wider than left ones (servo neutral offset). Separate tables `LEFT_CURVATURE_TABLE = [0, 1.70, 3.34]`, `RIGHT_CURVATURE_TABLE = [0, 1.33, 2.49]` 1/m at steer 0, 0.5, 1.0 are used everywhere: the differential, the safety arc, pure pursuit and the planner (`lib/geometry.py`).

## Safety guard and the wall crash

- `lib/safety.py`: `Footprint(front 0.2245, rear 0.07, half_width 0.10, margin 0.04)` from the rear axle; `free_distance` sweeps the footprint along the current curvature arc against the obstacle scan (`rabbit.zed.obstacle`, 48 bins over ±60°, obstacles 4–45 cm above the floor).
- **11:33 UTC: false collision fault** 0.1 s after start: the launch jerk measured 3.49 m/s², right at the 3.5 m/s² bump threshold. Raised to 5.0 m/s² with a 0.4 s grace after speed changes.
- **11:34 UTC: the robot drove into a wall twice.** The stop distance (0.15 m) was inside the camera's depth blind zone (no depth below ~0.3 m): the wall disappeared from the scan just before contact. Fix: stop at 0.3 m, remember obstacles in world coordinates for 4 s, stall detection at 1.8 A for 1 s. The next run stopped at 0.297 m.
- **Flying pixels** (20:46 UTC): a single depth point about 5 cm from the lens zeroed the free distance and the robot stood still or jerked. Fix (`bd45b98`): points closer than the blind zone are dropped and each scan sector uses its 4th-nearest point (`bin_scan`).
- **Floor reported as contact** (21:49 UTC): 84–91 % of "nearest contacts" were the floor, because heights were measured from a global floor estimate and 1° of tilt is 5 cm at 3 m. Fix (`ae34946`): `heights_above_floor` fits a floor plane in every frame (±8 cm candidates, 2 least-squares iterations, 2 cm inlier band).
- After a rejected mission all safety trips were silently disarmed; found by a review agent and fixed in `d458588`.

## Path following

- `path` step: pure pursuit over planner waypoints with gear changes (`PATH_LOOKAHEAD 0.35`, reverse at 0.22).
- Reverse drifted sideways by up to 10–15 cm because pursuit tracked the camera point, 0.18 m ahead of the rear axle. From `bd45b98` paths are tracked by the rear axle (`rear_axle_path`, `camera_point`); straight forward-and-back passes then deviated ≤ 4 mm, and path ends land within 3.5 cm (was 10–13 cm early).
- Reverse is weak (about half the forward speed) and ZED tracking degrades when reversing towards a wall, so the planner penalises reverse heavily.

## Later changes (2026-10-02/03)

- Planner-driven stop distances (`2026-10-02-route-planner.md`): nav stops at 0.15 m of free travel (it already creeps at minimum speed below 0.6 m) and resumes at 0.25 m; scan points within 0.4 m of the camera do not expire while they stay there, otherwise a robot held in front of a wall forgets it after 4 s and drives on (a simulator test pins this). A phantom point stuck in the blind zone is released after about 30 s (2026-10-02 22:15 UTC).
- `free_distance` drops far points first: 7 ms → 0.18 ms per call (nav used 20 % CPU while driving).
- The operator heartbeat dead-man was removed (`2026-10-02-operator-heartbeat-removal.md`).
- nav drives on the continuous `odom` pose (`2026-10-02-odom-map-split.md`).
- Motor slew limiting in the roboclaw node (`2026-10-03-motor-slew-limit.md`).

## Commits

`ac133e3`, `d458588`, `a90adf8` (pose published before obstacles, so nav no longer matched a scan to a pose one frame older), `8e419f9`, `bd45b98`, `ae34946`. Later work is uncommitted at the time of writing.
