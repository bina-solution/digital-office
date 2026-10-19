# Operating `project-pln`

The office's task and project manager: **Plane Community Edition**, self-hosted — a whole product, not
something this platform wrote. Operate it as a system, never by reaching into it.
Vocabulary: a **workspace** holds **projects**; a project holds **work items** (Plane's word for
issues) grouped by **states**, **labels**, **cycles**, **modules**. One container serves the **SPA**,
the **API** (`/api/`, `/auth/`) and attachments from **MinIO** (`/uploads/`).

## Bringing it up — there is no wizard, and that is the point

Plane ships no bootstrap: a fresh instance refuses **every** sign-in until a human fills in the
instance-admin form under `/god-mode/` (`Instance.is_setup_done` gates every auth view) and then
creates a workspace and a project by hand. Here that is declared, like every other app's bring-up:

- `bootstrap.yaml` — the starting state (workspace, project, states, labels, first work items);
  `bootstrap.py` applies it through Plane's own ORM, idempotently, writing the rows Plane's own
  sign-up view and serializers write.
- `hooks/onboard` — the driver (`bbox run` calls it; `./bbox project-pln onboard` alone): waits for the
  database, seeds the owner, never prints a secret. `hooks/verify` asserts the API answers, the state
  is in the database, and **the owner can sign in** (`./bbox project-pln verify`; `bbox baseline` P6).

The login is `PLANE_OWNER_EMAIL` / `PLANE_OWNER_PASSWORD` in `.env`, **and the declared value wins** —
`onboard` sets it on the owner's account and stores it in the vault as the credential
`project-pln-owner`, beside the office's own key `project-pln-api-key` (minted once, reused). Read
either at **חיבורים ומפתחות → סיסמאות אפליקציות → Plane**, audit-logged; the applier reads the same
rows back through the broker (`/api/export/project-pln`), so an edit there is what the next bring-up
applies. Handing the instance to someone else is `PLANE_OWNER_EMAIL=<his address>
PLANE_OWNER_TAKE_OVER=1 ./bbox project-pln onboard` — refused without that second flag.

## What you can do from here

`./bbox project-pln verify` — bootstrapped, not merely healthy. `./scripts/dc exec` takes the SERVICE
name (`project-pln`), not a container's.

## Traps

- **A green container is not a usable instance.** `is_setup_done` false → every sign-in answers
  `302 … INSTANCE_NOT_CONFIGURED`; true but empty → a login into a workspace with no project. `verify`
  tells them apart, `onboard` fixes both, and it is the ONLY writer of that flag.
- **The API can die while the container stays "healthy".** A gunicorn master whose only worker dies
  keeps sitting in `do_select` with no child: nothing binds the port and Caddy waits its timeout on
  every request. `GUNICORN_WORKERS=2` is the fix; the healthcheck asks the API through :80, not Caddy.
- **It is FRAMED on a host of its own, behind the office SSO** (`external: true`): the shell frames
  `plane.<the console's host>` — one site with the console on `.localhost` — because the bundle is
  a ROOT build (`basename "/"`, `/assets/*`) that no rewriting proxy can carry. A frame cannot show
  that host's sign-in, so the shell asks `/.dgo/signed-in` first and signs it in via `/.dgo/enter`.
  `/a/plane/*` (the `passthrough` rule) reaches the API with the prefix stripped, not the SPA.
  `module.url` is the INTERNAL base (`http://project-pln:80`), never handed to a browser.
- **Self-registration is OFF** (`ENABLE_SIGNUP=0`): the door is the office SSO, and an open
  registration form on a company host is an account-creating machine.
- **Four containers, not five: the Celery broker is REDIS.** RabbitMQ is gone;
  `patches/redis-broker.py` adds the line upstream lacks (`CELERY_BROKER_URL = REDIS_URL` when
  `AMQP_URL` is unset — upstream derives it from AMQP_URL only, overwriting the env var).
  Also off: `space`/`live` (`/spaces/*`, `/live/*` 502). `beat` is no process: the one worker
  sends its jobs (`patches/worker-scheduler.py`).
- **An instance that ALREADY has an administrator is left alone**, loudly, exit 0. One that
  MOVED here from another office is adopted, not taken over: README, «An instance that moved in».
- **`InstanceAdmin` soft-deletes, but its unique key `(instance, user)` carries no `deleted_at`**: a
  plain re-create dies on a duplicate key, so `bootstrap.py` revives the row. A deleted admin *user*
  (`SET_NULL`) leaves a row pointing at nobody — reported, never counted as owner.
- **The SPA reads `/api/users/me/{profile,settings}/`**, not `/api/users/me/`: the sidebar list is
  `/api/users/me/workspaces/`. **Language is a SERVER-side per-user field** (`Profile.language`,
  default patched to `he`), written into `localStorage.userLanguage` on every load.
- **A 404 from the edge right after a rebuild means "not healthy yet"**: the migrator gates the API and
  traefik routes nothing before `healthy`.
- **Never point `plane-db` at the platform's Postgres** (`max_connections=1000`) — its connection storm
  would become an office outage.
- **Hebrew is a build, not a setting**: `plane-he` (locale + RTL, CI) via `PLANE_HE_WEB_URL` +
  `PLANE_HE_WEB_SHA256`; both empty means upstream's English bundle. Its catalogue is complete — what
  upstream HARDCODES (never passed through `t()`) is translated by `patches/hebrew-strings.py` + `.tsv`
  (642 entries; a stale entry FAILS the build), the seeded states by `patches/hebrew-states.py`, and
  `patches/bundle-version.py` renames the patched bundle to `assets-<hash of its bytes>` so no browser
  keeps the English copy. Their home is `plane-he`'s sources.
- **Telemetry is off by enforcement, not default**: `patches/no-phone-home.py` flips the model default
  AND the god-mode form default, and gates both call sites on `PLANE_TELEMETRY=1`.
- **The cloud import is two tokens and plan-first** (`import-cloud`, dry run then `--apply`); tokens live
  in `.env`, and attachments do not come across.
