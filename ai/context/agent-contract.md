# `agent.v1` — the office agent contract

The platform talks to "the office agent" through ONE interface, whichever harness provides it.
`apps/bina-ds` (DeepSeek Harness, preset עזריה) is the first implementation; another harness
becomes a provider by serving the same routes. Callers never speak a harness's own protocol.

Provider: the app that declares capability `office-agent` with `"interface": "agent.v1"`; its
`endpoint` is the in-network base URL. Callers resolve it from the capability, never hardcode it.
The client everyone uses is `bbox agent` (`scripts/bbox_agent/`, Python 3.9 + stdlib).

## Reach — why a call costs one socket and not a hand-off

The provider publishes its port on the **docker host's loopback only**
(`127.0.0.1:${BINA_DS_AGENT_PORT:-3081}`, apps/bina-ds/docker-compose.yml). From a Linux docker host
and from WSL that is `http://127.0.0.1:3081`; on the macOS engine Lima forwards a guest loopback port
to the Mac's loopback (measured 2026-09-30: no configuration, no edge, no DNS), so the address is the
same everywhere and `bbox agent` runs natively on the host. Nothing else is reachable that way.

Measured before this design (2026-09-30, engine at load ~90): `bbox agent list` from the Mac cost a
hand-off into the guest, two bash start-ups (20 s each under load), a `docker version` probe (27 s),
two `docker exec`s (14 s) and then the harness (200 s+) — six minutes for one list. Natively it is
one TCP connection; the only remaining cost is the harness's own answer.

## Authentication

`Authorization: Bearer <token>`. The provider mints the token into its own state (bina-ds:
`$DSH_HOME/api-token`, root-only, named by the container's `AGENT_TOKEN_FILE`) and it reaches the
operator's tooling only through the engine — `bbox agent login` reads it with `docker exec`, the same
trust as docker itself — and is cached at `~/.config/bbox/agent.json` (0600). A 401 refreshes it once.
It is a credential of the office, not of a person, and never an identity header: an agent API that
accepted `X-authentik-username` from any container on the network would have no authentication.

## Routes

Read routes answer JSON; `GET …/events` and `GET /v1/watch` answer `text/event-stream`.
`{id}` accepts a unique prefix. Errors: `{error, code}` with 400 bad request, 401 token,
404 no such session, 409 ambiguous prefix, 502 the harness behind the provider refused or is down.

| Route | Body / query | Answer |
|---|---|---|
| `GET /v1/health[?deep=1]` | — | `{ok, provider, version, harness, harness_ms, uptime_s, stream, [sessions, list_ms]}` — no token needed |
| `GET /v1/sessions[?fresh=1]` | — | `{sessions:[summary]}` (cached 3 s unless `fresh`) |
| `POST /v1/sessions` | `{text?, title?, preset?, cwd?, files?}` | `{id, preset}` — a session on the office checkout; `text` sent as its first message |
| `GET /v1/sessions/{id}` | — | summary: `{id, title, running, blank, updated_at, preset, permissions, model, goal, todos, turns, tokens, queue}` |
| `POST /v1/sessions/{id}/messages` | `{text, steer?, files?}` | `202 {accepted}` — queued behind the running turn, or steered into it |
| `GET /v1/sessions/{id}/messages?limit=N` | — | `{events:[…], has_more}` — the latest N messages as contract events, oldest first |
| `GET /v1/sessions/{id}/events?history=N&since=SEQ&raw=1` | — | **SSE**, live: `open`, `snapshot`, then events (below); `id:` is the harness seq |
| `POST /v1/sessions/{id}/cancel` | — | `202` — interrupt the running turn |
| `POST /v1/sessions/{id}/rename` | `{title}` | `{id, title}` |
| `POST /v1/sessions/{id}/fork` | `{at_seq?}` | `201 {id, forked_from}` |
| `POST /v1/sessions/{id}/upload?name=` | raw bytes | `201 {receipt, attachment}` — use `attachment` in `files`, `receipt` in commands |
| `POST /v1/sessions/{id}/command` | `{line:"/…", receipts?}` | `{result}` — a slash command of the harness |
| `GET /v1/sessions/{id}/commands` | — | `{commands:[{name, description, input}]}` |
| `GET /v1/sessions/{id}/goal` · `POST …/goal {objective, max_rounds?}` · `POST …/goal/{pause,resume,clear,complete}` | | `{goal}` |
| `POST /v1/sessions/{id}/model` | `{provider, model, effort?}` | — |
| `POST /v1/sessions/{id}/preset` | `{preset}` | — |
| `GET /v1/sessions/{id}/subagents` | — | `{subagents}` |
| `GET /v1/models` · `GET /v1/presets` · `GET /v1/permissions` | — | the catalogs |
| `GET /v1/search?q=` | — | `{items, hasMore}` |
| `GET /v1/watch` | — | **SSE**: `baseline {sessions, queues, jobs}`, then `update {id,key,value}`, `queue`, `jobs` |

### Events (the vocabulary a terminal renders)

`turn.start` · `turn.end {reason}` · `step.start` · `step.end` · `user {text, source}` ·
`inbox {text}` (a steer arrived) · `reasoning {text}` · `assistant {text}` · `delta {kind: text|reasoning|tool, text}`
(live tokens, before the durable message) · `attempt.start` · `attempt.finish {reason, message}` ·
`tool.call {id, name, args}` · `tool.result {id, ok, text}` · `retry {reason}` · `retry.start {attempt}` ·
`approval.asked` · `approval.decided` · `goal {goal}` · `title {title}` · `error {code, message}` · `end`.
Every event carries `seq`, `at`, `turn`, `step` when the harness knows them. `?raw=1` passes the
harness's own events through untouched, for debugging a provider.

## Rules for callers

- A running session is not an error: `messages` queues, `steer` interrupts. Follow `…/events`
  for `turn.end`, or poll `GET /v1/sessions/{id}` for `running: false` (`bbox agent wait`).
- Never restart the provider from inside a session it is running (apps/bina-ds/self-update.sh
  exists for that).
- The agent's work is the repository and the platform; its answer is text. Verify effects against
  the system, not against the reply.
- Questions the agent asks a person (`ask_user_question`) are answered in the office UI; the
  stream shows them. Answering them from the CLI is not part of v1.

## Work items — the agent's tasks live in the project tool

The office's roadmap is data: `apps/project-pln/plans/<name>.yaml`, rendered into Plane by
`./bbox project-pln plan <name>` (upsert, never delete; sequence numbers follow the file). The
agent has an account of his own there, the items are assigned to him, and **one implementation**
moves them — `./bbox project-pln tasks …` (`list|show|start|done|comment|take`, `--as <agent>`,
`--json`). `bbox agent` only gives it the agent's point of view:

| Verb | Does |
| --- | --- |
| `bbox agent tasks [list\|show\|start\|done\|comment\|take] …` | `bbox project-pln tasks --as <agent> …` — no second client, no second contract |
| `bbox agent do <REF> [words] [-s <id>] [-F]` | hands him a work item: sends `complete task @project-pln/<REF>` into a new session titled `<REF>` (or `-s` into one); the `plane-tasks` skill in his preset tells him to read the item, move it to started, work, and move it to done with a comment carrying the proof |
| `bbox agent <name> tasks …` | the agent's name first selects whose tasks (`azaria` is the office agent) |

The timeline (`any-concurrency`) shows both lanes — the agent's sessions from `/timeline/spans` of
this adapter, and the work items from the project tool's own span source — so a task closing and
the turn that closed it line up on one axis.
