# Relocalization problems, the millimetre-pose SDK bug and the fixes

Dates: 2026-10-01 10:57 UTC – 2026-10-02 23:09 UTC. Most fixes are uncommitted at the time of writing.

## Background

The camera uses ZED GEN_3 positional tracking with area memory: on start it loads `room.area` and tries to recognise the place (`spatial_memory_status` INITIALIZING/SEARCHING → KNOWN_MAP). Until then poses are in a temporary frame. Everything that depends on the global map (mapping, planner trips, saved places, object positions) has to wait for it.

## Evolution of the give-up rule

| When (UTC) | Rule | Why it changed |
|---|---|---|
| 2026-10-01 11:05 | none: relocalization after a reboot hung and the pose froze; a 6 A "stall" was really a frozen pose | add a timeout |
| 2026-10-01 11:05 | 15 s timeout, then start a clean map | on two failures in a row the single `room.area.previous` backup was overwritten and the big room map was lost for good (night of 2026-10-01) |
| 2026-10-01 14:18 | 30 s, archive of the last 5 maps (`e6e69d7`) | a robot staring at a wall should not discard the map |
| 2026-10-01 21:38 | 30 s counted only while the camera is moving (`02bbd54`) | the SDK reports `camera_moving_state = MOVING` while standing still: timeouts fired at 06:41, 07:47 UTC on 2026-10-02 |
| 2026-10-02 07:47 | motion counted only while SEARCHING + MOVING, plus a 120 s wall timeout | the wall timeout fired with the status stuck at INITIALIZING (07:56, 08:00, 08:03) |
| 2026-10-02 08:03 | give up only after the robot has driven 3 m without relocalizing | relocalized in 16 s on the next start |
| 2026-10-02 13:22 | relocalized only after a localized status holds for 10 s; steps over 1 m are not counted as travel | false relocalizations (below) |
| 2026-10-02 22:15 | plus: no relocalization within 45 s → archive and start a new map | a robot left facing a wall waited for ever; current state |

## Incidents and root causes

- **Millimetre poses (SDK bug).** For 2–3 s after relocalizing (once for a whole 11-minute session, once for 2 minutes while SEARCHING) the SDK returned translations in millimetres despite `coordinate_units = METER`: (−2803, 64, −3331) instead of (−2.80, 0.06, −3.33). On 2026-10-02 there were 21,576 such poses in 25 episodes. They reached nav ("Pose jump 1587 / 2063 / 2289 / 4340 m"), the planner, the HUD and Forge, and nvblox integrated them: the map of 11:02–12:32 UTC had obstacles where the robot had stood. Found offline from the Parquet export on 2026-10-02 13:17–13:21 UTC. Fix: `lib/geometry.plausible_position` drops poses with |y − floor| ≥ 3 m or |x|, |z| ≥ 200 m; the camera process restarts if they last 15 s outside relocalization; health counts `implausible_poses`.
- **False "relocalized".** After a restart the SDK goes INITIALIZING → KNOWN_MAP → (5–8 s later) INITIALIZING → KNOWN_MAP; the second window is the millimetre window. The old code treated anything other than INITIALIZING/SEARCHING as relocalized, so on 2026-10-02 10:46 UTC LOST counted and the camera ran 13 minutes without a real fix. Fix: `lib/relocalization.py` (10 s of KNOWN_MAP / MAP_UPDATE / OK / LOOP_CLOSED), a `relocalizing` field in `rabbit.health.zed`, and trips/place saves refused while it is true.
- **Smaller jumps.** Poses at about (70, 114) m with confidence 25–56 passed the 200 m bound (2026-10-02 22:02–22:07 UTC). `lib/pose_gate.py` `JumpGate`: a position is accepted within 0.5 m + 1.5 m/s × dt of the last accepted one; a distant pose that holds for 4 s is accepted as a real relocalization.
- **Area file saved while LOST.** At shutdown on 2026-10-02 13:16 UTC the 68 MB `room.area` was overwritten by an unlocalized session. Next morning the camera stayed INITIALIZING for more than 6 minutes; waking it to 30 fps, a 1 m drive and a 30° turn, a restart and even restoring the 74 MB backup did not help; the map was reset. Fix: the area map is saved only in mapping mode and only in a localized state.
- **Tracking lost its frame** when the robot was carried (2026-10-01 11:36): the world tilted 14°/12° with the robot 0.24 m under the floor, and that state was saved. Pose tilt is compared with the IMU; a mismatch of more than 8° for 3 s restarts tracking.
- **Re-enabling tracking in-process** after such a failure left the SDK broken and produced poses ~54 m away (2026-10-01 22:01 UTC). Since `2d49c37` the whole camera process restarts (Docker brings it back) and the failed session is not saved.
- **Runaway to z = −138 m** (2026-10-01 21:10–21:16 UTC) with no data to explain it; it overflowed the int16 map format.
- **Environment.** Relocalization fails facing the glass door, in front of a blank wall, or with evening light against a daytime map; turning the robot towards the room helps. Twice on 2026-10-02 (22:00, 23:09 UTC) it failed against a map saved minutes earlier with the robot not moving.

## Current state (2026-10-03)

- Full frame rate for the first minute and while relocalizing (relocalization 16–21 s typical; 64 s at idle frame rates).
- nav drives on a continuous odometry pose (`2026-10-02-odom-map-split.md`), so map corrections no longer jerk the steering.
- The SLAM survey concluded that this scaffolding patches a black box and proposed odom + an external global localizer; a benchmark is running (`2026-10-02-slam-survey-and-benchmark.md`).

Report: `docs/reports/2026-10-02-zed-camera-and-pose.md`.
