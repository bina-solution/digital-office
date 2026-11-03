# bina-ds — בינה

The office agent: a customized [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
(MIT, pinned to `0.1.6-alpha.1`) that speaks Hebrew natively and runs inside the console.

What is ours, and where:

| Piece | Path | What it does |
|---|---|---|
| Hebrew language pack | `plugins/locale-he/` | Adds the `he` language to the harness web client — one Hebrew dictionary per UI namespace (`dicts/he/*.json`, checked against the pinned English source in `dicts/en/`) and right-to-left document direction while Hebrew is active. `build-client.mjs` generates the browser bundle. The node half also DECLARES the office's language, once (`declareOfficeLocale`: the harness's own `locale` setting, written only while it holds no preference) — adding a language is not selecting one, and until DGO-550 nothing selected one, so the interface opened in whatever the browser asked for with stock `en` as the fallback. `node test/locale-default.test.mjs` pins that write and its three refusals. |
| Random Hebrew wording | `plugins/locale-he/phrases.json` | The keys whose Hebrew value is drawn at random instead of being one fixed sentence: the blank-session hero title (`conversation/hero.headline`) and the turn-status verb shown while the agent works (`chat/chat.deepDiving`). One pick per page load, validated against both dictionaries at build time. Owner decision 2026-09-25. |
| Bina brand | `plugins/brand-bina/` | The sidebar name and mark and the blank-session hero mark, in place of the harness vendor's wordmark and whale — and hides the harness's own "preview" pill beside the hero title (matched by the CSS-module suffix `_previewBadge`). |
| The conversation in the address bar | `plugins/session-link/` | The harness was the one embedded app that took no part in the shell's route contract: its URL was `#/m/bina` whatever conversation was open, because the browser half has no URL routing and keeps its selection in the browser's storage. This plugin opens `?s=<sessionId>` off its own URL when the shell hands one over (the console's `#/m/bina?s=<id>`, or `bina.<domain>/?s=<id>` standalone) and reports every change of the open conversation back with `bina:route`, which the shell mirrors into the address bar. Owner request 2026-10-12. |
| Profile | `harness/profile/` | Which plugins run and how the web surface is composed (`cordis.patch.yml`); installs stock dsh + the Bina plugins with pnpm at image build. |
| Edge auth | `harness/customize.sh` | The one change to the harness's own code: when `DSH_TRUST_PROXY_AUTH_HEADER` is set, a request carrying the identity header Traefik adds after SSO (`X-authentik-username`) is authenticated, the same trust every other embedded app places in the edge. Stock dsh's launch-token + cookie flow stays for any other deployment. Owner-approved 2026-09-17. |
| Office timeline | `plugins/timeline-lanes/` | The lane `כל מקביל` (any-concurrency) draws this app on: the harness's own session events projected into spans — a span per turn, step, tool call, command, approval, workflow run, and an instant for everything else. The store lives on the volume (`$DSH_HOME/timeline`), the adapter serves it (`GET /timeline/spans`), and `app.json` declares it as `SPAN_SOURCE_BINA`. |
| Container | `Dockerfile`, `harness/entrypoint.sh` | `node:24-slim`, the profile under `/opt/bina/harness/profile`, user state on the `bina_ds_home` volume. |

How it reaches the console: the index is embedded at `/a/bina/` like every app, but the harness's
browser code addresses `/api` and `/plugins` at the origin root, so `app.json` root-mounts those two
prefixes on the console host (`module.passthrough[].mount: root`, a platform extension added for this
app) with the console's own `reserved_paths` carved out. Standalone, the app also answers on
`bina.<domain>`.

Updating the harness version: bump `harness/profile/package.json`, re-extract the English
dictionaries (the extraction script lives in the bina-lab notes), and let `build-client.mjs`
report which Hebrew keys changed.

## On the office timeline (כל מקביל)

Every other app in the office draws itself on the concurrency timeline; the agent — the thing doing
most of the work — was a blank row. It is now a lane of its own, the same way the connected apps do
it: the app declares the lane (`contributes.env["any-concurrency"].SPAN_SOURCE_BINA` in `app.json`),
serves the spans itself (`GET /timeline/spans?hours=|since=` on the adapter, port 3081), and the base
service only draws what it is handed — its ring is the live tail, this app's store is the history.

What appears, and why it is complete rather than summarised: the producer is a harness plugin that
listens to `session/event` — the post-commit firehose of the canonical session log — so the timeline
is the log, drawn. A bracketed pair (`turn/start→turn/end`, `step/start→step/end`,
`tool/call→tool/result`, `command/run→command/done`, `compaction`, `approval`, `llm/retry`,
`tool-workflow/*`) becomes a span with its real duration and status; every other event becomes an
instant at its own timestamp; an event type this build has never seen is drawn under its raw name
instead of vanishing. Rows are sessions (`סשן <id8>`, and `תת-סוכן <id8>` for delegated ones), the
row's parallel sub-lanes are that session's overlapping work, and `svcid` is the full session id.

Boundaries worth knowing: the store starts when the plugin first mounts (there is no replay of the
sessions that ran before it), the endpoint says so in `history_from`, and it is unauthenticated by
design — an any-concurrency span source is a bare GET with no credential to present, exactly like
INDOX's lane, and it is reachable only from the office network. `GET /v1/health` reports the store,
so "the lane is empty" and "the store is gone" are different answers.

## From the terminal: `bbox agent`

Everything the Bina screen does with a session has a verb — `bbox agent list | new | send | follow |
watch | show | log | wait | cancel | rename | fork | cmd | goal | model | presets | upload | login |
doctor` (`bbox agent --help`). It speaks the platform's `agent.v1` contract
([ai/context/agent-contract.md](../../ai/context/agent-contract.md)) to the adapter in this
container (`adapter/server.mjs`), which this compose publishes on the docker host's loopback
(`127.0.0.1:3081`). On the macOS engine Lima forwards that port to the Mac, so the CLI runs natively
on the host: no hand-off into the guest, no docker round trips — one socket. The action token comes
out of this container once (`bbox agent login`, via the engine) and is cached at
`~/.config/bbox/agent.json`. `bbox agent doctor` prints every hop with a timing when something is slow.

`bbox agent follow <id>` is the live view — tool calls, their results and the answer as they
happen; `bbox agent new -F - < brief.md` hands a brief to עזריה and stays attached until the turn
ends. Ctrl-C detaches; the session keeps running.

## Local models — every Ollama in reach is in the model picker (`tools/llm-routes.mjs`)

The harness mounts its pi-ai adapter dormant. It has no routes until a `llm-pi-ai:` section in
`settings.yaml` declares them, and it re-reads that section on every request. The
`bina-ds-llm-routes` container (same image, same volume, the checkout read-only) writes that
section once a minute.
- **Sources:** this office's `ollama` app (route `dgo-ollama-local`), and every paired office's
  (`.generated/registry/remote.<office>.ollama.json`), route `dgo-ollama-<office>`. A paired
  office's Ollama is reached at `http://ollama.<office>:<link_port>/v1`, its door on the link.
  The name is the office id this office paired with, never a label the peer gave itself.
- Each model that declares tool calling joins the route, beside DeepSeek in the picker.
- **What the writer owns:** only those routes, and one placeholder credential, `DGO_OLLAMA_KEY`.
  pi-ai refuses a route without a key, and Ollama ignores it.
- **What it never does:** create `settings.yaml`, or touch a section it cannot read as a map.
- **Silence:** an Ollama that stops answering keeps its route for 30 minutes. A route that
  `agent-default-model` names is never removed.
- **A silent stream is not a dead one:** a CPU reads the whole prompt before its first token, so
  every route says `streamIdleTimeoutMs: 2700000` (45 minutes; pi-ai's default is 300 s). The
  owner's first local session, on the full preset, ended on six 300-s timeouts in a row
  (2026-10-21).
- **The relay:** every route's `baseURL` is the writer itself
  (`http://bina-ds-llm-routes-<office>:11435/<route>/v1`). Ollama sends its headers with the first
  token, and Node's fetch drops a response whose headers have not come in 300 s ("Request timed
  out.", the HP asking the Dell over the link). The relay answers a streamed request at once and
  sends an SSE comment every 15 s until the model's stream starts. An Ollama error comes back as an
  SSE `error` event, and a client that goes away cancels the request at Ollama.
- **Thinking is off unless a session asks for it:** a model whose `/api/show` says `thinking`
  gets `reasoningEfforts: {off: none, low, medium, high}`, so a request with no level sends
  `reasoning_effort: "none"`. qwen3.5:2b on the Dell answered a sum in 1.5 s that way, and in
  273.5 s by default.

**`עזריה · מקומי` (`presets/azaria-local`)** is installed into `$DSH_HOME/.agent-presets` once the
office has a local route. It keeps a short persona, bash, the file tools and compaction.
- Measured against a stub model on the Dell: a session on it sends 4.5k characters of messages and
  5 tools (6.7k characters). The full preset sends 67.7k characters and 26 tools (28.5k).
- That is the difference between a few minutes and the better part of an hour, cold, on a laptop
  CPU.
- Measured on the Dell (DGO-825): the route is live in the catalog on the next request, a session
  that selects it sends its whole turn there, and the turn completes.

**Choosing the model also changes the default.** `session/selectModel`, which the web model
picker sends, rewrites `agent-default-model` in `settings.yaml` too. Every new session then
starts on the chosen route. On an office whose agent works on its own (goals, the pulse), choose
the local model for the conversation and put the default back afterwards.

## The clock — n8n, declared with this app (`blueprint/n8n/`)

The owner's ruling, 2026-10-14: *«use n8n automation blueprinted inside bina-ds app. And remove pulse and
all of this mod bullshit, keep clean and official like dsreleased»*. What used to be a shell loop inside
this container — `pulse.sh`, a 5-minute timer that nudged conversations, re-armed goals and consumed a
"wake queue" of notices — is **deleted**. Nothing in this container polls, sleeps or wakes on a timer.

The schedule lives where the office declares automations: `apps/bina-ds/blueprint/n8n/`, imported into
the office's n8n with `./bbox n8n push bina-ds`.

| workflow | fires (Asia/Jerusalem) | does |
|---|---|---|
| `binaSeder00001` | 07:00 · 13:00 · 21:00 | `POST http://bina-ds:3081/v1/seder/<cycle>` — opens the day's סדר |

### The door a workflow may call

`POST /v1/seder/<cycle>` (`shacharit` · `mincha` · `arvit`), served by this app's adapter, is **one verb
wide on purpose**: it opens a new session titled `סדר <name> · <date> · <time>`, hands it the `seder`
brief, posts a notice with the link, and answers `{started, session, link}`. It refuses a second start of
the same cycle on the same day, so two triggers — or a second clock somebody adds later — cannot run a
cycle twice.

It is deliberately **outside the Bearer-token gate**: the agent token can list, read and drive every
conversation, and an n8n workflow must not hold it. Everything else on `bina-ds:3081` still answers 401
without the token. The one thing that survived from the pulse is the harness's own behaviour: an active
goal is continued by the harness itself. Nothing re-arms a goal that was disarmed — a סדר that stopped
resumes from the day's page (`data/bina-ds/sedarim/<date>/`), or when the owner says its name.
