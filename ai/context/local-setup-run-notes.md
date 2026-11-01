# Local-Setup: full bring-up run notes + "runs smoothly everywhere" fixes

*2026-07-13. A complete from-scratch bring-up of the local stack was run headlessly in a locked-down
managed sandbox (no Docker daemon at start, HTTPS-only egress via a TLS-intercepting proxy, nested
Docker with capped rlimits, no IPv6). Goal: prove `bbox run`-equivalent works, and make every
environment-specific snag a committed fix so it "just works" on a normal machine AND in a cage.*

## What ran (result)
Brought up 24 services from cached images + local builds: traefik-less subset = supabase (db/rest/meta/
storage/kong/studio) + redis + n8n (main + worker-1 + task-runners + **worker-1-runners**) + apitools +
inbox + localmail(GreenMail) + localdrive + mailview + morning + any-concurrency + notifications +
connections + **console** + incoming-documents + indox-demo-docs.

- **Console (המרכז) federates every module** — `/a/pinkas`, `/a/localdrive`, `/a/mailview`, `/a/incoming`,
  `/a/alerts`, `/a/any-concurrency`, `/a/connections` all serve 200 through the shell; the install/onboarding
  wizard renders; guest fallback works with no Authentik.
- **Local Hebrew OCR proven** — apitools (Tesseract 5.5.0 heb+eng) OCR'd a real demo invoice fetched from
  localdrive, zero cloud.
- **Full INDOX pipeline proven end-to-end through extraction**: uploaded 2 demo docs → drive sources
  (visible in the Drive UI under to_sync with the to_sync→in_progress→synced→failed state model) →
  registered in `incoming_documents` → main driver figured **TYPE=INVOICE**, resolved **COMPANY_ID (זלמן
  סחר)**, extracted **SHORT_DOC_ID=01868, DOC_DATE=31/12/2025, DOC_TOTAL_AMOUNT=95675.03** from the seeded
  `ai_extraction_cache` (no Gemini), and auto-renamed the file. 112 workflows pushed, 107 active.
- **Remaining gap (not a fresh-setup issue):** the invoice stalls at `IN_PROGRESS` before flipping to
  `COMPLETED` — a stale `n8n.process_lock.doc_step.*` / re-drive issue (the balance sheet lands at the
  legitimate `MISSING_COMPANY_ID`). This is exactly the runtime tuning the release plan's acceptance phase
  budgets 1–2 days for (locks / check_from_office / poll re-drive), independent of the bring-up.

## Environment snags → fixes (so it's smooth everywhere)

| # | Snag (in a locked-down sandbox) | Fix (committed = universal/opt-in; runbook = operator step) |
|---|---|---|
| 1 | Private submodules blocked a fresh clone | **RESOLVED** upstream: monorepo (apitools/whatsapp in-tree). |
| 2 | `.env` ships placeholders → compose won't interpolate | Runbook: `scripts/supabase-keygen.py` + generate the ~15 `change_me`/required tokens. *(Recommend a `bbox env bootstrap` that fills all of them — see backlog.)* |
| 3 | `kong-entrypoint.sh` "permission denied" on fresh clone | **COMMITTED**: file now tracked `100755` in git (was 644). |
| 4 | `n8n-postgres` `nofile hard=262144` rejected by nested Docker | **COMMITTED**: `ulimits.nofile` now `${PG_NOFILE_SOFT:-102400}`/`${PG_NOFILE_HARD:-262144}` — normal hosts keep the high default; a sandbox sets `PG_NOFILE_HARD=4096` in `.env`. |
| 5 | n8n crash-loops binding IPv6 `::` (no IPv6 in sandbox) | **COMMITTED**: `N8N_LISTEN_ADDRESS=0.0.0.0` on n8n + workers (IPv4 works on every host). |
| 6 | code-node actions time out ("task request timed out 120s") | **Operator**: each n8n worker needs its OWN task-runner — bring up `n8n-worker-1-runners` (not just the worker). Missing it = every code node stalls. |
| 7 | `indox-demo.py` hardcoded container name `*-shlomo-laptop` | **COMMITTED**: derives `DEPLOYMENT_NAME` from `.env`. |
| 8 | Docker **builds** can't reach PyPI/apt/npm behind an HTTPS-only, TLS-intercepting proxy | **Build-time only** (no normal-host impact) — see "Building behind a proxy" below. Recommend a `scripts/sandbox-build` helper; documented here so it's reproducible. |
| 9 | INDOX schema/config not auto-created without the (flaky-via-REST) Reset+Setup | Seed the CI fixtures directly: `psql < production/n8n/fixtures/01_schema.sql`, then load `settings.json` / `tag_rules.json` / `ai-extraction-cache.json`; create the `drive` storage bucket. This is what CI does. |

## Building behind a TLS-intercepting, HTTPS-only proxy (sandbox only)
Normal hosts: plain `docker compose build` works. In a cage where egress is HTTPS/CONNECT-only and TLS is
intercepted by a corporate/agent CA, image builds need:
- **`docker build --network=host`** so the build reaches the host-local proxy.
- **apt over HTTPS mirrors** (apt's default HTTP mirrors get 405 from a CONNECT-only proxy):
  `sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources`.
- **pip**: `--cert <ca-bundle>` (or `PIP_CERT`).
- **npm**: go **direct** (not via the proxy — proxied npm stalls) + trust the CA via
  `NODE_EXTRA_CA_CERTS=<ca-bundle>`; and add `git config --system url."https://github.com/".insteadOf
  "ssh://git@github.com/"` so npm git-deps (e.g. `n8n-nodes-puppeteer`'s) resolve over HTTPS instead of SSH:22.
- **daemon**: `HTTPS_PROXY` in dockerd's env is needed for image *pulls* but poisons *builds* (BuildKit
  injects it and npm hangs) and *runtime* (containers inherit `HTTP_PROXY` and can't reach sibling services →
  502s). Pull first, then run the daemon proxy-free (enable `live-restore` so containers survive the restart).

## Backlog to make it one-command everywhere
- `bbox env bootstrap` — generate every secret + local toggles (idempotent), so snag #2 disappears.
- `scripts/sandbox-build` — wrap the build knobs in #8 behind auto-detection of a CA bundle / proxy (no-op on
  a normal host), so a cage builds with plain `bbox run`.
- Make Reset+Setup + demo-inject robust when triggered head­lessly (REST `/run` on `executeWorkflowTrigger`
  workflows doesn't cascade in queue mode) — or expose them via the `/indox-manage` webhook the CLI can call.
- Close the acceptance-run last mile (doc_step lock re-drive / check_from_office) so docs reach `COMPLETED`.
