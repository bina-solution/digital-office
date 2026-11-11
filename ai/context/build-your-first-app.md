# Build your first app

Everything an app is, it declares. There is no registration step, no central list to edit, and no
base-layer file that has to learn your app's name — a rule the compiler enforces as gate G9. Adding
an app means creating one directory; removing it means deleting that directory.

This walks the manifest field by field, using `apps/hello-bina/` — a real installed app, three
files, no dependencies — as the worked example. For publishing to a signed catalog and installing
by URL, see [app-catalog.md](app-catalog.md).

## The shape

```
apps/<your-app-id>/
  app.json             the manifest — the ONLY thing the platform reads about you
  docker-compose.yml   your services
  Dockerfile           if you build rather than pull
  blueprint/n8n/*.json optional: automations, imported on enable, removed on disable
```

`<your-app-id>` and `app.json`'s `id` must match. The compiler exits if they do not — a mismatch
means "uninstall app X" and "delete directory X" stop meaning the same thing, and every later
question about the app gets two answers.

Where the directory lives IS its layer, and that is also enforced:

| Directory | Layer | What belongs there |
|---|---|---|
| `platform/` | 1 (mechanism) | the schema and the compiler. No app manifests. |
| `platform-base/` | 1–2 | the chassis every deployment needs: edge, identity, state, automation, the shell. Not things a user chooses. |
| `apps/` | **3** | the installable surface. **Your app goes here.** |

## The manifest

### Identity — who you are

```jsonc
"id": "hello-bina",                       // == the directory name
"title":   { "he": "שלום בינה", "en": "Hello Bina" },
"summary": { "he": "…", "en": "…" },      // one line; shown on the store card
"layer": 3,
"kind": "service",                        // service | blueprint | ui
"version": "0.1.0"
```

`title` and `summary` are objects, not strings. Writing `"title": "Hello"` passes a naive presence
check and then breaks the apps screen at runtime with `'str' object has no attribute 'get'`, so the
validator type-checks them — a lesson that cost a red apps screen once.

`kind: blueprint` is for an app that owns no container and whose entire installation is the
workflows it imports. It is a real kind, not a degenerate case: such an app is "installed" when its
blueprints are in n8n.

### Capabilities — what you offer

```jsonc
"capabilities": [
  { "name": "chat",
    "required_ops": ["send", "sendDocument", "state", "qr", "disconnect"],
    "optional_ops": ["broadcast", "createGroup", "groupParticipants"] }
]
```

A capability is a contract, and `required_ops` is the part that makes it one. Declaring `mail`
without saying which operations you serve means a consumer that calls `sendDocument` finds out in
production; declaring them lets the compiler refuse the plan instead. Serve every op you list.

### Use — what you need

```jsonc
"use": [
  { "capability": "sql",      "strength": "requires" },
  { "capability": "workflow", "strength": "requires", "ops": ["import", "activate"] },
  { "capability": "llm-local", "strength": "wants", "default_provider": "ollama" }
]
```

| Strength | Meaning |
|---|---|
| `requires` | hard. The provider is pulled in and started before you. |
| `requisite` | hard, and must already be present — do not pull it in. |
| `binds_to` | hard, and you bind to one specific instance. |
| `wants` | soft. Used if present; **never** pulls anything in. |
| `conflicts` | you and that capability's providers cannot both be enabled. |

Two more, both about ordering rather than presence:

- `"after": false` — you need it, but you do not need it started first.
- `"dependency": "weak"` — drops the ordering edge. This is how you break a cycle; the resolver's
  error message tells you so when it finds one.

**Ambiguity is never guessed.** If two apps provide `llm-local` and nothing says which, the plan
fails and names both candidates. Resolve it with `default_provider` on your `use[]` entry (your
preference) or `bindings.<capability>` in `platform.state.yaml` (the operator's, which wins).

### Routing — how you are reached

```jsonc
"routing": [
  { "host": "hello-bina", "port": 80, "auth": "sso",
    "module": { "group": "עסק", "icon": "box", "embed": true, "alias": "hello-bina",
                "name": "שלום בינה", "desc": "…", "order": 80 } }
]
```

The compiler emits **every** traefik label, the authentik proxy provider, the outpost binding and
the console tile from this. Do not hand-write traefik labels; `emit_labels: false` exists only for
apps whose labels have not been migrated yet.

- `auth: "sso"` puts you behind Authentik forward-auth, on every router of the host. `auth: "none"`
  is for a door whose callers are NOT the office's people (a webhook, a DSN, a customer's form) and
  never for a screen: G96 refuses a `module` with `tile` not `false` on a host of its own that says
  `none`, because that is what let n8n's editor answer the internet on every office (DGO-1594).
  `auth_exclude: ["/webhook", "/healthz"]` is where paths that must answer unauthenticated are
  LISTED — and today that is all it does on a host the compiler routes: the label emitter does not
  implement it, so a compiled app's excluded path is still behind sign-in (G21 prints it as a note;
  the decision to implement or withdraw it is hub sec-022). For a compose that writes its own
  labels it binds the other way: an open path the manifest does not list fails G21.
- **A host that carries an API, not a screen** (DGO-1557, supabase): `"https_only": true` emits no
  `-http` router on `web` at all — a browser gets the URL the app itself hands it, and on a server
  office the edge's port-80 answer is already a 308 (DGO-1595) — and `"publish": "domain"` renders the
  public routers **only where this office names a real host**: a `.localhost` value in the host
  variable renders the `-local` twin and nothing else, which is how an office that publishes nothing
  says so. It is also what keeps a certresolver off a name no authority can issue for.
- `module` present = a tile in the shell. Absent = routed but not surfaced.
- `module.embed: true` needs an `alias`; you are framed at `/a/<alias>/` with the navigation intact.
  `embed: false` means your UI lives on its own host and opens in a new tab.
- **Two more fields, for the two things a chain cannot say by itself** (DGO-1594, the n8n editor):
  - `middlewares: ["my-embed"]` — middlewares YOUR compose defines on your own service's labels,
    attached to this entry's routers AFTER the platform's sign-in (emitted `<name>@docker`; the
    provider is never yours to name, and G21 refuses a name it cannot find in your compose — traefik
    drops a whole router whose middleware it cannot resolve, and the app then answers nothing at all
    while the stack looks healthy). This is how an app keeps its own edge behaviour — headers, a
    frame policy — now that the compiler owns the routers. It is NOT a way to put auth somewhere
    else: the sign-in is first in the chain, always.
  - `sub_routes: [{"name": "push", "path": "/rest/push", "priority": 200, "on": "host",
    "middlewares": ["my-push-origin"]}]` — a PATH on this host that needs a chain of its own
    (`on: "framed"` instead addresses the host the shell frames you at). Use it for an endpoint whose
    headers or auth genuinely differ from the rest of the app, never for "this path should be open":
    a path that must answer the whole internet is an entry with `auth: none` on its own service, and
    G96 will ask you why (`/webhook/`, `/form/` and a DSN are the agreed reasons).
- **Let the console frame you.** Framed apps (`embed`, `external`) must allow the console as a frame
  ancestor: answer `Content-Security-Policy: frame-ancestors 'self' https://console.<domain>` and send
  no `X-Frame-Options` (an embedded app also passes with `SAMEORIGIN`, being proxied under the
  console's origin). Enable and `bbox update` ask your answer once you are up
  (`platform/manager/framecheck.py`, the console's own verdict) and record it in
  `data/platform/frame-checks.json`; with `FRAME_GATE=refuse` in `.env` (default `warn`) a refusal
  switches a new app off again / puts the previous image back. An `embed: false` app is recorded,
  never refused — it opens in a tab by design.
- **Your name, icon and description live here.** The console does not keep a list of apps — it did
  once, for five of them, and the list drifted and advertised tiles for apps that were not
  installed.

Two apps claiming the same host, or the same tile id, is a compile error naming both.

### The screen — one palette, one legend

If the app draws a screen, the screen wears the office's palette and writes no colour of its own.
The palette is written once, in `platform-base/bina-ui/theme-tokens.css`. An app has to stay
independently installable, so it carries a COPY of that block instead of loading it:

- **Carry the block.** Put its two marker lines (`/* @bina-theme-tokens:start */` and `…:end */`) in
  your stylesheet, add the file to `TARGETS` in `scripts/refactor/theme-token-lint.py`, and run that
  script with `--fix`: it writes the block and keeps it identical from then on. Gate G27 fails on a
  copy that drifted, on a listed file that lost its block, and on a file that carries the markers
  and is not listed. (This list is the one thing outside your directory a screen is added to: it is
  the gate's record of what must carry the block, not something the app needs in order to run.)
- **Name tokens, never a colour** — `var(--surface)`, `var(--ink)`, `var(--line)`, `var(--accent)` …
  Gate G82 fails on any colour literal in a screen's source: `#hex`, `rgb()`, a fallback inside
  `var()`. It reads what your server draws and declares too — a string of a Python source, a YAML
  manifest; where a token cannot be named there (a picture, a QR code, another program's field)
  write the palette's VALUE, which the gate lets through. The few allowances (another company's
  mark, paper) are named in the gate, each with its reason. If the palette lacks a role you need,
  the role is added THERE, once. What the browser paints by itself comes from the block as well:
  its own controls (a checkbox, a radio, a range) take the accent, and the stop the keyboard is on
  wears the palette's ring. Do not set `accent-color`; write a `:focus-visible` rule only for a
  part that needs a different ring, and never take an outline off without showing the focus
  another way.
- **A hue means one thing in every app, on the light ground and on the dark one:** olive — the
  brand, the main action, what is done and well; sky — in motion, what only informs; lime — look
  here, a warning, something waiting; plum — failed, a removal, the one final action; violet — a
  person has to look. Fills take the hue, text takes its `-d` step.
- **The office's mark is one file.** A screen that shows the «iO» mark carries the region of
  `platform-base/bina-ui/brand/mark.html` between its two markers (`<!-- @bina-brand:start -->` …
  `:end -->`) — inline, its parts wearing tokens through `.t`/`.m`/`.a` — and is listed under «the
  office's mark» in the same lint; `--fix` keeps every copy identical. A favicon or a site takes the
  image files beside it (`logo.svg`, `logo-dark.svg`, `favicon.svg`), which carry the palette's values
  because a file cannot name a token. Never draw a mark of your own.
- **Do not choose the ground.** The block follows the reader's device, and the console sets
  `data-theme` on your document when a person chose otherwise. A page that pins
  `data-theme="light"` on itself is light on a dark device, and flashes light inside a dark console.
- **Somebody else's component inside your screen** (a grid, a date picker) is dressed through ITS
  variables — every one it reads. One it is not given falls back to the component's own colour,
  and that usually shows only on the dark ground: the office's table once drew black text on a
  dark card and a white filter panel there, because fifteen of the twenty-four colour variables
  the grid reads were never set (gate G82 now checks that list). Look at its pop-ups too, on
  both grounds.
- **Say it and ask it through the office's notice and question.** A screen has no toast, snackbar
  or confirm dialog of its own, and never the browser's `alert` / `confirm` / `prompt`. Carry the
  `/* @bina-ask:start */ … :end */` block the way you carry the palette — its markers in your
  script, the file listed under «a question and a notice» in the same lint, `--fix` — and, because
  the gate fails a block with no listing AND a listing with no block, in ONE commit. Then:
  `binaTell(text, "ok" | "warn" | "bad")` and `await binaAsk({ title, body, facts, ok, danger, input })`.
  Read the service's answer BEFORE saying good news (one screen said «נותק» for a bot that had not
  logged out, another «ההתראה הוסרה» whatever came back): a
  failure is `bad` — it interrupts a screen reader and stays longer — and a step the person has not
  taken yet is `warn`, not a failure. A notice can carry a way back or the service's own sentence:
  `binaTell(text, kind, { act: ["ביטול", undo], more, stay })`. A removal is asked with its facts
  and opens on «ביטול»; one that cannot be undone asks for a text to be typed (`input.must`). A
  verb that takes a while, or that the service may well refuse, is handed to the question itself
  (`run: () => api(…)`): the question stays up with its button busy, says the refusal in itself and
  offers the verb again, and answers only once it succeeded — so no screen keeps a dialog of its
  own for that either. If a
  panel of yours keeps its buttons at the bottom, lift the notice above them while the panel is
  open (`body.drawer-open #bina-tell{inset-block-end:…}`): the notice's corner is where those
  buttons are, and a refusal said on top of «שמירה» hides the button it sends the person back to.

### The address is the state — your screen must be linkable

The console URL is the state of the office: **one address per screen, in every app** — copy it, open
it in another tab, send it to a colleague, and it lands on that screen (owner, 2026-10-12).

**The rule has no protocol in it.** The tail of the console's hash and your app's own URL are the
SAME string under your mount: `#/m/<module>/folder/5` is `/a/<alias>/folder/5`. Nothing is encoded
and nothing is translated, and **you write nothing for the shell**. The console reads your frame's
own navigations (same origin, one standard `navigate` listener) and mirrors them into its address
with `replaceState`, and it hands the tail back to your frame on arrival — where your own router,
reading `document.baseURI`, renders the screen.

So taking part means exactly what it means for any web app:

- **Read your route from your URL on load.** Your mount is `document.baseURI` (`/a/<alias>/` framed,
  `/` on your own host) — derive your route from `location.pathname` (or your hash) after it.
- **Write it back when the screen changes** — `history.pushState`/`replaceState`, or the hash. One
  screen per address: a folder, a document, a drawer that matters, a tab that is a place.
- **A screen with no state of its own** (a one-page view, a live board with nothing selected) simply
  has the module's address; there is nothing to invent.

Measured on the live console 2026-10-12 (`ci-artifacts/route-contract/navigate-probe.py`):
`#/m/drive/trash` is the app's own `/trash` and renders it; a click inside the app's own rail put
the app's route into the console's address with no code in the app and no polling; a full page load
inside the frame keeps working (the shell re-subscribes on `load`).

**Gate G83 fails an app that keeps no screen in its URL** (`scripts/refactor/embed-route-lint.py`):
it asks, per embedded app, whether the front end reads its own URL and writes it. An app whose screen
genuinely has no state to carry is named in that gate with its reason — a declaration, never a silent
pass. The product half — that every screen the UI map declares opens at its own console path — is
measured per app in a browser.

**A frame the browser isolates from the shell** — an app on its own host, another office's app
through the door, a `sandbox` without `allow-same-origin` — cannot be read, and there the console's
address names the app (and the office), never the screen inside it. That is the origin boundary, and
it is the only case the rule does not cover.

### Connections — the secrets you need

**Where the herd's secrets live: in the MacBook's vault, «חיבורים ומפתחות».** The owner's standard (2026-11-03,
DGO-1330): «סודות (שתמיד שומרים במק)». A secret that belongs to the business — a bot token, a provider key, an
account — is kept in the Mac's vault, under the name the owner gave it; an agent looking for one looks there
first. Every office has its own vault and none writes another's (hos-001), so another office does not get a
secret by copying it: it is MADE there or PULLED from the Mac over the link, by that office's own process, into
its own vault. Never paste a secret into a chat, a file of the repo or a terminal line. The mechanism and its
state are on DGO-1330.

```jsonc
"connections": [
  { "id": "supabase-service-key",  "required": true },
  { "id": "supabase-db-password",  "required": true }
]
```

This is the forward direction, and the only one anyone maintains. The credential plane derives
"who uses this secret" from these declarations — never the reverse.

If your app introduces a secret that exists *only because your app exists*, declare the whole
catalog entry rather than asking someone to add it to layer-1 config:

```jsonc
"contributes": {
  "connection_providers": [
    { "id": "portainer-admin", "title": "Portainer admin password", "kind": "password",
      "automint": { "type": "password", "chars": 24 }, "env": "PORTAINER_ADMIN_PASSWORD",
      "probe": { "type": "http", "url": "http://portainer:9000/api/status" } }
  ]
}
```

Uninstall the app and the secret leaves the catalog with it.

To hold no standing plaintext at all, add a `broker` block: the compiler blanks those variables in
your environment and you lease them at runtime from `connections`, which identifies you from the
docker socket and grants only what this manifest declares.

### Data — what survives you

```jsonc
"data": { "volumes": ["myapp_data"], "on_uninstall": "keep" }
```

`keep` (default) or `purge`. Choose `keep` unless the data is genuinely worthless without the app;
the store shows the operator which one you chose *before* they confirm, and `purge` is a red
warning box.

If a service of yours writes to your stores while it runs (a worker, a poller), name it in
`"writers": ["myapp-worker"]` inside `data`: a quiesced export (`--quiesce`) stops exactly the declared writers
and starts them again after. Each must be a service of your compose whose `container_name` is
`<service>-${DEPLOYMENT_NAME:-bina-deployment}`, never a database (G26).

If your compose mounts a volume ANOTHER app creates (any-concurrency reads n8n's `n8n_storage`), name it in
`"shares": ["n8n_storage"]`, never in your `volumes`: a volume has one owner, the app it is backed up, restored and
purged with. Your `--app` export and import skip it and say whose it is, and your `uninstall --purge` leaves it
(G26 fails a volume in two apps' `volumes`, DGO-1510).

### Health and readiness

```jsonc
"progress_deadline_seconds": 900
```

How long you may stay not-Ready before the control plane stops calling it "starting" and reports
`ProgressDeadlineExceeded`. The default (600s) is generous. Raise it only for a genuinely slow first
boot — n8n's cold-volume migrations take minutes — because a long deadline hides real breakage.

Your compose `healthcheck` must use a binary **your image actually has**. Gate G18 checks this,
because the failure is silent: a probe calling `curl` in a `node:22-slim` image fails with
`exec: curl: executable file not found`, and the container reports unhealthy forever while serving
perfectly well. An official language image always has its own interpreter — use that.

### Automations

```jsonc
"blueprints": { "n8n": ["blueprint/n8n/*.json"] }
```

Imported on enable, removed on disable. If you ship these you must `use` the `workflow`
capability — gate G13 enforces it, because a blueprint app without the engine is an app that
installs and does nothing.

Convention worth following: one **router workflow** per app exposing your capability's ops as
`{op, params}`, so callers never learn your internal endpoints. `drive api`, `mail api` and
`whatsapp api` are all the same shape.

### The office agent — teach it to operate you

```jsonc
"agent": { "context": "AGENT.md", "order": 30 }   // path is relative to the app directory
```

The app owns one Markdown file and points at it here. `reconcile` renders every **enabled** app's
brief into `.generated/registry/agent-context.md`, and `apps/bina-ds` loads that file as one
system-prompt section on **every** turn — so installing an app teaches the agent it exists and how to
drive it, and disabling the app takes the brief away with it. There is no second list to maintain:
the agent's persona deliberately names no app (`computers`, `git`, … each arrive only through this
file), which is the same rule the console tiles and the connections catalog already follow.

What belongs in the brief — and only that:

- what the app is FOR, in the caller's words, and the vocabulary it uses;
- the door: which endpoints or ops to call, with one copy-pasteable example;
- the traps: what looks like success but is not, what is irreversible, what refuses and why.

What does **not** belong: anything the manifest already states mechanically (capability, interface,
endpoint, ops, tile, required secrets) — `reconcile` prints those in the same section, and a brief
that repeats them spends the agent's context on a copy. The compiler REFUSES a brief over
**6000 bytes** (`MAX_BRIEF_BYTES`): it is injected into every session, so its size is bought from
every other app's brief. A `context` path that does not exist is also a refusal — a missing brief is
otherwise silent, and "the agent never learned this app" is a bug with no owner.

Look at `apps/git/AGENT.md` and `apps/computers/AGENT.md` for two worked examples.

## The four channels — screen, CLI, API, event stream

Every app is reached four ways, and an app that has something to say offers all four (the owner,
2026-11-03, DGO-1300). Three are a person or a program ASKING; the fourth is the app TELLING, so
that agents and automations listen instead of polling.

| Channel | What it is | Where it is declared |
|---|---|---|
| **Screen** | the console tile, `/a/<alias>/` | `routing[].module` (above) |
| **CLI** | `./bbox <app> <verb>` and `dgo <app> <verb>` — both run `hooks/<verb>` | a file in `hooks/`, its first `#:` line is its help |
| **API** | the service's HTTP ops: canonical ops answer `{"ok":true,"op":…,"data":…}` | `capabilities[].required_ops` |
| **Event stream** | what happened, as it happens: `<app> flow` prints the last 10 events and stays live | `use: [{"capability": "kv", "strength": "wants"}]` + `hooks/flow` |

The rule each channel keeps is in [app-cli-api-standard.md](app-cli-api-standard.md): «what the screen does,
the API and the CLI do», with the grammar, `--json` on every verb, the exit codes 0/1/2/3, help, secrets and
writes.

### The event stream — flow.v1

The stream is a platform contract on the redis every office already runs — its `kv` capability
(`platform-base/redis`, which lists the stream ops); no broker and no capability of its own, because a
capability of its own is "provided" by every app that runs a private redis (G25). One Redis stream per
app, **`dgo:flow:<app-id>`**.

- **Publish** — one `XADD` per event, with these fields (strings):
  `type` (dotted, `<noun>.<verb>`: `message.new`, `account.lost`), `title` (ONE line a person reads,
  Hebrew is fine), `at` (ISO-8601 UTC), `app` (your id), and optionally `link` (an address in the
  console) and `data` (a JSON object: the facts a program needs, so nobody parses `title`).
- **Cap it and keep it a window**: `XADD dgo:flow:<app> MAXLEN ~ 1000 * …` and `EXPIRE dgo:flow:<app>
  2592000` in the same `MULTI`. Redis has 256 MB and refuses every write when full (noeviction), and
  a key with no TTL fails the deployment export (`platform-base/redis/hooks/backup`): an event stream
  is not the office's state. A stream quiet for 30 days is gone; that is the point.
- **Never block on it**: a publish that fails is counted and shown on your screen, never raised —
  your app keeps working while redis is away.
- **What not to publish**: a secret, a token, a session — ever; and a person's private content only
  when a person switched that source on (the stream is read by every agent of the office).
- **Listen** — `./bbox redis flow [app…]` (every stream when none is named; `-n N`, `--once`,
  `--json` for one JSON object per line), or your own verb: `hooks/flow` is two lines that exec
  `platform-base/redis/hooks/flow <your-id> "$@"`, so `dgo <app> flow` works. A program on the office
  network reads with `XREVRANGE` (the last N) and `XREAD BLOCK` (what comes next); a consumer that
  must not miss an event between runs keeps its last id, or uses a consumer group.
- The app needs `REDIS_PASSWORD` in its environment to publish; the reader takes it from `.env` and
  hands it to `redis-cli` on stdin, never on a command line.

**Publish through the ONE publisher, never a copy of your own** (DGO-1402):
`platform-base/redis/flowpub.py` — standard library only, so any Python image can load it. Mount it
read-only (`- ../../platform-base/redis/flowpub.py:/opt/dgo/flowpub.py:ro`, and `REDIS_PASSWORD` in the
environment), then `sys.path.insert(0, "/opt/dgo"); import flowpub` and
`flowpub.emit("<your-id>", "file.uploaded", "הועלה קובץ", data={...})`. Work that takes time is one bar:
`with flowpub.span("<your-id>", "site.deploy", "פריסה"):` writes `site.deploy.started` and `.ended` (or
`.failed`, and re-raises) with one `data.span`. It never blocks and never raises; `flowpub.stats()` says
what it sent and what failed. `platform-base/redis/test_flow_publishers.py` refuses a new copy of the
contract. Worked examples: `apps/sites/store.py` (one call in its event log covers the whole app),
`apps/drive/app.py` (an upload as a bar), `platform-base/connections/app.py` (ids, never values),
`apps/telegram` (`message.new` for every message in a watched chat, `account.connected` / `account.lost`).

**A notice is already an event.** `platform-base/notifications` publishes every notice that is news as
`notice.<level>`, with its answers (`meta.actions`, checked by its `flow.py`) — the relay to the owner's
group offers them as buttons (DGO-1329). So an app that already posts a notice is on the stream without
code of its own.

**«כל מקביל» hears every stream by default**: its `flow` lane reads every `dgo:flow:*` it finds (a row
per app, `apps/any-concurrency/flow_source.py`), so an app that publishes is on the office's timeline
with nothing more to declare.

## Build it

```bash
python3 platform/manager/reconcile.py validate   # structure, types, host/tile collisions
python3 platform/manager/reconcile.py plan       # the graph: order, providers, diagnostics
python3 platform/manager/reconcile.py render     # write .generated/
./bbox run                                       # up
```

`plan` before `render` is worth the habit — it reports *every* diagnostic at once rather than
failing on the first, and it is where an ambiguous provider or a dependency cycle shows up, before
a single container starts.

Enable it by adding to `platform.state.yaml`:

```yaml
apps:
  your-app-id: { state: enabled }
```

`enabled` / `disabled` / `archived`. Archived removes images and containers to reclaim disk and
**keeps the data and the tile** — it is not uninstall.

## Before you call it done

```bash
python3 scripts/refactor/ownership-lint.py --strict     # G5  nothing lives outside an app
python3 scripts/refactor/layering-lint.py --strict      # G9  no base app names yours
python3 scripts/refactor/blueprint-dep-lint.py --strict # G13 blueprints imply the engine
python3 scripts/refactor/healthcheck-lint.py            # G18 the probe binary exists
python3 scripts/refactor/image-pin-lint.py              # G15 third-party images are pinned
python3 scripts/refactor/theme-token-lint.py            # G27 your screen's copy of the palette IS the palette
python3 scripts/refactor/palette-lint.py                # G82 your screen names no colour of its own
bash scripts/fresh-machine-check.sh                     # a bare clone still compiles
```

The last one matters most and is the one people skip. It clones into a scratch directory with no
`.env`, no `.generated/` and no volumes. Almost every bug that reaches someone else's machine is a
thing that worked here because this machine already had it.

## The two rules worth remembering

**Declare, do not register.** If you find yourself editing a file outside `apps/<your-app>/` to make
your app work, that is the bug. The mechanism you need either exists (`contributes.*`) or should be
added to the compiler — not worked around by teaching a base app your name.

**Uninstalling must be `rm -rf` on your directory.** Every derived artifact — traefik labels, SSO
providers, console tiles, credential entries, imported workflows — is compiled from the manifest, so
all of it disappears on the next render. Anything you leave behind in a base file is drift someone
will find months later, still 502-ing.
