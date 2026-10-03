# Frontier exploration and the Hybrid A* planner

Date: 2026-10-01, 11:26–21:03 UTC. Continued on 2026-10-02 in the route planner (`2026-10-02-route-planner.md`).

## Goal

A command that makes the robot map the flat by itself ("построил карту помещения сам").

## Decisions

- **Frontier exploration (Yamauchi) written in-house.** The ready-made packages (`explore_lite`, `m-explore`) depend on ROS, which the project does not use. The core is numpy (later numba) on the project's own grid.
- **Hybrid A* for Ackermann.** Written by a subagent in `lib/planner.py` with forward and reverse primitives, reverse and gear-change penalties, Dubins/arc analytic shots and smoothing. It uses the asymmetric curvature tables (minimum radius about 0.40 m to the right, so the planner uses 0.40).

## How exploration works (`node/explore.py`, `rabbit.nav.explore {max_duration_s, max_distance_m}`, state on `rabbit.explore.state`)

1. Occupancy grid from the map (at first `grid_from_mesh` over the ZED mesh, 5 cm cells, obstacles in the 4–45 cm band; since 2026-10-02 the GPU clearance grid `rabbit.map.grid`), plus free space along obstacle-scan rays (misses count as free up to 2.5 m).
2. Frontier clusters, ranked by information gain over path cost, with a turnaround penalty. The viewpoint is 0.5–0.8 m in front of the frontier facing the unknown area, because the camera only looks forward.
3. Drive there as a nav mission, look around with ±45° turns, repeat until no frontiers are left or a time/distance limit is hit, then save the map.

## Problems and fixes

| Problem | Cause | Fix |
|---|---|---|
| "no reachable frontiers left" after 3 s | scan history wiped on every map session change | keep scans across the first session change (11:53 UTC) |
| planner failed next to walls | start pose inside the inflated clearance | allow starting inside it (`66310d5`) |
| robot drove off by itself about 1 s after a manual takeover; stopping exploration left the mission running; blocked goals never blacklisted | races between explore and nav mission ownership | missions carry ids, explore waits up to 2 s for nav to adopt its id (`3ff28f1`, `8e419f9`) |
| A* time budget burned on a frontier 2.37 m away whose path was 42 m (behind a wall) | no pre-filter | `rank_frontiers(max_detour=3.0)`: skip frontiers whose cost exceeds 3 × straight distance + 1 m (`582d92a`) |
| exploration gave up after 5 failures in total | counter never reset | count only consecutive failures; blocked > 3 s within 0.5 m of the viewpoint counts as arrived (`582d92a`) |
| exploration aimed at z = −138 m and drove 0 m | tracking ran away (see `2026-10-01-map-resets.md`) | pose plausibility checks, later the odom/map split |

## Results on 2026-10-01

- 13:47 UTC: 6.02 m in 46 s after the depth-threshold rollback.
- 20:56 UTC: 9.7 m in 112 s; blocked episodes were real stops at 0.28 m from furniture.
- Planning times then: 0.1–7 s on the CPU grid (a 6.98 s plan during the pose runaway).

## Commits

`ac133e3`, `66310d5`, `3ff28f1`, `8e419f9`, `582d92a`.
