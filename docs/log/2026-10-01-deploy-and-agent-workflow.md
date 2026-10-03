# Deploy pipeline and working with several agent sessions

Dates: 2026-10-01 14:43 UTC – 2026-10-03 00:03 UTC.

## Deploy script (`scripts/deploy.sh`)

| UTC | Change | Why |
|---|---|---|
| 2026-10-01 14:44 | first version: rsync `compose.yaml`, `nats/`, `rabbit/` to `/root/rabbit/workspaces`, `docker compose up -d --build`, restart the given services (`055299d`) | manual rsync + restart until then |
| 2026-10-01 23:04 | `up -d --no-deps --force-recreate <services>` instead of `restart` | `docker compose restart` keeps the old image: the Forge writer ran stale code and did not record `rabbit.map.reset` |
| 2026-10-01 23:20 | one shared `rabbit` image for all `rabbit-*` services; `workspaces/rabbit/.dockerignore`; Forge sources mounted read-only; build only with `--build` (`5b51fb4`) | every deploy rebuilt 7 identical images with a 400 MB build context (maps); a deploy hung for over 10 minutes; `pnpm install` segfaulted (exit 139) inside a build at low memory |
| 2026-10-01 23:20 | result | code-only deploy about 30 s, `--build` 24.7 s when cached, `rabbit-web` about 23 s |
| 2026-10-02 07:53 | the image's first stage builds nvblox and `rabbit_nvblox`: about 15 minutes from scratch, cached afterwards | `2026-10-02-nvblox.md` |
| 2026-10-02 23:09 | services start with `uv sync --quiet && exec .venv/bin/python …` instead of `uv run` | about 240 MB of wrapper processes |

Side effects that remain:
- Any deploy rsyncs all of `workspaces/rabbit`, `forge/src` and `web/dist`, whatever the service list. Half-finished files of another session reach the robot and go live on the next container restart.
- Any deploy runs `docker compose up -d`, which recreates every container whose image changed (a rebuilt `rabbit:latest` restarts all nodes, `rabbit-zed` included) and starts services that were stopped on purpose (it interrupted a GPU benchmark window on 2026-10-03 00:02 UTC).
- `workspaces/web/dist` ships on every deploy, so a local `vite build` with default settings reaches the robot (`2026-10-01-hud.md`).

## Several agent sessions at once (2026-10-02)

On 2026-10-02 06:40–08:56 UTC three sessions worked in the same tree and on the same robot: nvblox in `rabbit-zed`, the object detector (also in `zed.py`) and voice chat (Forge + HUD). What it took:
- explicit "taking camera / camera released" messages (the ZED is exclusive; a TensorRT build and an SVO benchmark could not run together, and benchmark numbers taken next to another session's work were contaminated);
- a hold on all deploys for about an hour while the tree imported `rabbit_nvblox` before the image had it (any restart of `rabbit-zed` would have crashed);
- checking hashes and restarting a single container instead of a full deploy when another session's files were already on the robot;
- asking the owners of uncommitted robot-code changes before any deploy.

## Long-running processes

Background tasks of an agent session die after 2 hours: the HUD dev server died twice on 2026-10-01 and a Forge chat server started by an agent was killed. Servers the owner relies on are started with `nohup`, and Forge runs as Compose services with `restart: unless-stopped`.

## Data rescue before offline work

Before switching the robot off for the night of 2026-10-02 all ClickHouse tables were exported to zstd Parquet with 24 h of container logs (170 MB) and the maps (391 MB) to `~/projects/rabbit/data/offline/` on the Mac. The overnight forensics (millimetre poses, false relocalization) and the planner replay depended on it.
