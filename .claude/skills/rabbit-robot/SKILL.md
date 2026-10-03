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
  - `rabbit-zed`, `rabbit-nav`, `rabbit-planner`, `rabbit-explore`, `rabbit-roboclaw`, `rabbit-steering`, `rabbit-ina` (`rabbit-planner` and `rabbit-explore` compile numba kernels at start: ~30 s after a code change, then cached);
  - `rabbit-telemetry`, which runs with host networking;
  - `forge`: Forge's writer, Parquet store and chat API in one process (see `forge-dev`);
  - `rabbit-web`: nginx serving the built HUD at https://jetson.rabbit (port 443). It proxies `/api` to the chat and `/nats` to the NATS websocket, so the HUD needs only one address. It resolves both upstreams on every request, so recreating them doesn't break it.
  - `tunnel`: the Cloudflare tunnel `rabbit` (account Sergey, zone `rabbit0.dev`) that publishes `rabbit-web` at https://live.rabbit0.dev (and https://robot.bunnyfleet.com, zone `bunnyfleet.com`) only to holders of an access link (see "Access links" below). Its token is in `/root/rabbit/workspaces/tunnel.env` on the robot (gitignored, never print it). The route (HTTPS to `rabbit-web:443`, No TLS Verify) is configured in the Cloudflare dashboard under Zero Trust → Networks → Tunnels.
- **Images:** all `rabbit-*` nodes share one image, `rabbit`, built by `rabbit-zed` from `rabbit/docker/Dockerfile.zed`, with the code bind-mounted. Its first stage compiles nvblox (pinned commit) and the `rabbit_nvblox` extension into `/opt/rabbit_nvblox`, which takes about 15 min from scratch and is cached afterwards. `docker compose up` rebuilds the image by itself when the Dockerfile or `native/` changed. Forge's `forge` image holds only `node_modules`, and its sources are mounted read-only too.
- `/root/rabbit/workspaces/rabbit` is bind-mounted into the containers at `/rabbit`. A code change needs a container restart, not a rebuild. Only `docker/Dockerfile.zed` changes need a rebuild.
- **Saved room map** is in `/root/rabbit/workspaces/rabbit/data/map/`:
  - `room.area`: ZED tracking memory (GEN_3 keyframes);
  - `room.nvblx`: the nvblox TSDF map, loaded after relocalization;
  - `room.id`: the map id (creation stamp), stable across restarts, new after a reset or archive; published as `map_id` in health and as header `map` on map messages;
  - `room.extend`: present while the tracking is in mapping mode (see below);
  - `room.ply`: the mesh, for humans;
  - `archive/`: the last 5 maps, `.area` with its `.nvblx` (older ones have `.chunks`), kept when tracking had to restart fresh;
  - `stand/`, `tilted/`, `raised/`, `stale/`: old manual backups.
- `nats/data` holds JetStream (the log buffer, 7 days).

## Access links

Public (tunnel) access to the HUD needs a revocable link; the LAN (https://jetson.rabbit, NATS on `:9222`) stays open.

```sh
scripts/links.sh              # list: name, date, link
scripts/links.sh add alice    # prints https://live.rabbit0.dev/k/<token>
scripts/links.sh rm alice     # revoke
```

- **Registry:** `/root/rabbit/workspaces/links/links.map` on the robot (gitignored, not in the repo), lines `<token> <name>; # <date>`, included as an nginx `map` by `web/nginx.conf`.
- **How it works:** `/k/<token>` sets the `rabbit_link` cookie and redirects to `/`. A request that came through the tunnel (it has `Cf-Connecting-Ip`) without a listed cookie gets a 403 on every path, including `/nats` and `/api`.
- **Revoking** reloads nginx, and `worker_shutdown_timeout 5s` (in the `rabbit-web` command) closes open websockets 5 s later, so the user is cut off within seconds. Every add or rm briefly reconnects every open HUD, LAN ones included.
- **Who is using it:** `docker logs rabbit-web` prints `link=<name>` on every request.


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
4. After a successful deploy it runs `docker image prune -f`, which removes only dangling images (the previous untagged `rabbit` image after a `--build`, about 11 GB each), never tagged or running ones.

A code-only deploy takes about 30 s, because nothing is built. Any deploy runs `docker compose up -d`, so it also starts services that were stopped on purpose (for example rabbit-zed during a benchmark window). `tunnel`, `nats` and `forge-clickhouse` are not in the default list, so a deploy keeps the tunnel URL and the database running. The default list is every `rabbit-*` service plus `forge-writer` and `forge-chat`.

Even with a service list, step 3's `compose up -d` recreates every container whose image or config changed, so after someone rebuilt `rabbit:latest` a deploy of one node restarts all `rabbit-*` nodes, `rabbit-zed` included; check `docker compose up -d --dry-run` on the robot first when that matters.

A full deploy takes about a minute. Restart only what you changed: `lib/node.py` affects every node, `lib/geometry.py` and `lib/safety.py` affect zed, nav and explore.

### Map mode

GEN_3 "lifelong" area mapping keeps adding keyframes even standing still (an SDK 5.5.0 bug). That costs 0.5–1 core and grows `room.area` by MBs per minute, which in turn makes relocalization slow or impossible. So rabbit-zed runs the tracking in two modes, `map_mode` in health:
- `localization` (the default when `room.area` exists): the area is only used, never extended; rabbit-zed idles at ~20–45% CPU.
- `mapping`: for a fresh map, or after a `rabbit.map.extend` request (`{"source": ...}`, sent by explore before exploring). The reply is `{accepted, restarting, reason}`; it is refused unless the camera is localized in the saved map. When accepted, rabbit-zed saves, restarts (~20 s without pose) and maps. It switches back to localization (save + restart) after 3 min of idle, but only when it has been localized for a minute and the view is open (> 1.2 m free ahead): relocalizing in front of a blank wall fails, and a robot left facing a wall stays INITIALIZING until it is turned towards the room.
nvblox (the voxel map and `rabbit.map.grid`) integrates in both modes. In localization mode, rooms outside the area show `spatial_memory_status` LOST while the pose keeps coming from VIO.

### Frame rates

The camera runs at 30 fps and is processed at 30 fps while anything moves (nav driving, joystick or drive commands, pose motion, or `rabbit.zed.wake` `{"seconds": ≤60}`). It drops to 5 fps when idle with a HUD open (`rabbit.operator.heartbeat`), and to 1 fps when idle and unwatched. Depth is computed only on every 2nd frame (GEN_3 tracking doesn't need it), which feeds the obstacle scan (15 Hz), nvblox (15 Hz) and the detector (every 4th frame). A 15 fps compute cap was tried and removed: same CPU, but +55 ms of pose latency.

### Restarting `rabbit-zed`

It takes 30–60 s and is the only disruptive restart.

1. **On stop**, it saves the map (`room.area`, `room.nvblx`, `room.ply`), but only if it has already relocalized. It also saves a minute after start, every 5 min and on `rabbit.map.save`, logging `Saved the map: ...`.
2. **On start**, it logs `Relocalizing against .../room.area`, usually `Dropping implausible poses` (an SDK glitch it filters), then `Relocalized (KNOWN_MAP)` once the status has held for 10 s, `Loaded N saved map blocks` and `Mapping enabled`.
3. **Mapping** (nvblox) turns on only after relocalization, and integrates depth only while the camera moves.
4. **If relocalization never succeeds**, it gives up after the robot has driven 3 m (odometry) or after 45 s at full frame rate without a localized status, archives the map and restarts the process with a fresh map. The time limit is deliberate: the owner often carries the robot to another room and switches it on there, and a robot stuck in INITIALIZING is useless; a new map is rebuilt by exploring. Relocalization fails when the view or the light differs a lot from when the map was made (facing the glass door, evening vs day); turning the robot towards the room helps.
5. **If tracking fails** (pose tilt disagrees with the IMU), the process discards the session without saving, restarts itself and relocalizes against the last saved map. It archives the map only if the failure repeats within 2 minutes of start.
6. **A fresh session's origin** is where the SDK puts it, which is not always the robot's position (it has started at x = 17 m). Map and pose stay consistent, so this is harmless.

Wait for those log lines before testing:

```sh
ssh -i ~/.ssh/rabbit_id_rsa root@192.168.1.53 'timeout 150 sh -c "until docker logs --since 2m rabbit-zed 2>&1 | grep -qE \"Mapping enabled|Restarting the camera process\"; do sleep 2; done"; docker logs --since 3m rabbit-zed 2>&1 | grep -E "Relocal|Loaded|Restarting|Archived|Error" | cut -c1-160'
```

## Bring-up after the robot was off

`scripts/bringup.py` (run with `uv run scripts/bringup.py <phase> ...`) runs the steps of "When the robot is back on" in `docs/roadmap.md` and prints PASS, FAIL or SKIP with evidence for each check; the report goes to `data/bringup/<UTC time>.md`. Phases, in the usual order:

- `check`: ssh, every container up and healthy, clocks pinned (CPU `scaling_min_freq` 1728000, GPU `min_freq` 1020 MHz), the nvpmodel drop-in and `rabbit-performance`, ≥ 700 MB RAM available and ≥ 20 GB disk, ZED health, NATS rates of pose, obstacle, IMU, RoboClaw and nav state (after `rabbit.zed.wake`), the Wi-Fi link. Read-only.
- `deploy`: `scripts/deploy.sh` with the roadmap's services (`--services` to change them; forge services are refused unless `--forge`, which is for after the cutover), waits for the containers, checks each for tracebacks and that `node.<name>` imports, then runs the nvblox tests in rabbit-zed.
- `diet`: copies `workspaces/jetson/diet.sh` to the robot and shows its dry run; `--apply` applies it and checks that a second dry run is empty.
- `forge-cutover`: checks the shadow store, runs the eval before (old code, ClickHouse), exports ClickHouse rows before the shadow start and imports them into the Parquet store, then stops; `--switch` goes on with runbook steps 3–10 (tags the images, stops forge-shadow, applies the compose patch and the deploy/nginx changes in the tree, deploys `forge`, removes the old log consumer, eval after, parity, bench). Forge's ClickHouse is never removed by the tool.
- `motion`: needs `--motion` and the operator typing `floor` at the prompt. Tests (`--tests wall,restart,trip,explore`): creep to a wall 0.5–1.8 m ahead (expects a stop with 0.15–0.2 m free distance), a camera restart (`docker restart rabbit-zed`) during a 1 m mission (expects the `odometry reset` fault), a 2 m planner trip straight ahead (tracking error to the planned path), a 60 s exploration (distance, frontiers, blocked and stuck counts). Each test publishes `rabbit.nav.cancel` and a zero `rabbit.cmd.drive` when it ends, however it ends, and aborts when nav reports less than 0.1 m of free distance while driving or goes silent for 2 s.
- `loc-shadow`: starts rabbit-loc (compose profile `loc`, image built off the robot) with rabbit-zed in shadow mode and reports the `rabbit.loc.map_odom` status counts, matches and corrections after `--minutes`.

`--sim` runs `check` and `motion` against `scripts/sim.sh` (NATS on 127.0.0.1:14222 by default, `--nats` for another port; the camera restart is `rabbit.sim.restart`). Don't start a second simulator on 14322: `tests/test_e2e.py` uses that port.


- **Container logs:** `docker logs --tail 100 rabbit-nav`. Every node also publishes its log records to `rabbit.log.<node>`, and Forge stores them, so Forge's `logs` table is the searchable history (see `forge-dev`).
- **ZED health:** `rabbit.health.zed`, 1 Hz. Check:
  - `current_fps` (30);
  - `spatial_memory_status` (`KNOWN_MAP` or `MAP_UPDATE` is good; `SEARCHING` means still relocalizing);
  - `map_chunks`, `floor_y` (≈ 0 on the floor);
  - nvblox: `integrate_ms` (~1), `mesh_ms` (30–90 every 2 s), `stored_frames`, `map_rebuilds` (the map is rebuilt from stored frames when ZED corrects keyframe poses by > 5 cm / 2°), `keyframes`;
  - `frames_dropped`, `corrupted_frames`, `dropped_publishes`.
- **Expected rates:** `rabbit.zed.pose` 30/s while moving (5/s or 1/s idle, see Frame rates; latency camera→subscriber ~50–65 ms), `rabbit.zed.imu` ~110/s, `rabbit.zed.obstacle` half the pose rate, `rabbit.roboclaw` ~50/s, `rabbit.ina` 50/s, `rabbit.steering` 20/s, `rabbit.nav.state` 10/s.
- **Jetson load:**
  - `docker stats --no-stream`: `rabbit-zed` sits at ~20–45% CPU standing in localization mode, ~175% driving, up to ~280% exploring in mapping mode and ~200% while stuck relocalizing, with 1.3–1.8 GB, which is normal. Autosaves happen only when idle (an area save blocks the grab for ~0.3 s). Most of it is the GEN_3 tracking optimizer (`sl_ceres`), which grows with the number of keyframes. Never attach gdb to it: the camera freezes for minutes. Use `py-spy dump --nonblocking` and `top -H`;
  - `timeout 3 tegrastats`;
  - `free -m`.

## Phase 0 on the robot

Rabbit 2.0 phase 0 needs no purchases; the background is in `docs/log/2026-10-03-phase-0-tools.md`. None of this moves the robot. The RoboClaw tools never send drive commands, and while `rabbit-roboclaw` is stopped nothing else can. The code must be on the robot first: `scripts/deploy.sh rabbit-ina rabbit-roboclaw` also syncs `rabbit/tools/`.

1. **INA shunts.**
   - Read the markings on the INA4235EVM shunts: `R010` is 10 mΩ, `R005` 5 mΩ, `R002` 2 mΩ.
   - rabbit-ina logs what it assumes at every start: `SELECT ts, values FROM events WHERE name = 'power.calibrated' ORDER BY ts DESC LIMIT 1` (default 10 mΩ, SHUNT_CAL 512 on both channels).
   - If a shunt differs, add `environment: ['INA_SHUNT_OHMS=1=0.002']` (`channel=ohms`, comma-separated) to `rabbit-ina` in `workspaces/compose.yaml` and run `scripts/deploy.sh rabbit-ina`. The new values appear in `power.calibrated` and `node_starts.env`.
   - Sanity check: at idle, battery power is about 2× the Jetson's VDD_IN (21.7 W vs 9.8 W median so far).
   - `power.battery_clipped` marks readings from 90% of the shunt range (7.37 A on 10 mΩ).
2. **RoboClaw configuration** (current limit 3 A per channel, serial timeout 0.5 s, saved to NVM):

   ```sh
   ssh -i ~/.ssh/rabbit_id_rsa root@192.168.1.53
   docker stop rabbit-roboclaw
   R="docker run --rm --privileged -v /root/rabbit/workspaces/rabbit:/rabbit -v /dev:/dev -v /var/run/docker.sock:/var/run/docker.sock -w /rabbit --entrypoint /rabbit/.venv/bin/python rabbit"
   $R tools/roboclaw_config.py read         # firmware, battery limits, max currents, S3-S5, timeout, PWM and encoder modes, status
   $R tools/roboclaw_config.py plan         # diff to the target
   $R tools/roboclaw_config.py apply --yes  # writes, reads back, saves to NVM (command 94)
   ```

   - **Check the NVM.** Power-cycle the RoboClaw with the usual shutdown (save the map, `docker compose stop -t 30`, `shutdown -h now`, switch off and on), then `$R tools/roboclaw_config.py read`: M1 and M2 max current must be 3.00 A. Then run `docker start rabbit-roboclaw`. With `restart: unless-stopped`, a container stopped by hand stays stopped after a reboot.
   - **Choosing the port.** Add `-e ROBOCLAW_PORT=/dev/ttyTHS1` to `$R` for the UART; the default is the USB port if present.
   - **The tool refuses to run while `rabbit-roboclaw` is running.**
   - **Phase 2 only.** `--battery` (main battery 12.4–17.4 V, refused while the RoboClaw reads the 12 V buck) and `--estop` (S3 non-latching E-stop, only with the 1 kΩ pull-down wired and the Pi holding the line high).
3. **Encoders**, after rewiring them (table in `docs/reports/2026-10-03-architecture-2.0-wiring.md`), with `rabbit-roboclaw` stopped:
   - `$R tools/roboclaw_encoders.py` streams counts and speeds at 10 Hz. Turn each wheel by hand: its count must move, and forward must count up.
   - `$R tools/roboclaw_encoders.py --distance 1.0`: push the robot 1 m along a tape and press Ctrl-C. Each side must PASS (19,014 counts ± 3%). The summary says what to fix when there are no counts or a side counts down.
   - Then `docker start rabbit-roboclaw`.

## Topics worth knowing

| Subject | Content |
|---|---|
| `rabbit.zed.pose` | translation (camera, floor-relative y ≈ 0.137), orientation, confidence |
| `rabbit.zed.obstacle` | nearest, ahead and a 48-bin scan (±60°) of obstacles 4–45 cm above the fitted floor; `blind` when the floor ahead has no depth |
| `rabbit.nav.state` | mode (idle, driving, maneuvering, blocked, arrived, fault), fault, free_distance, path, mission_id (kept after a mission ends) |
| `rabbit.nav.mission` | `{id?, steps: [move/turn/goto/path], source}`; coordinates are camera positions in the map frame |
| `rabbit.nav.cancel`, `rabbit.nav.explore`, `rabbit.explore.state` | stop, start exploration `{max_duration_s, max_distance_m}`, its progress |
| `rabbit.planner.goal`, `rabbit.planner.state` | planned trip to `{x, z}`, `{object: {label, x, z, width, length}}` or `{place}` (request-reply; `preview: true` plans without moving), and its progress (phase, route, replans, message) |
| `rabbit.planner.places`, `.places.save`, `.places.delete` | named places on the current map (request-reply) |
| `rabbit.cmd.drive`, `rabbit.cmd.joy` | motor commands; the joystick overrides missions (steering alone counts as active input) |
| `rabbit.map.chunks`, `rabbit.map.snapshot` (request), `rabbit.map.save` | live mesh updates (nvblox blocks, every 2 s, only changed ones), the full mesh, save to disk |
| `rabbit.map.grid`, `rabbit.map.grid.snapshot` | 2D clearance grid from the nvblox ESDF (obstacles 4–45 cm above the floor), `lib/spatial_map.decode_grid`; int16 mm to the nearest obstacle, 0 obstacle, -1 unknown, 5 cm cells; every ≤2 s while the map changes |
| `rabbit.map.extend` | switch the tracking to mapping mode (restart), see Map mode |
| `rabbit.zed.record` | `{"name": "x"}` records an SVO2 to `data/svo/x.svo2` (lossless, CPU-encoded, ~15 fps, ~1 GB/min), `{}` stops |
| `rabbit.operator.heartbeat` | sent by an open, visible HUD; only raises the camera's idle rate to 5 fps. The HUD is a viewer: nothing stops or changes when it disconnects |

## Moving the robot

Only with the user's go-ahead in this session; see the rules in `AGENTS.md`.

- **Guard every test script.** Watch `rabbit.nav.state` and publish `rabbit.nav.cancel` in a `finally`, and when the robot is driving with `free_distance` < 0.2, cancel at once.
- **Prefer nav missions to raw drive commands.** Nav has the collision guard; joystick and keyboard driving bypass it.
- **Reversing.** The scan only covers the front, so reverse only into space the robot just came from.
- **Build paths along the current heading.** Take the forward vector from the pose quaternion: `fx = -2(qx*qz + qy*qw)`, `fz = -(1 - 2(qx² + qy²))`. Heading 0 is not −z.

## Power, Wi-Fi and shutdown

- **Power mode:** MAXN_SUPER. The `rabbit-performance` systemd service (versioned in `workspaces/jetson/`, installed to `/usr/local/bin` and `/etc/systemd/system`) does the following at boot:
  - runs `jetson_clocks`, which locks the CPU at 1.728 GHz, the GPU at 1.02 GHz and EMC at 3.2 GHz, with idle states off;
  - turns off USB autosuspend and Wi-Fi power save;
  - sets PCIe ASPM to `performance`;
  - sets `vm.swappiness` to 10;
  - pins the camera's USB interrupt to CPU2, the RoboClaw UART to CPU4 and I2C to CPU5. All interrupts used to land on CPU0 and kept it at 100%. The Wi-Fi interrupt (PCIe MSI) can't be moved on this platform.

  There is no thermal throttling: the junction stays under 60 °C at about 12 W. Never run `nvpmodel -m 0`, which is the 15 W mode. Never run `systemctl isolate` or `nvpmodel -m` on the live robot either: `nvpmodel.service` re-runs and resets the clock floors (on 2 Oct that left CPU and GPU in DVFS for 85 minutes). The drop-in `workspaces/jetson/nvpmodel-rabbit.conf` (installed as `/etc/systemd/system/nvpmodel.service.d/rabbit.conf`) keeps it from re-running and re-applies `jetson_clocks` if it does. OC3 events (`soctherm_oc` hwmon, ~1–8/s) are NVIDIA's expected instantaneous-power throttle in MAXN_SUPER: about 1 ms each, ~0.5 % of performance.
- **Host diet.** `workspaces/jetson/diet.sh` trims the host for a headless robot (`docs/reports/2026-10-03-jetson-audit.md`): removes the snaps and the snapd package (only if apt would remove nothing else; otherwise it masks snapd) and pins snapd out of apt; stops and masks ModemManager, networkd-dispatcher, nvargus-daemon, rpcbind, lpd and cups, apport, whoopsie, unattended-upgrades and the apt-daily timers (and sets `20auto-upgrades` to 0); turns on a persistent journal capped at 500 MB (`/etc/systemd/journald.conf.d/rabbit.conf`); moves the broken `/etc/logrotate.d/jetson-logging` to `/var/backups/rabbit-diet/`. It never touches jtop, NetworkManager, docker, containerd, ssh, nvpmodel or `rabbit-performance`, and lists their state at the end. It is idempotent; run it as root, first with `--dry-run`: `scp workspaces/jetson/diet.sh rabbit:/root/ && ssh rabbit 'bash /root/diet.sh --dry-run'`. To undo one service: `systemctl unmask <unit> && systemctl enable --now <unit>`.
- **Headless.** The Jetson boots to `multi-user.target`: the GNOME desktop and x11vnc are off, which frees about 300 MB of RAM and half the swap. `systemctl isolate graphical.target` brings the desktop back for one session.
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
- **Forge:** Parquet files in the Docker volume `workspaces_forge-data`, about 15–20 MiB per hour of driving, capped at 50 GB (`FORGE_MAX_DATA_GB`).
