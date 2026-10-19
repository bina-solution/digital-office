# project-pln — Plane, self-hosted, trimmed to fit the office

The office's project and task manager. Upstream is **Plane Community Edition**
([makeplane/plane](https://github.com/makeplane/plane), **AGPL-3.0-only**) — the same product the
owner already uses on Plane Cloud, run here, on our own database, with no subscription.

The full research behind every decision in this directory (what is mandatory, what the real floor
is, why Hebrew is the expensive part, how the cloud data comes across) is
[`ai/context/plane-selfhost-research.md`](../../ai/context/plane-selfhost-research.md).

## The shape, and why it is this shape

Four containers (RabbitMQ was the fifth until `patches/redis-broker.py`: 14% of a core at idle):

| service | what it is | why it is not optional |
|---|---|---|
| `project-pln` | the upstream **All-In-One** image (web + admin + api + worker + Caddy under supervisord), trimmed to four programs by `Dockerfile` | one container instead of eight; the only shape that fits a 5 GiB engine |
| `plane-db` | `postgres:15.7-alpine` | Plane requires 15.7+ and assumes `max_connections=1000`; it must not share the platform's 100-connection server |
| `plane-minio` | `pgsty/minio` (the image Plane's own CE release ships) | every attachment is an S3 object: `STORAGES["default"]` is `S3Storage` unconditionally, so **no filesystem backend exists** |
| `plane-redis` | `valkey/valkey:7.2.11-alpine` | cache, sessions, Celery results — and Celery's BROKER: upstream assigns `CELERY_BROKER_URL` from `AMQP_URL` and reads nothing else, so `patches/redis-broker.py` adds the one line it lacks (`= REDIS_URL` when `AMQP_URL` is unset) |

Three files change upstream's AIO image, and each change is a bug we would otherwise inherit:

1. **`supervisor.conf`** — four programs instead of eight. `space` (public sharing), `live` (realtime
   cursors) and `beat` (a third full Django process, for scheduled jobs) are ~400 MB of the stack.
   `space` and `live` are features this deployment does not use; their Caddy routes stay, so they
   answer 502 rather than silently serving index.html to a JSON request. `beat`'s **jobs** are kept
   without its process: the one worker runs the scheduler (`patches/worker-scheduler.py`, Celery's
   `-B`). Until 2026-10-07 none of Plane's twelve periodic jobs ran here — nothing was hard-deleted,
   no auto-archive or auto-close was applied, no log was pruned — and `api_activity_logs`, which
   keeps the full response of every API-key request, grew about 200 MB a day under the office's own
   task CLI. Its retention is `PLANE_API_LOG_RETENTION_DAYS` (default 3; upstream's is 14), and
   `patches/api-log-reads.py` stops it storing a READ's answer: 94% of its rows were GETs carrying
   81 KB each — a second copy of data Plane already holds, which nothing reads back. A write's
   answer is kept (it is what the request changed); a read's row still says who asked for what and
   what code came back.
2. **`Caddyfile`** — upstream's AIO Caddyfile is the external-S3 variant and has **no `/uploads`
   route**. With on-box MinIO, `USE_MINIO=1` makes both the public file URL and the presigned POST
   host derive from the request, i.e. the browser talks to this host; without the route every upload
   and avatar 404s while the API reports success.
3. **`entrypoint.sh`** — upstream's `start.sh` validates `DOMAIN_NAME` as a bare FQDN, so it
   **rejects `plane.localhost:8080`** (the edge on macOS is :8080, not :80) and exits 1; it also
   rewrites `WEB_URL` on every boot. Ours writes `plane.env` from the environment and keeps the two
   Django secrets on the data volume instead of regenerating them.

## Reachability

`module.embed: false` and a dedicated host — Plane cannot be served under a subpath (root-absolute
paths, static SPA with `VITE_*` baked at build time, upstream bug #8168). On this machine:
**http://plane.localhost:8080**. It is `auth: "none"` because Plane CE has no OIDC: edge SSO would
add a second login in front of Plane's own. Log in with email + password
(`ENABLE_EMAIL_PASSWORD=1`), so no SMTP is needed on a first boot.

## Configuration

`.env` (local) / `.env.ex` (template):

```
PROJECT_PLN_BASE_URL=plane.localhost:8080      # exactly what the browser types, port included
PROJECT_PLN_PROTOCOL=http                      # https in production
```

The two must agree with reality or logins redirect to the wrong origin and the API answers CORS
errors. Optional: `PLANE_DB_PASSWORD`, `PLANE_MQ_PASSWORD`, `PLANE_S3_ACCESS_KEY`,
`PLANE_S3_SECRET_KEY`, `PLANE_FILE_SIZE_LIMIT` (default 50 MB), `PLANE_API_KEY_RATE_LIMIT`.

### Secrets — three required, no defaults

`PLANE_DB_PASSWORD`, `PLANE_MQ_PASSWORD` and `PLANE_S3_SECRET_KEY` are **required** (`:?` in the
compose): the shipped defaults used to be the word `plane`, which is a database password anyone can
guess and never notices. `scripts/ci-env.sh` mints them on a fresh machine, and they were rotated on
this deployment on 2026-09-29 **while the instance held no data**:

* postgres — `ALTER USER plane` through `psql -f -` (never an argument, so the value is not in `ps`);
  verified by connecting over TCP from another container, where the OLD password is refused with
  `password authentication failed`. Note the image's `pg_hba.conf` trusts `local`/loopback, so a
  check run *inside* the container proves nothing — the app's path is TCP;
* rabbitmq (the broker at the time; gone since) — its volume was transient by design, so it was
  removed and re-initialised from the new environment;
* minio — root credentials are read from the environment on every start, so a restart is enough.

### Telemetry — off, and off means off

`PLANE_TELEMETRY` defaults to `0`, and `patches/no-phone-home.py` (run at image build) requires it
to be `1` at BOTH call sites that talk outward: the OpenTelemetry metrics push to
`telemetry.plane.so` and the GitHub release check. It also flips Plane's own defaults — the model's
`is_telemetry_enabled` and the god-mode form's — so a fresh instance reads `false`.

The environment gate is the layer that matters: a database flag, a restored archive or a god-mode
toggle cannot re-enable it. The cost is that the god-mode telemetry switch is inert unless the
operator sets `PLANE_TELEMETRY=1`; that is deliberate and is written down here rather than left as a
surprise. Verified: the worker logs `Telemetry is off for this deployment (PLANE_TELEMETRY != 1),
skipping metrics push` on every boot, and the container holds **zero** connections to port 443.

**Do not confuse it with `PLANE_BASE_URL`**, which already existed in `.env.ex` for the office's
LibreChat/Plane-MCP integration: that one is Plane **Cloud's** API root (`https://api.plane.so`),
this one is the origin of the **self-hosted** instance. Renaming one into the other is not a
theoretical hazard — it happened while building this app, and the symptom was an instance whose
`WEB_URL` read `https://https://api.plane.so` and whose `CORS_ALLOWED_ORIGINS` Django rejected with
`corsheaders.E014`. Both names now carry a comment saying which is which.


## First run — declared, not clicked

A fresh instance **refuses to sign anyone in** until it is configured. Every auth view checks
`Instance.is_setup_done` and redirects with `INSTANCE_NOT_CONFIGURED`; measured:

```
POST /auth/sign-in/  →  302  …/?error_code=5000&error_message=INSTANCE_NOT_CONFIGURED
```

In upstream Plane the only writer of that flag is the **instance-admin sign-up in god-mode**
(`plane/license/api/views/admin.py` → `POST /api/instances/admins/sign-up/`, which also creates an
`InstanceAdmin`) and the workspace/project that follow are created by hand in the UI. On this platform
that is a missing declaration, so it is declared like every other app's bring-up — `bootstrap.yaml`
(the state) + `bootstrap.py` (an applier that runs in `manage.py shell`) + `hooks/onboard` (the driver,
called by `bbox run` and by `./bbox project-pln onboard`). Nothing is clicked, and `hooks/verify`
asserts the result: the API answers, the declared state is in the database, and the owner can sign in.

The owner's login comes from `.env`:

```
PLANE_OWNER_EMAIL      the login. Empty → N8N_OWNER_EMAIL (the same human as everywhere else here).
PLANE_OWNER_PASSWORD   the password. Empty → minted into .env by hooks/onboard on first use.
```

`hooks/onboard` never prints the password: it says which file to read it from. A fresh machine gets
both from `scripts/ci-env.sh`.

**The declared password wins.** `onboard` sets it on the owner's account — including one that already
exists — and stores it, with the email and the origin, as the connection instance
`plane_local_admin-local` in the credential plane, beside the office's own API key
(`plane_local_api_token-local`, minted once and reused). Both are read from the console's
**חיבורים ומפתחות → חשבונות Plane**, audit-logged, one field at a time: Plane is the one app here with
no office-written UI of its own, so that screen is where its password lives. The visible consequence,
stated plainly: a password changed **inside** Plane is reverted by the next bring-up — change it in
`.env` instead (`./bbox run`, or `./bbox project-pln onboard`), which is also the recovery path.

The bootstrap otherwise only ever acts on a fresh instance — an instance that already has an
administrator under a DIFFERENT address is left completely alone (the hook says so and exits 0). The
deliberate exception is a one-off hand-over:

```bash
PLANE_OWNER_EMAIL=<the person's address> PLANE_OWNER_TAKE_OVER=1 ./bbox project-pln onboard
```

Without that second flag the hook refuses, because releasing an administrator is not a decision a
bring-up may reach on its own. With it, the previous admin row is **soft**-deleted (named in the
output; running again with its address puts it back) and the named person becomes the instance
administrator and the owner of the declared workspace.

### `/god-mode/` — English on purpose, and documented rather than hidden  (DGO-15)

**Owner's decision (2026-09-30):** keep the instance-admin screen where it is and write it down,
instead of routing it away from the edge.

It is not ours to translate. Upstream serves it as a **separate static build** at `/app/admin`
(measured in this image: `index.html` carries `lang="en"`, and the bundle contains no Hebrew and no
`dir="rtl"`) — that build is not routed through the SPA's i18n layer and does not read the office's
`plane-he` bundle, so the Hebrew work in this app cannot reach it. Two ways to react to that, and
both are honest: proxy the path away, or say plainly what it is. We do the second, because the
screen is genuinely useful (instance-wide settings, the telemetry switch, user administration) and a
hidden-but-working door is worse than a documented English one.

What makes that safe is the **edge, not the screen**: the whole `plane.<domain>` host is `auth: sso`
in `app.json`, so `/god-mode/` is behind the office SSO like the rest of the app — an unauthenticated
visitor gets the authentik redirect, never the admin form. The daily product does not depend on this
screen at all: workspaces, projects, states and labels are declared in `bootstrap.yaml` and applied
by `bootstrap.py`, and the office reads and moves work items through `bbox project-pln tasks`.

To reach it: sign in to the office first, then open the app's own host and add `/god-mode/`. To
verify the claim about the build:
`docker exec project-pln-local grep -o 'lang="en"' /app/admin/index.html`.


## Working the items from the CLI — `bbox project-pln tasks`  (DGO-8)

`plan` writes a plan INTO Plane; `tasks` reads and moves the result. It is the one implementation:
the owner's `bbox agent tasks` and this agent's `plane-tasks` skill call the same verb, so "my tasks"
means the same thing in both places.

```bash
./bbox project-pln tasks list --project DGO --mine --as azaria
./bbox project-pln tasks list --project DGO --state unstarted --json
./bbox project-pln tasks show DGO-12
./bbox project-pln tasks start DGO-12
./bbox project-pln tasks done  DGO-12 --comment "what was done, where, the proof"
./bbox project-pln tasks comment DGO-12 "…"      # or: take, to assign it to me
./bbox project-pln tasks attach DGO-12 mockup.png notes.pdf   # a request's files, on its item
```

- **`attach`** puts files on an item the way Plane's own screen does — Plane signs an upload form for
  each, the file goes to the object store through it, and the item is told it arrived — so it works
  from any office, also one that reaches Plane behind the link. `show` lists the files the store
  confirmed (`files`). A request of the owner is a work item FIRST, with every file he sent on it
  and its link in the answer (AGENTS.md, the owner's standing rule 10).

- **`--as <slug>`** acts with that office agent's own account: the token comes from the vault instance
  `plane_local_api_token-<slug>` (the same instance `plan` uses to resolve a name to a member), never
  from an argument or a file. Without it, the office's own key (`plane_local_api_token-local`) is used.
- A **ref names its project** (`DGO-12` is in `DGO`), so a verb that takes one item never needs
  `--project`; only `list` does.
- **The JSON contract is stable** (`--json`), and it is what other tools should parse:

  ```json
  {"tasks": [{"ref": "DGO-12", "id": "…", "project": "DGO", "name": "…", "state": "לביצוע",
              "group": "unstarted", "priority": "high", "labels": ["שער"], "assignees": ["עזריה"],
              "module": "שלב 1 · …", "url": "…", "updated_at": "…"}]}
  ```

  Mutating verbs answer `{"ok": true, "ref": …, "id": …, "state": …, "group": …, "url": …}` with
  `--json`, and one human line without it. `group` is the portable half of a state (`unstarted`,
  `started`, `completed`) — the Hebrew name is the owner's to change, the group is not.
- **429 is waited out**, never failed: Plane's key is limited to 60 requests/minute.

## The Hebrew interface

Plane ships **19 locales and none of them is Hebrew**, and upstream has **no RTL support at all**
(`<html lang="en">` hardcoded, `setLanguage()` never sets `dir`, zero `rtl:` Tailwind variants, no
logical-property utilities). So the Hebrew UI is a patch, not a setting — and because the SPA ships
as a prebuilt static bundle, it cannot be added at runtime:

1. **[solomonBoltin/plane-he](https://github.com/solomonBoltin/plane-he)** (public, AGPL — the
   licence requires the source be offered, which is why it is not private): 3,837 strings across the
   28 namespaces in `locales/he/`, plus whole-file overrides of the six upstream sources that make
   direction a property of the language (`TLanguage`, `SUPPORTED_LANGUAGES` + `RTL_LANGUAGES` +
   `getLanguageDirection()`, `setLanguage()`, the i18n instance that applies `lang`/`dir` before the
   first React render, and the app shell `root.tsx`, which must render `dir` itself — React owns
   `<html>` and its hardcoded `lang="en"` otherwise drops the attribute on the next render).
   `tools/check-parity.py` enforces key, placeholder and ICU-plural parity against upstream English.
2. **A GitHub Actions workflow in that repo** builds `apps/web/Dockerfile.web` on a native arm64
   runner (the office is Apple Silicon; QEMU emulation of this monorepo is hours) and publishes the
   built SPA as a **release asset** — public, anonymous, no registry login — plus the image on GHCR.
3. **This app** consumes the release asset: set `PLANE_HE_WEB_URL` and `PLANE_HE_WEB_SHA256` and the
   Dockerfile verifies the checksum and replaces `/app/web`. With both empty, a fresh clone serves
   upstream's English build. Nothing else in this directory changes.

### What the Hebrew build now includes (2026-09-29)

* **A Hebrew typeface**, shipped with the app: Noto Sans Hebrew (variable, 12 KB, Hebrew subset,
  `unicode-range` scoped so it is only fetched when the page has Hebrew), placed after Inter in
  `--font-heading`/`--font-body`. Inter has no Hebrew glyphs, so before this the Hebrew face was
  whatever the platform happened to have — different on macOS, Windows and Linux, and tofu on a bare
  Linux. Verified in the browser: `getComputedStyle(body).fontFamily` lists the Hebrew family and
  `document.fonts.check('16px "Noto Sans Hebrew Bina"')` is true.
* **Timezone default = Asia/Jerusalem** on all four model fields (`Workspace`, `Project`, `Cycle`,
  `User.user_timezone`), via `patches/hebrew-defaults.py`. Verified: a workspace created after the
  patch is born with `Asia/Jerusalem`.
* **Date LANGUAGE**: the date-fns helpers in `@plane/utils/datetime.ts` are wrapped to use the
  Hebrew locale (English for a user who chose English). **Not fixed**: the home widget's date line
  is formatted by **luxon**, whose locale comes from `Settings.defaultLocale` — luxon is not a
  declared dependency of any workspace package (it arrives transitively and pnpm runs with
  `node-linker = isolated`), so no file this patch overrides may import it, and adding it needs a
  lockfile change that the build's `--frozen-lockfile` forbids. It still renders as
  `Tuesday, Sep 29 13:53`. The fix is one line in a package that declares luxon, plus that lockfile
  change — a follow-up with its own build, not a half-patch here.

Known gaps, deliberately not "fixed" by pretending they are done:

* **Some screens are hardcoded English upstream** and can only change by overriding the
  component that renders them (a whole-file override each): the welcome modal
  (`We're glad that you decided…`, `Take a Product Tour`), the nav's `Projects` and `More`,
  `Community`, and the command bar's `Search commands…` placeholder. Measured one by one: — the welcome modal, the profile-completion step
  and the instance-setup page have **no i18n key at all** (checked: `We're glad that you decided…`,
  `Take a Product Tour`, `Create your profile` appear in no locale file), so no translation can
  reach them. Measured rather than assumed, because "the patch missed it" and "upstream never
  internationalised it" look identical on screen and only the second is true here.
* **Layout utilities that are physical rather than logical** (`ml-*`, `text-left`, directional
  icons) still do not mirror on some screens — `dir="rtl"` moves the document, not every hand-placed
  element.
* **`/god-mode/` is English and LTR**: it is a separate static build at `/app/admin` that upstream
  never wired to i18n. Administrator-only.
* **The font stack has no Hebrew face** (Inter has no Hebrew glyphs), so Hebrew falls back to a
  system font — it renders, it is just not a chosen typeface yet.



## Data from Plane Cloud

No official cloud → self-hosted migration exists (upstream issue
[#1070](https://github.com/makeplane/plane/issues/1070), closed), and the built-in importers are
Cloud/Commercial-only, so this side of it is ours:

```bash
# 1. two single-use tokens, both in .env:
#    PLANE_CLOUD_API_TOKEN  — Plane Cloud → Profile settings → Personal access tokens (plane_api_…)
#    PLANE_LOCAL_API_TOKEN  — the same screen on THIS instance (http://plane.localhost:8080)
#    plus PLANE_CLOUD_WORKSPACE and PLANE_LOCAL_WORKSPACE (the workspace slugs)
# 2. STEP ONE — creates any missing LOCAL project (empty) and writes a plan per project. It reads
#    the cloud and writes nothing else:
./bbox project-pln import-cloud
# 3. review apps/project-pln/import-plans/<KEY>-plan.yaml (the unmatched-member list is the part a
#    human has to fill in — cloud emails rarely match the local ones), then:
# 4. STEP TWO — moves the work items in, using that plan. It REFUSES if no plan exists.
./bbox project-pln import-cloud --apply
```

`hooks/import-cloud` drives **[`plane-migrate`](https://pypi.org/project/plane-migrate/)** (PyPI,
third-party) once per project: work-item types, states by name, labels, members by email, estimates,
work items with relations, links and comments, modules, cycles, intake and pages. It is resumable —
a re-run continues rather than duplicating.

**Verified end to end against this instance (not against the cloud, which needs the owner's token).**
Run with the source and destination BOTH pointed at this deployment — one workspace holding a
project with two work items, an empty workspace as the destination — the hook read both project
lists, created the missing destination project **through the API**, and the migration reported
`Created: 2, Failed: 0`; the destination then really held the project with its two work items, and a
second run matched it by identifier and offered to continue. Four real failures were found and fixed
by doing that rather than by reading the code:

* `docker run -e SRC_TOKEN` copies the value from the **docker CLI's own environment**, so an
  unexported shell variable arrives empty and plane-migrate answers "Missing required: --src-token";
* under `set -u`, `${#A[@]}` on a **declared-but-empty associative array** is an "unbound variable"
  error in bash 5.2 — and an empty destination is exactly how every real import starts;
* `--src-project` needs the project **UUID**: passing its identifier answers `404`, which the tool
  reports as "Cannot access source project", i.e. it looks like permissions;
* project lists are **cursor-paginated**, so a workspace with more than one page would have been
  migrated silently half-way.

Known limits, stated rather than discovered later: **attachments do not come across** (they live in
the cloud's object-storage bucket, and file URLs embed that bucket and endpoint — a complete move
needs the bucket too), and neither does anything the workspace export does not cover. The export
path (Workspace settings → Exports, CSV/XLSX/JSON, work items only) remains the fallback if the
migration tool and this instance disagree about a field. One more, from the API itself: a token whose
user is a workspace member but has **no `ProjectMember` row** gets **403 on every project-scoped
endpoint** — the migration then fails per project with that "cannot access" message, and the fix is
to add the user to the project, not to reissue the token.


## Operating it

```bash
./bbox apps enable project-pln
./bbox project-pln onboard        # the declared first-run state (bbox run calls it too)
./bbox project-pln verify         # bootstrapped, not merely healthy
./scripts/dc up -d --build project-pln plane-db plane-redis plane-minio
./scripts/dc exec project-pln supervisorctl status         # migrator api worker proxy
./scripts/dc logs --tail 100 project-pln
docker inspect --format '{{.State.Health.Status}}' project-pln-local   # see the trap below
```

`./scripts/dc exec` takes the **service** name (`project-pln`); the container is `project-pln-local`,
so a bare `docker exec project-pln` reports "No such container" and looks like a dead app.

The app is **framed inside the console on a host of its own**, behind the office SSO
(`module.external: true`, `routing auth: sso`). The shell derives the address —
`plane.<the console's host>`, which on a `.localhost` office is one site with the console, so
Plane's own session cookie travels — and the compiler makes that host exist (a router, and an
identity record of its own). It is a host and not a path because the web bundle is a **root build**:
measured 2026-10-06 on the running instance, `basename: "/"` and every asset under `/assets/*`. A
rewriting proxy cannot carry that (a module specifier inside a script is not an attribute to
rewrite), which is the failure upstream reports as #8168.

A frame cannot show that host's sign-in (the identity provider is another site on `.localhost` and
refuses framing), so the shell ASKS first — `GET /.dgo/signed-in` on the app's host, answered by this
office's edge — and when the answer is "not signed in" it takes the browser there itself: a
top-level load of `/.dgo/enter/<the tile's route>`, which the edge answers with the office's sign-in
(nothing is asked while that sign-in is alive) and then with the console again, at that route. Once
a minute per host; a host that still asks gets a card whose one button, «כניסה», is the same trip.
The desktop's window does the same when it is opened, and only says so while it is already open.

**Plane's own sign-in answers on the host that was asked.** Every answer of a sign-in is a redirect
to `WEB_URL` — one configured origin — while the browser is on the host the office frames the app on
(here, or on a linked office's console). Left alone, the session cookie the answer sets stays behind
and the frame lands on a host of another site (measured 2026-10-06: the window of a person who had
just typed the right password was the browser's "refused to connect" page). The Caddyfile's `asked`
rewrites a `Location` of this app's own origin to the origin the edge in front says was asked
(`X-Forwarded-Proto`/`-Host`), or the request's own host when nothing stands in front; `verify`
asks it without credentials (`project-pln-origin`).

`/a/plane/*` still exists (one `passthrough` rule: the EDGE carries it with the prefix stripped): the
API answers there, the SPA does not. `module.url` is the INTERNAL base (`http://project-pln:80`) the
console's server uses, and is never handed to a browser — with `embed: false` the shell would hand
that string to the BROWSER, which answers *"לא ניתן היה למצוא את כתובת ה-IP של השרת של project-pln"*.

An install or enable from the apps screen starts containers but runs no app hooks — follow it with
`./bbox run` (or the `onboard` verb above), which is what makes the instance signable-into.

## An instance that moved in

A Plane that arrived from another office (the app's data moved; 2026-10-05, MacBook → hp-laptop)
brings its owner, his password, the agents and their keys **in its database**. The office it
arrived in knows none of it: its `.env` names whoever was declared there (on a fresh machine, the
CI placeholder), and its vault holds no key for this instance. Until it is adopted, `onboard`
refuses on every run and the office's own tooling (`plan`, `tasks`) has no key.

Adopting it is three steps, in this order:

1. `PLANE_OWNER_EMAIL` in `.env` = the administrator the instance already has (`onboard` names him
   in its refusal).
2. `./bbox run connections` — **the credential plane answers what `.env` said when ITS container
   was created**, and its answer outranks the hook's. Run `onboard` without this step and the
   bootstrap is told the OLD address.
3. `./bbox project-pln onboard`, then `./bbox project-pln verify`.

What the bootstrap guarantees on the way (each one was a hole, found the first time this was done):

* the "already has an administrator" guard judges the address the bootstrap will ACT for — the
  credential plane's when it names one — so a stale answer is refused, never applied;
* the owner keeps his own password: the one in `.env` is stored as his sign-in only when
  `check_password` says it is his;
* an agent is recognised by the label of its key, not by an address derived from this office's
  host, so the agent that came with the instance is not created a second time.

## Backups — the app now owns its own

`hooks/backup` exists so the owner's work is not snapshotted by the generic volume tar alone. Plane
runs its **own** PostgreSQL, and a raw tar of a live data directory is a hot copy: postgres usually
recovers one, which is exactly what makes the failure show up once, on the restore that matters. The
hook takes a logical `pg_dump -Fc` and reports the facts a restore is checked against — users,
workspaces, projects, work items, comments, and a hash of the attachment index (`file_assets`, which
is what Plane actually serves from). It deliberately does **not** claim `project_pln_minio`: that is
a plain file tree and the tar is the right tool for it, so the archive ends up carrying both the
dump and the volume.

Confirmed through the office's own inventory (`GET /api/inventory?refresh=true`): all six volumes
move from `covered (generic tar)` to `covered (hook)`, and `apps_with_hooks` goes 6 → 7. There is no
`hooks/restore` on purpose — the volume tar already brings the cluster back, and a second writer into
the same data directory would be two writers for one fact; the reasoning is written at the top of
the hook.

## Verified on this machine (2026-09-29)

| | |
|---|---|
| first `up` → healthy | **4 to 21 minutes, and the load decides which.** The migrator (~150 migrations) is a fixed cost, but the API entrypoint then walks ~100 `configure_instance` configuration keys one at a time and runs `collectstatic`; on a quiet engine that is minutes, and with the office busy it was measured at 21 minutes. The app is not hung — `docker exec … supervisorctl status` shows the step it is on (`manage.py create_bucket` is the last one before gunicorn binds) |
| footprint, all five containers | **~400–520 MiB** (app 273–345, mq 32–75, minio 67–78, db 11–18, redis 2–3) — against the 1.5–2.5 GB a stock 13-service install is documented to need |
| route | `Host: plane.localhost` through the office edge → 200; `/api/instances/` returns the instance config; `/auth/` 200 |
| the Hebrew UI, on screen | walked in the office's own Chromium (at the time through the welcome screen and god-mode, which the bootstrap has since replaced): `dir="rtl"`, `lang="he"`, and the sidebar, home page and project list all in Hebrew (`tmp/plancheck/workspace.png`) |
| Hebrew bundle installed | served shell is `<!DOCTYPE html><html lang="he" dir="rtl">`; 19 asset chunks carry the translation; the compiled i18n reads `localStorage.userLanguage \|\| "he"` with `RTL_LANGUAGES=["he","ar","fa","ur"]` |
| `plane-migrate` against this instance | dry run read the project, its states and its work items and reported `[dry-run] would create: …` — so the tool speaks to a self-hosted v1.4.2 API. Verified locally→locally with a throwaway workspace; the cloud side needs the owner's token |
| API writes need `ProjectMember` | a workspace member with no `ProjectMember` row gets **403 on every project-scoped endpoint** (work items, states, labels), and `plane-migrate` reports it as `Cannot access source project` |
| **the declarative bootstrap** | on a pristine instance (`users=0 workspaces=0 setup_done=false`), `./bbox project-pln onboard` created 11 rows and flipped `is_setup_done`; a second run created 0 and kept 11 (`bbox project-pln verify` green after both). The whole thing is `bootstrap.yaml` + `bootstrap.py` + `hooks/onboard` |
| **sign-in, end to end** | `POST /auth/get-csrf-token/` → `POST /auth/sign-in/` with `PLANE_OWNER_PASSWORD` answers `302 http://plane.localhost:8080/` — **no `error_code`** — and the session then reads `/api/users/me/profile/` as `language=he, is_onboarded=true, last_workspace_id=<the declared workspace>` and `/api/users/me/workspaces/` as the workspace with `role: 20`. A wrong password answers `302 …?error_code=5065&error_message=AUTHENTICATION_FAILED_SIGN_IN`, which is why `hooks/verify` matches `error_code` BEFORE the 302 |
| **the owner's password** | minted into `.env` by `hooks/onboard` (`PLANE_OWNER_PASSWORD`) on first use and never printed; `hooks/verify` reads it back and proves it signs in. A deployment that already has one (ci-env.sh mints it) is used as-is — verified by running the hook against an instance with no admin and the password present |
| **a second owner is refused** | with an existing `InstanceAdmin` under another email, `onboard` writes nothing, adds nobody, says so and exits 0 — verified by pointing `PLANE_OWNER_EMAIL` at a second address |


### Two upstream v1.4.2 findings the bootstrap ran into (measured)

**`InstanceAdmin` soft-deletes, but its unique key does not know that.** The row's index is
`(instance_id, user_id)` with **no `deleted_at`** in it, while `InstanceAdmin.objects` (the default
manager) hides soft-deleted rows. So `objects.get_or_create(user=…, instance=…)` finds nothing, tries
an INSERT, and dies on `duplicate key value violates unique constraint
"instance_admins_instance_id_user_id_2e80a466_uniq"` — a hard failure of a bring-up hook that must be a
no-op on every `bbox run`. `bootstrap.py` therefore looks in `all_objects` and **revives** the row
(`deleted_at = None`). Separately, deleting an admin *user* leaves its row behind pointing at nobody
(`user` is `on_delete=SET_NULL`): the applier counts only rows with a live user and reports the
dangling ones, and `hooks/verify` does the same — a row pointing at nobody is not an owner.

**`GET /api/users/last-visited-workspace/` answers 500 for every user.**
`plane/app/views/workspace/user.py:72` reads `user.last_workspace_id`, but that field lives on
**`Profile`** (the `User` class has no such attribute): `AttributeError: 'User' object has no attribute
'last_workspace_id'`. The web bundle defines `getLastActiveWorkspaceAndProjects()` for it and never
calls it, so it is dead code from the UI's point of view — the bootstrap deliberately does not try to
"fix" it by inventing a field, and `/api/users/me/settings/` (which reads `Profile.last_workspace_id`)
is the endpoint that actually decides where the SPA opens.

### Trap: a 404 from the edge usually means "not healthy yet", not "no route" (measured)

Recreating the container (`up -d --build`) or rebuilding the image makes `plane.localhost` answer
**404 with no router name in the access log** for several minutes — which reads like a missing route
and sends you to traefik. It is not traefik's discovery: **traefik does not route a container that
declares a healthcheck until that healthcheck reports `healthy`**, and this container is legitimately
`starting` for minutes while the migrator runs and the API boots (`collectstatic` alone is ~40s on
this engine). The correlation was measured end to end:

```
health=starting   edge=404   api(inside)=502
health=unhealthy  edge=404   api(inside)=502
health=unhealthy  edge=404   api(inside)=200     <- gunicorn up, docker's probe had not rerun yet
health=healthy    edge=200   api(inside)=200     <- route appears with NO traefik restart
```

An earlier version of this file claimed that `./scripts/dc restart traefik-deployment` was the
remedy. It was not: the restart happened to land after the container had become healthy, and the
conclusion survived two more reproduce attempts before the correlation above was actually measured.
**The remedy is to wait, and to check `docker inspect --format '{{.State.Health.Status}}'` first.**
A traefik restart is only called for when a host was never routed at all (a brand-new app).

The signal to watch while waiting — the API logging that static files were collected, i.e. gunicorn
is about to bind:

```bash
./scripts/dc exec project-pln tail -3 /app/logs/access/api.log
# … 35 static files copied to '/app/backend/plane/static-assets/collected-static'  <- then healthy
```

