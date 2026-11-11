# Provider apps — how DGO implements an outside service

The owner, 2026-11-08 (DGO-1473):

> every implementation of a specific provider becomes an application solving interaction with that provider,
> and if it's generic, like domain, social, news, ai, tasks etc, [there is] one generic one organising and
> serving all.

> once we say "dgo implement internic/facebook/youtube/gmail/hostinger/telegram/etc" to an agent [we] will get
> [an] application giving us all 4 channels to fully interact with this external app.

This is that standard. The worked example is `apps/domain-internic` (the InterNIC provider of `apps/domains`).
The second, with both kinds side by side, is «קבצים» (DGO-1500, `apps/drive/ENGINES.md`): the generic `drive`
and its engines `drive-local` (kind `engine`: the office's own storage) and `drive-google` (kind `external`),
one protocol (`drive-engine.v1`, whose engine side is one file copied into every engine and held equal by a
test), and the generic app keeping every route its callers had, so splitting it changed none of them.

## Two kinds of app, one name rule

| | the GENERIC app | a PROVIDER app |
|---|---|---|
| what it is | one domain of work: `domains`, `social`, `news`, `ai`, `tasks`… | one outside service: InterNIC, Facebook, YouTube, Gmail, Hostinger… |
| what it holds | the office's vocabulary for that work, its screens, its history, its rules, its consent doors | everything that service needs: sign-in, scripts, endpoints, quirks, the service's own words |
| what it never holds | a line of any one provider's code | a screen or rule of the generic work |
| its id | `domains` | `<generic>-<provider>`: `domain-internic`, `social-facebook`, `ai-deepseek` |

The id IS the registration. The generic app finds its providers by name in what the compiler already writes
(`apps/domains/provider_client.py`): an app of this office in `.generated/registry/office.apps.json`, or one a
linked office gives in `.generated/registry/remote.<office>.<alias>.json`. Ours first. When two linked offices
give the same provider it is reported, never guessed: a client's office may run its own with its own account
(`DOMAIN_PROVIDER_<ID>_OFFICE` chooses). Nothing is added to the generic app to add a provider; removing the
provider app removes it.

A service with no generic app yet (Hostinger's VPS panel, a single SaaS) is still a provider app; its generic
app is written when a second provider of the same work arrives.

## External or engine — say which, before writing a line

Every provider app carries `provider.json` beside its `app.json` (served by its `/ops`):

```json
{"for": "domains", "id": "internic", "kind": "external", "service": "https://portal.internic.co.il",
 "why_external": "…", "ladder": [ {"rung": "official-api", "state": "none", "evidence": "…"}, … ]}
```

- **`external`** — the app BRIDGES a service that runs elsewhere (InterNIC, Facebook, YouTube, Gmail,
  Hostinger, Telegram). The office signs in to it and drives it; nothing of the service runs here.
- **`engine`** — the app RUNS the service's own engine inside the office, because it is open source (Plane,
  n8n, Jitsi, Supabase), and gives the same four channels over the copy it runs.

"dgo implement youtube" is external — there is nothing to run. "dgo implement plane" is ambiguous, because
Plane can be both: the agent ASKS «only external (bridge your Plane cloud account), or also internal (run the
whole engine inside the office)?» before it writes anything. It asks only when the service is open source
AND self-hostable; otherwise it decides and writes down why.

## The access ladder — research every door first, use the best one that holds

Before building, the agent finds every way to interact with the service, with evidence for each, and records
them in `provider.json` `ladder`. Highest first:

1. **official-api** — the service's documented API (REST, GraphQL, IMAP/SMTP, a CLI). Its own, stable, with
   scopes. Note what it needs (a key, an OAuth app, an IP allowlist) and who can grant it.
2. **webapp-api** — the API the service's OWN web app calls (its XHR/fetch routes, seen in the browser's
   network log while a person does the action once). Called with the signed-in session from inside the page,
   it is the screen's own request without the clicks: fast, and as stable as the web app itself. Observe it,
   write it down, then build on it.
3. **browser** — drive the office browser (`apps/browser42`, `browser_session.v1`) by role and accessible
   name, every effect READ BACK. It always works, and it is the slowest and the most fragile: the last rung.

The rule: build on the highest rung that is open, keep the next one below as the fallback, and add a rung
beside the one in use (never instead of it) until it is proven on the live account. A rung that is closed for
a reason someone can lift (an API key, an allowlist) is a work item, with that sentence, for whoever can.

## The four channels — every provider app has all four

(ai/context/build-your-first-app.md, «The four channels».)

- **ui** — a console tile `/a/<id>/`: the connection's state, what the service holds, what happened.
- **cli** — `./bbox <id> <verb>` from `hooks/` (each file's first `#:` line is its help): `status`, `login`,
  the reads, the writes. On an office that does not run the app, the same verbs reach the office that does,
  through the link (`apps/domain-internic/where.sh` → `scripts/herd_home.py`).
- **api** — the generic app's interface for its providers (`domain-provider.v1` for domains): `GET /ops`
  names the interface, the kind, the ladder and the ops; every answer is `{"ok": …}` with a named `state`.
- **flow** — `dgo:flow:<id>` on the office redis: what happened (`login.ok`, `record.created`,
  `session.lost`), never a secret, a code or a cookie.

## Signing in by itself — the credential, the code, the stop

- The service's credential is a row the provider app declares in its own `app.json`
  (`contributes.connection_providers`), typed once in חיבורים ומפתחות. For an API rung the app LEASES it
  at call time under its container identity (`POST /api/broker/lease`, and `connections[]` grants it),
  holds it only as locals, and never prints, returns, journals or publishes it.
- For the browser rung the secret does not pass through the app at all: the row declares the service's
  address (`app.url`), the office browser mirrors it into its own password store
  (`apps/browser42/logins.py`), and the app clicks the field and picks that saved login. Never type a
  secret through the Playwright MCP (its reply carries the code it ran, text included), and never open the
  browser's DevTools port to an app (DGO-983).
- A consent to a write is taken only inside the provider's container (the CLI at its office's shell); a
  `consented_by` from any other caller is dropped.
- A code the service e-mails is read through the office's mail (mail.v1 `search` + `get`); a TOTP through the
  credential plane's `totp` kind (`apps/browser42`, `browser42-totp-facebook`).
- ONE attempt per call, no retry: a captcha, an unknown form, a refused password stop with their own state and
  the live view, where a person finishes. A locked account costs more than any action.

## Writes and consent

A write the office has not seen succeed is refused until a named person consents (the generic screen's
signed-in person, or `--consent "<who>: <why>"` at the office's own shell). One consented write that was READ
BACK from the service makes that action the office's own, kept with who and what
(`apps/domain-internic/portal.py` `mark_verified`). Money and irreversible actions keep their exact
confirmation (`confirm: "<thing>:<op>"`).

## Where it runs

A provider app runs where its account lives — where the browser signed in to it runs, or where its API key
is — and that office gives it to the others (`apps/computers/herd.yaml` `apps:` and `give:`). The generic app
may run anywhere; it reaches its providers through the link.

## «dgo implement <service>» — the recipe

1. Name it: `<generic>-<service>`; decide `external` or `engine` (ask only when both are real).
2. Research the ladder: the official API, the web app's own calls, the browser — evidence for each.
3. Write `provider.json`, `app.json` (credential row, connections, routing for the tile), `docker-compose.yml`.
4. Build the api first (the generic interface), then cli (`hooks/` + `cli.py` + `where.sh`), ui, flow.
5. Tests with every door faked: the gates of writes, the stops of sign-in, no secret in any answer.
6. `reconcile.py validate` + `plan`, the gates of build-your-first-app.md, a second reader, then the proof on
   the live account through the CLI.
