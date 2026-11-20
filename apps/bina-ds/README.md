# bina-ds — עזריה

The office agent: a customized [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
(MIT, pinned to `0.2.2-rc.3`, the newest release on 2026-11-13) that speaks Hebrew natively and runs
inside the console, and on its own address, `azaria.<domain>` (EXU-64; `bina.<domain>` still answers).
The app's id stays `bina-ds`: the CLI, the n8n clock, the linked offices' catalogs and the volume name it.

**Claude, inside עזריה.** A «Claude» row in the sidebar opens the office's OFFICIAL Claude app
(`apps/bina-claude`, signed in once): its sign-in state and its sessions, read and written over its agent.v1
contract — what is typed there runs in that app, on that sign-in. עזריה holds no Claude credential and offers
no claude.ai sign-in of its own: Anthropic's terms keep that sign-in in Anthropic's own flow
(code.claude.com/docs/en/legal-and-compliance). `plugins/claude-sessions/`.

**The screen: one place for every conversation (EXU-64, DGO-2036).** `azaria.<domain>` and the console's tile open
עזריה's own screen: `web/` (static), with its data from the adapter's `/ui/…` door (`adapter/ui.mjs`). The door
answers only the office's edge and console, only with the identity header the edge adds, only same-origin, and
every write as JSON.
- `GET /ui/sessions`: ONE list. It holds Azaria's conversations and those of every Claude app of the office: the
  first, `bina-claude`, and each instance of it (DGO-1920), found from `instances/<id>/app.json` with
  `instance_of: bina-claude`. Each Claude row names its `app`, and its reads and writes go to that app.
- `GET /ui/models`: the harness's model catalog, each Claude app's state (`claudes`), and the name of each computer
  that serves a local model (`computers`). An office of our own herd is named by its label; any other is
  `<id> · מחוץ לעדר`, never the name it gave itself.
- `GET /ui/providers` («איפה זה רץ»): every place a conversation can run.
  - Each cloud provider: is its key there, and does it come from the office's secrets.
  - Each computer with a local model.
  - Each Claude app.
  - No key value ever crosses.
- `POST /ui/providers/<deepseek|openai|anthropic>/vault`: points the provider's key reference at its connection
  (`vault:<connection>`, the vault-key plugin's pointer). It is refused over a key that already works from
  elsewhere, and when the harness cannot say where the key comes from.
- `POST /ui/sessions` `{engine: "azaria"|"claude", app?, text, model?}`. Per conversation: `messages`, `stream`,
  `cancel`, `answer`, `rename`, `archive`, `edit`, `retry`, `upload`, `model`.

Tests: `adapter/test_providers.mjs`, `adapter/test_claude_apps.mjs`.

What is ours, and where:

| Piece | Path | What it does |
|---|---|---|
| Hebrew language pack | `plugins/locale-he/` | Adds the `he` language to the harness web client — one Hebrew dictionary per UI namespace (`dicts/he/*.json`, checked against the pinned English source in `dicts/en/`) and right-to-left document direction while Hebrew is active. `build-client.mjs` generates the browser bundle. The office's language is DECLARED in the profile (the `locale` row's config, `preference: he`) — adding a language is not selecting one, and until DGO-550 nothing selected one, so the interface opened in whatever the browser asked for with stock `en` as the fallback. `node test/locale-default.test.mjs` pins that declaration. |
| Random Hebrew wording | `plugins/locale-he/phrases.json` | The keys whose Hebrew value is drawn at random instead of being one fixed sentence: the blank-session hero title (`conversation/hero.headline`) and the turn-status verb shown while the agent works (`chat/chat.deepDiving`). One pick per page load, validated against both dictionaries at build time. Owner decision 2026-09-25. |
| Brand | `plugins/brand-bina/` | The sidebar name «עזריה» and mark «ע», the blank-session hero mark and the tab title, in place of the harness vendor's wordmark, whale and "DeepSeek Harness" — and hides the harness's own "preview" pill beside the hero title (matched by the CSS-module suffix `_previewBadge`). |
| Claude | `plugins/claude-sessions/` | The «Claude» panel: the official Claude app's sign-in state and sessions (list, conversation, composer) through a narrow door on the harness's web server, `/office-claude/…`, behind the office's sign-in. The door takes bina-claude's action token the way `bbox agent --app bina-claude` does (from its container, through the engine) and never hands it to the browser. EXU-64. |
| The conversation in the address bar | `plugins/session-link/` | The harness was the one embedded app that took no part in the shell's route contract: its URL was `#/m/bina` whatever conversation was open. This plugin opens `?s=<sessionId>` off its own URL when the shell hands one over (the console's `#/m/bina?s=<id>`, or `azaria.<domain>/?s=<id>` standalone) and writes every change of the open conversation into its own URL, which the shell mirrors. On 0.2.x the open conversation is `uiWorkspace.selection`. Owner request 2026-10-12. |
| Profile | `harness/profile/` | Which plugins run and how the web surface is composed (`cordis.patch.yml`); installs stock dsh + the office plugins with pnpm at image build. The plugin manager and the harness's own scheduler are OFF: plugins are declared here only, and the office's clock is n8n. |
| Agent presets | `harness/profile/agent-presets/<id>/preset.patch.yml` | עזריה (the default), רפאל and עזריה · מקומי — since 0.2.x each is a row of the preset registry, composed in by `entrypoint.sh` with `--patch`, beside its `skills/`. (`presets/azaria-local/` is the 0.1.6 copy, superseded.) |
| Edge auth | `harness/customize.sh` | The changes to the harness's own code, each asserted exactly once and skipped when already applied: a request carrying the identity header Traefik adds after the office's sign-in (`X-authentik-username`), or the adapter's token, is a signed-in browser; the page "owns the host" behind the edge; bundles load under the console's `/a/bina/`; the copy button falls back inside a frame. Owner-approved 2026-09-17. |
| Office timeline | `plugins/timeline-lanes/` | The lane `כל מקביל` (any-concurrency) draws this app on: the harness's own session events projected into spans — a span per turn, step, tool call, command, approval, workflow run, and an instant for everything else. The store lives on the volume (`$DSH_HOME/timeline`), the adapter serves it (`GET /timeline/spans`), and `app.json` declares it as `SPAN_SOURCE_BINA`. |
| Container | `Dockerfile`, `harness/entrypoint.sh` | `node:24-slim`, the profile under `/opt/bina/harness/profile`, user state on the `bina_ds_home` volume. |

How it reaches the console: the index is embedded at `/a/bina/` like every app, but the harness's
browser code addresses `/api` and `/plugins` at the origin root, so `app.json` root-mounts those two
prefixes on the console host (`module.passthrough[].mount: root`, a platform extension added for this
app) with the console's own `reserved_paths` carved out. Standalone, the app answers on
`azaria.<domain>` (and `bina.<domain>`). Since 0.2.x the harness listens on ONE concrete address (a
wildcard is refused), so `entrypoint.sh` resolves the container's own office-network address into
`DSH_BIND_HOST`, and the adapter and the healthcheck call the harness there.

Updating the harness version (what EXU-64 did for 0.2.2-rc.3):
1. bump `@deepseek-ai/dsh` in `harness/profile/package.json` and re-pin the `~`-ranged packages its tree
   asks for (`pnpm.overrides`);
2. install it in a probe, run `harness/customize.sh` (it fails loudly on an anchor that moved), boot it
   beside the live app on a copy of the volume;
3. list the bundles the page loads (the served index's boot manifest), then in `plugins/locale-he`:
   `node extract-en.mjs <profile> --packages <list> --keep directory-browser --write`, translate the keys
   it reports, `node apply-he.mjs <translations.json>`, `node build-client.mjs --check`;
4. the plugins' own tests (`node --test plugins/*/test/*.test.mjs`).

Sessions written by an older harness are migrated when opened; the adapter opens every one of them once
at start (a rename to its own title), so the list and `bbox agent show` say everything about them.

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

**`עזריה · מקומי` (`harness/profile/agent-presets/azaria-local/preset.patch.yml`)** is declared in the
profile like the other presets (0.2.x has no user preset root to install it into; a preset pins no
model, so it is harmless where no local route exists). It keeps a short persona, bash, the file tools
and compaction.
- Measured against a stub model on the Dell: a session on it sends 4.5k characters of messages and
  5 tools (6.7k characters). The full preset sends 67.7k characters and 26 tools (28.5k).
- That is the difference between a few minutes and the better part of an hour, cold, on a laptop
  CPU.
- Measured on the Dell (DGO-825): the route is live in the catalog on the next request, a session
  that selects it sends its whole turn there, and the turn completes.

**In the web picker, choosing the model also changes the default.** `session/selectModel`, which
the web model picker sends, rewrites `agent-default-model` in `settings.yaml` too. Every new
session then starts on the chosen route, the default preset follows it (`tools/llm-routes.mjs`),
and on a local default the seder cycles are refused.

**Through agent.v1, the model is that session's own** (DGO-1731):
- `POST /v1/sessions/{id}/model` (and `bbox agent model <id> --set`) puts the office's default
  back after it selects. It answers `default`: `kept`, `restored`, `changed` with `why`, or
  `unknown` with `why`.
- `default: true` (`--default`) makes the selection the office's default too.

Measured on the HP 2026-11-11: two per-session sets moved its default from qwen3:1.7b to DeepSeek,
then to the Dell's qwen3:4b, unseen.

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
