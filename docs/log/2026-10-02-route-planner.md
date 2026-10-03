# Route planner node: trips to points, places and objects

Date: 2026-10-02, 09:48–13:42 UTC (built by a planning subagent; robot drives from 10:46 UTC), plus fixes on 2026-10-02 21:43 – 2026-10-03 00:08 UTC. Uncommitted at the time of writing.

## Context

"Подъедь к холодильнику" (drive up to the fridge) failed: the voice/chat agent had no route tool and sent blind motion steps. The owner asked for long missions, replanning on new obstacles and on new wall information in the map.

## Design

- **Node** `node/planner.py` (`rabbit-planner`), trip state machine in `lib/trip.py` (`Navigator`, pure, also driven by the simulator), map source in `lib/navmap.py` (the GPU clearance grid `rabbit.map.grid`, or the mesh plus scan rays as a fallback), kernels in `lib/planner.py` compiled with numba (`nogil`; about 30 s cold after a code change on the Jetson, 0.5 s from cache).
- **Contract.** `rabbit.planner.goal` (request/reply) takes `{x, z, heading_deg?, tolerance?}`, `{object: {label, x, z, width, length, seen_from?}}` or `{place}`; `preview: true` plans without driving. Progress on `rabbit.planner.state` (2 Hz during a trip). The route goes to nav as one `path` step. Forge, the HUD GO TO click and explore all go through it. Places are stored per `map_id` in `data/map/places.json`; a place from another map is refused.
- **Costs.** A pose collides when one of three footprint circles has less than 0.18 m clearance; within 0.35 m beyond that the cost per metre rises linearly to 4×; unknown cells cost 2×; reverse 4×; a gear switch costs 2 m; reverse never enters unmapped cells (the scan only covers the front).
- **Search.** Dijkstra cost-to-go heuristic on a 10 cm grid (an unreachable goal fails in milliseconds), states 10 cm × 5°, 0.15 m arc primitives at five steering levels per gear, analytic shots within 4 m accepted only within 10 % of the heuristic.
- **Replanning** at up to 4 Hz (at most every 0.75 s): when the remaining path gets closer to an obstacle than planned, the robot is 0.35 m off the path, after a pose jump, nav is `blocked` for 1.5 s, or nav arrives short. After repeated blocks it backs up 0.35 m along its own trail (the only space known to be free behind) and replans, at most 3 times. Before a detour longer than max(2× remaining, remaining + 3 m) it waits 4 s once, so a person passing does not send it around the flat.
- **Object viewpoints.** The detector centre snaps to the nearest obstacle cluster within 0.6 m; viewpoints face it at 0.3–1.5 m and are scored by distance along the view ray to the first obstacle cell (0.5 m preferred, at least 0.4 m), line of sight through mapped cells, a free 0.3 m straight approach, and `seen_from` spots from Forge only as a tie-break within 1.2 m.

## Measurements

- On the Jetson with a real archived map (warm): fridge trip 32 ms, a 12 m cross-flat route 76 ms. Routes of 12–13 m with a turnaround took 140–260 ms (27–49k expansions). Before, planning on the CPU grid took up to 3 s.
- Drives on 2026-10-02: `point 2.0` arrived in 18.1 s with 0.02 m error; `place corner2` 3.32 m in 27.5 s, error 0.13 m; `point −1.5` (target behind) 1.33 m in 12.5 s, error 0.19 m; explore 6.03 m in 53.8 s; fridge 5.35 m in 52 s, stopping 0.3–0.4 m from the door.

## Failures found and fixed

| Symptom | Cause | Fix |
|---|---|---|
| `point −1.5` failed "could not settle" | point goals targeted the rear axle; reached in reverse the camera ended 0.37 m off | the goal search checks the camera point |
| fridge trip ended in front of a wall corner (11:23 UTC, 11 replans) | viewpoint chosen without line of sight; two "refrigerator" records, one recorded while the camera was still in a temporary frame | line of sight through known cells; Forge drops detections made while INITIALIZING/SEARCHING |
| fridge trip "arrived" 2.26 m short (12:51) | the far `seen_from` spot won the scoring | surface standoff along the view ray; `seen_from` only a tie-break |
| fridge trip with 6 replans and a 12–13 m detour flip (13:09) | no goal hysteresis | 0.5 per metre penalty for moving away from the previous viewpoint, 4 s hold before long detours |
| planner at 87 % CPU idle, cut by NATS as a slow consumer (12:23) | 15 Hz scan compared against every remembered batch while facing a wall | one deduplicated memory array (one point per 5 cm cell, 0.08 ms per scan), costmap cropped; idle CPU 1.6 % |
| a route could cross walls (replay) | "escape from the inflated zone" accepted any cell no worse than the start; with the robot inside a phantom obstacle that was every occupied cell | escape limited to 0.5 m from the start, with a "the map is probably wrong here" message |
| trips during relocalization went to wrong places | poses are in a temporary frame while INITIALIZING/SEARCHING | trips and place saves refused while health `relocalizing` is true |
| explore aborted on camera restarts | `map.extend` raced the zed restart ("no responders") | `map.extend` became request/reply; explore waits for the new session and steady poses |

## Offline replay

On 2026-10-02 night the robot was off. All 26 planner trips of the day were replayed (`workspaces/bench/replay/`; the data is in the gitignored `data/offline/` because it contains the flat's maps) through `tests/sim.py`: real nav node, real `Navigator` and planner, a bicycle model with the real curvature tables and a ray-cast scan with the 0.3 m blind zone. The saved `.nvblx` (sqlite) files are decoded into clearance grids. The map of 11:02–12:32 UTC was corrupt (obstacles where the robot had stood, 9 of 10 trip starts in occupied cells): integration debris from the millimetre poses (`2026-10-02-relocalization.md`). Report: `docs/reports/2026-10-02-planner-nav-explore.md` (not in the repo).

## Open

- Planner-side preference for an initial reverse when the start faces a near wall.
- Pose extrapolation in nav (lag about 0.6 cm at 0.12 m/s; not needed at current speeds).
- Long routes above the 200 ms target.

## Files

`workspaces/rabbit/src/node/planner.py`, `src/lib/trip.py`, `src/lib/navmap.py`, `src/lib/planner.py`, `src/node/nav.py`, `src/node/explore.py`, `tests/sim.py`, `tests/test_navigation.py`; Forge tools `go_to`, `plan_route`, `find_object`, places (`workspaces/forge/src/robot.ts`).
