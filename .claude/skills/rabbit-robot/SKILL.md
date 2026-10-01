---
name: rabbit-robot
description: Operate the Rabbit robot - check that it is alive and healthy, deploy code to it, restart its services, read its logs, manage its saved room map, diagnose Wi-Fi, and shut it down. Use for any task that runs something on the robot or talks to its NATS.
---

# Operating Rabbit

## Access

- **Host.** `root@192.168.1.53` (hostname `rabbit`, the HUD calls it `jetson.rabbit`). SSH with `ssh -i ~/.ssh/rabbit_id_rsa root@192.168.1.53 '<command>'`. Never print or copy the key.
- **NATS.** Client `nats://192.168.1.53:4222`; websocket with TLS on `:9222` (HUD); monitoring at `http://192.168.1.53:8222` (`/varz`, `/connz?subs=1`), reachable over SSH as `localhost:8222`.
- **Quick scripts from the Mac.** `uv run -q --with nats-py python script.py`. Keep scratch scripts outside both repos.
- **Status at a glance.** Run `uv run -q --with nats-py python ~/projects/rabbit/.claude/skills/rabbit-robot/status.py`. It prints pose, obstacle scan, nav, explore, ZED health, power, motors and Wi-Fi from 3 s of traffic. If it times out, the robot is off, still booting, or the Wi-Fi is down: `ping 192.168.1.53`.

## Layout on the robot

- `/root/rabbit/workspaces/compose.yaml` runs these services:
  - `nats`, `nats-init` (creates the KV bucket `rabbit` and the `LOGS` stream) and `nats-dashboard`;
  - `rabbit-zed`, `rabbit-nav`, `rabbit-explore`, `rabbit-roboclaw`, `rabbit-steering`, `rabbit-ina`;
  - `rabbit-telemetry`, which runs with host networking;
  - `forge-clickhouse`, `forge-writer` and `forge-chat` (Forge, see `forge-dev`);
  - `rabbit-web`: nginx serving the built HUD at https://jetson.rabbit (port 443). It proxies `/api` to the chat and `/nats` to the NATS websocket, so the HUD needs only one address. It resolves both upstreams on every request, so recreating them doesn't break it.
  - `tunnel`: a Cloudflare quick tunnel to `rabbit-web` for sharing the HUD outside the LAN, with no authentication (the user's choice). The URL changes whenever the container restarts. Get it with `ssh -i ~/.ssh/rabbit_id_rsa root@192.168.1.53 'docker logs tunnel 2>&1 | grep -o "https://[a-z0-9-]*\.trycloudflare\.com" | tail -1'`.
- **Images:** all `rabbit-*` nodes share one image, `rabbit`, built by `rabbit-zed` from `rabbit/docker/Dockerfile.zed`, with the code bind-mounted. Forge's `forge` image holds only `node_modules`, and its sources are mounted read-only too.
- `/root/rabbit/workspaces/rabbit` is bind-mounted into the containers at `/rabbit`. A code change needs a container restart, not a rebuild. Only `docker/Dockerfile.zed` changes need a rebuild.
- **Saved room map** is in `/root/rabbit/workspaces/rabbit/data/map/`:
  - `room.area`: ZED tracking memory;
  - `room.chunks`: the mesh in the wire format, reloaded as the base layer;
  - `room.ply`: the mesh, for humans;
  - `archive/`: the last 5 maps, kept with their `.chunks` when tracking had to restart fresh;
  - `stand/`, `tilted/`, `raised/`, `stale/`: old manual backups.
- `nats/data` holds JetStream (the log buffer, 7 days).

## Deploy

From the Mac:

```sh
cd ~/projects/rabbit && scripts/deploy.sh --build         # also rebuild images (dependencies or a Dockerfile changed)
cd ~/projects/rabbit && scripts/deploy.sh                 # all rabbit-* services
cd ~/projects/rabbit && scripts/deploy.sh rabbit-nav      # only the listed ones
cd ~/projects/rabbit && scripts/deploy.sh nats rabbit-zed # nats only when nats/ config changed
```

`deploy.sh` does the following:
1. On a full deploy, or with `rabbit-web` in the list, it builds the HUD (same-origin chat).
2. It rsyncs `compose.yaml`, `nats/`, `rabbit/`, `forge/` (not `.env`, `node_modules` or `data/`) and `web/dist`.
3. It runs `docker compose up -d --remove-orphans` (with `--build` only when asked), then recreates the listed services (`--force-recreate`).

A code-only deploy takes about 30 s, because nothing is built. `tunnel`, `nats` and `forge-clickhouse` are not in the default list, so a deploy keeps the tunnel URL and the database running. The default list is every `rabbit-*` service plus `forge-writer` and `forge-chat`.

A full deploy takes about a minute. Restart only what you changed: `lib/node.py` affects every node, `lib/geometry.py` and `lib/safety.py` affect zed, nav and explore.

### Restarting `rabbit-zed`

It takes 30–60 s and is the only disruptive restart.

1. **On stop**, it saves the map (`room.area` and `room.chunks`), but only if it has already relocalized.
2. **On start**, it logs `Relocalizing against .../room.area`, then `Relocalized (KNOWN_MAP)` and `Loaded N saved map chunks`.
3. **Spatial mapping** turns on only after relocalization.
4. **If relocalization never succeeds**, it gives up after 30 s of camera motion (time standing still doesn't count), archives the map and restarts the process with a fresh map.
5. **If tracking fails** (pose tilt disagrees with the IMU), the process discards the session without saving, restarts itself and relocalizes against the last saved map. It archives the map only if the failure repeats within 2 minutes of start.
6. **A fresh session's origin** is where the SDK puts it, which is not always the robot's position (it has started at x = 17 m). Map and pose stay consistent, so this is harmless.

Wait for those log lines before testing:

```sh
ssh -i ~/.ssh/rabbit_id_rsa root@192.168.1.53 'timeout 150 sh -c "until docker logs --since 2m rabbit-zed 2>&1 | grep -qE \"Loaded .* saved map chunks|Restarting the camera process|Spatial mapping enabled\"; do sleep 2; done"; docker logs --since 3m rabbit-zed 2>&1 | grep -E "Relocal|Loaded|Restarting|Archived|Error" | cut -c1-160'
```

## Logs and health

- **Container logs:** `docker logs --tail 100 rabbit-nav`. Every node also publishes its log records to `rabbit.log.<node>`, and Forge stores them, so `logs` in ClickHouse is the searchable history (see `forge-dev`).
- **ZED health:** `rabbit.health.zed`, 1 Hz. Check:
  - `current_fps` (30);
  - `spatial_memory_status` (`KNOWN_MAP` or `MAP_UPDATE` is good; `SEARCHING` means still relocalizing);
  - `map_chunks`, `floor_y` (≈ 0 on the floor);
  - `frames_dropped`, `corrupted_frames`, `dropped_publishes`.
- **Expected rates:** `rabbit.zed.pose` 30/s, `rabbit.zed.imu` ~110/s, `rabbit.zed.obstacle` 10/s, `rabbit.roboclaw` ~50/s, `rabbit.ina` 50/s, `rabbit.steering` 20/s, `rabbit.nav.state` 10/s.
- **Jetson load:**
  - `docker stats --no-stream`: `rabbit-zed` sits around 100% CPU and 3 GB, which is normal;
  - `timeout 3 tegrastats`;
  - `free -m`.

## Topics worth knowing

| Subject | Content |
|---|---|
| `rabbit.zed.pose` | translation (camera, floor-relative y ≈ 0.137), orientation, confidence |
| `rabbit.zed.obstacle` | nearest, ahead and a 48-bin scan (±60°) of obstacles 4–45 cm above the fitted floor; `blind` when the floor ahead has no depth |
| `rabbit.nav.state` | mode (idle, driving, maneuvering, blocked, arrived, fault), fault, free_distance, path, mission_id (kept after a mission ends) |
| `rabbit.nav.mission` | `{id?, steps: [move/turn/goto/path], source}`; coordinates are camera positions in the map frame |
| `rabbit.nav.cancel`, `rabbit.nav.explore`, `rabbit.explore.state` | stop, start exploration `{max_duration_s, max_distance_m}`, its progress |
| `rabbit.cmd.drive`, `rabbit.cmd.joy` | motor commands; the joystick overrides missions (steering alone counts as active input) |
| `rabbit.map.chunks`, `rabbit.map.snapshot` (request), `rabbit.map.save` | live mesh updates, the full mesh, save to disk |
| `rabbit.operator.heartbeat` | sent by an open HUD; nav trips if it stops for 3 s after being seen |

## Moving the robot

Only with the user's go-ahead in this session; see the rules in `AGENTS.md`.

- **Guard every test script.** Watch `rabbit.nav.state` and publish `rabbit.nav.cancel` in a `finally`, and when the robot is driving with `free_distance` < 0.2, cancel at once.
- **Prefer nav missions to raw drive commands.** Nav has the collision guard; joystick and keyboard driving bypass it.
- **Reversing.** The scan only covers the front, so reverse only into space the robot just came from.
- **Build paths along the current heading.** Take the forward vector from the pose quaternion: `fx = -2(qx*qz + qy*qw)`, `fz = -(1 - 2(qx² + qy²))`. Heading 0 is not −z.

## Power, Wi-Fi and shutdown

- **Power mode:** MAXN_SUPER. The `rabbit-performance` systemd service runs `jetson_clocks` and turns off USB autosuspend and Wi-Fi power save. Never run `nvpmodel -m 0`, which is the 15 W mode.
- **Wi-Fi:** `wlP1p1s0` (Realtek rtl88x2ce), NetworkManager connection `richbitch`, power save pinned off in that connection, regulatory domain AU. To check:
  - drops: `journalctl -b | grep CTRL-EVENT-DISCONNECTED`; reason 34 means the router kicked the robot;
  - link: `iw dev wlP1p1s0 link`;
  - jitter: `ping -c 300 -i 0.1 192.168.1.1`.
  Rare 300–600 ms stalls are the driver.
- **Shutdown:** save the map (publish `{}` to `rabbit.map.save`, wait ~5 s), then `cd /root/rabbit/workspaces && docker compose stop -t 30 && shutdown -h now`. After boot every container starts by itself.
- **Hardware quirks:**
  - The ZED camera sometimes needs re-plugging on USB; ask the user.
  - The RoboClaw is on UART `/dev/ttyTHS1` unless its USB cable is connected.
  - The wheel encoders do not count, so speed comes from the pose.

## Disk

- **Jetson:** NVMe 915 GB with lots of free space. About 75 GB are stale Docker images, reclaimable with `docker image prune -a` (ask first).
- **Forge:** ClickHouse on the robot grows about 15 MiB per hour of driving, in the Docker volume `workspaces_forge-clickhouse`.
