# Operator heartbeat removed from nav

Date: 2026-10-02, 22:17–22:21 UTC. Uncommitted at the time of writing.

## Before

Added on 2026-10-01 during the code review as a dead-man: the HUD publishes `rabbit.operator.heartbeat` every 500 ms while the tab is connected and visible, and nav faulted missions with "operator link lost" after 3 s without it (`OPERATOR_TIMEOUT = 3.0`, `OPERATOR_PRESENCE = 60.0`).

## Problem

Autonomous trips failed whenever no HUD was open or the tab was hidden: test scripts and explore runs ended with `nav fault: operator link lost` after 2.7–15 s (2026-10-02 21:5x and 22:17 UTC).

## Attempt abandoned

A `supervised` flag only for missions started from the HUD (`source: hud`). It was implemented in `trip.py`/`nav.py` and reverted: it kept two behaviours for the same robot.

## Final

All heartbeat logic was removed from nav. The HUD is a viewer: nothing stops or changes when it disconnects. The heartbeat now only raises the camera's idle frame rate from 1 to 5 fps; explore and the planner wake the camera themselves (`rabbit.zed.wake`). Safety comes from the robot itself: the collision guard, stall and bump detection, the 0.25–0.4 s command timeouts and the RoboClaw's hardware serial timeout.

Docs updated: the `rabbit-robot` skill, Forge `robot.md` (fault list) and `ask.md` ("operator link lost" appears only in data before 3 October 2026, Sydney time).

Result the same morning: explore drove 8.02 m in 95 s, two goals reached, one back-up with replan, no false blocks.
