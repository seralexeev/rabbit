# Forge + Rabbit

Forge (this repo) records the telemetry of Rabbit, a small Ackermann rover, into ClickHouse and serves it to agents (slabs, MCP, chat). The robot's code and its web HUD live in the sibling repo `../rabbit`. Most tasks touch both, so read the skill that matches the work before starting:

| Task | Skill |
|---|---|
| Check the robot, deploy to it, restart services, read its logs, shut it down | `rabbit-robot` |
| Change robot code (Python nodes) or the web HUD | `rabbit-dev` |
| Change Forge (writer, schema, slabs, graph, chat, MCP) or investigate an incident in the data | `forge-dev` |

`README.md` is the reference for Forge itself. `alloy-presentation-context.md` explains why all this exists (an interview with Alloy Robotics) and lists the debugging stories with numbers.

## Rules

- **Secrets.** `.env` (OpenAI, tsfm.ai, chat token) and `id_rsa` (SSH key to the robot) are gitignored. Never print, copy or commit them, and never use keys from other projects.
- **Robot motion.** Nothing that can move the robot (`rabbit.cmd.drive`, a `rabbit.cmd.joy` with throttle, `rabbit.nav.goal`, `rabbit.nav.mission`, `rabbit.nav.explore`) is sent unless the user said in this session that the robot is on the floor and motion is fine. On a stand the wheels spin freely, but ask anyway.
- **Commits.** Both repos are personal and work on `main`. Commit only when the user asks, with conventional commits (`fix: ...`, `feat: ...`), staging only your own files. In `../rabbit`, never stage `cert/*.pem` (a dev certificate's private key in a public repo).
- **Long-running processes.** Background tasks of an agent session are killed after 2 hours. Start servers the user relies on (the HUD dev server) with `nohup ... &`. Forge's writer and chat already run in Docker with restart policies.
- **Style.** No comments in code unless a constraint can't be expressed in code. Match the surrounding code. A test must pin a regression that types and existing tests would miss.
