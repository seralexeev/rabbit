# Rabbit

A small Ackermann rover and everything around it, in one repo:

| Path | What |
|---|---|
| `workspaces/rabbit` | robot code: Python nodes on NATS (camera, navigation, exploration, motors, power, telemetry), run in Docker on the Jetson |
| `workspaces/web` | the web HUD: React, three.js and uPlot, talking to the robot's NATS over websockets |
| `workspaces/forge` | Forge: records all telemetry, commands and logs into Parquet files, queries them with chDB (embedded ClickHouse) and serves them to agents (slabs, MCP, the HUD chat). See its `README.md` |
| `workspaces/compose.yaml`, `workspaces/nats` | the robot's services and NATS config |
| `scripts/deploy.sh` | deploys to the robot |
| `scripts/links.sh` | manages the revocable links that give public access to the HUD |
| `workspaces/blog` | the build log at rabbit0.dev (Russian and English posts, media); `scripts/blog.sh build` renders it locally; a push to `main` deploys it to GitHub Pages |
| `scripts/sim.sh` | full-stack simulator on the Mac: local NATS + `rabbit-sim` + the real nav, planner and explore (see `rabbit-dev`) |

Read the skill that matches the work before starting:

| Task | Skill |
|---|---|
| Check the robot, deploy to it, restart services, read its logs, shut it down | `rabbit-robot` |
| Change robot code or the web HUD | `rabbit-dev` |
| Change Forge (writer, schema, slabs, graph, chat, MCP) or investigate an incident in the data | `forge-dev` |
| Add a post to the blog (dictated or from the session) and publish it | `rabbit-blog` |

## Work log and blog

Keep both up to date as part of the work (see the README section "Work log and blog" for paths and commands):

- **`docs/roadmap.md`**: what to do next, in order; update it when an item is done or priorities change.
- **`docs/open-issues.md`**: every open question for the owner, unresolved problem, measurement and on-robot check, numbered (Q/M/P/V). Read it at the start of a session; add an item the moment you find one (with a link to the source); move it to "Закрыто" with the answer and date when resolved. Mention new Q items to the owner.
- **`docs/`**, the engineering log: read the relevant entries in `docs/log/` and `docs/README.md` before changing a subsystem; after significant work (a feature, an experiment that was dropped, an incident and its root cause, new measurements) add or update a `docs/log/YYYY-MM-DD-<topic>.md` entry, keep `docs/README.md` current, and add hard-won rules to `docs/lessons.md`. Factual, English, with numbers and file paths; this repo is public, so no secrets.
- **The blog** (`workspaces/blog`, rabbit0.dev; `scripts/blog.sh build`, deployed by GitHub Pages on push): at the end of a work session, append short entries to `README.ru.md` in the owner's voice (read the recent entries first and match them: first person, short, concrete, a bit of humour, Russian) and the matching English ones to `README.md`, with the next ids and the date in Sydney time (DD-MM-YYYY). Only cool or cardinal things: a new capability, a funny failure, a surprising root cause, a big decision. Skip routine fixes and the obvious, never write meta about documenting or the blog itself, and keep small thoughts rare. Media should be real: live HUD screenshots, camera frames, plots with clear data, a short code snippet; no near-empty charts. Blur people. Labels, titles and legends on charts and images are in English, even in Russian posts. Build and push to publish (format, media and commands are in the `rabbit-blog` skill). Ask before publishing anything about third parties or anything that looks private.

## Rules

- **Temporary (until the Forge cutover in `docs/reports/2026-10-03-forge-cutover-runbook.md` is done):** deploy only named `rabbit-*` services. `scripts/deploy.sh` with no arguments or with `forge-*` would start the new Forge code in the old containers and break it.
- **Access links.** When the user asks for a HUD link, run `scripts/links.sh add <name>` and reply with the printed URL; when they ask to remove one, run `scripts/links.sh rm <name>`; `scripts/links.sh` lists them. No confirmation needed. Use the name the user gives, otherwise the next free `guestN`.
- **Secrets.** The robot SSH key is at `~/.ssh/rabbit_id_rsa`. Forge's `.env` (OpenAI and tsfm.ai keys) is gitignored, in `workspaces/forge/.env` and on the robot in `/root/rabbit/workspaces/forge/.env`. The Cloudflare tunnel token is in `/root/rabbit/workspaces/tunnel.env` on the robot. Never print, copy or commit them, and never use keys from other projects.
- **Robot motion.** Nothing that can move the robot (`rabbit.cmd.drive`, a `rabbit.cmd.joy` with throttle, `rabbit.nav.goal`, `rabbit.nav.mission`, `rabbit.nav.explore`) is sent unless the user said in this session that the robot is on the floor and motion is fine.
- **Commits.** Personal repo, public on GitHub, work on `main`. Commit only when the user asks, with conventional commits, staging explicit paths. Never stage `cert/*.pem` (a dev certificate's private key).
- **Package managers.** The root and `workspaces/web` use Yarn 4 (`node .yarn/releases/yarn-4.9.3.cjs`). `workspaces/forge` is a separate pnpm project with its own lockfile and Node version (`.nvmrc`). The Python code uses uv.
- **Where things go.** Everything lives in this repo: reports and analyses in `docs/reports/` (dated), engineering log in `docs/log/`, tools and benchmarks as code under `workspaces/` (e.g. `workspaces/bench/`), and data (SVO dumps, Parquet exports, maps of the flat, benchmark outputs) in the gitignored `/data/` directory, e.g. `data/offline/`. No sibling folders like `~/projects/rabbit-offline`; temporary scratch goes to the session scratchpad.
- **Hardware choices.** Money is not a constraint: pick quality components from reputable makers with real datasheets (the owner's rule, 2026-10-03). Rank by fit with the robot, quality and reliability, then cost; never default to the cheapest option.
- **Long-running processes.** Background tasks of an agent session are killed after 2 hours. Start servers the user relies on with `nohup ... &`.
- **Style.** No comments in code unless a constraint can't be expressed in code. Match the surrounding code. A test must pin a regression that types and existing tests would miss.
- **Observability.** Every new behaviour, decision, failure path or state change must be visible in Forge with a reason, ids (mission, trip, exploration, session, boot) and the numbers behind it: a structured event (`self.event`), a state field or a metric, per the convention in `docs/reports/2026-10-03-observability.md` and the checklists in `rabbit-dev` and `forge-dev`. A change isn't done until "what happened and why" can be answered from the recorded data alone (check it in the simulator).
