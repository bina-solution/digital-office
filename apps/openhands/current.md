# current.md — Product Context & Honest State

> Single source of truth for what this product is, what exists today, what is
> actually proven, and what the last development sessions taught us.
> Companion: `next.md` (the road from here to a v1.0 stable release).
> Last updated: 2026-06-13 02:00 (live-verified). Decision of record: **we stay on the full
> OpenHands platform** (app server + sandboxed agent-servers), not a bare-SDK
> rebuild.
> 
> **Verification re-run: 2026-06-12 22:10** — all HTTP surfaces 200,
> /status and /issues commands return "ok". 1 active session, 0 in-flight.
> server.js at 2136 lines (target: ≤800). **Modular refactor in progress**:
> 10 lib modules (1370 lines) extracted. 3 more modules scaffolded and
> awaiting wiring (models.js, polling.js, system-prompt.txt).
> Remaining extraction targets: dispatchForTelegram (~500 lines),
> ohPollResponseWithTelegram (~185 lines), streamDispatch (~100 lines),
> handleSystemCommand (~170 lines), plus smaller functions. Estimated
> extractable remaining: ~1465 lines → achievable target of ~670.
> Disk at 93% (14G free).
>
> **Vision fix: 2026-06-12 22:10** — Gemini vision was failing in the OpenHands
> Web UI (DeepSeek silently drops images → agent browses the workspace and asks
> for clarification). Root cause: the openhands stack (openhands, openhands-init,
> dispatcher) is launched **standalone from the `openhands/` subdir**, so Compose
> interpolated `${GEMINI_API_KEY}` from `openhands/.env` (DeepSeek-only) instead
> of the root `.env` (which holds a valid Gemini/OpenAI/Anthropic key). Fix:
> `openhands/.env` is now a **symlink → `../.env`** (single source of truth;
> backup at `openhands/.env.bak.pre-gemini-2026-06-12`). Re-ran `openhands-init`
> → **9 profiles** now (was 3): DeepSeek×3, **Gemini 2.5 Flash/Pro**, GPT-4o×2,
> Claude×2. A real Gemini 2.5 Flash vision call on `downloads/test_photo.png`
> returned HTTP 200 with a correct description. PENDING user approval: recreate
> `openhands` + `dispatcher` so the running env matches the declarative config
> (the main container still shows `GEMINI=<EMPTY>` — runtime drift).

---

## 1. Product vision (what we are building)

A **self-hosted AI software company in a box**. One VPS, one repo, one
`docker compose up`. You talk to a single **Dispatcher agent** — via Telegram
or via the Dispatcher Web UI — and it runs, develops, debugs, and grows the
entire deployment for you:

- "what services are running?" → answers itself (no heavy session).
- "clone ktivayehudit.co.il into our machine" → opens an OpenHands session,
  pilots it, streams progress, returns "done, live at <url>".
- "here's a screenshot, this page is broken — file an issue and fix it" →
  vision + issue tracker + dev session.
- "screenshot google.com and send it back" → file flows both directions.
- "every morning at 8, check disk space" → scheduler.

The Dispatcher is the **product surface**. OpenHands is its **power tool** —
the development/execution toolkit it pilots. The deployment itself
(`/root/deployment-hacohen`, ~60 services behind Traefik) is the **workspace**
the agent develops, including its own code (self-improving deployment).

### Non-negotiable product properties

1. **Fully declarative / one-click.** Fresh machine → clone → fill `.env` →
   `docker compose up` → everything works. No manual UI steps, no runtime
   mutations that aren't captured in the repo. Every fix must be a *setup*
   fix, not a *current-runtime* fix.
2. **Two required keys only**: `DEEPSEEK_API_KEY` + `GEMINI_API_KEY`
   (Google). Any *additional* provider (OpenAI, Anthropic, …) must light up
   automatically just by adding its API key to `.env` — no other edits.
3. **Telegram optional.** `TELEGRAM_BOT_TOKEN` enables the TG channel; without
   it the Dispatcher Web UI is a complete interface on its own.
4. **Full bidirectional file flow** user ↔ dispatcher ↔ OpenHands sandbox
   (images, video, documents, zips, audio — in and out).
5. **Guaranteed response contract**: every user turn ends with exactly two
   bot messages — (1) a live-edited runtime/log message, (2) the final
   response (or a clear error + retry path). Never silence.

---

## 2. Architecture as deployed today

```
User ── Telegram ──► Dispatcher (Node.js, dispatch.hacohen.bina-solutions.co.il)
User ── Web UI  ──►   ├─ webhook + queue (per-chat serialization)
                      ├─ dispatcher LLM loop (classify → answer or delegate)
                      ├─ vision call (Gemini 2.5 Flash) for media
                      ├─ scheduler (cron-ish tasks)
                      ├─ issues module (GitHub-style, web UI at /issues-ui)
                      ├─ chat dashboard (/dashboard, /chat alias)
                      └─ OpenHands client (REST: start-tasks, messages, events)
                                   │
                  OpenHands app server (ghcr.io/openhands/openhands:1.8.0)
                  openhands.hacohen.bina-solutions.co.il
                                   │ spawns via docker.sock
                  Agent-server sandboxes (custom image `openhands-agent-fixed`,
                  based on ghcr.io/openhands/agent-server:1.27.0-python)
                      ├─ /workspace/project ⇄ /root/deployment-hacohen (rw)
                      ├─ docker via host.docker.internal:2375 (docker-proxy)
                      └─ browser + VNC (noVNC at /agent/<port>/vnc.html)

openhands-init (one-shot container): generate-settings.py reads *_API_KEY
from .env → writes settings.json (LLM profiles) into the shared
openhands_state volume. Dispatcher reads the same file to list models.
Shared file plane: /root/deployment-hacohen/downloads/  (host)
                 = /workspace/project/downloads/        (sandbox)
                 = served at dispatch.../downloads/<file> (HTTP)
```

**Model plane today (after the 2026-06-12 22:10 vision fix):** **9 profiles**
in `settings.json` (DeepSeek V4 Pro / V4 Flash / Reasoner, Gemini 2.5 Flash /
Pro, GPT-4o / GPT-4o Mini, Claude Sonnet 4 / Haiku 4). The root `.env` holds
`DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.
`openhands/.env` is now a **symlink → `../.env`** so the subdir-launched stack
reads the same single source (this was the bug: keys present only in root were
invisible to the subdir launch). The generator (`generate-settings.sh`,
Python-backed) supports all four providers. Default: DeepSeek V4 Pro for text;
**Gemini 2.5 Flash/Pro available for vision** (each profile embeds its own
api_key). Gemini profiles carry `caching_prompt: false` (LiteLLM
context-caching URL bug workaround).

**Verified profiles:** 9 in `settings.json`; Gemini vision verified via a real
image call (HTTP 200). Designed capacity: 9.

**Legacy still in the tree (to be retired):** `agent-runner`,
`anthropic-proxy`, the WhatsApp bot path (`whatsapp-hacohenim`) — WhatsApp is
currently dead (QR re-auth needed) and explicitly out of scope this cycle.9 agent containers running (some paused) — auto-cleanup interval exists
but effectiveness unverified.
---

## 3. What is genuinely working (evidence-backed, re-verified 2026-06-12)

- **Declarative model bootstrap**: `openhands-init` (Python generator)
  produces valid `settings.json` from env keys. Currently 3 DeepSeek profiles
  active. `generate-settings.sh` code supports Gemini/OpenAI/Anthropic — just
  add the key. Verified with `docker exec` on live container.
- **Dispatcher HTTP surfaces**: `/`, `/chat`, `/dashboard`, `/issues-ui`,
  `/healthz` all return HTTP 200. Verified via curl.
- **Dispatcher core loop**: classify → direct answer (no sandbox) or
  OpenHands delegation; per-chat queue; two-message protocol implemented;
  emoji-free plain-text status prefixes. Direct answer: 2.2s end-to-end
  (1.8s LLM). Verified via Telegram webhook simulation.
- **Vision (DeepSeek fallback)**: TG image → dispatcher vision round-trip
  confirmed using DeepSeek's markdown image format (no Gemini key needed).
  376-char response in 2.2s. The Gemini REST API path (`inlineData` camelCase)
  is coded correctly but untestable without a Gemini key.
- **Issues module**: full CRUD + comments + images, web UI at `/issues-ui`,
  HTTP 200 verified.
- **Host read/write from sandbox**: `/workspace/project` mount is live.
- **Downloads file plane v1**: TG attachments saved to disk under `downloads/`,
  served over HTTP from disk, survives restarts. Test photo (83KB PNG) present.
- **Scheduler + /retry + /files commands** exist and respond.
- **OpenHands Web UI**: creates conversations, sends messages, gets responses
  (verified via Playwright — "say hello in one word" → "hello" with DeepSeek
  V4 Pro). Default model in UI is "gpt-5.5" (OpenHands internal default,
  overrides `active_llm_profile`), must manually switch to a working profile.
- **Two-message protocol**: runtime status (Message 1, live-edited) + final
  response (Message 2) implemented in `dispatchForTelegram()`.
- **Modular refactor**: 7 modules extracted from server.js — `lib/telegram.js`
  (141 lines), `lib/openhands.js` (143), `lib/dashboard.js` (77), `lib/schedules.js`
  (167), `lib/sessions.js` (91), `lib/issues.js` (126), `lib/obsidian.js` (161).
  Total: 906 lines of modules + 2311-line server.js = 3217 lines.
- **FileBus scaffold**: `downloads/in/`, `downloads/out/`, `downloads/tmp/`
  directories created; contract documented in next.md M4.
- **LLM Gateway scaffold**: `generate-litellm-config.py` generates provider
  config from .env keys; Dockerfile built but blockered by Alpine/Python
  dependency resolution (litellm proxy requires many deps). Punted to M3.
- **Disk guard**: scheduled cleanup every 2 hours via `/schedule`.
  4 paused agent containers cleaned manually; 5 active remain.

## 4. What is broken or unproven right now

- **[FIXED 2026-06-12 22:10] Gemini key now wired**: a valid `GEMINI_API_KEY`
  was already in the root `.env`, but the openhands stack is launched from the
  `openhands/` subdir, so Compose read `openhands/.env` (DeepSeek-only). Made
  `openhands/.env` a symlink to root `.env`; `settings.json` regenerated to 9
  profiles incl. Gemini. Gemini vision verified by a real image call (HTTP 200).
  **Remaining:** recreate `openhands`+`dispatcher` (pending approval) so the
  running container env stops showing `GEMINI=<EMPTY>`.
- **[FIXED] Now 9 profiles** (was 3): adding the Gemini/OpenAI/Anthropic keys to
  the shared `.env` lit up all of them. The "add a key → profiles appear" claim
  is now proven on this deployment for Gemini/OpenAI/Anthropic at once.
- **Files OUT of the sandbox**: nothing systematic. Screenshots, generated
  zips/code artifacts are not detected or sent back to the user. The user's
  headline cases (screenshot google.com → photo back; "send me a zip of
  ./hello"; ffmpeg-generated audio back) **do not work yet**.
- **Reply-to-older-media context**: replying to a previous image and asking
  "what's in this?" is not resolved to the stored file.
- **OpenHands Web UI browser pane**: still shows "No page loaded yet" while
  the URL bar updates; live noVNC stream never visually verified in a real
  browser.
- **Version mismatch**: app server `1.8.0` vs agent image based on SDK
  `1.27.0-python` — two different release tracks. It mostly works but is the
  suspected source of several "ghost" failures.
- **Custom agent image is a patch pile**: `openhands-agent-fixed` carried an
  entrypoint wrapper, background profile-overwriters, and forced env keys.
  The refactor removed most bandaids, but the image was never rebuilt from
  a clean matched base.
- **9 agent containers running** (some paused/old). Auto-cleanup interval
  exists in code (every 30min) but disks are filling. Need disk guard.
- **Fresh-start proof never re-run** after the final refactor: nobody wiped
  volumes on a clean machine and watched `docker compose up` reach a working
  chat with zero manual steps.
- **Session links in TG** now point at the dispatcher chat dashboard
  (OpenHands deep links showed "conversation does not exist" — auth/ID format
  issue never root-caused).
- **Scheduler self-conversation**: scheduled tasks injected messages that the
  bot then answered as if a user wrote them (msg-183 analysis). Partially
  addressed, not re-verified.
- **Response guarantee is shaky**: user repeatedly observed tasks ending with
  no final answer in TG; a per-task monitor/watchdog was designed but its
  reliability was never measured (target ≥95% over 20 mixed tasks — never run).
- **Secrets are burned**: the Telegram bot token, a Gemini API key, and the
  DeepSeek key were pasted in plaintext into chat/commits/logs. **All must be
  rotated** and the repo history treated as compromised for those values.
- **Sandbox startup flakiness**: repeated `Sandbox startup failed (status=ERROR)`
  bursts under load/disk pressure; disk-guard cleanup job designed, not shipped.
- **OpenHands Web UI default model**: "gpt-5.5" appears as default (OpenHands
  internal), not respecting `active_llm_profile` from settings.json. User must
  manually switch to DeepSeek V4 Pro for each new conversation.

---

## 5. Session critique (what the 251-turn session teaches)

**What went right.** The session converged on the correct product shape:
dispatcher as a self-operating agent with OpenHands as one tool; declarative
env-driven model bootstrap; disk-backed file plane; issues module dogfooding;
two-message UX. Root-cause discipline improved markedly near the end
(volume-name mismatch, env-loading-from-wrong-dir, camelCase API bug — all
real root causes, all declarative fixes).

**Systemic failure #1 — verification theater.** The single most repeated user
correction (turns 94, 123, 131, 198, 245, 247): "verified" was claimed from
logs, curl, or internal probes instead of the actual end-user surface. The
fix is procedural and goes into next.md as a hard rule: *a test passes only
when the literal expected output is observed on the end surface (Telegram via
Playwright, or the Web UI), and the observed output is quoted.*

**Systemic failure #2 — runtime fixes instead of setup fixes.** Many fixes
mutated the running system (manual model added in UI, env exported in a
shell, profile overwritten by a background loop) and silently evaporated on
restart or git operations — twice the media-handler code was found reverted.
The user's final instruction codifies the rule: every fix must answer "is
this declarative? will a fresh machine get it from the repo alone?"

**Systemic failure #3 — patching around upstream instead of aligning with
it.** The 1.8.0/1.27.0 version split, the entrypoint wrapper fighting the
platform's own profile system, and hardcoded provider keys created a fragile
custom fork of OpenHands behavior. Upstream OpenHands V1 already provides the
needed mechanisms (env forwarding of `LLM_*` to sandboxes, configurable
`AGENT_SERVER_IMAGE_*`, WebSocket/webhook event streams); we should ride
them, not wrap them.

**Systemic failure #4 — coupling via files instead of APIs.** Dispatcher
discovers models by reading OpenHands' `settings.json` out of a shared
volume, and follows sessions by reading event files. Both are undocumented
internal formats that will break on upgrade. The event plane should move to
the documented WebSocket/webhook interfaces, and model discovery to a real
`/v1/models` endpoint (see next.md: LLM gateway).

**Systemic failure #5 — monolith drag.** A 3,315-line `server.js` made every
edit risky (the `userId is not defined` crash came from a sed across scopes).
`lib/telegram.js` and `lib/openhands.js` were extracted; the rest of the
planned split (dispatcher core, sessions, issues, schedules, dashboard,
files) is pending.

**Process notes.** Long autopilot runs worked best when the user pinned an
explicit acceptance phrase ("don't move on until the bot literally says it
sees a JBL speaker"). Hebrew/English drift, emoji spam, and >2 messages per
turn were all UX regressions caught only by the user — the QA suite must
assert on message *count, language, and format*, not just content.

---

## 6. Reliability snapshot

Last verified: 2026-06-12 22:10. All HTTP surfaces 200. /status and /issues
commands return "ok". 1 active session, 0 in-flight. server.js at 2136 lines
(target: ≤800). **Modular refactor in progress**: 10 lib modules (1370 lines)
extracted. 3 more modules scaffolded and awaiting wiring (models.js, polling.js,
system-prompt.txt). Remaining extraction targets: dispatchForTelegram (~500 lines),
ohPollResponseWithTelegram (~185 lines), streamDispatch (~100 lines),
handleSystemCommand (~170 lines), plus smaller functions. Estimated
extractable remaining: ~1465 lines → achievable target of ~670.
Disk at 93% (14G free).

## 7. Key numbers as of 2026-06-12 22:15

| Metric | Value |
|--------|-------|
| Active profiles | 9 (DeepSeek×3, Gemini×2, GPT-4o×2, Claude×2) |
| Agent containers | 5 active |
| Active sessions | 1 |
| In-flight tasks | 0 |
| server.js lines | 2136 |
| Extracted lib/ modules | 10 (1370 lines total) |
| Scaffolded, ready but not wired | models.js, polling.js, system-prompt.txt |
| Remaining extractable | ~1465 lines (dispatchForTelegram 500, ohPollResponse 185, streamDispatch 100, handleSystemCommand 170, dispatcherLLM 70, dispatcherVision 80, loadOpenHandsProfiles 70, buildSessionContext 50, system prompt 60, schedule funcs 170) |
| Target after full extraction | ~670 lines |
| FileBus directories | in/, out/, tmp/ |
| LLM Gateway | Scaffold built, not integrated |
| Disk usage | 94% (14G free) |
| Gemini key in .env | Yes (root .env; openhands/.env → symlink) |
| OpenAI key in .env | Yes |
| Anthropic key in .env | Yes |
| Gemini vision verified | Yes (real image call, HTTP 200) |
| openhands/.env | symlink → ../.env (single source of truth) |

## 7. Glossary / key paths

- Repo root (host): `/root/deployment-hacohen` — also the agent workspace.
- Dispatcher service: `openhands/dispatcher/` (Node.js; `server.js` +
  `lib/telegram.js`, `lib/openhands.js`).
- OpenHands compose + env: `openhands/docker-compose.yml`, `openhands/.env`,
  init generator `openhands/generate-settings.py` (run by `openhands-init`).
- Shared state volume: `deployment-hacohen_openhands_state`
  (contains `settings.json`).
- File plane: `downloads/` at repo root = `/workspace/project/downloads/` in
  sandbox = `https://dispatch…/downloads/…` over HTTP.
- Public URLs: `dispatch.…`, `openhands.…`, apps at `*.hacohen.bina-solutions.co.il`.
