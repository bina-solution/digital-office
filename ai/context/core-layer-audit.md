# Which of `platform-base/` is actually core — an evidence-based audit

Owner, item **core-008**: *"core should have only strictly required apps … we need to check what is
really layer 0/1 and take down what is not."*

This is the audit and the plan; it removes nothing. Every number below comes from a command that was
run, and every claim names the file and line it rests on. Where a number could not be measured here,
the row says so instead of estimating.

Measured **2026-10-09** on hp-laptop, worktree `/tmp/wa-core-008` at `de2ded14` (`hp-dgo`), against
the office that is running on that machine. Two states are used throughout and they are **not** the
same file:

* **the committed default** — `git show HEAD:platform.state.yaml`, 13 apps enabled. This is what
  `git clone` + `./bbox run` gives a new machine.
* **this office, live** — `/mnt/c/…/MyDGO/platform.state.yaml` at the same commit, 20 apps enabled.
  `diff` against the committed file reports 236 differing lines (17 apps switch disposition, the
  `remote:` block is a different office), and other agents were editing that file while this ran;
  every live measurement below is a snapshot, not a property of the file.

## 1. What `platform-base/` actually provides

Fifteen manifests, plus one directory that is not an app:

```
$ ls platform-base/*/app.json | wc -l
15
$ ls platform-base/
any-concurrency  app-management  authentik  autoheal  bina-ui  connections  console
data-management  forward-auth    glitchtip  machine   n8n      notifications  postgres
redis            traefik
```

`platform-base/forward-auth/` has **no `app.json`**: it is a Go program (Dockerfile, 12 tests,
README) with no compose service, no `bbox` verb and no reader anywhere in the tree. `git log -1` on
it says `c20c25ef 2026-10-09 core-006: the Go forward-auth … as a proposal`. It is a *proposal to
replace authentik*, not a service — see §7.

`python3 platform/manager/reconcile.py validate` → `OK — 41 manifest(s) valid` (26 apps + 15
platform-base), 40 capabilities. The whole graph is consistent; nothing below is a validation error.

## 2. Method — the four questions, and the command that answers each

| question | what was run |
|---|---|
| who *declares* it | `json` walk of every `app.json`'s `capabilities[]` / `use[]`; the compiler's own reverse index: `reconcile.py required-by --app <id>` |
| who *calls* it | `git grep` per service for its in-network name, its `*_URL`/`*_HOST` env and its capability name, filtered to code that runs (`.py .js .mjs .ts .sh .yml .yaml .json .html .go`) — docs, `issues/`, plans and tests excluded |
| does the office still start without it | `reconcile.py services --for <enable-set minus X>` — the compiler's own closure. Nothing was enabled, disabled or deleted to get this |
| what it costs | `docker image ls` for the built name; `docker stats --no-stream` ×3 for resident memory on the running office |

The closure experiment is the load-bearing one, because it is the compiler answering rather than an
opinion. In the committed default (`reconcile.py services`, 18 services over 13 apps) dropping one
app at a time gives:

```
drop redis       -> redis gone, 0 pull-in lines            (nothing wants it)
drop postgres    -> db STILL THERE: "postgres: pulled in as provider of 'sql' for authentik"
drop connections -> connections back: 1 pull-in (bina-ds, computers, dgo-extend, git)
drop authentik   -> authentik back:  1 pull-in (identity for console)
drop traefik     -> gone, 0 pull-in lines
drop console     -> gone; it is what pulls authentik + connections + postgres in
drop bina-ui     -> no service changes at all (it owns no container)
```

And per-app, what each enabled app drags in on its own:

```
app-management   services: app-management                                     | no pull-in
traefik          services: traefik-deployment                                 | no pull-in
postgres         services: db                                                 | no pull-in
redis            services: redis                                              | no pull-in
authentik        services: db authentik-server …                              | postgres pulled in for 'sql'
connections      services: connections                                        | no pull-in
console          services: db authentik-* connections console                 | connections + authentik + postgres
bina-ui          services: (none)                                             | no pull-in
bina-ds          services: connections bina-ds                                | connections for 'secrets'
computers        services: connections computers                              | connections for 'secrets'
git              services: connections git forge                              | connections for 'secrets'
dgo-extend       services: connections computers dgo-extend dgo-net dgo-link  | computers + connections
digital-assets   services: digital-assets                                     | no pull-in
```

**`./bbox run` names exactly two apps, and names neither of them.** Its boot is: render → network →
`dc up -d --wait` over the compiled `include:` list → `run_app_hooks prepare|onboard` → then two
capability lookups, `bbox:270-272` (`capability-provider --capability forward-auth`) and
`bbox:307` (`--capability control-plane`), which resolve whoever provides those roles and `docker
exec` into them (`bbox:322`). Every other app is in the boot **only because its `enabled:` line says
so** — nothing pulls it in.

## 3. The table

`resident` = `docker stats --no-stream`, three consecutive reads (stable to ±0.5 MiB); where a first
read differed it is given as `a → b`. `committed boot` = present in `reconcile.py services` for the
committed default; `live boot` = present for this office's enable-set.

| # | app | layer / kind | provides | declared by | live callers (installed code) | committed boot | live boot | image | resident |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `traefik` | 1 service, `system` | `edge` | **nobody** | everyone — 55 code refs; `authentik@file` middleware (`traefik/config/authentik-forwardauth.yaml`) | yes (root) | yes | `traefik:v3.3` 224 MB | 66–68 MiB |
| 2 | `authentik` | 1 service, `system` | `identity`, `forward-auth` | `console` (requires identity), `my-docs`; `traefik` (wants identity) | `bbox:272` by role; 14 SSO-gated hosts; `blueprints/deployment-apps.yaml` | yes (for `console`) | yes | `goauthentik/server:2024.12` 1.08 GB ×3 services + `postgres:16-alpine` 294 MB | server 287.5 + worker 256.7 + bootstrap 4.2 + pg 41.8 = **590 MiB** |
| 3 | `connections` | 1 service, `system` | `secrets`, `connection-instances` | `secrets`: 15 apps (5 enabled). `connection-instances`: **nobody** | `console/app.py:24`, `app-management/app.py:312`, `dgo-extend/{app,converge,links}.py`, `computers/app.py`, `chat`, `browser42` | yes (for console, bina-ds, computers, git, dgo-extend) | yes | `deployment-hacohen-connections` 157 MB | 40–45 MiB |
| 4 | `console` | 2 service, `system` | `shell` | **nobody** | `app-management/app.py:973` `CONSOLE_INTERNAL_URL` (`_peer()` reaches a linked office through the console's door) — and it *is* the owner's front door | yes (root) | yes | `deployment-hacohen-console` 160 MB | 42–46 MiB |
| 5 | `app-management` | 1 service, **not** `system` | `control-plane` | **nobody** | `bbox:307/322` by role; `apps/dgo-extend/app.py:66`, `projection.py:148`; `autoheal.py` (reads its container list) | yes (root) | yes | `ghcr…/app-management:latest` 234 MB | 45–55 MiB |
| 6 | `bina-ui` | 2 **library** | `ui-kit` | 10 apps, all `wants`/weak (console, computers, dgo-extend, digital-assets, domains, git, my-docs, sites, social-list, telegram-tv) | 8 vendored `static/vendor/bina-table.{css,js}` copies + `theme-token-lint.py:33` reads `theme-tokens.css` as the palette source | **no container** | **no container** | none (1.1 MB of source) | **0** |
| 7 | `postgres` | 1 service, `system` | `sql` | `drive`, `indox`, `apitools`, `chat`, `my-docs`, `supabase`, `any-concurrency`; decorative (`own_instance: true`) from `authentik`, `n8n`, `glitchtip` | `apps/drive/docker-compose.yml:27` `PGHOST=supabase-db` — **real**; live `pg_stat_user_tables` shows `public.drive_files` 4 rows, `public.indox_instances` 2, `indox_hacohen.settings` 58 | yes — **only because authentik's decorative `sql` pulls it** | yes (drive) | `supabase/postgres:15.8.1.085` 1.96 GB | 44–47 MiB |
| 8 | `redis` | 1 service, `system` | `kv` | `any-concurrency` (real), `chat`, `indox`, `n8n`(own), `glitchtip`(own), `project-pln`(own), `redisinsight` | `any-concurrency/docker-compose.yml:37` `REDIS_URL=…@redis:6379/0` | **yes, and nothing pulls it in** (`required-by --app redis` → `[]`) | yes | `redis:7-alpine` 39.1 MB | 49.6–50 MiB |
| 9 | `n8n` | 2 service | `workflow`, `automation-stdlib` | `workflow`: `drive`, `indox`, `mail`, `chat`, `google-workspace-agent`, `raphael`. `automation-stdlib`: **nobody** | the whole automation estate; pulled in for `drive` in both states | no (n8n disabled in the committed file) | yes | `binaos/n8n:2.17.4` 1.65 GB ×4 + `n8nio/runners` 386 MB + `postgres:17` 454 MB | 200.7 + 139.6 + 146–157 ×2 + 3.9 + 20–28 ×2 ≈ 640 MiB |
| 10 | `notifications` | 2 service | `notify` | `console`, `autoheal`, `indox`, `chat`, `domains`, `sites`, `social-list`, `raphael` — **every one `wants`/weak** | `bina-ds/harness/entrypoint.sh:113`, `bina-ds/pulse.sh:36`, `self-update.sh:80` (**and bina-ds declares nothing**), `domains/app.py:1386`, `sites/scheduler.py:45`, `autoheal/autoheal.py:128` | no | yes | `ghcr…/notifications:latest` 150 MB | 38–46 MiB |
| 11 | `glitchtip` | 2 service | `error-tracking` | `n8n` (wants), `notifications` (wants) | `n8n/workflows/{errorHandler01,glitchtipReporter01}.workflow.ts`, `notifications/app.py` | no | no | `glitchtip/glitchtip:6.2.2` 728 MB ×3 + pg + valkey | **not running here** |
| 12 | `any-concurrency` | 2 service | `concurrency-metrics` | **nobody** | `apps/browser42/docker-compose.yml:168,200,245` (`ANY_CONCURRENCY_SPANS_URL`), `reaper.py:43`, `group-manager.py:66`, `task-watchdog.py:31`; `apps/raphael/**` | no | yes | `ghcr…/any-concurrency:latest` 209 MB | 91–94 MiB |
| 13 | `machine` | 2 service | `host-metrics` | **nobody** | **no installed caller.** `console/app.py:777` is a *comment*; everything else is `apps/raphael/**` (in no state file) and the raphael agent preset inside `bina-ds` | **no** (disabled) | yes | `ghcr…/machine:latest` 184 MB | 262.8 MiB (×3 reads) |
| 14 | `data-management` | 2 service, `system` | `data-management` | **nobody** | `app-management/app.py:972` `DATA_URL` → `_data_job()` (the app-move / export path); `apps/raphael/**` | no | yes | `ghcr…/data-management:latest` 405 MB | 38–54 MiB |
| 15 | `autoheal` | 1 service, `system` | **none** | **nobody** (it has no capability to declare) | **6 live containers by label** — `platform-base/n8n/docker-compose.yml:547,799,882,1107,1142` + `apps/project-pln/docker-compose.yml:128`; `autoheal.py:128` posts to `notifications` | no | yes | `deployment-hacohen-autoheal` 127 MB | 7.6 MiB |

Verified independently: `docker ps`-inspect for the label finds exactly `n8n-worker-1-hp`,
`n8n-worker-2-hp`, `n8n-worker-1-runners-hp`, `n8n-worker-2-runners-hp`, `n8n-task-runners-hp`,
`project-pln-hp` — six containers, matching the manifest count of zero.

## 4. The classes, and the count in each

**Strictly required in layer 0/1 — 6.**
`traefik`, `authentik`, `connections`, `console`, `app-management`, `bina-ui`.
Each is either the compiler/host contract itself or the thing a *role* resolves to at boot. Four of
the six (`traefik`, `console`, `app-management`, and `connections`' second capability) provide a
capability **that no manifest anywhere declares** — their necessity is real and entirely
inexpressible in the graph. `app-management` is not even marked `system: true`.

**Required as a provider — 8.**
`postgres` (named app: `drive`), `redis` (`any-concurrency`), `n8n` (`drive`, `indox`, `mail`,
`chat`), `notifications` (weak declarations only, but called by `bina-ds`, `domains`, `sites`),
`glitchtip` (`n8n`, `notifications` — neither is installed here), `any-concurrency` (`browser42`),
`data-management` (`app-management`), `autoheal` (six containers by label).
Three of these eight — `any-concurrency`, `data-management`, `autoheal` — have a live consumer that
**declares nothing at all**, and `notifications` has a fourth: `bina-ds`, enabled on both offices,
posts into it from inside its own image while declaring only `secrets` and `computers`. That is §5.

**Removable — 1.**
`machine`. Nothing declares `host-metrics`; nothing that is installed calls it. See §6.

15 = 6 + 8 + 1. Nothing in the tree is a pure orphan: every other row has a caller, declared or not.

## 5. The trap this item exists to catch — four capabilities, no declarations

The measured shape, in the order of how much it matters:

1. **`any-concurrency` / `concurrency-metrics`.** `apps/browser42/app.json` has `"use": []`, and
   `apps/browser42/docker-compose.yml:168,200,245` hands three of its services
   `ANY_CONCURRENCY_SPANS_URL: http://any-concurrency:8080/ingest/span`, with `reaper.py:43`,
   `group-manager.py:66` and `task-watchdog.py:31` each defaulting to the same URL. **Five call
   sites, zero declarations.** `reconcile.py services --for <live set minus any-concurrency>` drops
   it and pulls nothing back — browser42 simply starts posting into a DNS name that is not there,
   and every span push fails silently inside a container nobody watches.
2. **`data-management`.** `platform-base/app-management/app.py:972` binds `DATA_URL` and
   `_data_job()` drives export/pull/import through it; `app-management/app.json:21` is `"use": []`
   and it is the *control plane*. The failure mode is graceful but wrong-shaped: the code already
   has a paragraph for "this office's data-management did not answer … and has to be switched on",
   which is how a missing capability becomes a user-facing apology instead of a resolved dependency.
3. **`autoheal`.** Its interface is a **docker label**, not a capability — `binaos.autoheal=true` on
   five n8n services and on `project-pln`. Nothing in the graph can see it, nothing validates it, and
   a typo in one of those six lines turns a self-healing container into a silently unhealed one. This
   is the strongest case for *not* counting it under "removable": it has six consumers.
4. **`notifications`.** Eight declarers, all `wants`/weak, so it is never pulled in. And a ninth
   consumer that declares nothing at all: **`bina-ds` is enabled on both offices and posts into the
   notification centre from inside its own image** — `harness/entrypoint.sh:113`, `pulse.sh:36`,
   `self-update.sh:80`, each ending in `|| true` so a failed post is invisible — while
   `apps/bina-ds/app.json` declares only `secrets` and `computers`.

The same gap, from the other end: `apps/raphael/app.json` declares `workflow` and `notify`, and its
five workflows call `machine:8080`, `any-concurrency:8080`, `data-management:8080` and
`notifications:8977` — three of them undeclared. **Raphael is in no state file on either office**, so
those three callers do not count as live anywhere today; that is the whole of §6's case, and it is
also why the raphael plan is the thing that could change this audit's answer overnight.

**And one declaration that points the wrong way.** `platform-base/any-concurrency/app.json` declares
`use: [{capability: "sql", strength: "requires"}]` — no `own_instance` — which is what pulls the
platform `postgres` app (`db`) into the closure whenever `any-concurrency` is enabled
(`reconcile.py services --for any-concurrency` → `db redis any-concurrency`). Its own compose then
connects to somebody else's server:

```
platform-base/any-concurrency/docker-compose.yml:32   PG_HOST=n8n-postgres
platform-base/any-concurrency/app.json  "sql": [{ "instance": "n8n-postgres", "database": "n8n" }]
```

So this app asserts a dependency on the platform database, starts it, and talks to n8n's. Its `kv`
declaration, by contrast, is honest — `REDIS_URL=…@redis:6379/0`
(`platform-base/any-concurrency/docker-compose.yml:37`) and `data.kv` names instance `redis`, db 0.
One of the two is a real edge and one is a decoy, in the same manifest.

## 6. The one removable candidate, and its smallest safe action

### `machine`

**Evidence it is removable.**
* `reconcile.py required-by --app machine` → `[]`; `services --for <live set minus machine>` → gone,
  no pull-in line. It is a root in the graph, held up by one `enabled:` line.
* The only non-doc references to `machine:8080` anywhere in tracked code are
  `apps/raphael/blueprint/n8n/{raphaelMachine,raphaelContainers,raphaelPulse}00001.workflow.ts`, the
  `raphael` agent preset shipped in `bina-ds`, and `platform-base/console/app.py:777` — which is a
  **comment** using the string as an example of an app-absolute redirect.
* It costs 184 MB of image and **262.8 MiB resident** — more than `traefik` + `console` +
  `connections` + `app-management` added together (67 + 44 + 42.5 + 50 ≈ 204 MiB), for a service
  nothing installed talks to.

**Smallest safe action.** One state line — `machine: { state: disabled, by: <who> }`, i.e.
`./bbox apps disable machine` — and **not** deleting the directory. In the committed file `machine`
is *already* `{ state: disabled, by: user }`, so this is a change to this office, not to the default.

**What breaks if you are wrong.**
* `machine.localhost` 404s at the edge and its tile leaves the console. Containers keep running
  correctly; the office stays healthy.
* `platform-base/authentik/blueprints/deployment-apps.yaml` names `machine` **twice** by hand
  (`provider-machine` at :41 and `provider-machine-local` at :147) and calls it the
  `-local`-routers CANARY (:145). That file is committed, not generated — `reconcile.py:1031`
  (`COMMITTED_AUTHENTIK_BP`) only *reads* it. So the SSO application and provider stay behind for a
  host with no container: harmless, and visually a stale entry in authentik's app list.
* `reconcile.py:1034 committed_sso_estate()` harvests `MACHINE_BASE_URL` out of that file, and the
  README (`platform-base/authentik/README.md:62`) lists machine among "the base estate … console,
  connections, machine, traefik, apps, any-concurrency". Two hand-written declarations of machine's
  host live outside machine's manifest; disabling the app does not remove them.
* **Raphael.** The owner asked for exactly this service, in his own words, in
  `apps/project-pln/plans/office.yaml:4713`: *"machines — CPU, RAM, networks … scanned continuously;
  Raphael goes over the scans"*. `bbox raphael` does not exist yet (`grep raphael bbox` → nothing)
  and `apps/raphael` is in no state file, so today the demand is a plan, not a caller. **If the
  Raphael work lands before someone re-reads this file, `machine` is a provider with a consumer and
  not removable.** Disabling it is reversible in one line; deleting it is not what this item is for.

## 7. Deliberately left alone, and why

* **`platform-base/forward-auth/`** — the Go replacement for authentik, landed 2026-10-09 as a
  proposal (`c20c25ef`). It is not an app: no manifest, no compose service, no verb. Deleting it as
  "nothing calls it" would delete the answer to this table's most expensive row (**authentik: 1.08 GB
  of image across three services, plus a 294 MB postgres, ~590 MiB resident** — the single largest
  item in layer 1 by every measure). It stays until its own item decides.
* **`authentik` itself.** It is the one component whose replacement is already written and tested;
  removing *it* is a migration with a rollback per step (`ai/context/core-go-forward-auth.md`), not a
  pruning.
* **`bina-ui`.** `kind: library`, `compose: null`, 0 MB resident, 1.1 MB of source. It is the palette
  and component source every screen is stamped from (`scripts/refactor/theme-token-lint.py:33`,
  gate G27/G82) and eight vendored copies are built from it. "No container" is not "not required".
* **The `system: true` flag is not a mechanism.** It appears on eight manifests (authentik, autoheal,
  connections, console, data-management, postgres, redis, traefik) and is read in exactly **one**
  place in the tree: `scripts/refactor/registry-drift-lint.py:97`, gate G8, which requires a login row
  in `platform-base/connections/providers/` to belong to an app that can never be switched off.
  `reconcile.py` never mentions it (`grep -n system platform/manager/reconcile.py` → three
  occurrences, all prose in comments), and neither does the console or the control plane. So
  "cannot be disabled" is documentation: `reconcile.py set-state --app traefik --state disabled`
  would be accepted. That is a finding of its own and it is left as such — this item audits, it does
  not tighten.
* **`own_instance: true` is not a mechanism either, and that is why §5's decoy survives.** It is
  declared by `authentik`, `n8n`, `glitchtip` and `project-pln`, validated by
  `platform/schema/app.schema.json`, and read by **one** file:
  `scripts/refactor/capability-use-lint.py:295` (gate G25), which uses it to excuse an app that runs
  its own server. `grep -rn own_instance platform/manager/*.py` → **no output**: the resolver never
  sees the flag, so an app saying "I run my own" still has the platform's provider pulled into the
  closure and started for it. G25's own docstring describes exactly this class ("the resolver duly
  pulled the `postgres` app into the closure and started it first. Then all three connected to a
  Postgres of their own") — the gate was written to make the *declaration* honest, and it did; the
  pull-in it describes is still there.
* **`n8n`.** Layer 2 by its manifest, provider of `workflow` to six apps, and the engine the whole
  automation estate runs on. Its absence from the committed default is a product decision recorded in
  `platform.state.yaml:63-67`, not an audit finding.

## 8. The ordered plan — small, reversible, each step with its proof

Nothing here is executed by this item. Each step is one change with one command that proves it.

**S1 — declare the four capabilities whose consumers are code, not manifests.**
Add `use: [{capability: "concurrency-metrics", strength: "requires"}]` to `apps/browser42/app.json`,
`use: [{capability: "data-management", strength: "wants"}]` to
`platform-base/app-management/app.json`, `use: [{capability: "notify", strength: "wants",
dependency: "weak"}]` to `apps/bina-ds/app.json`, and — for `autoheal` — whatever S2 settles on.
*Prove:* `reconcile.py validate` → OK; `reconcile.py services --for browser42` now lists
`any-concurrency`; the compiled service set is otherwise identical in both states (both consumer and
provider are already enabled there), and the one new ordering constraint — provider before consumer —
is already satisfied today.
*If wrong:* a `requires` edge on an app that is enabled while its provider is not will pull the
provider in — that is the intent, and it is why the second one is `wants`, not `requires`, for a
surface that already degrades gracefully.

**S2 — give `autoheal` an interface that can be checked.** It needs a capability
(`self-heal`) declared by the six containers it watches, or a gate that asserts every
`binaos.autoheal=true` label names a container whose app actually provides it.
*Prove:* the new gate is red on a fixture with a typo and green on the tree.
*If wrong:* today's behaviour is unchanged; a label with no provider is currently indistinguishable
from a label with one.

**S3 — teach the resolver what `own_instance` already means.** `authentik`, `n8n` and `glitchtip` all
declare `use: [sql]` **with `own_instance: true`** and then connect to their own servers
(`AUTHENTIK_POSTGRESQL__HOST`, `DB_POSTGRESDB_HOST`, glitchtip's own valkey). This is the exact defect
`scripts/refactor/capability-use-lint.py` (G25) was written about, and it is still live: it is what
puts `db` — 1.96 GB of image — into the *committed default* boot for a server nothing connects to
(`bbox`'s own `pg_stat_activity` check on the running office shows the only clients behind the
platform postgres are `supabase-rest` and `supabase-storage`, i.e. drive's `object-storage`
dependency, not an app's data path).
The flag is not broken — **the resolver has never read it** (`grep -rn own_instance
platform/manager/*.py` → no output; it is read by G25 and nothing else). So the change is: make the
resolver skip the provider for a `use` entry that carries `own_instance: true`, with a case in
`platform/manager/test_resolve.py`.
*Prove:* `reconcile.py services --for authentik` no longer lists `db`;
`python3 platform/manager/test_resolve.py` (G17) passes with the new case;
`capability-use-lint.py` (G25) still green.
*If wrong:* an app that names `own_instance` but secretly talks to the shared server loses it —
`grep` already shows the three that do this all name their own host in compose.
The mirror of the same defect is `any-concurrency` (§5): it declares `sql` **without** `own_instance`
and connects to `n8n-postgres`. Same edit, opposite flag.

**S4 — `redis` in the default.** With S3 done, re-run `reconcile.py services`. In the committed
default `redis` is in the closure with **no pull-in line of any kind** and
`required-by --app redis` → `[]`. The only real consumer is `any-concurrency`. This is a state
question, not a code question: either the app that wants `kv` is installed, or the line says so.
*Prove:* `reconcile.py services` names redis only when a `kv` consumer is enabled.
*If wrong:* a new app that needs `kv` gets it the moment it declares it; nothing today is broken by
redis being absent because nothing today talks to it (its keyspace could not be read here — `redis-cli
INFO keyspace` → `NOAUTH`, and the vault credential is the app's, not this audit's).

**S5 — `machine`.** Only after S1–S4 and only with the owner's Raphael decision:
`./bbox apps disable machine`.
*Prove:* `bbox status` green, no `machine-*` container, the console tile gone, and
`reconcile.py services` unchanged for every other app.
*If wrong:* reverse with one line. What stays behind is described in §6.

**The `system: true` flag** gets its own item (a refusal in `set-state`, or the flag deleted and its
one reader rewritten). It is named here so it cannot be forgotten; it is not part of a removal plan.

## 9. What could not be measured here

* **`glitchtip`** — not running on this office; no resident figure. Image size is a real `docker
  image ls` row (728 MB ×3 services), memory is "not running here".
* **`redis` key count and live clients** — `NOAUTH`; its consumer is known from code
  (`any-concurrency/docker-compose.yml:37`) but not from the server.
* **`bina-ui`** — no image, no container, hence 0 MB resident by construction; its cost is 1.1 MB of
  source and eight generated copies.
* **The two state files disagree** and the live one was being edited while this ran: the running
  office has `supabase` declared `disabled` with six of its containers up (it is pulled in as
  provider of `object-storage` for `drive`), and `n8n` declared `disabled` with all seven of its
  containers up. Every live figure above is a snapshot taken 2026-10-09 13:10 UTC, not a stable
  property of the file.
* **`machine`'s first memory read was 586.5 MiB** and three later reads agreed on 262.8 MiB. The
  three-read figure is the one used; the outlier is named rather than hidden.

**One red met on the way, pre-existing and not this item's.** G0 (`paths-exist.py`) was run against
the office's own render to check that nothing here rests on a broken compose:

```
$ cd /mnt/c/…/MyDGO && ./scripts/dc config > /tmp/candidate.yml && \
  python3 scripts/refactor/paths-exist.py /tmp/candidate.yml
G0 FAIL — 9 referenced host path(s) do not exist (docker would silently create empty dirs):
  any-concurrency          bind           /run/bbox-docker.sock
  app-management           bind           /run/bbox-docker.sock
  autoheal                 bind           /run/bbox-docker.sock
  bina-ds                  bind           /run/bbox-docker.sock
  connections              bind           /run/bbox-docker.sock
  data-management          bind           /run/bbox-docker.sock
  data-management          bind           /var/backups/bbox
  machine                  bind           /run/bbox-docker.sock
  traefik-deployment       bind           /run/bbox-docker.sock
  [exit 1]
```

Neither path exists on this host (`ls -ld /run/bbox-docker.sock /var/backups/bbox` → *No such file or
directory*), and the render is this office's, not this worktree's. It is recorded here because it was
measured, and because eight of the nine rows are **the engine socket** — i.e. the same
`bind`-mounted-socket surface this audit's "strictly required" rows depend on. It is not caused by
anything in this document and it is not fixed by it; it needs its own item.
