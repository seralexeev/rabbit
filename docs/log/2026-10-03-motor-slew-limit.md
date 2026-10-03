# Motor slew limiting

Date: 2026-10-03, 00:01–00:03 UTC. Uncommitted, deployed to `rabbit-roboclaw`, not yet verified while driving.

## Problem

During manual mapping drives (2026-10-02 23:02–23:05 UTC) the robot moved "дергано, как будто какой-то latency". Wi-Fi at −74/−75 dBm delivered joystick messages in bursts (432–606 per 20 s instead of a steady 30/s), the owner drove at full throttle (0.67 motor command after the joystick cap), and the 0.25 s command timeout hard-stopped the motors in every gap.

## Change

- `lib/drive.py`: `slew(current, target, dt, accel, decel)`, with the faster rate when braking or reversing.
- `node/roboclaw.py`: `ACCEL = 1.5` (half power in about 0.3 s), `DECEL = 5.0` (half power to zero in about 0.1 s); the command `TIMEOUT` 0.25 → 0.4 s, after which the output ramps down instead of stopping dead; `dt` capped at 5 I/O periods (0.1 s).
- Tests: `tests/test_drive.py` — a full-throttle burst after a pause does not jerk; braking stays fast.

## Constraint

The owner rejected a separate control link: the robot connects to everything only over Wi-Fi. Control has to tolerate bursts (hold the last command smoothly, smaller video while driving) instead.

## Side effect during the deploy

`scripts/deploy.sh rabbit-roboclaw` runs `docker compose up -d`, which also started `rabbit-zed`, stopped on purpose for a GPU benchmark window; the camera was stopped again and the benchmark step repeated. Rule added to the `rabbit-robot` skill.
