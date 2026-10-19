# bina-ds — בינה

The office agent: a customized [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
(MIT, pinned to `0.1.6-alpha.1`) that speaks Hebrew natively and runs inside the console.

What is ours, and where:

| Piece | Path | What it does |
|---|---|---|
| Hebrew language pack | `plugins/locale-he/` | Adds the `he` language to the harness web client — one Hebrew dictionary per UI namespace (`dicts/he/*.json`, checked against the pinned English source in `dicts/en/`) and right-to-left document direction while Hebrew is active. `build-client.mjs` generates the browser bundle. |
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

## The office pulse — the reminder that outlives a turn (`pulse.sh`)

The owner's standing ask (2026-10-09): *"set yourself a reminder every 5 minutes to verify that
development is progressing as well as possible … keep working until everything is perfect"*, and *"give
Azaria automations like Raphael's, so he can trigger himself on a schedule and continue a specific
session"*. A reminder cannot live inside a turn: the turn that was building exactly this was cut
mid-work when this container was recreated at 04:53, and the reminder died with it. So the timer lives
in the container and starts with it (`harness/entrypoint.sh`, `BINA_DS_PULSE=0` disables).

Every `BINA_DS_PULSE_EVERY` (default 300 s) it:

1. asks the agent API on loopback — with **this container's own** token — which sessions exist and how
   many are actually running;
2. if something is running, says so and stops (the office is working);
3. if nothing has run for `BINA_DS_PULSE_IDLE_TICKS` ticks (default 4 ≈ 20 min) **while a session still
   holds an active goal**, it nudges that session to carry on — and the nudge names the next work item
   from the hub (`bbox project-pln tasks list --as azaria --state unstarted`), so the continuation starts
   on an item rather than on a shrug;
4. handles the **wake queue** (below), and posts a notice when it nudges.

### The wake queue — how an automation outside the container gets work moving

An outside app cannot hold the agent token (it is root-only here, by the contract), and handing it out
would mean "any container may drive the agent" — a design decision nobody asked for. So the door is a
queue nobody needs a secret to write: the **notice centre**. Any n8n workflow (Raphael's scans already
post there) can ask for work by posting a notice whose `source_id` starts with `wake`; this timer,
which *does* hold the token, reads it, wakes the session the notice names — or the one holding an active
goal — and marks the notice read. Every wake is an auditable row, and no credential crosses a container
boundary. `BINA_DS_PULSE_ONCE=1` runs a single tick, `BINA_DS_PULSE_DRY=1` prints what it would do.

The other half of the same idea lives outside: `n8n`'s `raphaelPulse00001` (every 5 minutes, no token)
reads `/v1/health?deep=1`, the containers and the notice centre, reports what is broken, and posts the
wake request that this timer acts on.
