# Code review of the robot code changed since `b36435d` (3 Oct 2026)

Scope: the uncommitted `workspaces/rabbit` code: `node/zed.py`, `node/nav.py`, `node/roboclaw.py` with `lib/drive.py`, `node/planner.py`, `node/explore.py`, `lib/{trip,planner,navmap,safety,relocalization,pose_gate,detector,floor}.py` and `native/rabbit_nvblox/{module.cpp,depth.cu}`. The loc work (`node/loc.py`, `lib/loc.py`, the loc hooks in `zed.py`) belongs to another session. I only skimmed it. The robot was off during the review, so nothing was run on it and nothing is deployed or committed.

Tests: 100 passed, 1 skipped before the review; 109 passed, 1 skipped after it. Each of the 9 new tests failed with its fix reverted and passes with it. The command:

```sh
uv run --no-project --python 3.10 --with pytest --with numpy --with pydantic --with numba --with nats-py python -m pytest tests -q
```

`tests/test_nvblox_mapper.py` runs only on the robot. The native code was reviewed by reading it; I found no defect in it.

## High

### H1. nav kept driving a mission across a camera restart (fixed)

- **Where:** `node/nav.py:139-160` (`on_pose`), with `node/zed.py:850-856` (`_read_odom`).
- **Scenario:**
  - A `rabbit-zed` restart starts odometry again from the first pose of the new process (tilt mismatch, implausible poses, give-up, map reset or switching map mode). The old process's frame is lost.
  - Nav runs in the `odom` frame and re-anchors only in the `map` frame, so it saw no jump. While the camera was down it held the motors at zero, but it kept the mission (step timeout 90 s; paths get 15 s/m).
  - When poses came back it resumed with the goal, the path (including reverse segments) and the remembered obstacles in the old frame. It then drove toward a meaningless point.
  - The planner cancels its own trips only once health reports `relocalizing`, about 1 s later, and missions sent straight to nav (`move`, `goto`, `path` from Forge or the HUD) were never cancelled.
- **Fix:**
  - The `odom` object now carries `session`, which is new for every camera process.
  - When the session changes, nav drops the remembered obstacles and the old position. It trips `odometry reset` if a mission is running.
  - The planner treats that as a safety stop and ends the trip.
- **Test:** `test_a_camera_restart_mid_mission_stops_instead_of_driving_in_the_new_odometry_frame`.

## Medium

### M1. Odometry steps were checked for translation but not rotation (fixed)

- **Where:** `node/zed.py:828` (`_update_odom`), with the check moved to `lib/pose_gate.odometry_step_ok`.
- **Scenario:** if a heading correction ends up in the `REFERENCE_FRAME.CAMERA` delta, it is integrated into odometry. That brings back the steering jerk the odom/map split was built to remove (for example 10° is 35 cm of lateral error 2 m down the path). The translation part was bounded (0.05 m + 1.5 m/s·dt), the rotation part was not.
- **Fix:** also reject steps that rotate more than 2° + 120°/s·dt. That is about 6° per frame at 30 fps, while the robot turns at most about 50°/s.
- **Test:** `test_odometry_takes_a_fast_turn_but_not_a_heading_correction_folded_into_one_frame`.
- **Open question:** whether GEN_3 folds corrections into CAMERA-frame deltas at all is unverified; the guard costs nothing if it doesn't.

### M2. Any exception silently stopped mapping (fixed)

- **Where:** `node/zed.py:1355-1383` (`_map_loop`).
- **Scenario:**
  - The worker had no `try`. A CUDA error or out-of-memory in `integrate`, `_correct_stored_frames` or `save` raised as a Python exception would kill the thread.
  - After that the mesh and the clearance grid stopped updating, while health still said mapping OK. The planner would keep planning on a frozen grid.
  - The log of 2026-10-02 23:02 already has an nvblox CUDA out-of-memory.
- **Fix:** log the exception, set `mapping_state = "FAILED"` and restart the process (`_restart_process`, without archiving). This is the same policy as for tracking failures.
- **Test:** `test_a_failing_map_update_restarts_the_camera_instead_of_silently_freezing_the_map`.

### M3. `stored_frames` grew without limit during long sessions (fixed)

- **Where:** `node/zed.py:1395-1409` (`_store_frame`).
- **Scenario:**
  - A frame of about 115 KB is kept every 0.2 m or 10° and is dropped only by a save. Saves happen only when the robot is idle.
  - A long exploration or a long manual drive therefore piles up hundreds of megabytes on an 8 GB Jetson that has already hit nvblox out-of-memory at 6.2–6.5 GB.
  - Every pose correction also re-integrates every stored frame while holding `mapper_lock`, so rebuilds get longer and longer.
- **Fix:** above 400 frames (about 46 MB), bake them into `room.nvblx` with `_save_nvblox`, which is what an idle autosave already does. This is skipped while the process is restarting.
- **Trade-off:** frames that are baked in are no longer moved by later loop closures.
- **Test:** `test_stored_frames_are_baked_into_the_saved_map_before_they_pile_up`.

### M4. An SVO recording had no stop condition (fixed)

- **Where:** `node/zed.py:602-605` (`publish_health`).
- **Scenario:** a lossless HD720 recording writes about 5.4 MB/s (2.6 GB in 8 minutes on 2026-10-02), about 20 GB per hour. A forgotten recording fills the disk that ClickHouse, Docker and the maps live on.
- **Fix:** stop the recording when the disk has less than 10 GiB free. The check runs every second.
- **Test:** `test_a_recording_stops_before_it_fills_the_disk`.

### M5. Persistent grab errors never restarted the camera (fixed)

- **Where:** `node/zed.py:670-677` (`_grab`).
- **Scenario:**
  - A non-success `grab()` raised, and `async_task` logged it and retried every second for ever, for example after a USB disconnect.
  - Nav stops safely without poses. But the robot stayed blind until someone restarted the container, unlike the documented "restart on failure" rule.
- **Fix:** restart after 10 consecutive failures, which takes about 10 s.
- **Test:** `test_a_camera_that_keeps_failing_to_grab_restarts_the_process`.

### M6. The planner's scan memory dropped hits that entered the depth blind zone (fixed)

- **Where:** `lib/navmap.py:149` (`ObstacleMemory.add`).
- **Scenario:**
  - A sector with no points becomes a 2.5 m "free" ray. Once the robot is within about 0.3 m of a scan-only obstacle, that sector goes empty and erases the remembered hit.
  - The planner then replans through the obstacle, and only nav's own blind-zone memory stops the robot.
- **Fix:** a ray no longer clears hits that are within 0.4 m of the camera (`BLIND_RANGE`, the same value nav uses). They still expire after 6 s.
- **Test:** `test_obstacle_memory_keeps_a_hit_that_moved_into_the_blind_zone`.

### M7. Scan obstacles beyond the ESDF bounds were lost before padding (fixed)

- **Where:** `lib/trip.py:550-559` (`planning_costmap`).
- **Scenario:**
  - The costmap was built in this order: crop, stamp the scan obstacles, then pad. `with_obstacles` silently drops points outside the grid, and `expand` pads with unknown space that counts as clear.
  - The ESDF grid covers only the observed bounding box. So a scan hit just beyond it, which is common when exploring, vanished, and replans and the path re-check could route through it.
- **Fix:** pad first, with the obstacle points included in the bounds, then stamp the obstacles.
- **Test:** `test_a_scan_hit_beyond_the_mapped_area_still_blocks_the_padded_costmap`.

### M8. Exploration could loop on a frontier that survives arrival (fixed)

- **Where:** `node/explore.py:224-227` and `263-266`.
- **Scenario:**
  - `arrived` reset the failure count and recorded nothing. When a frontier stays after arrival (glass, dark surfaces, cells under furniture), `plan_next` picked the same frontier and viewpoint again.
  - The planner then reported arrival at once, and the loop repeated without progress until `max_duration_s`.
- **Fix:** `arrived_at` remembers visited frontiers. A frontier reached twice (within 0.6 m) goes to `failed`. `tests/sim.py` uses the same method.
- **Test:** `test_exploration_gives_up_on_a_frontier_that_is_still_there_after_two_arrivals`.

## Low (not fixed)

- **Relocalization timeout.** `lib/relocalization.py` and `zed.py:1107`: the 45 s timeout archives the map and starts a new one even when the robot never moved. This was a deliberate change (a robot facing a wall waited for ever), but it goes against the "distance, not time" lesson. Twice on 2026-10-02 relocalization against a map saved minutes earlier failed with the robot standing still, and this rule would have discarded that map. The map is archived, not lost, but consider requiring some travel or a much longer timeout.
- **Stale pose for scan points.** `nav.py:240` (`on_obstacle`) places scan points with the current pose, not the pose at capture time. The obstacle worker adds 50–100 ms, so at 0.25 m/s obstacles are placed about 2.5 cm too far, which eats into the 0.15 m stop. The fix is to place each scan with the pose closest to its `ts`.
- **Ground speed from a per-message EMA.** `nav.py:155` drives the `stall` and `stuck` trips. I checked it against the 2026-10-02/03 pose exports: on a standing robot the EMA has p99 0.008–0.015 m/s and is above the 0.02 threshold on only 0.4–0.6 % of frames. That noise can delay `stuck` but not disable it. A displacement over a 0.5 s window would be more robust.
- **Re-anchoring queued steps.** `nav.py:180` (`reanchor`) on an odom→map frame switch also moves queued steps, which are still in map coordinates and are converted again when they start. In practice this path is dead, because every published pose carries `odom`.
- **Map far floor and the docs.** The map integrates up to 5 m (`zed.py:173`) thanks to the new far-floor drop in `depth.cu` (beyond 2 m, a band of 3 cm + 2 %·d above the floor is discarded). That also drops real obstacles 4–13 cm tall farther than 2 m until the robot is closer. The lesson "don't raise past 3.5 m" in `docs/lessons.md` is now out of date.
- **Telemetry reports the target, not the output.** `roboclaw.py:139` reports `self.target` as the wheel `command`, not the slewed output that is actually sent.
- **Benign races in the RoboClaw node.**
  - The I/O thread's timeout reset (`roboclaw.py:97`) can overwrite a command that arrives at the same moment. That only produces a stop.
  - The slewed `output` survives a port reconnect, but it ramps down within 0.1 s.
- **Costmap cache invalidated on every tick.** `planner.py:237` calls `navigator.on_map` every tick (4 Hz). That bumps `map_version`, so the costmap cache in `planning_costmap` (crop, obstacles, padding) is rebuilt on every tick. This is CPU only.
- **Stale nav state in the planner.** If `rabbit-nav` dies, a trip keeps reading its last state until `TRIP_TIMEOUT` (900 s). The motors stop through the RoboClaw timeout, so this is not a safety problem.
- **Thread-safety of mesh-mode map reads.** In mesh mode (the fallback, since `USE_GRID = True`), `MeshMap.costmap` and `ScanHistory.apply` iterate `chunks` and `scans` in a worker thread while the event loop modifies them. That can raise and abort an exploration. Take snapshots before `to_thread`.
- **Explore quirks.**
  - Explore fills `ScanHistory` in grid mode but never uses it.
  - Planner refusals caused by the camera's state count as frontier failures.
  - `ScanHistory.add` takes the middle ray as the heading, which is half a sector off.
- **Loc hooks** (the other session's code).
  - `_log_shadow` appends a line to `data/loc/shadow.jsonl` every second without rotation, about 26 MB a day.
  - `_loc_health` reads `self.pose` from the event loop while the grab thread writes it.
- **pyzed calls outside the camera lock.** `get_current_fps` in health is called from the event loop without `_camera_lock`. This was already the case before these changes.

## Dead code

- `lib/planner.py`:
  - `_mod2pi` (449), `drive_arcs` (565) and `dubins_shots` (571) have no callers.
  - `OccupancyGrid.clear_ray` (53) is used only by a test, and it frees occupied cells, unlike `_clear_rays`.
  - `_stamp` has an unused `reach` parameter.
- `node/explore.py`:
  - `trip_id` is written but never read.
  - `map_chunks` in the state is always 0 in grid mode.
  - `target.reverse_length` is always 0.0.
- `lib/navmap.py`: the `map_id` attributes are never read.
- `node/nav.py`: `imu_orientation` was never used. I removed it.

## Checked and found correct

- **Frames and signs.** `planar_pose`, `rigid_transform`, `to_control` / `to_map`, the rear-axle conversion of paths, curvature signs and the planner's theta convention (`lib/planner.py` was reviewed by a subagent; its Dubins words, indexing and numba typing are consistent).
- **Native code.** The `depth.cu` floor maths: the rise of each ray, the floor intersection, snapping, and the far band applied only to downward rays. In `module.cpp`, the Y-up ↔ Z-up conversions in the mesh and the grid window.
- **Pose gates.** The relocalization state machine and `JumpGate`.
- **Motor safety.**
  - Every fault path in nav (`trip`, cancel, stale pose, stale scan, blind) commands zero.
  - A stale pose or scan always yields zero speed in both directions.
  - The RoboClaw output ramps to zero within 0.1 s after the 0.4 s timeout. The hardware serial timeout (0.5 s) still backs it up.
- **Monotonic clocks.** All timers in nav, the planner, explore, RoboClaw and the zed state machines use `time.monotonic()`; wall time is used only for timestamps and filenames.

## Files changed by this review

- **Code:**
  - `workspaces/rabbit/src/node/nav.py`
  - `workspaces/rabbit/src/node/zed.py`
  - `workspaces/rabbit/src/node/explore.py`
  - `workspaces/rabbit/src/lib/pose_gate.py`
  - `workspaces/rabbit/src/lib/navmap.py`
  - `workspaces/rabbit/src/lib/trip.py`
- **Tests:**
  - `workspaces/rabbit/tests/test_navigation.py`
  - `workspaces/rabbit/tests/test_pose_gate.py`
  - `workspaces/rabbit/tests/test_zed.py` (new; it imports the camera node with pyzed, cv2 and rabbit_nvblox mocked)
  - `workspaces/rabbit/tests/sim.py`

After the next deploy, check on the robot:

- `test_nvblox_mapper.py` passes.
- A camera restart during a mission ends it with `odometry reset`.
- `odom_rejected` in health stays near 0 while driving. If it climbs, the 120°/s bound is too tight.
