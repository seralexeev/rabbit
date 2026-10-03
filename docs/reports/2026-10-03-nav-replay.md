# Navigation replay of 3 Oct 2026: recoveries, loops, stuck and escape

**Scope.** rabbit-planner (`lib/trip.py`, `node/planner.py`), rabbit-nav (`node/nav.py`, one change) and rabbit-explore. The robot was off throughout, so the work used only the Parquet export `data/offline/export-20261003/` (from 2 Oct 13:00 UTC) and the saved maps in `data/offline/map-20261003/archive/`. Nothing is deployed or committed.

**Parallel work.** Another session reviewed the same code at the same time. It added explore's "a frontier that survives two arrivals is dropped" rule (`Node.arrived_at`), nav's odometry-session reset and the planner's scan-memory and padding fixes. I built on those changes and did not repeat them.

**Tests.** `cd workspaces/rabbit && uv run --no-project --python 3.10 --with pytest --with numpy --with pydantic --with numba --with nats-py python -m pytest tests -q` gives 123 passed, 1 skipped. Fourteen of these tests are new, in `tests/test_recovery.py`. All 14 fail on the code as it was before this work.

**Times** are UTC, on 2026-10-03 unless marked otherwise.

## Summary

| # | Incident | Root cause | Verdict / fix |
|---|---|---|---|
| 1 | 01:07–01:09: 198 explore trips to the same spot | Explore asked for a viewpoint 7 cm from the robot and 22.5° off its heading. The planner drew a 2.2 m loop for it, and nav declared every loop finished at once. | Nav fix (`segment_left`) confirmed. The planner now arrives at once when the robot already meets the arrival rule (0.3 m, 50°). Nav no longer counts a blocked loop as arrived. Explore drops a frontier after two arrivals (the other session's change). |
| 2 | 01:10:50: false `collision` | Single-sample IMU spikes (5.6 m/s² raw) | The 50 ms mean is fine. Steady driving: p99.9 1.95, max 4.5 m/s², no false trips at 5.0. Real slow contacts peak at only 1.7–2.5 m/s². Threshold left unchanged. |
| 3 | 01:22:20–01:23:29: backed into a wall for 70 s | The recovery route crossed gear changes in the trail. Each crossing flipped the heading by 180°, which puts the camera point 0.37 m off the trail. The route ran 0.33 m behind the trail, into a wall that **was in the map**. The trip also had no time or distance cap. 7 of 11 recoveries today were malformed this way. | Recovery now backs up only over trail the robot drove *forward*, recently, in the odometry frame, through cells the map knows are free. It is capped in time and distance, `stuck` while backing up stops it, and a second block at the same spot fails the trip. |
| 4 | 01:28:59: `stuck` 0.8 m into a trip | **True positive.** The planned route reversed ~0.9 m through mapped-free space the robot had never driven, and the left wheel hit something unmapped. Left current rose from 0.6 to 1.0 A and the pose froze for 2.75 s. The detector has no false positives over all of today's driving. | No tuning. `stuck` no longer ends the trip: the planner marks the contact point as an obstacle for the rest of the trip and replans, backing up first when it was going forward. |
| 5 | 01:37–01:39: fridge trip failed | Same recovery bug as #3: 42 s and 4.3 m of blind reversing across the room, ended by `stuck`. That caused the 4 s hold before a "6.1 m detour"; on the polluted map the trip then failed. | Fixed by #3. The handling of a start inside obstacles is consistent and sensible (see below). |
| 6 | Others | Blocks come mostly from full-lock corrections after a gear change; a block at the start of a loop counted as arrival; an explore target is unreachable when the heading is dropped | Nav's blocked-arrival check uses the length left along the path. The rest is open, see the recommendations. |

## Tooling

`workspaces/bench/replay/` now covers this day:

- **`replay.py 20261003 [trip]`** picks the export and the map by day. Each map has a validity window: `archive/room.20261003-HHMMSS.nvblx` is the map that was live up to that reset, starting from the time encoded in its `map_id`.
- **Explore trips are replayed with the requested heading and tolerance.** These come from `command_events` (`rabbit.planner.goal`); `planner_state` doesn't carry them. The harness used to replay explore trips as plain points.
- **DuckDB runs in UTC.** It used local time before, so a trip could be matched to the wrong map.

## 1. The 01:07 turnaround loop

- **What happened.** The robot stood at camera (0.596, 0.134) with heading 0°. Explore requested (0.534, 0.168) at heading 22.5°, tolerance 0.3, 198 times in 70 s. Each plan was a forward loop of 2.19 m (the first took 302 ms), and nav finished each one at once.
- **Second path to the same failure.** At 01:08:15–01:08:16 nav logged "Blocked 0.11 m from the goal, counting it as arrived" for the same kind of loop. The blocked-arrival check measured the straight distance to the end of the path. For a loop, that end is next to the start.
- **Should such goals be planned at all? No.** The camera sees ±60°, and the arrival rule accepts 0.3 m and 50°. A robot 7 cm from the viewpoint and 22.5° off already satisfies the trip. The planner now finishes a trip as "already at the goal" when the first plan's goal already meets the arrival rule. Previews still plan.
- **Replay.** With the fix, all 198 loop trips and the 01:09:57 retry end "already at the goal". The other session's `arrived_at` rule then drops the frontier on its second arrival, so explore moves on.
- **Nav change.** A blocked path step counts as arrived only when the length left along the path is ≤ 0.12 m, not just the straight distance to its end.

## 2. IMU collision threshold

The data:

- IMU messages arrive at 130–155 Hz in the export (1.1–1.3 samples each).
- I replayed nav's computation over the whole export: `linear_acceleration`, then a trailing 50 ms mean, then the horizontal magnitude. Samples within 0.4 s of a speed change are excluded, as in nav.

| Horizontal acceleration (m/s²) | p50 | p90 | p99 | p99.9 | p99.99 | max |
|---|---|---|---|---|---|---|
| Steady driving, 50 ms mean (69.7k samples, ~9 min) | 0.09 | 0.25 | 0.71 | 1.95 | 3.03 | 4.50 |
| Steady driving, raw sample (old) | 0.23 | 0.53 | 1.22 | 3.99 | 6.29 | 8.03 |

- **The 50 ms mean holds.** Raw samples exceeded 5.0 m/s² 28 times during steady driving; the 50 ms mean never did. The false trip at 01:10:50 had a raw peak of 5.62 and a 50 ms mean of 2.66.
- **The maximum of 4.50 is floor vibration.** It came at 22:20:28.4 (2 Oct), at a steady 0.12 m/s with no change in speed or current.
- **Real contacts today peak low:**
  - recovery into the wall, 01:22:22: 2.41;
  - reversing stuck, 01:28:58: 1.71;
  - end of the runaway reverse, 01:38:38: 2.53.
- **The IMU cannot detect a contact at these speeds** (~0.1 m/s): the peaks sit inside the vibration distribution, so no threshold separates them. That is the job of `stuck` (pose not moving) and `stall` (current). The 5.0 threshold is only for hard impacts.
- **Decision: no change.** It gives no false trips on today's data, but the margin over the worst sample is only 0.5 m/s². If false collisions come back, require two consecutive 50 ms windows rather than raising the threshold.

## 3. The recovery that reversed into a wall (01:22:20)

The sequence:

1. **01:22:01.** Trip to (0.26, −6.86), 8.7 m. The robot had just "arrived" facing an obstacle.
2. **01:22:01–01:22:20.** Three times, the route started with a short reverse and then a full-lock forward turn. Each time, nav was blocked (free 0.14 m) on the forward part. The reverse segments ended 0.1–0.15 m off the path. Pure pursuit then commanded full lock to converge, and the guard sweeps that full-lock arc.
3. **Third block.** Recovery: "backing up (obstacle in the way)". The route nav received (`nav_events`) was:

   ```
   (-0.647,0.216) (-0.634,0.168) (-0.648,0.121) (-0.639,0.074) (-0.574,-0.258) (-0.63,-0.214) (-0.687,-0.157) (-0.61,0.173)
   ```

   It jumps 0.33 m between the 4th and 5th points, and it ends 6 cm from its start.
4. **The reverse.** The robot reversed 0.24 m toward (−0.574, −0.258) and stopped against the wall at camera z = −0.025. It pushed there at −0.22 duty and 0.5–0.7 A until 01:23:29, when it was cancelled by hand.

### Root cause

- **The trail.** The planner keeps a trail of rear-axle positions, one every 5 cm. Before this trip the robot had shuffled forward and back three times in a 15 cm span, so the trail zigzagged (rear axle at z −0.11…+0.03).
- **The old recovery** took the last 0.35 m of that trail in reverse order, whatever the direction of motion. It derived each waypoint's heading from the direction between consecutive points. At every point where the robot had changed gear, that heading flipped by 180°, and the camera point, 0.18 m ahead of the axle, jumped by 0.37 m. Nav tracks reverse paths by the rear axle, so it chased points up to 0.33 m behind anything the robot had driven.
- **The wall was in the map.** I rebuilt the trail from the recorded poses and checked it against the map live at the time (`room.20261003-012940.nvblx`, saved 01:28). The trail cells have clearance 0.20–0.35 m. The jumped waypoint (−0.574, −0.258) has 0.05 m: 0.13 m inside the planner's collision radius. The wall row at z ≈ −0.33 is plain in the grid. A check against the map would have refused the route.
- **No cap and no reaction.** The trip waited for nav to report `arrived`, `fault` or `idle`. Nav's own path timeout is 90 s. Nav now has `stuck` (2.5 s with no pose motion), but the planner treated any fault during a recovery as "done backing up" and carried on.

### How widespread

There were 15 reverse-only recovery missions in the export. Ten had a jump between waypoints of 0.31–0.34 m:

- 22:20:52, 22:21:02 and 22:21:09 on 2 Oct;
- 01:21:22, 01:22:20, 01:31:57, 01:32:54, 01:33:20, 01:37:59 and 01:50:59 on 3 Oct.

Three of today's recoveries (01:22:20, 01:37:59, 01:50:59) ended within 6 cm of where they started.

To check the reconstruction, I rebuilt the planner's trail from the recorded poses and ran the old `Navigator.recover` on it. It reproduces 9 of today's 11 recovery missions exactly; the other two differ by a few cm, because the planner sees poses at a slightly different rate.

### Is the trail safe after re-anchoring or carrying?

- **Map jumps over 0.25 m or 10°.** The old code cleared the trail; that was safe.
- **Smaller map corrections.** The trail was in the map frame. A correction of up to 0.25 m shifted the robot relative to its own past positions by that much, and a recovery then drove a route offset by it. The trail is now recorded in the continuous odometry frame (`pose.odom`). It is converted to the map frame with the current map←odom transform only when a route is built. The trail is dropped when the odometry session changes (camera restart) or the map session changes.
- **Carrying.** At 01:28:00–01:28:48 the robot was carried: pose height 0.29–0.37 m instead of 0.137. The old trail would have included the carried positions. Now, a height change of more than 5 cm from the last trail point drops the trail. Height while driving today stayed within 0.106–0.161 m, and only drifted slowly.

### Fix (`lib/trip.py`)

- **Where the backup may go** (`Navigator.backup_route`). The trail is walked back from the robot only while:
  1. each step was driven forward (the motion between two points runs along the newer heading);
  2. the heading changes by at most 25° between points;
  3. the point is at most 120 s old.

  This stops at the most recent gear change. Waypoints use the recorded headings. The route is then cut at the first pose that is worse than `min(0, clearance at the start)` in the current planning costmap (map plus scan memory) or that touches an unknown cell. If less than 0.1 m remains, there is "no room to back up" and it replans instead.
- **Caps** (`watch_recovery`). The deadline is 3 s plus the route length at 0.08 m/s; the reach is the route length + 0.15 m from the start. Whichever is exceeded first, the planner cancels nav, drops the trail and replans.
- **Faults while backing up.** `stuck` (or `blocked`) while backing up drops the trail and replans. `collision`, `stall` and the other safety faults end the trip.
- **Escalation.** Each recovery records where it started. A block within 0.3 m of an earlier recovery spot ends the trip: "stuck: …, again where it already tried to back out". The limit of 3 recoveries per trip stays.

**Effect on the real recoveries.** The same reconstruction, run with the new code: all 11 of today's routes are monotonic (largest step 0.05–0.07 m), 0.16–0.42 m long. The 01:22:20 recovery becomes 0.17 m along the last forward stretch; 01:37:59 becomes 0.25 m.

**Simulator replay of the 01:22:01 trip on the 01:28 map.** The start is inside phantom obstacles, so the world is approximate.

- **Old code:** 862 colliding steps, 3 recoveries, failed.
- **New code:** it collides only while escaping the start cell (48 steps), backs up 0.14 m once, and arrives.

**Should the A\* search reverse only over traversed space?** I didn't restrict it. Recovery now reverses only where the robot has driven forward recently, through cells the map knows are free. A\* reverse moves still need only mapped cells, because three-point turns and points behind the robot (the "туда-сюда" goals; `test_point_behind_reached_in_reverse_counts_as_arrived`) need reverse into space the robot has not driven. Incident 4 shows the cost of that choice. See the recommendations.

## 4. The `stuck` at 01:28:59

- **The robot had been carried** (pose height 0.29–0.37 m at 01:28:00–01:28:48), so it started without a trail.
- **01:28:49.** The 8.1 m route began with a 0.5 m reverse. The replans at 01:28:52 and 01:28:57 again started with a reverse. Altogether it reversed ~0.9 m through cells the map shows as free (clearance 0.29–0.74 m in the 01:28 map) but that the robot had never driven.
- **01:28:58.75.** While reversing at −0.23 duty, the pose stopped dead: 0–1 mm/s at 28–32 poses per second. The left motor current rose from 0.6 to 1.0 A; the right stayed at 0.4 A. Nav tripped `stuck` 2.7 s later.
- **Verdict: a real contact behind the robot**, probably a low or thin obstacle below the map's 4 cm band. It was not slow poses (the camera ran at full rate), nor lag in the speed estimate (moving at 0.1 m/s until the contact), nor the planner slowing the robot (a constant −0.23).
- **Check against all of today's driving.** I replayed nav's ground-speed EMA and the `stuck` rule over ~530 s of commanded motion. Stuck-like periods over 2.5 s happened only at real stops:
  - 21:55:13 (2 Oct): RoboClaw errors, motors not running, 14.7 s;
  - 01:22:23: the wall, 63 s;
  - 01:28:59;
  - 01:38:38: the end of the runaway reverse.

  There are no false positives, so no tuning.
- **Change.** `stuck` used to end the trip as a safety stop, even though a route ahead existed. It is now treated like `blocked`:
  - three points across the bumper (front, or rear when it was reversing) become obstacles for the rest of the trip, so replans avoid the spot;
  - stuck going forward: back up along the trail;
  - stuck while reversing: no backup (the newest motion was reverse); replan.

  The recovery limit and the same-spot rule keep it from looping. In the simulator replay of this trip, the new code fails after 1 recovery with "again where it already tried to back out", without colliding. The old code took 3 recoveries and 13 replans, and collided.

## 5. The fridge trip (01:37:38)

- **Recovery.** At 01:37:59 it backed up along a malformed route (the same bug as #3) whose end was 6 cm from its start. Nav reversed in an arc for 42 s and 4.3 m across the room until `stuck` at 01:38:41.
- **The planner carried on as if the backup had finished.** The robot was now 3 m from where it had been, so the new route (6.1 m) tripped the detour hold: "way blocked; waiting 4 s".
- **The polluted map.** It then drove 1.3 m into a region the polluted map (5 m integration, before the far-floor fix) filled with obstacles. "path blocked 0.0 m ahead", then "no free, reachable spot near the target; the map shows obstacles where the robot stands" twice, then failed.
- **The map in the archive.** The saved map for that window (`room.20261003-014922.nvblx`, saved 01:48) is solid obstacle around both positions. It kept accumulating noise until 01:48, so it is worse than what the planner had at 01:38. This trip can't be replayed meaningfully on it.

**Escape from a start inside obstacles.** The robot is placed in a phantom disc of radius r, centred on its body, in an open room, with a point and an object target 2–3 m away:

| r (m) | point | object |
|---|---|---|
| 0.2 | route 1.9 m | route 2.1 m |
| 0.3 | 2.2 m | 2.3 m |
| 0.4 | 3.4 m | 4.3 m |
| 0.45 | 4.1 m | 4.5 m |
| 0.5 | no route, "map probably wrong" | no free reachable spot, "map probably wrong" |

The goal search (2D reach map) and the A\* search (0.5 m `escape_radius` with the never-worse floor) agree on the escape distance. Beyond it, both fail with the "map is probably wrong here" explanation. That is the right outcome for a robot enclosed by phantom obstacles: driving out through them would also drive through real ones. At 01:38:57 the blob was well over 1 m, so no escape radius would have helped. The fix was the far-floor drop in the depth kernel. No change here.

## 6. Other anomalies

- **Blocked loops.**
  - Since 01:09: 25 "obstacle in the way" replans, 15 "path blocked" replans and 8 recoveries.
  - Nav went from driving to blocked 24 times. In 17 of them |steer| was ≥ 0.7, while creeping at the 0.2 minimum speed and stopping at free 0.14 m.
  - **Typical sequence:** the route begins with a short reverse. Reverse tracking ends 0.1–0.15 m off the path. At the gear switch, pure pursuit commands full lock to converge, and the guard sweeps that sharper arc, not the path, into an obstacle the path avoids. The replan from the new pose produces the same reverse-then-turn route, and the cycle repeats until a recovery.
  - Not changed here (nav guard and pursuit). See the recommendations.
- **Nav blocked at the start of a loop counted as arrived.** Fixed (#1).
- **Arrivals facing an obstacle.** "stopped 0.19 m short: obstacle ahead" (01:22:01) and "0.33 m short" (01:31:03) are correct arrivals within 0.5 m, but they leave the robot facing an obstacle. The next explore trip then has to start with a reverse; that is how #3 began. Explore viewpoints sit 0.5–0.8 m from a frontier, which is often next to furniture.
- **Slow failing searches.** A "no route" plan took 583–786 ms (01:10:17, 01:10:25): the 2D heuristic says the goal is reachable, so the kinematic search runs to its time limit. That is acceptable within the 1.2 s budget.
- **Explore and the planner during map resets.** The planner's trail now also clears on a map session change.

## Changes

| File | Change |
|---|---|
| `src/lib/trip.py` | Trail in the odometry frame, with time and height (`on_pose(..., odom=, height=)`, `trail_points`, `forget_trail`). `backup_route` (forward-driven, heading-continuous, recent, map-checked). Recovery deadline, reach cap and fault handling (`watch_recovery`). Same-spot escalation. `stuck` handled like `blocked`, with `bump()` marking the contact point. "already at the goal" on the first plan. |
| `src/node/planner.py` | Passes the odometry pose and the camera height to the navigator. Drops the trail on an odometry or map session change. |
| `src/node/nav.py` | `path_left`: a blocked path step counts as arrived only when ≤ 0.12 m are left along the path. |
| `tests/test_recovery.py` | 14 regression tests (below). |
| `workspaces/bench/replay/replay.py`, `one.py` | Day selection with map validity windows, requested heading and tolerance, UTC. |

Tests, each failing on the previous code:

- `test_backing_up_stops_where_the_robot_last_changed_gear_instead_of_turning_around_on_the_trail` (the 01:22:20 shape)
- `test_backing_up_stops_short_of_an_obstacle_that_appeared_on_the_trail`
- `test_backing_up_never_leaves_mapped_space_even_on_the_trail`
- `test_backing_up_follows_the_odometry_trail_after_a_small_map_correction`
- `test_a_robot_that_was_lifted_does_not_back_up_along_where_it_was_carried`
- `test_backing_up_that_makes_no_progress_is_stopped_and_replanned`
- `test_backing_up_that_runs_away_from_the_trail_is_stopped` (the 01:37:59 shape)
- `test_hitting_something_while_backing_up_forgets_the_trail`
- `test_a_collision_while_backing_up_ends_the_trip`
- `test_blocked_again_where_it_already_backed_out_fails_the_trip`
- `test_a_goal_the_robot_already_stands_on_is_reached_without_driving_a_loop` (01:07)
- `test_nav_does_not_count_a_loop_blocked_at_its_start_as_arrived` (01:08:15)
- `test_stuck_while_reversing_replans_forward_around_the_spot_it_hit` (01:28:59)
- `test_stuck_while_driving_forward_backs_up_and_avoids_the_spot_ahead`

## Follow-up: reverse cost, blocks after turns, dead code

Done after the coordinator's decision. The suite is now 130 passed, 1 skipped; `tests/test_recovery.py` has 20 tests.

### Reverse outside the driven corridor costs more (`lib/planner.py`, `lib/trip.py`)

- **The rule.** Hybrid A\* gets a mask of the cells the robot's body covered in the last 120 s (`swept_cells` over the odometry trail, plus the current pose). A reverse primitive whose footprint probes leave that mask costs `reverse_penalty × (1 + 1.5 × share off the mask)`: up to 10× forward, against 4× along the corridor. It is a cost, not a ban: a dead end is still left in reverse along the way in, and points behind the robot in a 1 m corridor stay reachable. `plan_route(..., traversed=None)` keeps the old behaviour for other callers.
- **Effect.** Turning around in a 3 × 2.4 m room after driving in: without the penalty the plan reverses 0.59 m, up to 0.42 m off the corridor; with it, the plan reverses 0.15 m inside the corridor and loops forward.
- **Strength.** I chose it in the simulator. 2.0 pushed corridor turnarounds into forward turns that nav then blocked; 1.0 left 9 blocks in the replays of today's trips; 1.5 gave the fewest blocks and no extra failures.

### Blocks after turns and gear switches (item 6): chosen from the data

I re-ran the 24 real blocks against the recorded scans (`obstacle.scan_ranges`, the last 4 s, transformed with the poses) and the active nav path:

- **Re-entry is not the problem.** The lateral offset from the path at the block was 0.00–0.10 m, median ~0.04. So "plan the re-entry" or "start each segment from the actual pose" would change little.
- **The path itself was usually blocked.** In 15 of 24 blocks, the arc of the path's own curvature was also blocked (free ≤ 0.16 m), so capping pursuit's curvature alone can't help. I tried it in nav (when pursuit's arc is blocked, steer toward the path's curvature) and it changed nothing in the simulator; it was removed.
- **The planner used the whole steering range.** At 11 blocks the path itself was at ≥ 0.84 of full lock, so pursuit had no steering left to correct tracking error and saturated at 1.0.
- **Several blocks were at the end of a segment.** A few came within 0.2 m of a gear switch or the path end, where the guard's fixed 0.15 m stop distance reaches past the point where the robot stops anyway. The simulator's corridor turnarounds showed this clearly: blocked 7 cm before a cusp.

The fix:

1. **Steering headroom** (`lib/trip.py`). The planner plans with at most 70% of full lock: primitives at ±0.7 and ±0.35 steer; minimum turn radius 0.56 m right and 0.42 m left, instead of 0.40 and 0.30. Pursuit keeps the rest to correct errors.
2. **Comfort tier** (`PlanJob.run`). Each goal is first planned with the footprint margin raised by 0.07 m, on 40% of the time budget, then with the normal footprint. A route that keeps that clearance is used when one exists; tight places still work.
3. **Stop distance at the end of a segment** (`node/nav.py`). Forward, the guard stops at `min(0.15 m, length left in the segment + 0.03 m)` (resume +0.1 m above that). Nav no longer stops short of a gear switch or the path end that the planner put next to an obstacle. The footprint margin (0.04 m) still applies.

Simulator results (blocks are nav driving → blocked transitions):

| Scenario set | Before | Penalty only | Final |
|---|---|---|---|
| The day's trips replayed on their maps (12) | 9 blocks | 15 blocks, 1 more trip failed | 3 blocks, 1 failure fewer than before (01:28:49 arrives) |
| Corridor turnarounds, 0.9–1.4 m, 3 headings (15) | — | most failed | 5 blocks, all arrive (without the comfort tier: 11 blocks, 1 failure) |

Plan times on the real maps are unchanged: median 3 ms, p90 54 ms, max 104 ms on the Mac.

Each part is pinned by a test that fails without it:

- `test_turning_around_in_a_room_loops_forward_instead_of_reversing_where_it_never_drove` (penalty)
- `test_a_dead_end_is_still_left_in_reverse_along_the_way_in`
- `test_turning_around_in_a_corridor_needs_no_guard_stops[1.1, 1.2]` (headroom, penalty)
- `test_turning_around_in_a_one_metre_corridor_still_arrives` (comfort tier)
- `test_nav_drives_up_to_a_gear_switch_close_to_a_wall_instead_of_stopping_short` (segment-end stop)

Remaining blocks are mid-turn, with pursuit saturated; at 1.0 m width a turnaround still has one block and recovers.

### Dead code and unused fields

- **`lib/planner.py`.** Removed `_mod2pi`, `drive_arcs`, `dubins_shots`, `OccupancyGrid.clear_ray` and `_stamp`'s unused `reach` parameter. `clear_ray` was used only by its own test, so the test went with it rather than moving into the test file: the production code clears rays with `navmap.clear_unknown`, which the exploration tests cover.
- **Explore.** Removed `trip_id` and `target.reverse_length`, and the field from the HUD's `ExploreTarget` type; `tsc` passes. `map_chunks` stays in explore state because Forge's `ExploreState` schema requires it (0 in grid mode).
- **`lib/navmap.py`.** Removed the two unused `map_id` attributes.

## Follow-up 2: latency in nav

### Measured delays (today's data)

- **Pose.** Capture to nav: p50 47 ms, p99 77 ms (`2026-10-03-nats-docker-latency.md`). Obstacle scans: 56 ms.
- **Steering.** I fitted nav's steer commands (`drive`, source nav) against the yaw rate from the poses, over 779 s of driving. The best fit is a dead time of 0.06 s plus a first-order lag of 0.05 s, relative to the pose capture time. Yaw-rate gain is 0.95 of the curvature tables, so the calibration holds.
- **Motors.** The speed command against ground speed fits the same 0.06 s + 0.05 s, at 0.464 m/s per unit duty (the sim assumed 0.5).

Total: pursuit acts on a state about 0.15 s old. At today's 0.10–0.12 m/s that is about 1.5–2 cm of travel.

### Simulator (`tests/sim.py`)

It now models the measured delays:

- poses arrive 47 ms late and scans 56 ms late, each with its capture `ts`;
- actuation has a 0.06 s dead time and 0.05 s first-order lags on steering and speed, on 10 ms physics substeps;
- 0.464 m/s per unit duty.

`latency=False` gives the ideal model. A harness bug was fixed along the way: `Sim.explore` fed the first pose before nav's clock was switched to the sim clock.

### Results on the replay set (day's trips, the fridge route, 15 corridor turnarounds)

| | Tracking error mean / p95 | Blocks: replays / corridors | Arrival error median (replays / corridors) |
|---|---|---|---|
| Ideal simulator | 2.6 / 7.1 cm | 3 / 4 | 7.8 / 9.3 cm |
| Latency model, scans on the latest pose (old nav) | 2.4 / 6.7 cm | 3 / 6 | 6.7 / 8.4 cm |
| Latency model + extrapolation (a) + capture-time scans (b) | 2.6 / 8.2 cm | 3 / 11 | 7.3 / 11.0 cm |
| (a) for pursuit only (the guard on the measured pose) + (b) | 2.6 / 8.1 cm | 3 / 3 | 7.3 / 11.0 cm |
| (a) pose age only, pursuit only + (b) | 2.5 / 7.2 cm | 3 / 2 | 8.2 / 8.7 cm |
| **Final: (b) only** | **2.4 / 6.7 cm** | **3 / 4** | **6.7 / 8.4 cm** |

### Conclusions

- **Latency does not cause the mid-turn blocks.** The ideal and latency models give the same 3 blocks on the replays. The blocks come from pursuit saturating, which already happens without latency.
- **Extrapolation (a) does not pay off at these speeds.** I tried pose age + actuation 0.05–0.2 s, twist over the last 0.2 s. Tracking does not improve and gets slightly worse (p95 +0.5 to 1.5 cm), because the twist estimated from poses adds noise comparable to the 1.5–2 cm lag. With the guard on the predicted pose, blocks double. I removed the code rather than leave it switched off. It is worth revisiting if speed rises above ~0.3 m/s, where the lag becomes ≥ 5 cm.
- **Kept, as a correctness fix:**
  - each scan is placed with the pose interpolated at its `ts`, from a 1 s history of measured poses in the control frame;
  - ground speed is computed over capture-time intervals instead of arrival times, so the 37–80 ms delivery jitter no longer reaches `stuck` and `stall`.

  Message age is capped at 0.3 s. Corridor blocks went from 6 to 4.
- **Tests (`tests/test_latency.py`):**
  - `test_a_scan_is_placed_with_the_pose_from_when_it_was_captured` (error < 5 mm, against 3 cm before);
  - `test_ground_speed_comes_from_capture_times_not_delivery_jitter`.

  Both fail on the old nav. Two existing tests needed adjusting for the new calibration:
  - the creep test runs 25 s instead of 20, because the robot is 7% slower;
  - the corridor tests and everything else pass unchanged.

  Suite: 132 passed, 1 skipped.

## Follow-up 3: path tracker and cruise speed

### 1. Tracker (`node/nav.py`, `lib/planner.py`)

**First finding: the path itself was off on curves.** Nav rebuilt the rear-axle path from the camera points, taking each point's heading from the direction between neighbouring points. On a curve the camera point (0.18 m ahead of the axle, 6 cm off-centre) moves at an angle of about atan(κ·d) to the vehicle heading, ~23° at the planning curvature. The rear-axle path came out 3–5 cm off, and any tracker followed it with a steady error. Pure pursuit lived with this; the feedback law first did worse because of it.

Fix: the planner now sends the vehicle heading with every path point (`[x, z, direction, theta]`). Nav turns it into the odometry frame together with the points, and re-anchoring rotates it. Planner state (Forge, HUD) keeps 3 values. Paths without a heading still use the old tangent conversion.

**The tracking law.** Pure pursuit is replaced by the rear-wheel feedback law:

κ = κp·cos eθ / (1 − κp·e) − (2/L)·eθ − (1/L²)·e·sinc(eθ), with L = 0.2 m (critical damping over 0.2 m).

- κp is the path curvature over the next 0.15 m (feedforward).
- e and eθ are measured on the rear axle against the path heading interpolated along the segment. A chord heading jumped ±5° per waypoint on arcs, so steering chattered 0.45–0.95 around 0.7.
- κ → steer goes through the asymmetric tables.
- The steering rate is limited to 6/s. The servo is fast (τ = 0.05 s), so the limit hardly changes the results.
- Reverse uses the same law in the direction of motion.

Comparison in the latency simulator (12 replays of the day's trips, the fridge route, 15 corridor turnarounds):

| | Tracking mean / p95 | After a gear switch, p95 | Blocks: replays / corridors | Corridor arrivals |
|---|---|---|---|---|
| Pursuit, tangent headings (before) | 2.4 / 6.4 cm | 7.4 cm | 3 / 6 | 15/15 |
| Pursuit + true headings | 1.5 / 4.8 cm | 5.8 cm | 0 / 12 | 14/15 |
| Pursuit for 0.3 m after a switch, feedback elsewhere | 1.2 / 4.6 cm | 6.6 cm | 0 / 12 | 14/15 |
| **Feedback, L = 0.2 (final)** | **0.9 / 3.7 cm** | **5.5 cm** | **0 / 1** | **15/15** |

- Feedback is better everywhere, including right after gear switches, so pure pursuit was removed.
- L = 0.15 tracks about as well; 0.3 tracks slightly worse.
- On a constant arc at the planning limit (±0.7 steer) the steering holds 0.70 ± 0.02 and the error is about 1 mm. Pursuit had a steady 4 cm and swung between 0.45 and 0.95.

Tests (`tests/test_tracking.py`):
- `test_a_planned_arc_at_the_planning_limit_is_tracked_on_the_rear_axle_without_saturating`
- `test_path_headings_are_turned_into_the_odometry_frame_with_the_points`

Both fail on the old nav; so does `test_turning_around_in_a_corridor_needs_no_guard_stops[1.1]`.

### 2. Cruise speed

- **Stopping.** At duty d the robot goes v = 0.464·d m/s.
  - Reaction: scan age 56 ms + control tick ≤ 50 ms + actuation dead time 60 ms + motor lag 50 ms ≈ 0.22 s.
  - Braking at the 5/s slew adds v·d/10.
  - At d = 0.35 that is ~4 cm, at 0.5 ~6 cm, at 0.7 ~8 cm, against a 0.15 m stop with a 0.04 m margin. In the simulator, a wall that appears 0.32 m ahead of the camera, just beyond the blind zone, is never touched: the gap left is 0.24 m at 0.35 and 0.23 m at 0.7.
  - Slow zone (0.6 m, minimum speed 0.2) and creeping are unchanged.
- **Simulator** (the set above + a scan-only obstacle + a door closing mid-trip):

  | Cruise duty | Total time |
  |---|---|
  | 0.25 | 860 s |
  | 0.35 | 676 s |
  | 0.45 | 574 s |
  | 0.5 | 536 s |

  At every speed: no new blocks, no new contacts, the same arrivals, tracking 0.8/2.9 cm.
- **Camera (data, 0.5 s windows).** Share of windows with pose confidence < 50:

  | Ground speed | Share |
  |---|---|
  | 0.08–0.15 m/s | 7–13% |
  | 0.15–0.25 m/s | 18% |
  | 0.25–0.35 m/s | 27–41% |
  | > 0.35 m/s | > 60% (few samples) |

  The pose rate also fell to 17–20 fps in today's faster windows. The simulator does not model this, so camera tracking, not stopping, is the limit.
- **Decision.** `CRUISE_SPEED` 0.25 → **0.35** (0.12 → 0.16 m/s, trips ~20% faster in the simulator), the top of the range where tracking is still decent. 0.45–0.5 only after a field check of confidence and relocalization at 0.2 m/s; at 0.5 two scripted tests also need retiming (the robot arrives before the door closes). Reverse (0.22) and manoeuvre speeds are unchanged.
- **Test:** `test_at_cruise_speed_a_wall_appearing_just_beyond_the_blind_zone_is_not_touched`.

Suite: 135 passed, 1 skipped.

## Follow-up 4: exploration speed

### Benchmark

- **Simulator.** The latency model, plus a camera mapper (`ScannedMap.observe`: 87° FOV, 5 m range, rays every 0.25°, so far space doesn't stay speckled with unknown cells).
- **Worlds.** Three layouts, each with two starts as if the robot was carried in and switched on:
  - the old `apartment`;
  - `corridor_flat`: 10 × 7 m, a corridor with five rooms, furniture;
  - `open_plan`: 9 × 7 m, living room and kitchen with an island, a bedroom through a door, a narrow hallway.

  The real maps of the flat are too partial and noisy (~23 m² of free space) to serve as worlds.
- **Measured** (harness in scratchpad: `explore_eval.py`):
  - time and distance to 70% and 90% of the free area;
  - final coverage, total time and distance;
  - share of distance driven again over 0.2 m cells visited earlier;
  - failed trips and missions with reverse.

### What was wrong

- **No clean "done".** The apartment was 100% mapped at 73–143 s, but exploration went on to 144–281 s, visiting tiny leftover frontiers.
- **The ranking ignored what a view would see.** It used frontier size ÷ path, with the viewpoint 0.5–0.8 m from the frontier, so the robot drove into rooms instead of looking into them from the doorway.

### New (`src/lib/exploration.py`, `node/explore.py`)

- **Candidate views:**
  - from each frontier cluster (≥ 6 cells), positions at 0.8, 1.5 and 2.5 m on 12 bearings, facing the frontier; only positions on known free cells with ≥ 0.05 m clearance;
  - plus turns on the spot by ±90° and 180° (Ackermann: a short three-point manoeuvre, planned as usual, reverse only along the corridor).
- **Gain:** the unknown area visible in the 87° / 5 m cone, with rays stopped by obstacles. A ray counts at most 1.5 m of unknown space, because unknown space often holds furniture. The first version counted space behind thin walls; sampling at half a cell fixed that.
- **Cost:** 0.8 m per trip + path cost (2D, unknown 2×) + 0.5 m per radian of heading change on arrival. **Score = gain / cost.**
- **Hysteresis:** ×1.25 for views within 1.5 m of the previous one. On the benchmark its effect is within noise (±5%).
- **Done:** no reachable view shows at least 1 m². A minimum score per metre was tried and dropped: it stopped exploration at 57% when the remaining area was far away.
- **Faster planning:** 3–5 ms plus 4 ms for the reach map on the Mac, on the real maps.

### Before / after (same simulator)

| Case | t70 | t90 | total time | distance | coverage | failed |
|---|---|---|---|---|---|---|
| apartment / A | 119 → 87 s | 143 → 99 s | 281 → 155 s | 38 → 21 m | 1.00 → 0.99 | 0 → 0 |
| apartment / C | 57 → 67 s | 73 → 92 s | 144 → 160 s | 20 → 22 m | 1.00 → 1.00 | 0 → 0 |
| corridor / SW | 152 → 152 s | 343 → 258 s | 612 → 540 s | 77 → 71 m | 0.98 → 0.98 | 1 → 0 |
| corridor / NE | 283 → 259 s | 391 → 348 s | 606 → 398 s | 81 → 54 m | 0.99 → 0.99 | 0 → 0 |
| open plan / living | 100 → 71 s | 170 → 152 s | 298 → 241 s | 39 → 33 m | 1.00 → 0.97 | 0 → 0 |
| open plan / bedroom | 88 → 55 s | 166 → 199 s | 390 → 343 s | 51 → 46 m | 1.00 → 0.98 | 0 → 0 |
| **sum** | **799 → 691 s (−14%)** | **1286 → 1148 s (−11%)** | **2321 → 1837 s (−21%)** | **306 → 247 m (−19%)** | | **1 → 0** |

- Missions with reverse: 72 → 56.
- Repeated driving stayed small (1–6% of the distance) both before and after.
- Two starts got slower to 90% (apartment / C, open plan / bedroom); the time to 70% still improved in open plan / bedroom.
- What remains: the tail after 90% (mop-up of pockets left in rooms passed earlier, e.g. corridor / SW 258 → 540 s for the last 8%).

### Code and tests

- **Removed:** `find_frontiers`, `rank_frontiers`, `_viewpoint`, `_toward_unknown` and `Frontier` from `lib/planner.py`, with their 4 tests. Explore state keeps its fields; `target.cells` now holds the expected visible area in cells.
- **New tests (`tests/test_exploration.py`):**
  - a room behind a doorway is looked into from the corridor;
  - "done" when no view would show 1 m²;
  - unknown space right behind the robot is looked at without driving away;
  - the apartment from room A reaches 90% within 120 s and exploration stops by itself within 200 s (before: 143 s and 281 s).
- **Simulator:** `corridor_flat` and `open_plan` in `tests/sim.py`.
- Suite: 135 passed, 1 skipped.

## Follow-up 5: exploration tail

**Cause.** The view score gain / cost compared all views globally. A small corner (1–2 m²) left in the current room lost to a large view in another room. The robot left, and after 90% coverage it came back through the flat for the leftovers. Trace on the corridor flat: it left the south-east room while a 1.4 m² view was still nearby, and came back later over a 10.8 m path.

**Fix.**
- **Leaving costs a return trip.** While any view within 3.5 m of path cost shows ≥ 1 m², views beyond pay their travel twice.
- **Far trips need more.** A trip beyond 3.5 m must show ≥ 2 m².
- **Loop fix.** Turns on the spot are no longer offered at a spot explore has given up on. That could loop forever; in the simulator it hung the benchmark.

12-run benchmark (apartment, corridor flat, open plan, 4 starts each):

| | Old | New |
|---|---|---|
| Total distance | 490 m | 406 m (−17%) |
| Total time | 3646 s | 3051 s (−16%) |
| Distance after 90% coverage | 181 m | 87 m (−52%) |
| Return trips (count / distance) | 10 / 62 m | 8 / 31 m |
| Time to 90% | 2307 s | 2397 s (+4%) |
| Final coverage | 0.97–1.00 | 0.96–0.99 |

Corridor flat (5 rooms):

| Start | Old distance / tail | New distance / tail |
|---|---|---|
| SW | 70.9 / 36.9 m | 56.8 / 20.2 m |
| NE | 54.1 / 6.8 m | 56.8 / 9.6 m |
| hall | 74.6 / 31.3 m | 57.8 / 5.1 m |
| SE | 54.8 / 14.2 m | 47.6 / 6.3 m |

**Dropped:**
- a "same room" flood fill cut at doorways: 16 returns;
- a distance exponent: noise;
- a 3 m² far minimum: stopped at 57% coverage.

**Tests** in `tests/test_exploration.py`, each failing on the old logic.

## Recommendations (not done)

1. **Done in the follow-up above:** the reverse penalty outside the corridor and the post-turn blocks.
2. **On the robot:** check the new tracker and the 0.35 cruise speed (tracking error on arcs, pose confidence at 0.16 m/s) before raising the speed further.
3. **Explore viewpoints.** Prefer viewpoints with ≥ 0.5 m free ahead, so arrivals don't leave the robot facing an obstacle.
4. **Nav path overrun guard.** Defence in depth: fault a path step that has driven more than 1.5 × its length + 1 m. With the planner caps this is not needed for recovery, but it would have stopped the 4.3 m blind reverse by itself.
5. **On the robot.** After deploying, run a blocked-recovery check in a corridor and watch `rabbit.planner.state` events for "backing up …" lengths and "no known free trail" messages.
