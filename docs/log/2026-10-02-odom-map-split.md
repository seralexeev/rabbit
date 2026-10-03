# Odometry / map pose split

Date: 2026-10-02, 22:53–23:00 UTC. Uncommitted at the time of writing.

## Context

One ZED pose served as both odometry and the global fix. Every relocalization or map correction moved it, and nav had to "re-anchor" missions after pose jumps (0.96–1.26 m, and 132–134 m during the millimetre-pose episodes). The SLAM survey recommended the standard split (REP-105): a continuous `odom` frame for control plus a `map→odom` correction.

## Change

- `zed.py`: every pose message carries an `odom` sub-object built by composing per-frame deltas from `get_position(..., REFERENCE_FRAME.CAMERA)`. It starts from the first plausible map pose; implausible deltas are rejected and counted in `odom_rejected`. It carries no relocalization or map-correction jumps.
- `nav.py`: control runs in the odom frame; missions and published state stay in the map frame and are converted with `rigid_transform` (`lib/geometry.py`: `planar_pose`, `rigid_transform`, `matrix_to_quaternion`, `quaternion_to_matrix`). Map jumps no longer jerk the steering.
- Test: `test_a_map_pose_glitch_does_not_make_nav_swerve_when_it_drives_on_odometry` — a 0.2 m sideways map glitch for 5 s; on odom the swerve stays under 0.03 m. The simulator (`tests/sim.py`) gained `odom` and `map_error` options.

## Check on the robot

A 2.8 m drive with a 90° turn (646 poses): odom and map diverged by at most 3 mm; the mission arrived.

## Next

The planner and explore stay in the map frame. The global localizer that will provide `map→odom` is being chosen in the benchmark (`2026-10-02-slam-survey-and-benchmark.md`).
