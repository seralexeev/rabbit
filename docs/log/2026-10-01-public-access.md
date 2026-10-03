# Public HUD: Cloudflare tunnel, access links, HTTP/2

Dates: 2026-10-01 22:48 UTC – 2026-10-03 00:00 UTC.

## Steps

| UTC | Step |
|---|---|
| 2026-10-01 22:48 | HUD served by nginx on the robot (`rabbit-web`, https://jetson.rabbit) with `/api` proxied to the chat (`279876b`) |
| 23:05–23:20 | `/nats` also proxied (websocket upgrade), so the HUD needs one origin; a Cloudflare quick tunnel (`trycloudflare.com`, URL changes on every restart) as a first test (`5b51fb4`) |
| 23:35–23:41 | Named tunnel `rabbit` created in Cloudflare Zero Trust; route to `https://rabbit-web:443` with No TLS Verify; first hostname robot.bunnyfleet.com (`9acf01a`). The token lives in `workspaces/tunnel.env` on the robot (gitignored, mode 600) and was never printed |
| 23:44–23:47 | Main address https://live.rabbit0.dev on the same tunnel (`4d4980d`) |
| 2026-10-02 00:46 | `client_max_body_size 64m` on `/api`: long chats were rejected with 413 (`b36435d`) |
| 2026-10-02 05:31–05:38 | Revocable access links (uncommitted at the time of writing) |
| 2026-10-03 00:00 | Tunnel switched to `--protocol http2` |

## Access links

- Until 2026-10-02 05:38 UTC anyone with the URL could drive the robot, use the chat (which spends the OpenAI key) and reset the map.
- Now `/k/<token>` sets an HttpOnly cookie `rabbit_link` (one year) and redirects to `/`. A request that came through Cloudflare (it has `Cf-Connecting-Ip`) without a listed cookie gets 403 on every path, including `/nats` and `/api`. The LAN (https://jetson.rabbit, NATS on :9222) stays open.
- Registry: `/root/rabbit/workspaces/links/links.map` on the robot, included by `web/nginx.conf` as a `map`. Managed with `scripts/links.sh` (list / `add <name>` / `rm <name>`). Every access log line carries `link=<name>`.
- Revocation reloads nginx; `worker_shutdown_timeout 5s` closes open websockets, so a revoked HUD is cut off about 5 s after `rm` (measured: link removed at +8 s, socket closed at 13.4 s). Every add or remove briefly reconnects all open HUDs, LAN ones included.
- Tested locally against nginx in Docker, then through the real tunnel (403 without a link, 302 + cookie, 101 for the websocket with the cookie).

## Incidents

- **Negative DNS caching.** The new hostname was resolved before its record existed, and the home router cached NXDOMAIN for the SOA negative TTL (1800 s). Switching the Mac to 1.1.1.1 as a workaround broke `jetson.rabbit`, which only the router resolves. Check new names only against 1.1.1.1.
- **Unknown map resets from the HUD** at 2026-10-02 05:38 and 05:58 UTC (and 09:10 UTC), and unattributed joystick driving at 06:16–06:18 UTC that contaminated a CPU benchmark. The public HUD is not view-only: it has GO TO, START explore, RESET MAP and the chat.
- **Tunnel stuck after a Wi-Fi drop** (2026-10-02 23:59 UTC): Cloudflare answered 530; cloudflared's QUIC connections stayed in "failed to dial to edge with quic: timeout". A restart registered four QUIC connections again; the tunnel was then switched to HTTP/2 over TCP (`workspaces/compose.yaml`: `tunnel --no-autoupdate --protocol http2 run`), which registered four HTTP/2 connections.
- After deploying the link gate the owner was locked out of his own tunnel session until a link was made for him.
