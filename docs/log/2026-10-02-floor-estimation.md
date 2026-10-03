# Floor estimation

Dates: 2026-10-01 13:24 UTC (continuous floor), 2026-10-01 21:49 UTC (per-frame floor plane), 2026-10-02 08:57 UTC (table-proof estimator).

## Problem 1: one-shot floor origin (2026-10-01)

ZED's `set_floor_as_origin` is applied once at tracking start. Started on a raised platform or facing a wall, the whole session had the floor offset (13.5 cm too high in one case), and the fix applied was "reset the world and the saved room". The owner asked why the robot could not notice it had been moved instead ("Нельзя как то сделать так чтобы он сам определял это?").

Fix: `zed.py` keeps a smoothed floor estimate (smoothing 0.02), updated only when vertical speed is ≤ 0.05 m/s and tilt ≤ 10°, and publishes pose, obstacles and the mesh in a floor-at-zero frame (`encoded_floor_y`). The camera is 0.137 m above the floor (`CAMERA_HEIGHT` in `lib/geometry.py`). Verified: height 0.137, floor_y 0.135.

## Problem 2: the floor reported as an obstacle (2026-10-01)

84–91 % of nearest "contacts" were floor points at 6–10 cm: obstacle heights were measured from the global floor, and 1° of pose tilt is about 5 cm at 3 m. `lib/safety.py` `heights_above_floor` now fits a floor plane in each frame (candidates within ±8 cm, two least-squares iterations, 2 cm inlier band, slope ≤ 0.15, at least 200 points) and measures obstacle heights from it (`ae34946`).

## Problem 3: the robot "falls through the floor" on a table (2026-10-02)

The estimate assumed the wheels were always on the floor ("camera height − 0.137"). On a table it crept up to 0.69 m within seconds; the published pose dropped by the same amount and the HUD drew the robot sinking. A standing robot does no integration, so the mesh was not re-encoded either.

Fix: `lib/floor.py` `FloorEstimator` (smoothing 0.02, max step 0.15 m, candidate tolerance 0.05 m, adopt after 1.0 m). Slow drift is followed; a sudden height change becomes a candidate and is adopted only after the robot has driven 1 m at the new level. One floor offset is applied to everything zed publishes (pose, obstacles, objects, mesh). Verified on the table: pose y 0.823 m (0.69 + 0.137) with the room floor still at 0. The HUD draws its ground at `robot.y − 0.137`. Test: `tests/test_floor.py::test_lifting_the_robot_onto_a_table_keeps_the_room_floor`.

## Related

- The nvblox depth kernel clips rays at the floor plane and snaps points within 3 cm above it onto the floor (`2026-10-02-nvblox.md`).
- HUD voxels are offset by half a cell so floor noise of ±2.5 cm stays in one row (`2026-10-01-hud.md`).
- The ZED logs "Gravity alignment issues detected. Recomputing alignment…" on every start; an IMU calibration with the ZED tools was suggested, not done.
