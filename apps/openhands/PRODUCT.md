# Product Context — Open-Pilot / Dispatcher

> The single source of truth for what this product is, why it exists, how it is
> built, and the rules of engagement for developing it. Read this before
> touching code. Keep it under control — if reality drifts from this doc, fix
> the doc in the same PR.

---

## 1. One-line definition

A **self-hosted, declarative "private Copilot" for an entire live deployment** —
chat with an agent over Telegram (and WhatsApp), and it autonomously develops,
investigates, and operates the deployment (reads/writes the real project files,
runs the real host terminal, runs services), streaming its progress back to you
in chat.

## 2. The problem being solved

The owner runs `deployment-hacohen`: a multi-app Docker Compose deployment on a
remote VPS, fronted by Traefik, exposing many apps publicly (`*.hacohen.bina-solutions.co.il`).
Today it is developed by hand: VS Code + GitHub Copilot over Remote-SSH, looping
sessions until goals are met.

The goal is to **replace that human-in-VS-Code loop with a service** that does
everything Copilot does — session management, execution, observability, user
management, permissions — but runs locally, supports any LLM, supports media,
and is driveable from a phone chat. Two earlier attempts (`chat`,
`agent-runner`) proved the idea but became "a bit of a mess." This product
consolidates them into one clean service.

## 3. Target experience (the north star)

A user sends a message to the bot on Telegram:

> **User:** "what are the current running services?"
>
> **Bot:** *(creates an OpenHands session, runs `docker ps`, shows live
> thinking / tool calls / output as they happen)*
>
> **Bot:** *(final answer message with the result)*

And more ambitiously:

> **User:** "clone this website into clone2.hacohen.bina-solutions..."
>
> **Bot:** *(spins a long-running session, streams a progress thread, delivers
> a completion report)*

Hard requirements baked into that experience:

- **Declarative / reproducible.** On a fresh machine, `docker compose up` brings
  the whole stack live — bot, agent platform, models all auto-configured from
  `.env` (DeepSeek API key, Claude). **No manual WebUI clicks** to register
  models or settings. If a step needs a human, it is a bug.
- **Full deployment access.** The agent edits the real `./deployment-hacohen`
  tree and runs the **host VPS terminal** — exactly like Copilot-over-SSH does
  today — so it can develop new services, bump versions, investigate n8n via
  CLI, add open-source services, even modify the dispatcher and bot themselves.
- **Media.** Image and audio in chat must reach a model that can actually
  process them.
- **Guaranteed feedback.** Every message a user sends is **promised** a
  response. Thinking, actions, errors, and events propagate back to the chat in
  near-real-time. Silent failures are unacceptable.

## 4. Architecture (as built in this session)

```
Telegram / WhatsApp
        │
        ▼
┌──────────────────────┐     Dispatcher = a thin agent with essentially ONE job:
│  Dispatcher service  │     own the conversation, answer simple things itself,
│  (bina-deployment)   │     and use OpenHands as its main tool. It keeps a
│  + its own WebUI     │     live monitor thread per session it spawns, so the
└──────────┬───────────┘     end user is guaranteed updates + a final response.
           │ bridge token (dispatcher-hacohen-bridge-token-2026)
           ▼
┌──────────────────────┐
│  OpenHands platform  │  Session/conversation engine, WebUI, browser tool,
│  (openhands-*)        │  terminal, file read/write. Auto-configured from env.
│  + openhands-init     │  init seeds settings so models exist on fresh start.
└──────────┬───────────┘
           │
   ┌───────┴────────────────────────────┐
   ▼                                     ▼
agent containers (oh-agent-server)   agent-proxy / filesystem-mcp-sse
   │                                     (routes agent <-> host fs/terminal)
   ▼
LiteLLM proxy ──► DeepSeek API (default: deepseek-v4-pro)  / Claude
```

Supporting services seen in the stack: `traefik-bina-deployment` (routing +
TLS), `n8n-bina-deployment` (workflow automation, driveable by the agent),
`docker-proxy-bina-deployment`, `agent-runner-bina-deployment` (legacy — being
retired in favor of dispatcher+OpenHands).

Repos involved: `deployment-hacohen` (branch `COPILOT`) is the deployment;
`chat` is the WhatsApp bot (in-tree, source of good agent
features to port — e.g. `agent_chat.js`); `apitools` is a sibling project.

Routing convention: every app is reverse-proxied through the main compose and
exposed at `<app>.hacohen.bina-solutions.co.il`.

## 5. Key design decisions

1. **OpenHands is the execution substrate, not the product.** It owns sessions,
   terminal, files, browser. The dispatcher is the product surface.
2. **Dispatcher is a self-operating agent**, not a dumb relay. It can answer
   questions about a session *without* spawning a new session, and it wraps each
   spawned session in a monitoring thread that guarantees delivery.
3. **Everything flows from `.env`.** Models, keys, tokens. The `openhands-init`
   container exists to make fresh starts truly zero-touch.
4. **The agent's terminal is the host VPS**, mirroring the Copilot-over-SSH
   model, so it can self-develop the whole deployment.

## 6. State of reality at end of session (be honest)

This is what is **actually verified working** vs. claimed:

| Capability | Status |
|---|---|
| Host file integration (agent writes a file, it appears on host) | ✅ Verified |
| Direct answers (dispatcher replies itself, ~1.3–1.5s) | ✅ Verified |
| OpenHands session end-to-end via Telegram (~32s, tools fire, events stream) | ✅ Verified late in session (REQ 156) |
| Guaranteed-delivery `finally` wrapper around poll+completion | ✅ Implemented + stress-tested |
| `/retry` command + message queue (no more silent drops) | ✅ Implemented |
| Declarative model config on fresh start | ⚠️ Partially — required manual WebUI add at one point; init seeding added but not re-proven from a clean volume |
| Browser **view** inside OpenHands WebUI (live page render) | ❌ Broken — only renders screenshots; "No page loaded yet" persists |
| Image/audio understanding | ❌ Broken by model choice — images routed to text-only `deepseek-chat`; guaranteed-fail |
| Reliable session completion under load | ⚠️ Was ~71% stalled mid-session due to the Gemini-routing bug; fixed, but a clean post-fix success-rate number was never measured |

### The single worst bug found (cautionary tale)

For a long stretch, **a stale Gemini profile/key was injected into every agent**,
so LiteLLM routed all "DeepSeek" calls to `generativelanguage.googleapis.com`
and got 404. Result: ~80–101 sessions *appeared* to process ("Sandbox ready!",
"AI agent is now working...") and **silently failed**. Status messages kept
updating — all lies. This is the canonical failure mode of this product: a deep
hop in the chain fails silently and the UX papers over it.

## 7. Known UX failure modes (the things that make it feel bad)

1. **Black hole** — 5 hops (Telegram → Dispatcher → OpenHands → Agent → LiteLLM
   → DeepSeek); any hop can fail silently; user just gets nothing.
2. **Long silent waits** — minutes with no visible progress.
3. **Silent failures are the norm** — no error surfaced to the user, no retry,
   no cancel, no "what went wrong."
4. **Browser tab is misleading** — shows screenshots, not a live view.
5. **Dropped messages** — second message during processing is silently dropped
   (now partially addressed via queue).
6. **Status edits get buried** — single edited Telegram message; users miss the
   final "✅ Response ready" edit.
7. **Image support guaranteed to fail** — text-only model behind an image path.

## 8. Non-negotiable working rules (learned the hard way this session)

These exist because the session repeatedly violated them and wasted cycles:

- **Never claim "verified" without a real end-to-end check from the actual end
  surface (Telegram/WhatsApp).** "Code deployed" ≠ "works." Maintain a
  claims-vs-reality table.
- **No nuclear/shortcut solutions.** Don't manually create the artifact the
  product is supposed to produce (e.g. don't hand-make the hello-world project —
  it must be made *through* WhatsApp → dispatcher → OpenHands). Understand the
  real behavior and fix the real cause.
- **Fully declarative or it's a bug.** If a fresh `docker compose up` needs a
  manual click, that's unfinished work.
- **Logging at the highest level** so the "under the hood" is always visible —
  silent hops are the enemy.
- **One language: English** in chat/output. (Session drifted into Hebrew
  repeatedly; keep it English unless asked.)
- **Don't skip slow E2E tests** (OpenHands/WhatsApp/Telegram via Playwright)
  because they're slow — they are exactly the ones that catch the real bugs.

## 9. Glossary

- **Dispatcher** — the user-facing agent service; owns chat, monitors sessions.
- **OpenHands** — open-source agent platform used as the execution engine.
- **Session / conversation** — one OpenHands run; the dispatcher spawns and
  monitors these.
- **Direct answer** — dispatcher answers without spawning an OpenHands session.
- **Bridge token** — shared secret the dispatcher uses to drive OpenHands.
- **Declarative start** — fresh `docker compose up` yields a fully configured,
  usable stack with no manual steps.