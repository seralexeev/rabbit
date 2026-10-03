# Offline replay of the 3 Oct navigation failures: recovery, loops, stuck

Date: 2026-10-03, 02:00–03:00 UTC. The robot was off, so this used only the Parquet export (`data/offline/export-20261003/`) and the archived maps. A review session was editing the same nodes at the same time. Uncommitted, not deployed. Full report: `docs/reports/2026-10-03-nav-replay.md`.

## Context

The field session (`2026-10-03-field-session.md`) left four symptoms behind, each with a quick fix in nav:

- an endless explore loop at 01:07;
- a false IMU collision at 01:10:50;
- a recovery that reversed into a wall for 70 s at 01:22;
- a `stuck` trip at 01:28:59 with a "free path ahead".

A fridge trip also failed at 01:37. The task was to find the root causes in the data, check the quick fixes, and fix the planner with tests.

## Findings

- **Recovery routes crossed gear changes.** "Back up 0.35 m along the trail" took the trail's last points in reverse order, with headings derived from the order of the points. Where the robot had changed gear, the heading flipped by 180° and the camera point jumped by 0.37 m. 10 of the 15 recovery missions in the export had such a jump. Three ended within 6 cm of their start:
  - **01:22:20:** it reversed into a wall that was in the map;
  - **01:37:59:** it reversed blind for 42 s and 4.3 m across the flat;
  - **01:50:59.**

  Rebuilding the trail from the recorded poses reproduces 9 of 11 of today's recovery missions exactly. Recoveries had no time or distance cap, and any nav fault during a recovery, including `stuck`, counted as "done backing up".
- **The trail lived in the map frame.** A map correction under the 0.25 m jump threshold shifted it relative to the robot. Positions where the robot was carried (at 01:28, pose height up to 0.37 m) stayed in it.
- **The 01:07 loop.** Explore asked for a viewpoint 7 cm from the robot and 22.5° off. That already met the arrival rule, yet the planner drew a 2.2 m loop. Nav's blocked-arrival check also accepted a loop whose end lay next to its start (01:08:15).
- **The `stuck` at 01:28:59 was real.** A planned reverse of ~0.9 m through mapped-free, never-driven space ended against something: left current 0.6 → 1.0 A, pose frozen for 2.75 s. Replaying the stuck rule over all of today's driving finds only real stops.
- **IMU.** A 50 ms mean over steady driving reaches p99.9 1.95 and at most 4.5 m/s². Real contacts at ~0.1 m/s peak at 1.7–2.5 m/s², so only `stuck` and `stall` can catch them. The threshold stays at 5.0.
- **Escape from a start inside phantom obstacles.** The goal search and A\* agree: they escape up to ~0.45 m and otherwise say "the map is probably wrong here". The fridge failure at 01:38:57 was the polluted map plus the runaway recovery.
- **Most blocks come right after a reverse-to-forward gear switch** (17 of 24 at |steer| ≥ 0.7). Pursuit commands full lock to rejoin the path, and the guard sweeps that sharper arc. Left open.

## Changes

- `lib/trip.py`:
  - **Trail.** It is kept in the odometry frame, with time and height. It is cleared on an odometry jump, an odometry or map session change (by the node), or a 5 cm height change.
  - **Backup route.** `backup_route` follows only forward-driven, heading-continuous trail under 120 s old, and is cut at the first pose that the planning costmap (map plus scan memory) shows as worse than the start or unknown.
  - **Caps.** A recovery is cancelled after 3 s + length/0.08 m/s, or once it is more than its length + 0.15 m from its start.
  - **Faults while backing up.** `stuck` drops the trail. Other safety faults end the trip.
  - **Escalation.** A block within 0.3 m of an earlier recovery spot fails the trip.
  - **`stuck`.** It is now handled like `blocked`, and `bump()` marks the contact point as an obstacle for the rest of the trip.
  - **Arrival.** A first plan whose goal the robot already meets ends the trip "already at the goal".
- `node/planner.py`: passes `pose.odom` and the camera height to the navigator, and clears the trail on session changes.
- `node/nav.py`: a blocked path step counts as arrived only when ≤ 0.12 m are left *along the path*.
- `tests/test_recovery.py`: 14 regression tests, all failing on the old code. Suite: 123 passed, 1 skipped.
- `workspaces/bench/replay/`:
  - `replay.py 20261003` picks the export and the map validity windows by day;
  - explore trips are replayed with the requested heading and tolerance (from `command_events`);
  - DuckDB runs in UTC.

## Follow-up (same night)

- **Reverse outside the driven corridor costs more.** Hybrid A\* gets a mask of the cells swept by the robot's body in the last 120 s. Reverse primitives off it cost up to 2.5× the normal reverse cost (10× forward); not a ban, so dead ends and points behind in corridors stay reachable.
- **Blocks after turns.** The recorded scans showed:
  - the robot was only 0–0.10 m off the path, so re-entry was not the problem;
  - the path's own arc was blocked too in 15 of 24 blocks;
  - the planned path was at ≥ 0.84 of full lock in 11 of them;
  - several blocks were next to a gear switch.

  Fixes:
  - the planner keeps 30% steering headroom (±0.7 steer);
  - it first tries a route with a 0.07 m larger footprint margin;
  - nav's stop distance near the end of a segment shrinks to what is left of it + 3 cm.

  A nav-side "steer toward the path's curvature when pursuit's arc is blocked" was tried and dropped: it had no effect. In the simulator the day's replays went from 9 to 3 blocks, the corridor turnarounds from failures to arrivals, and plan times did not change.
- **Dead code removed:**
  - `lib/planner.py`: `_mod2pi`, `drive_arcs`, `dubins_shots`, `clear_ray` with its test, and `_stamp`'s `reach` parameter;
  - explore: `trip_id`, `target.reverse_length`, also in the HUD type;
  - `lib/navmap.py`: `map_id`.

  Explore's `map_chunks` stays (Forge's schema requires it).
- Suite: 130 passed, 1 skipped.

## Latency (follow-up 2)

- **Measured from the data.**
  - pose capture to nav: 47 ms;
  - steering response: 0.06 s dead time + 0.05 s lag;
  - motors: the same, at 0.464 m/s per duty.

  The simulator models all of it now.
- **Extrapolating the control pose did not help.** Tracking stayed at 2.4–2.6 cm mean and p95 got worse; with the guard on the predicted pose, blocks doubled. It was removed. At 0.1 m/s the lag is under 2 cm, and the mid-turn blocks also happen in the ideal simulator.
- **Kept:**
  - scans are placed with the pose at their capture `ts` (interpolated from a 1 s history);
  - ground speed uses capture times.

  Corridor blocks 6 → 4. Tests in `tests/test_latency.py`.

## Tracker and speed (follow-up 3)

- **The rear-axle path was off on curves.** Nav took headings from the direction between camera points, which on arcs differs from the vehicle heading by up to ~23°. Paths now carry the planned heading (`[x, z, direction, theta]`); planner state keeps 3 values.
- **Pure pursuit is replaced by rear-wheel feedback** (curvature feedforward + lateral/heading feedback, L = 0.2 m, steering rate ≤ 6/s). Path heading is interpolated along segments.
  - Tracking 2.4/6.4 → 0.9/3.7 cm (mean/p95);
  - blocks in replays 3 → 0, in corridor turnarounds 6 → 1.

  Pursuit was removed: it was not better anywhere, including after gear switches.
- **Cruise duty 0.25 → 0.35** (0.12 → 0.16 m/s). Stopping is safe even at 0.7 in the simulator; camera confidence drops above ~0.2 m/s, so higher speeds wait for a field check.

## Exploration speed (follow-up 4)

- **Benchmark.** Six runs: two starts each in the apartment, a corridor flat and an open plan. Latency simulator with an 87° / 5 m camera mapper.
- **New `lib/exploration.py`.**
  - Views at 0.8/1.5/2.5 m from frontiers, or a turn on the spot.
  - Ranked by unknown area visible in the camera cone (obstacles stop rays; at most 1.5 m of unknown per ray) ÷ (0.8 m + path + 0.5 m/rad turn), ×1.25 near the previous view.
  - Done when no view shows 1 m².
- **Results (sum over 6 runs):**
  - t70 −14%, t90 −11%;
  - total time −21%, distance −19%;
  - failed trips 1 → 0.

  Two runs got slower to 90%. The tail after 90% (mop-up) remains.
- **Removed** the old frontier ranking from `lib/planner.py`.

## Exploration tail (follow-up 5)

- **Cause.** Score = gain / cost was global. A 1–2 m² corner left in the current room lost to a big view in another room, so the robot left and came back later. Traced on the corridor flat: it left the south-east room with a 1.4 m² view still nearby, then came back over a 10.8 m path.
- **Fix (`lib/exploration.py`).**
  - While any view within 3.5 m of path cost still shows ≥ 1 m², views farther away pay their travel twice (`LEAVE_FACTOR` 2), the price of coming back.
  - A trip beyond 3.5 m must show ≥ 2 m² (`MIN_FAR_GAIN`), so small far pockets don't earn a trip. "Done" became correspondingly stricter.
- **Latent bug found on the way.** Turns on the spot were offered again at a spot explore had already given up on, so exploration could loop forever. In the simulator, instant arrivals hung the benchmark.
- **Tried and dropped:**
  - "same room" as a flood fill of cells ≥ 0.45 m from obstacles (cut at doorways): 16 return trips against 10;
  - a distance exponent gain / cost^α with α = 1.5–3: within noise;
  - a far minimum of 3 m²: stopped one run at 57% coverage.
- **Results** (12 runs: 4 starts each in the apartment, corridor flat and open plan; latency simulator):
  - total distance 490 → 406 m (−17%), total time 3646 → 3051 s (−16%);
  - distance after 90% coverage 181 → 87 m (−52%);
  - return trips 10 / 62 m → 8 / 31 m;
  - time to 90% +4%, final coverage 0.96–0.99 (was 0.97–1.00).
- **Tests** (`tests/test_exploration.py`), each failing on the old logic:
  - a corner in the current room is finished before a big room 5 m away;
  - a small pocket far away doesn't earn a trip;
  - a spot given up on is not turned around on again.
- E2E rerun on free ports: 2 passed. Suite: 164 passed, 3 skipped.

## Decisions

- **A\* reverse.** Reverse in A\* needs mapped cells and costs more off the driven corridor. A ban would break goals behind the robot in corridors.
- **No tuning.** The stuck and IMU thresholds stay as they are.

## Open

- Pursuit saturating mid-turn (the remaining blocks).
- Explore viewpoints that leave the robot facing an obstacle; the next trip then starts with a reverse.
- A path-overrun fault in nav as defence in depth.
- Verify on the robot: blocked recovery in a corridor, and the `rabbit.planner.state` recovery events.

## Files

`workspaces/rabbit/src/lib/trip.py`, `src/lib/planner.py`, `src/lib/navmap.py`, `src/node/planner.py`, `src/node/nav.py`, `src/node/explore.py`, `tests/test_recovery.py`, `tests/test_planner.py`, `workspaces/web/src/perception/Telemetry.ts`, `workspaces/bench/replay/replay.py`, `one.py`.
