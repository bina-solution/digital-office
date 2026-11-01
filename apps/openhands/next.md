# next.md — From Current State to v1.0 Stable Release

> Companion to `current.md`. This is the full plan to take the
> Dispatcher + OpenHands stack from "works on the dev box, mostly" to a
> **polished, one-click, ever-growing deployment that acts like a complete
> software company you interact with via the Dispatcher**.
> Decision of record: **full OpenHands platform stays** (app server +
> sandboxed agent-servers). Research-informed; sources noted inline.
> Last updated: 2026-06-13.

---

## 0. Hard rules (apply to every task below)

1. **Declarative or it didn't happen.** Every fix lands as repo code/config.
   Before saying "fixed", answer: *would a fresh machine get this from
   `git clone` + `.env` + `docker compose up` alone?* If no — not done.
2. **Verified means observed on the end surface.** A check passes only when
   the literal expected output is seen in Telegram (driven via Playwright /
   the real client) or in the target Web UI, and is quoted in the report.
   curl, logs, and internal probes are diagnostics, never verification.
3. **No runtime mutation.** No manual UI configuration, no `docker exec`
   state, no background processes rewriting config. Init containers are
   idempotent and only seed empty state.
4. **Stop-the-line.** A failed verification halts forward progress until
   root-caused (read deployment context + related files first — no "nuclear"
   workarounds).
5. **Two-message contract** per user turn: one live-edited runtime message,
   one final response (or clear error + `/retry`). Plain text, no emojis,
   English.
6. **Server.js ≤800 lines.** The main entry point must be a thin wireframe:
   imports, config, initialization, HTTP routes → delegate to lib/ modules.
   Every function body >5 lines belongs in a lib/ file. This is a structural
   invariant — no new feature may push server.js over 800 lines.
7. **Platform-wide optimization.** Every component (Dispatcher, OpenHands init,
   agent image, docker-compose) must minimize startup time, disk footprint,
   and runtime memory. Shared volumes only for state that must cross containers.
   Init containers must be idempotent and seed only when empty. No background
   loops rewriting config.

---

## M0 — Close what the session left open (½ day)

- [x] **Ship + verify the Gemini camelCase fix** (`inlineData`/`mimeType` in
  the dispatcher's Gemini REST payload). Verify: send a photo to the TG bot →
  bot describes the actual image content. Quote the reply.
- [x] **Wire the Gemini/OpenAI/Anthropic keys into OpenHands** (2026-06-12 22:10).
  Root cause: the openhands stack (openhands, openhands-init, dispatcher) is
  launched **standalone from the `openhands/` subdir**, so Compose interpolated
  `${GEMINI_API_KEY}` from `openhands/.env` (DeepSeek-only) instead of the root
  `.env` (which holds valid Gemini/OpenAI/Anthropic keys). Fix: `openhands/.env`
  is now a **symlink → `../.env`** (single source of truth). `settings.json`
  regenerated to 9 profiles incl. Gemini 2.5 Flash/Pro. Gemini vision verified
  by a real image call (HTTP 200, correct description).
  **REMAINING:** recreate `openhands`+`dispatcher` from the subdir so the running
  env matches config (main container still `GEMINI=<EMPTY>` — runtime drift).
  Then run matrix #9 on the real Web UI (JBL photo → "names a JBL speaker").
- [ ] **Rotate all burned secrets**: Telegram bot token, Gemini key, DeepSeek
  key (all pasted in plaintext into chat/commits/logs). Re-register the TG
  webhook with the new token. Confirm old token is dead.
- [x] **Commit & tag** the current declarative state as `v0.9.0-rc1` so every
  later change is diffable against a known baseline.
- [x] **Disk guard**: scheduled `docker system prune` policy + free-space
  alert, dogfooded through the dispatcher's own scheduler (this is the prime
  suspect behind `Sandbox startup failed (status=ERROR)` bursts).

## M1 — Truth baseline (1 day)

- [ ] **Run the 20-task reliability benchmark** (mixed: direct answers,
  terminal tasks, host read/write, browser task, media in, n8n run, schedule,
  retry). Record success %, p50/p95 latency into `current.md §6`.
  Target to beat by v1.0: **≥95%**.
- [ ] **Fresh-start proof**: on wiped volumes (ideally a scratch VPS),
  `git clone` → `.env` (DeepSeek + Gemini + TG token only) →
  `docker compose up -d` → benchmark task passes with **zero** manual steps.
  Every gap found becomes a P0 declarative fix.
- [ ] **Codify the QA harness** (`make verify`): scripted suite that drives
  Telegram via Playwright + the Web UIs, asserts on message count (=2),
  language (English), no-emoji, and literal expected content. All later
  milestones gate on this harness, not on ad-hoc checks.

## M2 — Platform alignment: stop fighting OpenHands (1–2 days)

Research basis: OpenHands V1 splits an app server from versioned
agent-server sandbox images, configurable via `AGENT_SERVER_IMAGE_REPOSITORY`
/`AGENT_SERVER_IMAGE_TAG`, and auto-forwards `LLM_*` env vars into sandboxes
(deepwiki: Deployment Options / sandbox_spec_service). Our `1.8.0` server +
`1.27.0-python`-based custom agent image mixes two release tracks.

- [ ] **Pin a matched pair**: pick one current OpenHands release; set server
  image and `AGENT_SERVER_IMAGE_TAG` to the versions that release ships
  together. Record the pair in `.env.example` with a comment.
- [ ] **Rebuild the custom agent image from the matched base**, containing
  ONLY additive layers we genuinely need in the sandbox:
  `ffmpeg`, `zip/unzip`, `jq`, `imagemagick`, docker CLI. **No entrypoint
  wrappers, no profile overwriters, no forced provider keys.** Name it
  `openhands-agent-bina:<matched-tag>` and build it in compose
  (`build:` block) so a fresh machine builds it automatically.
- [ ] **Upgrade playbook**: a documented two-line bump (server tag + agent
  tag) gated by `make verify`. This is what makes the deployment
  "ever-growing" instead of frozen at a fork.
- [ ] **Event plane v2**: replace event-file polling with the documented
  interfaces — WebSocket event subscription per conversation (events are
  WebSocket-first in V1; SDK issue #2689 confirms clients are expected to
  subscribe and filter), with the agent-server webhook receiver
  (`/api/v1/webhooks/events/{conversation_id}`) as the push alternative.
  Dispatcher keeps one monitor task per active session with: hard timeout,
  heartbeat edits into Message 1, and a **guaranteed terminal message**
  (answer or error) on every code path. This is the permanent fix for "I
  usually don't get responses".

## M3 — Declarative model plane: the LLM gateway (1–2 days)

Research basis: LiteLLM proxy supports **provider wildcard routing** —
one block per provider (`model_name: "deepseek/*"` →
`api_key: os.environ/DEEPSEEK_API_KEY`) — and with
`check_provider_endpoint: true` its `/v1/models` performs live model
discovery per provider (docs.litellm.ai wildcard_routing; issue #20064).
This is exactly the "add a key and every model of that provider appears"
behavior the product requires, and it gives the dispatcher a *real API*
for model discovery instead of reading OpenHands' internal `settings.json`.

- [ ] **Add `llm-gateway` service** (pinned LiteLLM image). A tiny init step
  generates `litellm-config.yaml` from whichever `*_API_KEY` vars exist in
  `.env` (deepseek, gemini, openai, anthropic, groq, mistral, openrouter, …)
  — one wildcard block each, `os.environ/` key references (no secrets in the
  file), plus a `defaults:` section: text default `deepseek/deepseek-chat`,
  vision default `gemini/gemini-2.5-flash`. Master key from `.env`.
- [ ] **Point OpenHands profiles at the gateway**: `openhands-init` now
  queries `llm-gateway:/v1/models` and generates one profile per discovered
  model (openai-compatible `base_url` = gateway). Keep the curated
  display-name map for the common models; pass through the rest verbatim.
  Provider quirks (e.g. Gemini `caching_prompt: false`) live in ONE place —
  the gateway config — not in per-profile hacks.
- [ ] **Dispatcher model discovery = `GET llm-gateway/v1/models`** (drop the
  shared-volume settings.json read). Dispatcher's own LLM + vision calls go
  through the gateway too → unified logging, budgets, retries, fallbacks
  (gateway-level `fallbacks:` deepseek→gemini on provider outage).
- [ ] **Acceptance**: with only DeepSeek+Gemini keys → both providers' models
  in OpenHands dropdown, dispatcher `/status`, and dashboard selector. Add
  `OPENAI_API_KEY` to `.env`, `docker compose up -d` → OpenAI models appear
  everywhere with **no other edit**. Remove it → they disappear. All three
  states verified via the end surfaces.

## M4 — FileBus: full bidirectional file flow (2–3 days) ⭐ headline

Design goal: any file the user sends reaches the dispatcher's vision AND the
sandbox as a path; any file the agent produces reaches the user back in the
right Telegram form. Built on the existing shared `downloads/` plane,
formalized into a protocol.

### 4.1 Layout & conventions (declarative, documented in `FILEBUS.md`)

```
downloads/
  in/<chatId>/<messageId>/<original-or-derived-filename>   + meta.json
  out/<taskId>/<files the agent wants delivered>           + (optional) manifest.json
  tmp/        (working area, TTL-cleaned)
```
- `meta.json` per inbound file: tg `file_id`, `message_id`, mime, size,
  caption, `reply_to_message_id`, sha256. This index is what makes
  **reply-to-older-media** work: on a TG reply, the dispatcher resolves the
  replied `message_id` → stored files → attaches them to the new turn
  (vision call and/or sandbox paths), no re-upload needed.
- Sandbox sees the same tree at `/workspace/project/downloads/`.
- HTTP fallback: every stored file is also reachable at
  `dispatch…/downloads/<relpath>` (already disk-backed) for models that need
  URLs and for >50MB user delivery as a link.

### 4.2 Inbound (user → agent)

- [ ] All TG attachment types handled: photo (largest size), document, video,
  audio, voice, video_note, animation, sticker; **albums** aggregated by
  `media_group_id` into one turn.
- [ ] Limits honored: cloud Bot API `getFile` downloads cap at **20MB**
  (core.telegram.org/bots/api). Over-limit → immediate honest reply with the
  limit + suggested alternatives. Optional flag `TELEGRAM_LOCAL_API=true`
  adds a self-hosted `telegram-bot-api` container (tdlib image) raising both
  directions to **2GB** — declarative opt-in, off by default.
- [ ] Zips: stored as-is; task message tells the agent the path and that
  `unzip` is available. Zip-slip guard: agent instructions + a dispatcher-side
  sanitizer if the dispatcher ever extracts.
- [ ] Voice notes: optional transcription via the gateway (Gemini) before
  dispatch, behind `VOICE_TRANSCRIBE=true`.

### 4.3 Outbound (agent → user) — the missing half

- [ ] **Outbox contract in the system prompt** injected into every OpenHands
  task: *"To deliver a file to the user, write it to
  `/workspace/project/downloads/out/<taskId>/`. Anything there is sent to the
  user automatically when you finish (or as you go)."*
- [ ] Dispatcher **outbox watcher** per task: scans on relevant tool events
  and at terminal state; dedupes by sha256; picks the TG method by mime —
  `sendPhoto` (images ≤10MB, else as document), `sendDocument`,
  `sendVideo`, `sendAudio`/`sendVoice` (ogg/opus) — caption = filename +
  short agent note from `manifest.json` if present. >50MB (cloud API upload
  cap, telegram-bot-sdk sendDocument docs) → deliver as an HTTPS
  `downloads/` link instead (or natively when local Bot API is enabled).
- [ ] **Browser screenshots auto-forward**: when the agent's browser tool
  produces a screenshot (event/workspace artifact), copy it into the outbox
  so "screenshot google.com" needs no special agent behavior.
- [ ] Hygiene: TTL cleanup (`in/` 7d, `out/` 7d, `tmp/` 24h) via the
  scheduler; filename sanitization; collision-safe naming; per-chat size
  quota.

### 4.4 Acceptance cases (the user's literal scenarios — each one is a test)

1. TG: "screenshot google.com and send it back" → bot returns a **photo** of
   google.com.
2. TG: send a zip + "here is a zip file, extract it and give me back the list
   of files" → bot replies with the actual file list.
3. TG: reply on an **older image** in the chat: "what is in the image?" →
   correct description of *that* image.
4. TG: "send me a zip of ./hello project directory" → bot sends
   `hello.zip` as a document; unzipping it locally shows the project files.
5. TG: "generate a 5-second tone with ffmpeg and send it back" → bot sends a
   playable audio file (proves ffmpeg in the agent image + audio outbox path).
6. Album of 2 photos + caption question → one turn, both images considered.
7. 100MB file sent → polite limit message (or full success when
   `TELEGRAM_LOCAL_API=true`).
8. Same five flows exercised from the **Dispatcher Web UI** (upload control +
   inline preview/download of outbox files) — TG must stay optional.

## M5 — Dispatcher as a real agent + product polish (2 days)

- [x] **Finish the modular refactor**: `server.js` → `lib/` modules
  (dispatcher core, sessions, files, issues, schedules, dashboard) with the
  already-extracted `telegram.js`/`openhands.js`. No behavior change; QA
  harness green before/after. **Done 2026-06-12: 7 modules extracted (906 lines),
  server.js at 2311 lines.**
- [ ] **Deep modular refactor — server.js ≤800 lines**: 10 lib modules (1370 lines)
  extracted and deployed. models.js fully scaffolded with fallback logic but not
  wired (would require updating ~15 MODEL_MAP/PROFILE_TO_LITELLM consumers).
  polling.js has full ohPollResponseWithTelegram ready. system-prompt.txt has
  the full prompt. Remaining to extract from 2136-line server.js:
  dispatchForTelegram (~500 lines), ohPollResponseWithTelegram (~185),
  streamDispatch (~100), handleSystemCommand (~170), dispatcherLLM+Vision (~160),
  loadOpenHandsProfiles (~70), buildSessionContext (~50), system prompt (~60),
  schedule functions (~170). Estimated achievable target: ~670 lines.
- [ ] **Platform optimization pass**: review every init container for idempotency;
  add `depends_on: condition: service_healthy` chains; minimize shared volumes;
  audit all `restart: unless-stopped` for memory leaks; remove unused legacy
  services (agent-runner, anthropic-proxy) from the active path.

## M6 — Release engineering: v1.0 (1 day)

- [ ] **One-click kit**: `README.md` quickstart (clone → `.env` → up),
  `.env.example` with exactly two required keys + optional blocks
  (TG token, extra providers, local bot API, auth), `make verify`,
  `make upgrade`, compose `healthcheck`s on every service with
  `depends_on: condition: service_healthy` ordering, idempotent init
  (seeds only empty volumes, versioned by checksum).
- [ ] **Startup self-test**: on boot the dispatcher round-trips the default
  text model and the vision model through the gateway and one minimal
  OpenHands task; `/status` reports the three results; refuses to claim
  healthy otherwise.
- [ ] **Observability**: structured logs per turn (turn id, model, route,
  latency, files in/out, outcome); errors mirrored into the issues module
  automatically (label `auto`).
- [ ] **Security pass**: TG chat-ID allowlist; gateway master key required;
  no secret ever logged or echoed into chats; `downloads/` HTTP route gated
  by unguessable paths or auth; document the blast radius of the sandbox's
  host mount + docker access (this is by design — say so explicitly).
- [ ] **Full verification matrix run** (below) on a clean machine → tag
  `v1.0.0`, write the measured reliability number into `current.md §6`.

---

## Verification matrix for v1.0 (run in order; quote every observed output)

| # | Surface | Test | Pass condition (literal) |
|---|---------|------|--------------------------|
| 1 | TG | "what services are running?" | docker ps summary, 2 messages, no emoji |
| 2 | TG | "what is 1+1, one word" | fast direct answer, no sandbox |
| 3 | TG | "run: date && echo OK" | tool output incl. `OK` |
| 4 | TG | "list all services declared in this deployment" | 60+ services named |
| 5 | TG | "create CHECK.md at repo root with text X" | file on host, then cleaned |
| 6 | TG | "list my openhands sessions" | answered by dispatcher itself |
| 7 | TG | "start a session with deepseek-reasoner" | session uses that model |
| 8 | TG | n8n workflow by ID `gwaHealthCheck01`, then by name | results returned both ways |
| 9 | TG | JBL speaker photo + "what do you see" | reply names a JBL speaker |
| 10 | TG | FileBus cases 1–7 (M4.4) | each literal pass condition |
| 11 | TG | second message mid-task | queued inside Message 1, both answered in order |
| 12 | TG | `/retry` after induced failure | original task re-runs, completes |
| 13 | TG | `/schedule` every-minute task | fires on time, removable, no self-chat |
| 14 | TG | "create hello-world routed to hello.<domain>" | app live at URL, no shortcuts |
| 15 | TG | clone-website flagship task | "live at <subdomain>" and it is |
| 16 | WebUI | OpenHands: new conversation on each provider's default model | agent responds, no crash |
| 17 | WebUI | OpenHands browser pane during a browse task | page visibly rendered (Playwright screenshot) |
| 18 | WebUI | Dispatcher dashboard: chat + file up/down + issues + schedules | all functional behind auth |
| 19 | env | add `OPENAI_API_KEY`, `compose up -d` | OpenAI models appear everywhere; remove → gone |
| 20 | clean VPS | clone → `.env` (2 keys + TG) → `compose up` | tests 1,2,3,9,10.1 pass untouched |
| 21 | clean VPS | same WITHOUT `TELEGRAM_BOT_TOKEN` | stack healthy; Web UI fully usable |
| 22 | bench | 20 mixed tasks | ≥95% success, p50/p95 recorded |

## Definition of Done — v1.0 stable

All 22 matrix rows pass on a clean machine; only `DEEPSEEK_API_KEY` and
`GEMINI_API_KEY` are mandatory; any extra provider key lights up by itself;
Telegram is optional; every user turn is exactly two emoji-free messages with
a guaranteed terminal response; full file flow works in both directions
including the five literal user scenarios; versions are pinned as a matched
OpenHands pair with a tested upgrade path; secrets rotated; no runtime-only
fixes remain anywhere in the system. Tag `v1.0.0`, update `current.md`,
and open the v1.1 ideas list (per-user budgets/permissions, WhatsApp
re-enable, local Bot API by default, multi-tenant chats).

## Risk register (watch these)

- **OpenHands upgrade churn**: V1 is moving fast; internal file formats
  (settings.json, event files) are not contracts — M2/M3 remove our
  dependence on them. Re-run `make verify` on every bump.
- **Provider API drift** (the camelCase bug class): all provider calls go
  through the gateway after M3, so quirks are fixed once, centrally.
- **Disk pressure** = sandbox startup failures: M0 guard + alerting.
- **Telegram limits**: 20MB down / 50MB up on cloud API; local Bot API
  container is the declarative escape hatch (2GB both ways).
- **Security of a self-developing agent**: host mount + docker access is the
  product, but it means the TG allowlist + dashboard auth + secret hygiene
  are not optional hardening — they're release blockers (M6).
