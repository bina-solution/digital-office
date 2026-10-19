# deployment-hacohen

[![ci-verify](https://github.com/solomonBoltin/deployment-hacohen/actions/workflows/ci-verify.yml/badge.svg?branch=shlomo-laptop)](.ci-cd/)

Infrastructure-as-code for **one live production VPS** (BINA Solutions / Hacohen), served under
`*.hacohen.bina-solutions.co.il`.

> **Deployment verification** — every push brings the whole stack up from scratch and asserts each app
> came up from its declarative config. The live scorecard + app screenshots are published to
> [`.ci-cd/`](.ci-cd/) (the badge above links there).

Core business: **automated Hebrew financial-document processing** (invoices, delivery notes,
balance sheets) via n8n + apitools OCR + WhatsApp — plus an in-development **AI agent that builds
and operates the deployment itself** (`apps/openhands`).

Design goal: **fully declarative** — `git clone` + `./bbox run` brings the whole stack live from a
single `.env`.

> **This is production.** Real users depend on it. See [AGENTS.md](AGENTS.md) for the operating
> rules any human or AI agent must follow before touching this repo.

## Quick Start

**Clone the repo** — everything builds from this single tree. `apps/chat` and `apps/apitools` are
both part of this repo (baked into the monorepo, no submodules to fetch):

```bash
git clone https://github.com/solomonBoltin/deployment-hacohen
cd deployment-hacohen
```

Then bring the stack up:

```bash
./debian-install.sh          # installs Docker, Compose, dependencies (Debian/Ubuntu host)
cp .env.ex .env              # then edit .env with real values + secrets
./bbox run                   # compile the manifests, then converge Docker onto the result
```

> **Do not call `docker compose` directly.** The root [compose.yml](compose.yml) declares only the
> shared network — every service is *compiled* into `.generated/`. A bare `docker compose up -d`
> therefore resolves **zero services and exits 0**: a silent no-op that reads as success. Use
> `./bbox run`, or `./scripts/dc` for raw compose subcommands. Gate G7 enforces this in CI.

## Prebuilt images (DGO-41)

Every first-party image (20 of them: `archify`, `bina-ds`, `console`, `dgo-extend`, `project-pln`,
`git`, …) is built once per commit by [`.github/workflows/images.yml`](.github/workflows/images.yml)
and pushed to GHCR as `ghcr.io/solomonboltin/digital-office/<app>:<sha>`, `:<branch>` and `:latest` —
the workflow's own header counts what is inside that set and what is outside it, with each reason.
Use them when a deployment should PULL rather than rebuild the same layers (a fresh office, a remote
converge, a CI runner):

```bash
overlay=platform/profiles/ci-images.yml
OVERLAYS=$overlay ./scripts/dc config --services        # the same stack, images instead of builds
OVERLAYS=$overlay ./scripts/dc up -d --no-build         # pull and start
docker pull ghcr.io/solomonboltin/digital-office/git:latest   # one image, on its own
```

Every app's compose also names the image directly — `image: ghcr.io/solomonboltin/digital-office/<app>:${IMAGE_TAG:-latest}`
with `pull_policy: missing` and its `build:` kept as the fallback — so a deployment that already has
the image does not rebuild it, and one that does not gets it from GHCR. `console` is the last app
still naming a tag no registry has (`deployment-hacohen-console`); the auxiliary builds
(`sites-render`, `mail`'s two, `browser42`'s four, `openhands`' three) are outside the CI image set
and still build from source.

`IMAGE_TAG` in `.env` chooses the tag: a commit SHA pins exactly the revision a declaration names
(`source.commit` in a dgo-extend office), and `latest` is the head of the branch that ran the
workflow (`dgo` today). **`./bbox run` still builds** — it passes `--build` deliberately — so pulling
is the explicit path: `BBOX_PREBUILT=1 ./bbox run`, or `up -d`/`pull` without `--build`, or the
overlay above. A GHCR package made from a private repository is private, so a machine that must pull
needs `docker login ghcr.io` once.

Verify a run: the workflow's summary names the packages it pushed; `docker pull` proves one is
readable from outside GitHub; `OVERLAYS=… ./scripts/dc up -d --no-build` proves a deployment can
start from them (`./scripts/dc ps` then shows the same services healthy). The images job was written
here and has NOT been executed by the author — this checkout has no Actions runner — so its first
green run is the one that closes DGO-41.

## Architecture

The platform is **compiled, not assembled**. `platform/manager/reconcile.py` reads every
`apps/*/app.json` manifest plus `platform.state.yaml`, resolves each app's declared capabilities to
a provider, and renders `.generated/` — the compose include chain, three overlays, five registries
and an authentik blueprint. Docker is then converged onto that output. Nothing is hand-wired, and
the compiler *refuses* an ambiguous provider choice rather than picking one.

Three layers, and **the directory is the layer** — where a file lives declares what it may depend
on, enforced by gate G9:

```
platform/            LAYER 0   the compiler + the manager CLI
  manager/reconcile.py           validate | render → .generated/
platform-base/       LAYER 1-2  the substrate every deployment gets
  traefik              edge: TLS termination + routing (80/443, +5432 Postgres, +6379 Redis)
  authentik            SSO / forward-auth
  postgres  redis      shared datastores
  n8n                  workflow automation (+ workers, task-runners)
  connections          the credential broker — apps get grants, not standing secrets
  console              the shell UI that embeds every app
  glitchtip            self-hosted error tracking (Sentry-compatible)
  machine  notifications  any-concurrency  app-management  bina-ui
apps/                LAYER 3   the products — one directory, one app.json manifest each
  chat                 multi-engine chat: private engine + WhatsApp/Telegram bots
  indox                Hebrew financial-document intake and extraction
  apitools             OCR / PDF processing API
  drive  mail  my-docs  supabase  portainer  openhands  ollama  browser42  …

.generated/          RENDERED OUTPUT — never edit by hand
compose.yml          the shared external network, and nothing else
platform.state.yaml  which apps are enabled, provider bindings, perf profile
.env / .env.ex       config + secrets (DEPLOYMENT_DOMAIN, *_BASE_URL, …)
scripts/             dc (the compose wrapper), lib.sh, baseline.sh, refactor/ (the gate registry)
ops/  packaging/     operational tooling and the measured optimisation study
ai/context/          agent context (healthy-baseline, architecture review, n8n-cli, plans, …)
ai/obsidian/         persistent cross-session memory vault (the "brain")
issues/              tracked defects with severity/status front-matter
```

An app is enabled or disabled with `bbox apps enable|disable <app>` (data is always kept); the
resolved plan is `bbox apps list`. Adding an app means adding a directory with a manifest — see
[ai/context/build-your-first-app.md](ai/context/build-your-first-app.md).

## Configuration

All configuration lives in `.env` (created from [.env.ex](.env.ex), git-ignored). Key variables:

- `DEPLOYMENT_NAME` — stack/container name suffix (e.g. `bina-deployment`).
- `DEPLOYMENT_DOMAIN` — base domain (`hacohen.bina-solutions.co.il`).
- `*_BASE_URL` — per-service hostnames (`N8N_BASE_URL`, `PORTAINER_BASE_URL`, …).
- `POSTGRES_USER` / `POSTGRES_PASSWORD`, `REDIS_PASSWORD` — datastore credentials.
- `TRAEFIK_ACME_EMAIL` — email for Let's Encrypt SSL.
- `TZ` — timezone.

**Never commit secrets.** `.env` is git-ignored; keep all credentials there, not in tracked files.

## n8n workflows: pull / push

Workflows live in `apps/n8n/` as a tracked blueprint and are moved with `bbox`, not with
loose scripts (the old `scripts/n8n-pull` / `n8n-push` are gone):

```bash
./bbox n8n status         # git ↔ live drift, active/published, key + credential health
./bbox n8n pull           # capture the running host → blueprint files
./bbox n8n push           # blueprint → host, non-destructive + publish
./bbox n8n verify         # credential connect-tests, missing-key warnings, re-auth links
```

`bbox n8n clean-recreate` wipes n8n and restores it *exactly* from the blueprint — the declarative
round-trip that proves the blueprint is complete. Broader n8n operations (CLI / API / DB, workflow
and credential IDs) are documented in [ai/context/n8n-cli.md](ai/context/n8n-cli.md).

## Operational scripts

`bbox help` lists the full command tree; these are the standalone helpers.

| Script | Purpose |
|---|---|
| `scripts/dc` | `docker compose` against the compiled file list, from anywhere |
| `scripts/collect-logs.sh` | gather service logs |
| `scripts/pg-maintenance.sh` | Postgres maintenance |
| `scripts/safe-clean.sh` | safe cleanup of unused Docker resources |
| `scripts/storage-report` | disk/volume usage report |
| `scripts/refactor/` | the gate registry — the static checks CI runs on every push |

## Before production changes

- [ ] All `.env` values set to secure, production-ready secrets — nothing default.
- [ ] `TRAEFIK_API_INSECURE=false` and the dashboard restricted.
- [ ] Changes verified against real output before claiming done.
- [ ] Backups in place for volumes and databases before any destructive action —
      **there is currently no tooling for this.** `bbox backup` / `bbox restore` do not exist, and
      `data.volumes` in the app manifests (the field such a tool would derive from) is known to be
      incomplete. Until both are fixed, a destructive action here is unrecoverable. Tracked as R3/R4
      in [ai/context/platform-architecture-review.md](ai/context/platform-architecture-review.md).

## Where context lives

| Need | Source |
|---|---|
| Agent quickstart (fresh UI map, cloud/web sessions) | [CLAUDE.md](CLAUDE.md) |
| Operating rules for agents | [AGENTS.md](AGENTS.md) |
| **How the platform is put together, and what is wrong with it** | [ai/context/platform-architecture-review.md](ai/context/platform-architecture-review.md) — the compile pipeline, the capability graph, the gate registry, and 26 ranked recommendations |
| Writing an app for this platform | [ai/context/build-your-first-app.md](ai/context/build-your-first-app.md) |
| Measured optimisation study (containers, memory, images) | [packaging/OPTIMISATION.md](packaging/OPTIMISATION.md) |
| Healthy-baseline proof (`bbox baseline`) | [ai/context/healthy-baseline.md](ai/context/healthy-baseline.md) |
| Services, domains, ports, networks, run commands | `ai/context/deployment-context.txt` |
| n8n operate (CLI/API/DB, IDs, lessons) | `ai/context/n8n-cli.md` |
| Charter, decisions, session log, system map | `ai/obsidian/` vault (start: `ai/obsidian/00 - START HERE.md`) |

## License

MIT — see the `LICENSE` file.

## License

DGO — the digital office
Copyright (C) 2026 Bina Solutions

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Third-party components keep their own licenses: see [NOTICE.md](NOTICE.md) and [LICENSES/](LICENSES/).
