# Planner, nav and explore: overnight report (2 Oct 2026)

Scope: rabbit-planner, rabbit-nav, rabbit-explore and their Forge tools. Nothing is deployed since the robot went off at 13:16 UTC. Nothing is committed.
Tests: `uv run --no-project --python 3.10 --with pytest --with numpy --with pydantic --with numba --with nats-py python -m pytest tests -q` gives 72 passed, 1 skipped, in 30 s. Forge `pnpm check` gives 121 passed.

## What I replayed

- **Trips.** All 26 planner trips of the day (`planner_state`, from 10:40 on), plus the nav faults of the whole export: only 2 nav faults (`blocked` at 23:37 and at 09:39, the original fridge attempt) and 40 `blocked` episodes.
- **Replay harness.** `workspaces/bench/replay/` (code; the flat's maps it reads are in the gitignored `data/offline/`):
  - `nvgrid.py` decodes a saved `.nvblx` file (sqlite; the ESDF slice is in the z = 0 blocks, voxel layers 3–4, 20-byte EsdfVoxel) into the same int16 clearance grid that rabbit.map.grid carries. There is also a TSDF fallback.
  - `replay.py` picks the map that was live at each trip (via `map_id`), takes the last plausible pose before the trip, and replays the trip through `tests/sim.py`: real nav.Node, real Navigator and planner, a bicycle model with the real curvature tables, and a ray-cast scan with the blind zone. Previews are replanned and compared. `one.py <trip>` replays one trip and draws it.
  - Latest output: `replay/replay-latest.txt`.
- **Map 11:02–12:32 is corrupt.** `archive/room.20261002-123231.nvblx` has obstacles where the robot actually stood: in 9 of 10 trips the start cell is occupied, clearance −0.18. That is the mm-pose integration debris (your zed fix). The trips from that window can't be replayed meaningfully. The other two maps replay cleanly: every drive arrives without collision, and object trips end 0.8 m from the fridge.

## Findings and fixes, by impact

### 1. Safety: a start inside obstacles allowed driving through walls (fixed)

- **Problem.** The "escape from the inflated zone" rule let the search accept any cell no worse than the start. When the map put the robot inside an obstacle (stale or corrupt map), every occupied cell qualified, so a route could cross walls.
- **Evidence.** The replay of explore trip 11:22:12 on the 12:32 map "arrived", with the robot body overlapping obstacles.
- **Fix.** Moves with negative clearance are only allowed within 0.5 m of the start (`escape_radius`), in the search and in analytic shots. When planning still fails from there, the message says "the map shows obstacles where the robot stands, so the map is probably wrong here".
- **Tests.** `test_planning_from_inside_a_phantom_obstacle_says_the_map_is_wrong`. The existing escape test still passes.

### 2. Safety: nav's new closer stop needs blind-zone memory (done together)

- **Change.** Your "lots of room before the obstacle" request: nav now stops at 0.15 m of free travel (was 0.3) and resumes at 0.25 m. Below 0.6 m it already creeps at the minimum speed.
- **Risk handled.** At 0.15 m the obstacle is inside the camera's blind zone (under ~0.3 m). Remembered scan points expire after 4 s, so a robot held in front of a wall would have forgotten it and driven on. The sim showed exactly this with the retention disabled: it drove 0.65 m into the wall.
- **Fix.** Remembered points within 0.4 m of the camera never expire while they stay there. A path or goto step blocked within 0.12 m of its end counts as arrived.
- **Test.** `test_nav_creeps_close_to_a_wall_and_stays_stopped_after_its_scan_memory_expires`: it stops about 0.18 m from the wall, doesn't move for 15 s, then faults `blocked`.

### 3. Object trips stopped too far away or in the wrong place (fixed; partly deployed at 13:02 and 13:14, the rest pending)

- **Evidence.**
  - Fridge 12:51: the camera ended 2.26 m from the fridge, because the far `seen_from` spot won.
  - Fridge 11:23: the robot faced a wall corner and made 11 replans and 3 recoveries.
  - Fridge 13:09: 6 replans and a 13 m detour.
- **Deployed.**
  - The detector centre snaps to the nearest obstacle cluster.
  - The standoff is measured along the view ray to the first obstacle cell: 0.5 m preferred, at least 0.4 m.
  - Line of sight and front clearance must hold through mapped cells first.
  - `seen_from` is only a tie-break within 1.2 m.
  - Goal hysteresis (0.5 per metre away from the previous viewpoint) and reach weight 0.6.
  - A 4 s hold before any detour longer than max(2× the remaining route, remaining + 3 m).
  - A 1.2 s budget per plan job.
- **Pending (tonight).**
  - Viewpoints that leave room for a 0.3 m straight approach are preferred, and heading goals are planned to a pose 0.3 m short of the goal plus a straight segment. Pure pursuit then settles the heading instead of curving into the goal.
  - Arriving facing more than 50° off is accepted only after 2 corrective replans, not 1.
  - Place goals use a 15° heading tolerance (corner2 arrived 18° off).
- **Replay now.**
  - Fridge 12:51 ends 0.84 m from the fridge centre.
  - Fridge 13:09 ends 0.83 m from it, with 0 replans.
  - Kettle on the 10:15 map: the robot used to be blocked at its viewpoint and back up; it now arrives cleanly.
- **Tests.** `..._ends_close_to_the_object_not_where_it_was_first_seen`, `..._prefers_a_line_of_sight_through_mapped_space`, `..._for_an_object_on_a_counter_leaves_room...`, `..._prefers_where_the_robot_saw_the_object_from`, `test_wall_found_in_new_map_data...` (now also checks the 4 s detour hold), `test_arriving_at_a_viewpoint_at_an_angle_settles...`.

### 4. Arrivals that never settled (fixed earlier, deployed at 11:12 and 11:38)

- **Point behind the robot.** The B2 run `point -1.5` failed "could not settle": point goals targeted the rear axle, so reaching one in reverse left the camera 0.37 m off. The search now checks the camera. Pinned by the sim test `test_point_behind_reached_in_reverse_counts_as_arrived`.
- **Explore viewpoint heading.** The explore trip at 11:21:52 also failed "could not settle", on heading. See item 3.

### 5. CPU and NATS: planner was a slow consumer (fixed, deployed at 12:32)

- **Evidence.** At 12:23 NATS cut rabbit-planner (WriteDeadline 10 s exceeded). py-spy showed the planner at 87% CPU while idle, all in the obstacle memory: with the 15 Hz scan facing a wall, every scan was compared against every remembered batch.
- **Fix.** The memory is now one deduplicated array, one point per 5 cm cell (0.08 ms per scan), and the trip costmap is cropped before stamping obstacles (the 50 × 50 m grid window is 1M cells). Idle CPU dropped to 1.6%.
- **Test.** `test_obstacle_memory_stays_small_while_the_robot_stares_at_a_wall`.
- **Pending (tonight).** `safety.free_distance` drops points beyond its reach before sweeping: 7 ms → 0.18 ms per call on the Mac with 2,900 remembered points. Nav peaked at 20–22% CPU while driving today. Pinned by `test_free_distance_ignores_points_beyond_its_reach...`.

### 6. Exploration aborted on camera restarts and pose gaps (fixed, deployed 11:19–12:52)

- **Problems.**
  - map.extend raced the zed restart ("no responders").
  - The planner refused trips with "no fresh pose" right after relocalizing, which burned the 5 allowed failures in a second.
  - The robot stood outside the grid's bounding box, so "no reachable frontiers left".
  - map.save was published after aborted runs.
- **Fixes.**
  - map.extend is a request-reply.
  - Explore waits for a new map_session, mapping mode and relocalization, then for 2 s of steady poses.
  - Refusals are retried without counting as frontier failures.
  - The costmap is padded around the robot.
  - The map is saved only after more than 0.5 m of driving.
- **Pending (tonight).** Also wait while health `relocalizing` is true.
- **New sim test.** `test_exploration_maps_most_of_an_unknown_apartment_without_touching_anything` runs the real explore `plan_next`, planner and nav, with a map built only from simulated scans. It explores more than 70% of the flat with at least 3 frontier trips and no contact.

### 7. Relocalization gate (pending)

- **Planner.** Trips and save_place are refused while health `relocalizing` is true (a missing field counts as false), or while memory is INITIALIZING or SEARCHING. A running trip fails "the camera lost its place in the map" if that happens mid-trip. LOST after relocalizing stays fine.

### 8. Not changed, but noted

- **Poses near walls.** In one replay (explore 12:49:29) the robot started close to a wall, facing it: nav's guard blocked the first turn twice, and then a 0.38 m back-up along its trail fixed it. That's acceptable. A planner-side preference for an initial reverse when the start faces a near wall would make it cleaner.
- **Pose extrapolation in nav (your suggestion).** At 30 Hz and 49 ms latency, the lag is about 0.6 cm at our ~0.12 m/s. Skipped; worth doing if cruise speed goes up.
- **Long tricky routes on the Jetson.** 12–13 m with a turnaround took 140–260 ms (27–49k expansions), above the 200 ms target. Typical trips take 5–80 ms.

## Files changed tonight (all uncommitted)

- **Robot code.**
  - `workspaces/rabbit/src/lib/planner.py`: escape radius; `goal_offset` (camera point goals).
  - `src/lib/trip.py`: viewpoints (snap, surface standoff, tiers, approach, hysteresis), detour hold, plan budget, arrival heading, buried-start message.
  - `src/lib/safety.py`: free_distance prefilter.
  - `src/node/nav.py`: 0.15/0.25 stop and resume, blind-zone retention, blocked-near-end counts as arrived.
  - `src/node/planner.py`: `relocalizing` gate, log levels.
  - `src/node/explore.py`: relocalizing and steady-pose waits, refusal retries.
- **Tests.** `tests/sim.py` (`run_mission`, `ScannedMap`, `explore`), `tests/test_navigation.py`, `tests/test_safety.py`.
- **Docs.** `.claude/skills/rabbit-dev/SKILL.md`, Route planning section.

## Needs on-robot verification (deploy rabbit-planner, rabbit-nav, rabbit-explore; about 30 s cold numba compile)

1. **Creep stop.** Drive slowly at a wall (`drive.py point 2` aimed at one). Nav should stop with the bumper about 0.15–0.2 m away, stay stopped for 10 s, then fault `blocked`. Watch the scan for flying pixels in the blind zone holding it stopped: retained points only clear once the robot moves away.
2. **Object trip.** Run `object fridge` from the living room. Expect about 0.5–0.9 m from the fridge, facing it within 30°, no detour flip, and at most one closer-view replan.
3. **Place trip.** Run `place corner2` and check the heading error at arrival (target ≤ 15–20°).
4. **Exploration after a zed restart.** It should wait ("waiting for the camera to relocalize"), not fail, and save the map only after driving.
5. **Load.** Check rabbit-nav CPU while driving (expect a few %), and that rabbit-planner stays under about 5% idle.
