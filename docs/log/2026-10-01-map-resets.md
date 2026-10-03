# Map resets and map losses, with causes

Dates: 2026-10-01 to 2026-10-03 (UTC). Every row is a moment when the saved room map stopped being used. Maps are archived in `data/map/archive/` on the robot (last 5) since `e6e69d7` (2026-10-01 14:18 UTC); before that a single `room.area.previous` was kept.

| UTC | What happened | Cause | Category |
|---|---|---|---|
| 2026-10-01 10:35 | map moved to `data/map/stand/` | it was made on a stand; the floor origin was wrong once on the floor | manual, floor origin |
| 2026-10-01 11:05 | map moved to `stale/` | relocalization hung after an unexpected Jetson reboot; the pose froze | relocalization |
| 2026-10-01 11:36 | map moved to `tilted/` | tracking lost its frame while the robot was carried (world tilted 14°/12°, robot 0.24 m under the floor) and that state was saved | tracking failure saved to disk |
| 2026-10-01 13:24 | map moved to `raised/` | the robot had been started raised; floor 13.5 cm off | floor origin (led to the floor estimator) |
| 2026-10-01 14:03, 14:08 | "Restarting tracking with a fresh map: relocalization timed out" | 15 s timeout; the big map was renamed to the single backup | timeout policy |
| 2026-10-01 20:02 | the big room map lost for good | first boot in the morning still ran the old code; relocalization from the platform failed and overwrote the only backup | timeout policy + single backup |
| 2026-10-01 21:31 | restored 57 MB map relocalized once, then timed out | viewpoint right against a cabinet | environment |
| 2026-10-01 22:01–22:37 | map archived on restart | tracking failure, re-enabled in-process → poses ~54 m away; the corrupted session was saved and could not be relocalized | tracking failure saved to disk |
| 2026-10-01 23:03 | reset (test of the new RESET MAP action) | intended | manual |
| 2026-10-02 05:38, 05:58, 09:10 | "map reset requested by hud" | unknown; the public HUD had no access control until 05:38 and someone with a link may have pressed it | HUD |
| 2026-10-02 06:41 | fresh map during an SVO drive | relocalization timeout (motion counted while standing) | timeout policy |
| 2026-10-02 07:47–08:03 | four archive-and-restart cycles after redeploys; maps restored by hand from the archive | timeout rules (motion counter, then 120 s wall timeout) | timeout policy, fixed with the 3 m rule |
| 2026-10-02 08:22, 08:34 | fresh maps for the GEN_1 experiment and back | intended | experiment |
| 2026-10-02 11:02 | reset | robot carried from the table to the floor stayed LOST; switching to mapping from LOST deadlocked | carried robot |
| 2026-10-02 11:02–12:32 map | corrupt (obstacles where the robot had stood) | millimetre poses integrated into nvblox | SDK bug |
| 2026-10-02 12:32 | reset | auto-switch to localization while facing a white wall corner; INITIALIZING for over an hour | environment + mode switch |
| 2026-10-02 22:00 | reset | `room.area` saved at shutdown while LOST; next morning no relocalization even with the backup restored | save policy |
| 2026-10-02 23:03 | new map | rabbit-zed crashed (CUDA OOM in nvblox) during a recording; no relocalization within 45 s after restart | crash + timeout |
| 2026-10-02 23:09 | new map | after a full deploy no relocalization within 45 s against a map saved 5 minutes earlier, robot static | GEN_3 relocalization |

## Patterns

1. **Saving a bad session over a good map** (carried robot, in-process tracking restart, LOST at shutdown). Now: the map is saved only after relocalizing, only in mapping mode and only when localized; failed sessions are discarded; archives keep the last 5.
2. **Give-up rules that fire on a standing robot** (time, `camera_moving_state`). Now: 3 m of travel while searching, or 45 s without any localized state.
3. **The SDK's own relocalization is fragile** (blank walls, glass, light changes, static start). This is the motivation for the localization benchmark (`2026-10-02-slam-survey-and-benchmark.md`).
4. **Unauthenticated public HUD.** Closed by access links on 2026-10-02 05:38 UTC.
