# The app CLI and API standard: what the screen does, the API and the CLI do

Every app of the office is reached four ways (build-your-first-app.md, «The four channels»): its screen,
its CLI, its API, and its event stream. This file is the rule each channel keeps, so a person, an agent and
an automation can do the same things in the same words.
- **Written:** 2026-11-10, for DGO-1243 (cli-201 of `apps/project-pln/plans/dgo-cli.yaml`).
- **The owner's words behind it:** apps are «completely usable in console, CLI and API», local and remote
  (2026-10-01, `dgo-remote-apps.md`), and every app gives «UI + CLI + API» (dgo-cli plan).

Each rule below says whether it holds today or is still to come. A rule marked **later** names the item that
brings it, and is not to be claimed before that item lands.

## 1. The rule

**Whatever a person can do on an app's screen, a program can do through its API and a person or an agent
through its CLI.**
- An operation with a face missing is a gap.
- A gap is either closed or written on the app's item, never left silent.
- The parity table (**later**, DGO-1248 / cli-206) will list the gaps per app.

## 2. The CLI

**Where a verb lives (today).**
- A verb is a file: `<root>/<app>/hooks/<verb>`.
- The dispatcher runs it for `./bbox <app-or-alias> <verb>` and `dgo <app> <verb>`.
- Nothing about an app is declared in `bbox` itself (app.schema.json `cli`, gate G31).
- An app's command surface is its `hooks/` directory.

**The grammar.**
- **Today:** `dgo <app> <verb> [args]`.
- **Target:** `dgo <app> <noun> <verb> [args] [--json]` (the plan's decision 3).
  - The noun has no plural: `dgo claude session send <id> "…"`, `dgo project-pln item new DGO "…"`.
  - A verb with no noun is allowed where the app has one obvious object: `dgo telegram send @user55 hi`.
- A verb that takes a noun also accepts the noun-first form. `tasks item new` is `tasks new` (DGO-1252).

**Help.**
- The first `#:` line of a hook is its one-line summary. `./bbox <app>` with no verb names the app's verbs.
- `-h` / `--help` prints every `#:` line and exits 0.
- A verb called with missing arguments prints its usage line and exits 2.

**Output.**
- A person reads one line per thing, in the language of the office's screens. Ids and paths stay as they are.
- **`--json` on every verb** prints machine output and nothing else:
  - one JSON object;
  - or, for a stream (`flow`, `list --watch`), one object per line.
- The shape of a verb's `--json` is a contract: documented in its help or its app's README, and not changed
  without a version.
- Progress and warnings go to stderr, so `--json` output parses even when something was said.

**Exit codes.**
| code | means |
|---|---|
| 0 | it did what was asked (or, for a read, it answered) |
| 1 | it failed: the line before says why |
| 2 | usage: a wrong verb, a missing argument, an unknown flag (refused by name, never dropped in silence) |
| 3 | not reachable: the app, its office or its engine did not answer. Trying again later may work |

- An app may define a code above 3 for a case its callers must tell apart, in that verb's help.
  `project-pln tasks attach` exits 4 when the rest landed and every refusal is final.

**Secrets.**
- A secret never crosses a command line, an environment a person can list, or a log.
- A verb takes its credential from the vault at run time (`connections`).
- A secret a person gives arrives on stdin or as `@<file>`.

**Writes.**
- **A destructive verb asks for its reason, and uses the recoverable form when there is one:**
  - trash, not delete (drive);
  - cancelled, not deleted (`tasks rm`);
  - disabled, not removed (apps).
- **An outward action** (a send, a publish, a payment) is a verb of its own:
  - it is never a side effect of another;
  - it is bound last, after the reads (DGO-1255);
  - an agent runs it only on the owner's word.
- **An edit keeps what it replaces.** `tasks edit` posts the old description before it writes the new one.

## 3. The API

- **Canonical ops** answer `{"ok": true, "op": "<name>", "data": …}`, or `{"ok": false, "error": "…"}` with
  a non-2xx status. A capability lists its ops in `capabilities[].required_ops` (app.schema.json).
- **The address is the app's.**
  - Inside the office network: `http://<service>:<port>/…`.
  - From the console: `/a/<alias>/…`.
  - An app on a linked office: through that office's door, with the identity that office declared for
    this one (DGO-545). No key on the caller.
- **Not an API:** `docker exec` into a container, reading another app's files or database, or scraping its
  screen.
  - An app never reaches into another (AGENTS.md, «Layout»).
  - A CLI verb that needs another app's data calls that app's API.
- **The same op behind every face.**
  - A screen button calls the API route.
  - A CLI verb calls the same route, or does the same thing through the app's own client inside its
    container. `ollama models` is `ollama list`, the same answer as `GET /api/tags`.
- **Later:**
  - **cli-202 / DGO-1244:** an app declares its operations once, as app.json `ops`: id, method + path, the
    verb, the screen's action, read or write. The dispatcher builds help and verbs from it; the compiler and
    its Go twin render it.
  - **cli-203 / DGO-1245:** `dgo <app> api <METHOD> <path> [--data @file]` reaches any route of any app, local
    or linked, with the vault's credential. Nothing is out of reach while curated verbs are written.
  - **cli-204 / DGO-1246:** a gate fails when an op has a face missing. It is staged: it warns with the
    counts for one release, then refuses.

## 4. The event stream

flow.v1, as build-your-first-app.md defines it:
- one Redis stream per app, `dgo:flow:<app-id>`;
- events published through `platform-base/redis/flowpub.py`;
- `dgo <app> flow` to listen.

What an app does is announced there, so agents and automations listen instead of polling.

## 5. Agent apps

- An agent app (bina-ds, bina-claude) speaks agent.v1 (sessions, messages, approvals).
- **Today** the same agent answers to two roots: `bbox agent --app <id> …` and `bbox <app> sessions`.
- **Later (cli-205 / DGO-1247):** `dgo <app> session …` is the one door over agent.v1, and `dgo agent`
  stays an alias.

## 6. A wrapped official app

An app that wraps a vendor's own client (the bina-claude shape) keeps the same four channels:
- the vendor's Linux client streamed as the screen;
- the vendor's headless side (its CLI or library) behind an adapter for the API and the verbs;
- one volume that holds the sign-in.

The catalogue of which apps can take this shape is on DGO-1265. The template is DGO-1259, and the gate
for a new wrap is DGO-1266.

## 7. Checking an app against this standard

1. `./bbox <app>` names its verbs, and each verb's first `#:` line is its one-line summary.
2. Every verb has `--help`. A wrong call exits 2, and an unknown flag is refused by name.
3. Every read verb has `--json`.
4. Every screen action has a route and a verb, or a line on the app's item saying it is missing.
5. No secret on any command line. No `docker exec` of another app.
6. Destructive verbs have a reason and a recoverable form; outward verbs stand alone.
