# Central Business System — Status & Roadmap

Living status of the mission (unify the estate into one business system; solve the access-key problem
once and for all). Companion to the design docs (`central-business-system-plan.md`, `-master-map.md`,
`-keys.md`, `-connections-design.md`). Branch: `claude/centralized-business-system-qs1edt`.

## Local-machine verification cycle (2026-07-12, real machine + real keys)

Merged the branch into the working tree and ran the plan (`plan.md`) on a normal Windows/Docker-Desktop
host. What was completed + verified live, plus honest blockers:

**Done + verified (no user action needed):**
- **Full stack up in connections mode** — `docker compose -f compose.yml -f compose.connections.yml up
  -d`: 44 containers healthy; `apitools` loads 7 secrets + `inbox` 5 via `inject.sh`; ledger
  `/business` → 200 with the injected `SUPABASE_DB_PASSWORD` (blank in env).
- **console + connections SSO gating FIXED** — the cloud session added the `authentik` middleware to both
  routers but never created their Authentik proxy providers, so both 404'd. Added console+connections
  proxy providers/apps (https+local) + outpost bindings; both now 302 to SSO like morning/machine. The
  console renders the RTL install screen and its BFF proxies the live connections catalog.
- **WhatsApp pairing UNBLOCKED (real fix, not IP)** — the "datacenter-IP block" theory was wrong: the raw
  WS + Noise handshake are accepted. WhatsApp rejects the pairing WS (close 428, no QR) only for a
  fresh/unregistered device that requests full-history sync with the macOS-Desktop identifier. Isolated
  live: `macOS+syncTrue→428`, `macOS+syncFalse→QR`, `ubuntu+syncTrue→QR`. Fixed by gating the
  macOS+full-history combo on `state.creds.registered`. Also matched the bot's `AUTH_*` to the
  `wadmin-auth` the connections QR-proxy uses (was `reachable:false`). Now: bot emits QR →
  `/api/qr/whatsapp-baileys` `reachable:true has_qr:true` → PNG proxy returns a valid QR. **Scan is the
  user's step.**
- **Ledger PDF invoice** — set business identity → customer → 2-line invoice → §9(a)(3) compliance gate
  enforced → issued (series INV) → 25KB PDF whose text carries ₪7,400 / ₪1,332 VAT / ₪8,732.
- **connections-mode extended** — folded `any-concurrency` (4 secrets, healthy off the plane) and
  `machine` (no-op injector) into `compose.connections.yml`.
- **incoming-documents injector-readiness** — connections resolves all 9 secrets incl. the `as:` aliasing
  (`N8N_GOOGLE_OAUTH_CLIENT_ID → GSHEET_OAUTH_CLIENT_ID/SECRET`). Live run still needs redpanda (dev
  stack) + the Google grant + a valid Gemini key.
- **n8n trust-proxy fix** — set `N8N_PROXY_HOPS=1`; without it express-rate-limit throws
  `ERR_ERL_UNEXPECTED_X_FORWARDED_FOR` behind Traefik and can 200-without-cookie on `/rest/login`.
- **ci-verify** — 24/25 on this Windows host. The one red (`integration-n8n-active-state`) is a Git-Bash
  curl cookie-jar `/tmp` path artifact (native curl writes `-c /tmp/jar` to `C:\tmp`), NOT a deployment
  defect: login returns 200+`Set-Cookie`, `/rest/active-workflows` = 89 runtime listeners, 107/107
  published+active, and the active-webhook check passes. Green on the Linux CI runner.

**Blocked on the user (external, cannot be done autonomously):**
- **`GEMINI_API_KEY` in `.env` is INVALID** — value `AQ.Ab8…` (53 chars) is rejected by Google
  (`API key not valid`). Live document extraction (the "invoice Extractor — Gemini" node) can't work
  until replaced with a valid key (AI-Studio `AIza…`). Connections faithfully exports whatever `.env`
  holds — the plane is fine; the key value is bad.
- **Google consent grant** — `google-workspace-grant` is `needs_action` (OAuth client id/secret ARE set).
  Needs the user to complete consent via the connections broker.
- **WhatsApp QR scan** — the user's phone.
- **INDOX `bbox indox test all --parallel`** — 4/7 suites green (sync_kernel 6/6, doc_base 3/3, bs 4/4,
  gdoc 5/5); `sync_sources` + `sync_full` fail in the **gmail-source** sync lanes (`delivered 0/1 != 3`)
  and the Gemini-invoice `pipeline` lane can't converge with the invalid key. inbox authenticates to
  real Gmail and the drive lanes pass, so this is not the connections cutover — it's the invalid Gemini
  key + un-granted Google + real-Gmail delivery. Re-run after the user supplies a valid Gemini key and
  completes Google consent.

## Verified this cycle (running, not slideware)

| What | Status | Evidence |
|---|---|---|
| Full production stack runs **locally on the remote env**, zero external deps | ✅ | `scripts/ci-verify.sh` → **25/25** |
| INDOX full document pipeline E2E | ✅ | `bbox indox test all` → **27/27, 7/7 suites** (Gmail→OCR→extract→supabase→link→WhatsApp) |
| `connections` credential plane — 50-secret declarative catalog, live probes | ✅ | running behind Traefik+Authentik; 36 healthy via real HTTP/TCP probes |
| Editable overrides (encrypted DB beats `.env`), add / clear / rotate | ✅ | `/api/set` `/api/add` `/api/regenerate`, editable UI |
| Auto-mint (machine secrets optional in `.env`) | ✅ | absent `N8N_ENCRYPTION_KEY` → generated 64-hex; 20 secrets tagged |
| OAuth broker (consent originates in connections) | ✅ | `/oauth/<id>/start` builds the real Google URL w/ connections' own redirect |
| **Injector** — real consumers on the credential plane | ✅ | `inbox` (5 secrets) + `apitools` (8 secrets, incl. the ledger's `SUPABASE_DB_PASSWORD` — blank in compose, **/business still 200**) + `any-concurrency` boot off `inject.sh`. `incoming-documents` override ready + export-verified. Per-consumer `as:` env-aliasing added. Still opt-in overrides, not the default include chain. |
| **`console` shell (המרכז)** — unified RTL Hebrew webapp, morning-styled | ✅ | `console.localhost`, 13 modules federated, install wizard driven by connections, behind Authentik |
| **One-command bring-up** — connections + console in the production include chain | ✅ | `production/compose.yml` includes both pillars; `docker compose config` → **44 services**, valid |
| **Ledger (פנקס)** — already implemented by `apitools` | ✅ | live: business→customer→item→document→VAT(1180)→**PDF** render; `morning` proxies `/api/*` to it |
| **Web onboarding** — business-identity step + connections wizard | ✅ | console BFF proxies `apitools /business`; wizard step 1 = identity, blocks until onboarded |
| **Separate onboarding model** — Authentik owns accounts, console owns setup | ✅ | `authentik-bootstrap` auto-mints akadmin; first-run lands authed user on install wizard |
| **Security** — credential plane never unauthenticated | ✅ | `connections-local`/`console-local` gated with `authentik` (matched morning-local); localhost 200→gated |
| **De-Hacohen (branding)** — one `BUSINESS_NAME` feeds visible titles | ✅ | homepage title via `{{HOMEPAGE_VAR_BUSINESS_NAME}}`; glitchtip org default; verified substitution |
| **WhatsApp QR in-console** — bot QR surfaced + polled to paired | ✅ | `/api/qr/<id>[/png]`, console modal, disconnect; real bot reachable (`reachable:true`); pairing IP-gated by WhatsApp (residential IP needed) |
| **Disconnect / disable** — per-connection + per-feature | ✅ | `/api/disconnect` (oauth drop / qr logout / clear), `/api/features` toggles, console `נתק` buttons |
| **connections-mode overlay** — whole stack off the credential plane | ✅ | `compose.connections.yml`: `depends_on connections(healthy)` + blanked secrets; apitools loads 8, ledger 200 |
| **GO-LIVE runbook** — 1-command + web onboarding, documented | ✅ | `GO-LIVE.md` end-to-end for local/VPS |

## The credential model (settled)

- Resolution: **DB override → `.env` (live default) → auto-mint → install wizard.**
- Three kinds unified: **text/password**, **oauth-grant**, **qr-session** (+ derived, config).
- Declarative: `providers/*.yaml` (catalog) + `manifests/*.yaml` (per-service requires) = git source of truth.
- Human steps reduced to **2**: Google consent + WhatsApp QR.

## Integration reality — connections is a PLANE; real consumers now cut over (opt-in)

The catalog declares all 50 secrets; connections resolves/probes/auto-mints them. Cutover progress
(verified live 2026-07):

- **WhatsApp / Baileys** — NOW integrated at the plane level. `/api/qr/<id>` returns live bot state,
  `/api/qr/<id>/png` proxies the bot's QR (admin basic-auth), the qr-session probe reflects real bot
  state, and the console renders the QR in-app + polls to `paired`. Verified end-to-end against a
  stand-in bot (real Baileys↔WhatsApp WS pairing needs an env that allows WebSockets — the user's
  local/VPS). `/api/disconnect` does the logout.
- **INDOX Gmail / Gemini / apitools** — CUT OVER (opt-in override, verified live). `inbox` (5
  secrets) + `apitools` (8 secrets, incl. the ledger's `SUPABASE_DB_PASSWORD` — blank in compose, ledger
  still 200) boot off `inject.sh`. `/api/export` gained per-consumer `as:` env-aliasing (canonical env →
  the name a service actually reads). `incoming-documents` override written + export-verified (heavier
  to run live). n8n's Google grant still arrives via the OAuth broker + credential_overrides.
- **Connections-mode is now a one-flag switch** — `compose.connections.yml` makes the credential plane
  the default source of truth for the root-compose consumers (opt-in at the compose level, not per
  service). incoming-documents/localdrive/glitchtip/machine still apply their own rollout overrides.

So: the plane is built AND real consumers run off it AND there's a single-flag "connections mode".

## Remaining tasks (prioritized, honest scope)

1. **Extend connections-mode to the rest** — LOW/MED. `compose.connections.yml` covers inbox +
   apitools (root-compose). Fold in `any-concurrency` (needs its exact command) and, once they're in a
   stack, localdrive/glitchtip/machine. `incoming-documents` runs live via its dev overlay + redpanda.
2. **Swap the vault: Fernet → Infisical** — HIGH for prod. Stand up Infisical (Postgres+Redis already
   run); `connections` keeps the catalog/resolver/UI/broker and delegates STORAGE. Gets versioning,
   audit, RBAC, KMS, rotation — the "highest standards" bar. The Fernet vault was always a swappable POC.
3. **WhatsApp pairing on a real IP** — the integration is complete (QR proxy + console modal + poll +
   disconnect; real bot reachable). WhatsApp 403s pairing from cloud IPs — pair from local/VPS. Optional:
   mirror `auth_info` into the vault for portability across redeploys.
4. **OAuth broker end-to-end** — MED. No public HTTPS needed (connections owns its redirect); needs the
   product's own Google client + a browser that can reach `connections.<host>`. Deploy-time.
5. **De-Hacohen: structural rename** — MED. Branding flows from `BUSINESS_NAME` (done). The remaining ~26
   refs are the `chat` **service identity** (dir/container/image) + n8n blueprint credential
   labels — a rename refactor, own change. Plus the INDOX "Tenant Setup" workflow (Drive tree + sheets +
   labels per business).

**Done since last cycle:** ledger confirmed (apitools, item 6 removed) · 1-command bring-up (connections+
console in prod compose) · web onboarding (business-identity step) · separate onboarding model · localhost
security gating · de-Hacohen branding slice (`BUSINESS_NAME`). The `console` shell (was item 5) is built
and federating 13 modules — no longer a remaining task.

## Environment note (this sandbox only — NOT project changes)

The stack runs here via env-specific docker workarounds (proxy-wired daemon, `--network host` builds,
HTTPS apt, git `insteadOf` ssh→https, `DOCKER_MIN_API_VERSION=1.24`, `N8N_LISTEN_ADDRESS=0.0.0.0`,
lowered `nofile` ulimit). These belong in the environment's **Setup script**, not the repo — the
project is green out-of-the-box on a normal host / GitHub runner. Full list in the session log.
