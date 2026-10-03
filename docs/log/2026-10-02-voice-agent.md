# Voice mode for the Forge agent

Date: 2026-10-02, 06:40–08:41 UTC. Built by a parallel agent session; uncommitted at the time of writing.

## What

- OpenAI Realtime `gpt-realtime-2.1` over WebRTC, voice `marin`, transcription `gpt-transcribe`. The server keeps the key and issues an ephemeral client secret (`POST /api/voice/call`); tools run on the server (`POST /api/voice/tool`).
- The voice agent has all 21 chat tools; their charts, tables and approval cards appear in the same chat feed. `workspaces/forge/src/agent/voice.ts`, `voice.md` (short answers "like a colleague on a radio", no reading tables aloud), `web/src/chat/voice.ts` (◉ VOICE button, LISTENING / HEARING YOU / THINKING / SPEAKING, MUTE, END).
- `rabbit-web` and `forge-chat` must be deployed together, otherwise the button gets 404.

## Issues

- **English-only replies.** The shared prompt said "You always write in English". Replaced with "reply in the language the operator speaks to you; keep tool parameters, ids and SQL in English"; a test pins it.
- **CORS outage on the public HUD** (06:46–08:09 UTC): a plain local `vite build` baked `https://jetson.rabbit` into `workspaces/web/dist`, and another session's deploy shipped it (deploy.sh rsyncs `dist/` on every deploy).
- An in-place Python string replacement corrupted `voice.ts`; the file was rewritten.

## Spoken approvals (08:17–08:20 UTC)

The decision is made by HUD code from the operator's own transcript, never by the model: only utterances of at most 5 words, started after the approval card appeared; any negation wins ("Да нет, отмена" → deny); ignored when more than one card is pending; a card decided by button ignores a later "да". The model is told to ask «Подтверждаете?» and has nothing to call to approve. The server-side approval TTL stays 60 s.

## Robot background prompt

`workspaces/forge/src/agent/robot.md` (about 6 KB), appended to the system prompt for chat, voice and `pnpm forge ask`: hardware, geometry, capabilities, known failure modes and the build history from the blog. Unmeasured numbers (maximum speed) were left out on purpose; the agent must take speed from pose data.

## Evals

`pnpm forge eval`: 14/25 cases passed on the robot's fresh database, because the cases expect runs that only existed in the old laptop database; behaviour cases (mission, obstacle, stop, encoders) passed. Moving the eval set to new runs is open.
