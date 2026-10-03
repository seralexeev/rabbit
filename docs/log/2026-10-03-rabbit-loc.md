# rabbit-loc: RTAB-Map as the global localizer (shadow stage)

Dates: 2026-10-03 01:15–05:00 UTC, offline (the robot was off from about 02:00). Builds on `2026-10-02-slam-survey-and-benchmark.md` and `2026-10-02-odom-map-split.md`. Nothing is deployed yet.

## Goal

Replace ZED GEN_3 area memory (flaky relocalization, millimetre poses, `grab()` stalls, map resets) with a split: ZED GEN_3 VIO without area memory gives a continuous `odom`, and RTAB-Map provides `map←odom` from a persistent multi-session database. Stages: (1) the node and offline replay, (2) shadow on the robot, (3) zed applies the correction (`LOC_MODE=apply`, handed to another agent), (4) delete the area-file machinery.

## Design

| Piece | Where | Notes |
|---|---|---|
| `rabbit_rtabmap` | `workspaces/rabbit/native/rabbit_rtabmap` | nanobind module over librtabmap: `Localizer(db, params, incremental)`, `process(jpeg, png16, odom, stamp, fx, fy, cx, cy)` returns matches, inliers, timing and RTAB-Map's map correction; `set_mode`, `trigger_new_map`, `nodes`. Releases the GIL while processing. Works only in RTAB-Map frames |
| `lib/loc.py` | pure Python, tested | frame conversion (`to_rtabmap`/`from_rtabmap`), keyframe wire format, `LocalizationFilter`, `KeyframePolicy`, `planar` |
| `node/loc.py` | node `rabbit-loc` | `Session` (RTAB-Map plus filter plus mode policy) and the NATS node; `--replay DUMP` feeds a bench dump through the same `Session` without NATS or the ZED SDK |
| zed.py | `LOC_MODE=off\|shadow` (default `shadow`) | sends keyframes and reports the would-be correction; changes nothing else |
| image `rabbit-loc` | `docker/Dockerfile.loc` | Ubuntu 22.04, g2o, RTAB-Map (pinned commit, no ROS/Qt), uv-managed Python 3.12.11 (same as the staged 3.12 patch for `rabbit`). CPU only, built off the robot (the PCL-heavy compile units need ~1.6 GB each; the 4 GB colima VM thrashes, a separate `colima --profile build` VM with 14 GB works) |
| compose | service `rabbit-loc`, `profiles: ['loc']`, 512 MB, 1 CPU | `docker compose config --services` and a plain `scripts/deploy.sh` skip it; start with `docker compose --profile loc up -d rabbit-loc` |

### Frames

ZED `RIGHT_HANDED_Y_UP` (camera looks along −z, y up) maps to RTAB-Map's base frame (x forward, y left, z up) with `B = [[0,0,−1],[−1,0,0],[0,1,0]]`. The same rotation maps the Y-up world to RTAB-Map's Z-up world, so a pose `T` becomes `B T Bᵀ`, and the correction comes back as `Bᵀ C B`. The camera is the base (`localTransform` = optical rotation). `map←odom` is published in the raw ZED world, the same frame as zed's `self.odom`, not floor-shifted. The first session in an empty database defines the map frame: its odom frame.

### Messages

- `rabbit.loc.keyframe` (zed → loc): payload = JPEG (q85) of the left image + 16-bit PNG depth in mm, both 640×360; header `meta` = `{ts, session, odom (16 floats, row-major), intrinsics, rgb_bytes}`, `session` = zed's odom session. Sent on depth frames, at most every 0.5 s, when odom moved 0.1 m or turned 5°, or every 1 s while not localized; none while recording an SVO. About 0.15–0.3 MB per keyframe.
- `rabbit.loc.map_odom` (loc → all): `{ts (publish time), keyframe_ts (the keyframe the transform was last updated on), status: relocalizing|localized|lost, transform (16 floats), translation, orientation, map_id, odom_session, mode, matches, corrections, pending, last_match_ts}`, after each processed keyframe and at 1 Hz.
- `rabbit.health.loc`: status, mode, received/dropped/processed keyframes, process ms, WM size, nodes, inliers, RSS, DB size.
- `rabbit.health.zed` gets `loc`: status, age, matches, and `gen3_from_loc` = the planar (x, z, yaw) transform from the loc map frame to the GEN_3 map frame. In a correct shadow run it stays constant. In shadow mode zed also appends this to `data/loc/shadow.jsonl` at 1 Hz (rotated at 32 MiB to `shadow.jsonl.1`).

### Localization policy

- **Relocalizing runs in RTAB-Map's localization mode** (`Mem/IncrementalMemory=false`, every keyframe is tried), so a false match never writes to the persistent database. A false inter-session link would be permanent in a multi-session DB.
- **≥ 2 agreeing global matches** (appearance loop closures, within 0.3 m and 10°, within 10 s) before the first fix and before any jump of the accepted transform. In the bench, 1 of 40 simulated wake-ups was a lone false match 0.86 m off. Proximity matches only refine a transform they already agree with, because RTAB-Map searches for them around its own, possibly wrong, belief.
- **Lost**: no match for 30 s while odom travelled > 3 m. The last transform is kept; odom stays continuous.
- **Empty database**: mapping from the start; status `localized` with the identity.
- **Not localized after 60 s and ≥ 2 m of travel**: switch to incremental mapping as a new session in the same DB (`triggerNewMap`). Only matches to nodes of other sessions (by RTAB-Map map id) count. RTAB-Map's inter-session loop closures merge it, and its map correction then points into the oldest map's frame (verified in the bench merge runs: 27–29 links, 0 jumps).
- **New odom session** (rabbit-zed restarted): back to localization mode, `triggerNewMap` (clears RTAB-Map's correction and odometry cache), filter reset. `map_odom` carries `odom_session` so zed never applies a correction from a previous session.
- Parameters: `Mem/BinDataKept=false` (8× smaller DB, same localization in the bench), `Kp/MaxFeatures=300`, `Mem/InitWMWithAllNodes=true`, memory management off (`Rtabmap/TimeThr=0`, `MemoryThr=0`); `RGBD/LinearUpdate`/`AngularUpdate` 0.1 when mapping, 0 when localizing. Database `data/map/rtabmap.db`, map id in `data/map/rtabmap.id`.

## Offline results (replay, Mac arm64 container, Python 3.12.11)

`python src/node/loc.py --replay <dump> --db x.db` with `Mem/ImagePreDecimation=2`, because the dumps are 1280×720 and the robot sends 640×360. Keyframes at 2 Hz. RSS is VmRSS; anon is RssAnon. About 118 MB of VmRSS are clean shared-library pages (PCL, OpenCV): the imports alone are 151 MB.

| Replay | First fix | Localized keyframes | ms p50 | RSS / anon |
|---|---|---|---|---|
| loop1 into an empty DB (35 nodes) | mapping | — | 8 | 204 / 86 MB |
| loop2 against it | 1.03 s | 133/135, 0 corrections | 30 | 203 / 84 MB |
| mapping-manual2 into an empty DB (whole flat, 173 nodes, 55 MB DB) | mapping | — | 12 | 315 / 196 MB |
| loop1 against manual2 | 1.03 s | 59/61 | 36 | 289 / 170 MB |
| loop2 against manual2 | 21.5 s | 94/135 | 38 | 288 / 170 MB |

- loop2's map positions in the loop1 map are within 8 mm (median, 51 mm max) of the bench's RTAB-Map localization, which agreed with ZED's own relocalization to 1.5 cm.
- loop2's start isn't covered well by manual2. manual2 is a 4.5 fps recording, so the first fix comes only once loop2 reaches a mapped view. The GEN_3 baseline never relocalized loop1 or loop2 in manual2.
- `Kp/MaxFeatures=300` (default 500): −50 MB at the same or better localization. `RGBD/CreateOccupancyGrid=false` changed nothing. Expect 3–4× the Mac's per-keyframe time on the Jetson: ~120–150 ms at ≤ 2 Hz, ≤ 0.3 core.

A first replay showed a bug, now fixed: a first mapping session went `lost` after 30 s without loop closures. In that session the map is the odom, so `lost` is now off there.

Tests: `tests/test_loc.py` covers the axis mapping (camera forward = RTAB-Map +x, left turns stay left), round trip and correction composition, the wire format, the filter (single match is not a fix, two agreeing are, stale or disagreeing are not, proximity cannot fix, lone jump ignored and confirmed jump taken, lost needs time and travel, recovery), the keyframe policy and the planar offset. Full suite: 135 passed, 1 skipped.

## Growing the map while localized

`GrowthPolicy` (`lib/loc.py`) and `Session._grow` grow the map automatically when the robot drives into views the database doesn't cover. There is no extend request.

- **Start** (localization mode): localized; the last accepted fix at most 15 s old; 0.5–2 m of odometry since it, so a drifting or mis-localized pose is never written; 4 keyframes in a row without a match. Then switch to incremental mode. The first new node is linked (`addLink`, `kUserClosure`, variance 1e-3) to the last matched old node, with the transform implied by the verified `map←odom`, so the new chain is part of the map rather than an island. While growing, only matches to pre-growth nodes feed the filter, and `lost` is suspended: the grown map is the robot's own odometry.
- **Stop**: 2 consecutive keyframes match the map as it was before growing, or the fix is in doubt. Then back to localization mode. The database is saved on close when anything grew.
- **New session after 60 s** now applies only if this odom session never had a fix. A loss after a fix keeps localizing against the map instead of starting a disconnected session.

Replay (loop1 map only, 35 nodes; then mapping-manual2, which drives the whole flat):

| Check | Result |
|---|---|
| manual2 against the loop1 map | fixed after 9 keyframes, then grew 153 nodes, anchored to node 33; stayed localized to the end, 188 nodes, 55 MB DB |
| loop1 in the grown map vs loop1 in its own map | 59/61 localized, positions within 4 mm |
| loop2 in the grown map vs the bench reference (loop2 in loop1, validated against ZED) | first fix 1.03 s, 133/135, 11 mm median, 39 mm max |
| manual2 again against the grown map | 569/589 keyframes matched (55 on the first pass), positions within 6 mm median / 9 cm max of the first pass, nothing grown |
| loop2 against the loop1-only map | grew 18 nodes where loop2 leaves loop1's coverage |

## Not done yet

- Jetson numbers for the node (CPU, RSS with a whole-flat DB, keyframe latency): needs the robot.
- Forge (not deployed yet) records `rabbit.loc.map_odom` in the table `loc`, plus `loc_status` and `gen3_from_loc_x/z/yaw_deg` in `zed_health`. The shadow verdict for a day is one query: `SELECT stddevPop(gen3_from_loc_x), stddevPop(gen3_from_loc_z), stddevPop(gen3_from_loc_yaw_deg), count() FROM zed_health WHERE gen3_from_loc_x IS NOT NULL` (small spreads = both agree). Jumps: `SELECT ts, corrections, status FROM loc WHERE corrections > 0 ORDER BY ts`.
- Step 3 (applying `map←odom` in zed, nvblox in the map frame, rebuilds) is being written by another agent against the contract above. Step 4 (deleting `relocalization.py`, area save/load/archive, the planner's GEN_3 gate) comes after it.

## Shadow rollout (when the robot is back)

1. `docker save rabbit-loc | gzip -1 | ssh rabbit 'gunzip | docker load'` (≈ 170 MB compressed).
2. Deploy zed.py (`LOC_MODE` defaults to `shadow`), then `docker compose --profile loc up -d rabbit-loc`.
3. The first start creates `data/map/rtabmap.db` and maps the first session: drive the flat once, slowly, with this run as the reference map.
4. Watch `rabbit.health.loc` (RSS ≤ 300 MB, ≤ 1 core) and `gen3_from_loc` in `rabbit.health.zed` / `data/loc/shadow.jsonl` for a day.

## Step 3: rabbit-zed applies the correction (LOC_MODE=apply)

Added 2026-10-03, offline (not deployed). `lib/map_frame.py` (`MapFrame`, 13 unit tests in `tests/test_map_frame.py`) holds C = map←odom from `rabbit.loc.map_odom` and decides, per message, whether the map worker must reset (a new `map_id`), rebuild (C moved more than 5 cm or 2° from the C the nvblox map was built with) or flush (frames that waited while loc was not localized). zed (`LOC_MODE=apply`, 5 tests in `tests/test_zed.py`) then:

- turns GEN_3 area memory off (no `.area` save or load, no relocalization state machine, `on_map_extend` declines);
- publishes the map fields of `rabbit.zed.pose` from C·odom and leaves `odom` as it is; obstacles, objects, the floor estimate and `robot_xz` use the same map pose; before the first C the map pose is the odometry and health says `relocalizing`;
- integrates depth at C·odom into `data/map/loc.nvblx` (with `loc.nvblx.id` = the loc map id) and keeps each frame (every 0.2 m or 10°) with its odom pose. A rebuild reloads the file and re-integrates the kept frames with the new C; small changes only move the published pose, and new frames keep using the C the map was built with until a rebuild, so the map stays self-consistent.
- Relocalizing, lost or no message for 5 s: nothing goes into the persistent map; the frames wait (at most 300) and are integrated with the next C, since odometry is continuous within the odom session. A scratch map was rejected: it would need a second nvblox instance on the GPU and a merge, for data that the waiting frames already preserve.
- A message for another `odom_session`, or with a transform that is not a rigid transform, is ignored (counted in `loc.map_frame.rejected`).
- A new loc `map_id` archives `loc.nvblx` to `data/map/archive/` and starts an empty map; the kept frames are re-integrated once the new map localizes.

Known limit: content already saved into `loc.nvblx` keeps the C it was built with; only kept frames (since the last save) follow later corrections, as with the GEN_3 keyframe corrections before.
