# Rabbit

A small Ackermann rover and everything around it, in one repo:

| Path | What |
|---|---|
| `workspaces/rabbit` | robot code: Python nodes on NATS (camera, navigation, exploration, motors, power, telemetry), run in Docker on the Jetson |
| `workspaces/web` | the web HUD: React, three.js and uPlot, talking to the robot's NATS over websockets |
| `workspaces/forge` | Forge: records all telemetry, commands and logs into ClickHouse and serves it to agents (slabs, MCP, the HUD chat). See its `README.md` |
| `workspaces/compose.yaml`, `workspaces/nats` | the robot's services and NATS config |
| `scripts/deploy.sh` | deploys to the robot |

Read the skill that matches the work before starting:

| Task | Skill |
|---|---|
| Check the robot, deploy to it, restart services, read its logs, shut it down | `rabbit-robot` |
| Change robot code or the web HUD | `rabbit-dev` |
| Change Forge (writer, schema, slabs, graph, chat, MCP) or investigate an incident in the data | `forge-dev` |

## Rules

- **Secrets.** The robot SSH key is at `~/.ssh/rabbit_id_rsa`. Forge's `.env` (OpenAI and tsfm.ai keys) is gitignored, in `workspaces/forge/.env` and on the robot in `/root/rabbit/workspaces/forge/.env`. The Cloudflare tunnel token is in `/root/rabbit/workspaces/tunnel.env` on the robot. Never print, copy or commit them, and never use keys from other projects.
- **Robot motion.** Nothing that can move the robot (`rabbit.cmd.drive`, a `rabbit.cmd.joy` with throttle, `rabbit.nav.goal`, `rabbit.nav.mission`, `rabbit.nav.explore`) is sent unless the user said in this session that the robot is on the floor and motion is fine.
- **Commits.** Personal repo, public on GitHub, work on `main`. Commit only when the user asks, with conventional commits, staging explicit paths. Never stage `cert/*.pem` (a dev certificate's private key).
- **Package managers.** The root and `workspaces/web` use Yarn 4 (`node .yarn/releases/yarn-4.9.3.cjs`). `workspaces/forge` is a separate pnpm project with its own lockfile and Node version (`.nvmrc`). The Python code uses uv.
- **Long-running processes.** Background tasks of an agent session are killed after 2 hours. Start servers the user relies on with `nohup ... &`.
- **Style.** No comments in code unless a constraint can't be expressed in code. Match the surrounding code. A test must pin a regression that types and existing tests would miss.
