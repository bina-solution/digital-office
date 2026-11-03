# Central Business System — Consolidation & Unified Connections (Design Proposal)

Status: **proposal / thinking doc** (no code yet). Branch: `claude/centralized-business-system-qs1edt`.
Author intent (paraphrased): collapse the whole `deployment-hacohen` estate into **one business
webapp** that centralizes everything — dashboard, פנקס (ledger), דרייב (drive), מייל (mail),
incoming documents, WhatsApp bot (from wadmin), any-concurrency, alerts (from GlitchTip API),
machine, apps (from homepage), system validation (feature-validation / test suite), settings
(system settings, **access-key management**, connections), and an **install screen** (base
settings + external-system connections). Same visual language as morning/פנקס, localdrive/דרייב,
localmail/מייל — but one app that unifies the whole infrastructure into **one system backed by
distributed services**.

The load-bearing ask: **solve the access-key problem once and for all** — text keys, QR/barcode
keys (WhatsApp-style), and OAuth keys — in one service that centralizes them and plugs in wherever
needed, **streams keys from `.env`** for a friction-free boot, and **asks in the installer** only
for what is missing. This doc researches how professionals do that and recommends a concrete design.

---

## 1. Punch line (recommendation up front)

1. **Do not build a monolith.** Keep every domain a separate BFF service (the pattern morning,
   localdrive, mailview, machine already follow) and unify them with a thin **portal shell**
   (`console`) — a single RTL SPA with one top-nav, one design system, one identity. This is the
   "one webapp, distributed services" the user described, and it matches what the repo already does.
2. **Add one new cross-cutting service: `connections`** (חיבורים/מפתחות) — the single pane and
   single API for *all* credentials, with three credential **kinds**: `secret` (text), `oauth`, and
   `paired` (QR/device). Every consumer resolves credentials through it via one client, with a fixed
   resolution chain: **live store → `.env` fallback → install-wizard prompt**.
3. **Back it with proven OSS, don't hand-roll crypto.** Use **Infisical** (MIT, Postgres — you
   already run Postgres) as the secret store for text/`secret` kind, and **Nango** (self-hostable,
   800+ providers, managed OAuth + token refresh) as the OAuth broker for the `oauth` kind. The
   `paired` kind (WhatsApp) keeps using Evolution/Baileys, but its session blob is *stored as a
   secret in the vault* so it lives in the same place as everything else.
4. **Generalize the mechanism you already invented.** `production/n8n/blueprint.yml`
   `credential_overrides:` already seeds n8n credentials from `.env` on push (`${VAR}` → PATCH,
   re-encrypt). That is exactly the "stream keys from `.env`" pattern — **promote it from an
   n8n-only trick to a deployment-wide contract** owned by `connections`.

Everything below justifies and details these four moves.

---

## 2. What already exists (inventory → vision mapping)

The estate is *already* a set of small BFF services in a shared style. The consolidation is mostly
**federation + two new services**, not a rewrite.

| Vision surface (user's words) | Already in repo | Kind | Gap to close |
|---|---|---|---|
| דשבורד (dashboard) | `homepage` (Docker-label auto-discovery) | portal | fold into `console` shell as the landing module |
| פנקס (ledger) | `morning` (BFF → apitools, Authentik headers) | BFF+SPA | adopt shared shell/nav |
| דרייב (drive) | `localdrive` (Flask + Postgres + storage) | BFF+SPA | adopt shared shell/nav |
| מייל (mail) | `localmail` (GreenMail+Roundcube), `mailview`, `inbox` | BFF/infra | adopt shell; mail creds → `connections` |
| מסמכים נכנסים (incoming docs) | `development/incoming-documents` (FastAPI+Kafka) | BFF | promote to prod module |
| בוט ווצאפ (from wadmin) | `production/chat` (`wadmin.<dom>`), Evolution API | app | QR/session → `connections` `paired` kind |
| כל מקביל (any-concurrency) | `any-concurrency` (concurrency/timeline observability) | app | embed as module |
| התראות (from GlitchTip API) | `glitchtip` (Sentry-compatible, has REST API + DSNs) | infra+API | new `notifications` aggregator reads its API |
| מכונה (machine) | `machine` (FastAPI host+Docker metrics) | app | embed as module |
| אפליקציות (from homepage) | `homepage` services.yaml | portal | drives the "apps" grid in `console` |
| אימות מערכת (validation / test suite) | `development/feature-validation` (`fv.dev`, per-suite validators) | test | promote to prod "validation" module |
| הגדרות + ניהול מפתחות + חיבורים | scattered across `.env` (~150+ vars) + Authentik + n8n creds | **missing** | **new `connections` + `console/settings`** |
| מסך התקנה (install screen) | `debian-install.sh` + hand-edited `.env` | **missing** | **new install wizard driven by a manifest** |
| אימות/זהות (SSO) | `authentik` (ForwardAuth middleware `authentik`) | infra | **already the unifying identity layer — reuse it** |

Two things the repo *already* got right and we build on:

- **One identity layer.** Authentik ForwardAuth injects `X-authentik-*` headers; `morning`
  (`/api/me`) already reads them. The portal and every module trust the same headers → **no
  per-app login**. (`ai/context/deployment-context.txt` → "Auth posture".)
- **One design language.** `localdrive/app.py`'s own docstring says it "serves a **morning/פנקס-styled
  RTL SPA**". The shared look already exists informally; the shell makes it a real design system.

---

## 3. Architecture — one webapp, distributed services

The professional name for this is a **portal / micro-frontend shell over BFFs**, all behind one SSO
edge. Concretely:

```
                         ┌─────────────────────────────────────────────┐
   browser  ──TLS──►     │  Traefik (edge)  +  Authentik ForwardAuth     │   one login, one cookie
                         └───────────────┬─────────────────────────────┘
                                         │ X-authentik-* identity headers
                         ┌───────────────▼─────────────────────────────┐
                         │  console  (portal shell: RTL SPA + top-nav)   │  home.<dom> / app.<dom>
                         │  design-system + module registry + /api/me    │
                         └──┬───────┬────────┬────────┬────────┬────────┘
        federated modules   │       │        │        │        │   (each is an existing BFF, iframed
        (own BFF + SPA,     ▼       ▼        ▼        ▼        ▼    or module-federated, same shell CSS)
         same shell)   פנקס    דרייב     מייל   incoming   machine  any-conc  validation  wadmin …
                       morning localdrive mailview  docs
                         │       │        │        │        │
                         └───────┴────────┴────────┴────────┴──── all resolve credentials via ─┐
                                                                                               ▼
                         ┌─────────────────────────────────────────────────────────────────────┐
                         │  connections  (חיבורים)  — the single credential plane                │
                         │  kinds: secret | oauth | paired      resolution: store→.env→wizard    │
                         │  store: Infisical (text)   oauth broker: Nango   paired: Evolution     │
                         └─────────────────────────────────────────────────────────────────────┘
                         ┌─────────────────────────┐   ┌──────────────────────────────────────┐
                         │ notifications (GlitchTip │   │ settings + install wizard             │
                         │ API + wadmin + machine)  │   │ (manifest-driven required-conn list)  │
                         └─────────────────────────┘   └──────────────────────────────────────┘
```

**Why federation, not a rewrite:**
- Each domain already ships independently (own `docker-compose.yml`, own release cadence). A monolith
  throws that away and creates one giant blast radius — the exact opposite of the repo's "this is
  production, keep blast radius small" ethos (AGENTS.md).
- The shell only needs three contracts from a module: (a) trust `X-authentik-*`, (b) import the
  shared CSS/design tokens, (c) register itself (name, icon, route, health) so the nav + apps grid
  are auto-built — this is literally what `homepage`'s Docker labels already do; we formalize it into
  a small `console` **module manifest**.

**Integration mechanics (pick per module, cheapest first):**
- **iframe + shared chrome** for heavy legacy UIs (wadmin, redisinsight, portainer, GlitchTip web) —
  zero code change, just routed inside the shell with the shared top-nav. Start here.
- **Module Federation / web components** for the first-party SPAs (morning, localdrive, mailview) so
  they share one bundle, one theme toggle, one nav without a full-page reload — do this second.
- **Server-side include of the SPA** stays as-is; only the shell chrome + design tokens are shared.

---

## 4. The heart — unified Connections service ("access keys, solved once")

### 4.1 The problem, precisely

Today a credential can be any of:
- **text secret** — API keys, DSNs, passwords, app-passwords (`GMAIL_IMAP_APP_PW`,
  `GEMINI_API_KEY`, `REDIS_PASSWORD`, …). ~150+ live in `.env`.
- **OAuth grant** — Google Drive/Gmail, etc. Needs a browser dance, a refresh token, silent refresh.
  (`ai/context/setup-google-cloud-login.md` exists precisely because this is painful today.)
- **paired / QR (barcode) credential** — WhatsApp via Evolution/Baileys: the "key" is obtained by
  scanning a QR on a phone; the artifact is a **session blob** that must be persisted and can expire
  → re-pair.

They are scattered across `.env`, Authentik, n8n's encrypted credential store, and Evolution's own
state. **There is no single place to see "is connection X healthy, and where does its value come
from".** That is the whole pain.

### 4.2 How the professionals do it (research)

Three distinct layers in mature setups — **do not conflate them**:

- **Secrets manager** (text kind). Encrypted-at-rest KV with versioning, RBAC, audit, and an
  **agent/sidecar that injects secrets as env vars or files** into each service.
  - **Infisical** — MIT-licensed core, stack is **Postgres + Redis** (both already run here),
    gentle learning curve, has an **Agent** (`infisical run` / sidecar) that injects secrets as env
    or files with built-in caching + fallback, versioning, and dotenv import. Best fit for this repo.
    ([docs: Fetching Secrets](https://infisical.com/docs/documentation/platform/secrets-mgmt/concepts/secrets-delivery),
    [SDKs & Agent](https://deepwiki.com/Infisical/infisical/8.5-sdks-and-agent))
  - **OpenBao** — MPL-2.0 Linux-Foundation fork of Vault, API-compatible, dynamic secrets, but
    inherits Vault's operational weight (Raft, unseal). Overkill for a single VPS.
    ([OpenBao vs Vault, 2026](https://lalatenduswain.medium.com/openbao-vs-hashicorp-vault-the-secrets-management-showdown-every-devops-team-needs-to-read-in-2026-458ae0d9a408))
  - **HashiCorp Vault** — deepest but BUSL-licensed and heaviest; not worth the ops here.
    ([Vault alternatives, 2026](https://wetheflywheel.com/en/comparisons/hashicorp-vault-alternatives/),
    [GitGuardian top secrets tools](https://blog.gitguardian.com/top-secrets-management-tools/))
- **Integration / OAuth broker** (oauth kind). A service that owns the OAuth dance, **stores + auto-
  refreshes tokens**, and normalizes many providers behind one API.
  - **Nango** — open-source, self-hostable (Postgres control-plane), **managed OAuth + API-key + token
    refresh for 800+ providers**, encrypted credentials at rest, multi-tenant "connection" model,
    audit logs. This is the exact primitive for Google Drive/Gmail here.
    ([GitHub](https://github.com/nangohq/nango),
    [self-hosting](https://nango.dev/docs/guides/platform/self-hosting))
  - Pattern reference: **Unified.to / Apideck** normalize OAuth across 460+ APIs with a **single
    redirect URI** and per-connection encrypted token storage, and can even **bring-your-own secrets
    manager** so tokens live in *your* vault.
    ([Unified.to: normalizing OAuth](https://unified.to/blog/how_we_normalize_oauth_across_460_apis_at_unified),
    [BYO secrets manager](https://unified.to/blog/credential_management_in_unified_bring_your_own_secrets_manager))
- **Device/QR pairing** (paired kind). No standard product — it's app-specific (WhatsApp = Baileys
  QR → session files, perms `0600`). The professional move is: keep the pairing library, but **treat
  the resulting session as a secret** and store/rotate it in the same vault, surfacing the QR in your
  own UI. (Reference: OpenClaw stores channel auth + OAuth creds under `~/.openclaw/credentials`,
  `0600`. [architecture](https://ppaolo.substack.com/p/openclaw-system-architecture-overview))

**The env-fallback + install-prompt pattern** the user described is real and standard: Infisical's
agent has **built-in caching and fallback**, and both Infisical and Doppler support seeding a store
**from a `.env` import**, then failing/prompting when a *required* key is absent. We already do the
seed-from-env half in `credential_overrides:` — we just need the "required + prompt if missing" half.

### 4.3 The design for THIS repo

**One abstraction — the `Connection`:**

```jsonc
{
  "id": "google-workspace",          // stable, referenced by consumers (like n8n cred ids today)
  "kind": "oauth",                   // secret | oauth | paired
  "provider": "google",             // google | whatsapp | gemini | redis | priority | ...
  "title": "Google Workspace (Drive + Gmail)",
  "scopes": ["drive", "gmail"],
  "required_by": ["indox", "localdrive", "inbox"],  // drives the install wizard
  "source": "store",                 // store | env | unset  (where the live value came from)
  "value_ref": "infisical://prod/google_workspace",       // never the value itself in UI/logs
  "status": "healthy",              // healthy | degraded | expired | missing | never-connected
  "last_checked": "2026-07-09T…",
  "health": { "probe": "gmail:/labels", "ok": true }
}
```

- `secret` → value lives in **Infisical**; `value_ref` points at it.
- `oauth` → tokens live in **Nango**; `connections` stores only the Nango connection id + status,
  and proxies "get a fresh access token" calls (Nango handles refresh).
- `paired` → Evolution holds the session; `connections` mirrors the **session blob into Infisical**
  as a secret (so backups/restore are uniform) and renders the **QR** + "re-pair" button in-app.

**The resolution chain (the "stream from `.env`, ask on install" behaviour), enforced by one client:**

```
resolve(conn_id):
  1. STORE   — ask Infisical/Nango for the live value/token.           ← normal steady state
  2. .env    — if absent in store, read ${ENV_VAR} from .env and       ← friction-free first boot
               UPSERT it into the store (idempotent seed), then use it.   (declarative goal preserved)
  3. WIZARD  — if still absent AND the manifest marks it required,      ← install screen
               mark status=missing and surface it in the install wizard;
               the consuming service degrades gracefully / stays down.
```

Step 2 is precisely today's `credential_overrides:` generalized: on boot, a **seeder** walks the
manifest, and for every connection with an `${ENV}` mapping that isn't in the store yet, imports it.
Net effect: `git clone` + `.env` + `docker compose up` **still brings the stack live with zero
clicks** — the store is warm-started from `.env` — but from then on the *store* is the source of
truth, editable in the UI, versioned, and audited. Nothing regresses on the declarative promise.

**One client library, three transports.** Ship a tiny `connections-client` (Python first — every BFF
here is Flask/FastAPI) that wraps `resolve()` and a `/healthz`-style `check()`. Or, for zero-code
services, run the **Infisical agent as a sidecar** that injects resolved secrets as env vars — the
service keeps reading `os.environ` and never knows the difference. Offer both; sidecar for legacy,
client for first-party.

### 4.4 The `connections` UI (in the `console` shell)

- **List** every connection with a status pill (green/amber/red) and its `source` badge
  (`store` / `.env` / `unset`) — the single "is everything wired?" view that doesn't exist today.
- **secret** → masked value, "rotate", version history, "who/what uses this" (`required_by`).
- **oauth** → "Connect with Google" button → Nango popup → returns healthy; shows token expiry +
  "reconnect".
- **paired** → live **QR** (barcode) render + phone-pairing status + "re-pair"; exactly the WhatsApp
  flow the user cited, but now first-class and reusable for any future QR device.
- **health probes** per connection (e.g. inbox `/labels`, redis `PING`, gemini tiny call) so
  red means *actually* broken, not just "unset".

### 4.5 Why Infisical + Nango specifically (vs. build-your-own)

- You already run **Postgres + Redis + Authentik** — Infisical needs Postgres+Redis and can use
  Authentik as OIDC; Nango needs Postgres. **No new datastore classes.**
- Both are **self-hostable, OSS, encrypted-at-rest, audited** — you keep the "everything on one VPS,
  no external SaaS dependency" posture the repo insists on.
- Rolling your own AES-GCM store + OAuth refresh loop + token DB is a security liability and a
  maintenance sink; these two commoditize exactly that. `connections` stays a **thin orchestration +
  UI layer** on top, which is the right amount of custom code.

> Decision to confirm with the owner (see §8): full Nango may be heavy for *one* Google account —
> a ~200-line custom Google-OAuth handler could cover today's needs. Recommend **starting custom for
> Google, keeping the `oauth` kind's interface Nango-shaped** so we can swap in Nango when the number
> of OAuth providers grows past ~2.

---

## 5. Install screen (מסך התקנה)

A wizard, **driven by a manifest** — not hand-edited `.env`. Each service declares what it needs:

```yaml
# connections.manifest.yml  (one entry per Connection; the wizard + seeder both read this)
- id: gemini
  kind: secret
  env: GEMINI_API_KEY
  required_by: [indox, apitools]
  help: "Google AI Studio → API keys"
- id: google-workspace
  kind: oauth
  provider: google
  scopes: [drive, gmail]
  required_by: [indox, localdrive, inbox]
- id: whatsapp
  kind: paired
  provider: whatsapp
  required_by: [wadmin]
```

Wizard flow:
1. **Base settings** — domain, `DEPLOYMENT_NAME`, ACME email, timezone (today's `.env` head).
2. **Auto-detected from `.env`** — every manifest entry already satisfied by `.env` shows ✅ green,
   pre-filled, nothing to do (this is the "streams keys from `.env`" promise made visible).
3. **Only the gaps** — text fields for missing `secret`s, "Connect" buttons for missing `oauth`,
   QR panels for missing `paired`. Nothing else nags you.
4. **Verify** — run each connection's health probe; the installer is "done" when required ones are
   green. Mirrors the repo's existing "every push brings the stack up and asserts each app came up"
   verification ethos (README).

This makes the declarative goal *real for a human*: clone → the wizard shows what `.env` already
covered and asks only for the rest.

---

## 6. The other modules (thin wrappers, mostly)

- **notifications** — a small aggregator that reads the **GlitchTip API** (issues/events; DSNs already
  in `.env`), plus wadmin bot status and machine alerts, into one bell + feed in the shell. GlitchTip
  is Sentry-API-compatible, so this is a read-through, not a rebuild.
- **validation** — promote `feature-validation` (`fv.dev`) into the shell as the "system validation"
  tab: run suites, see green/red, gate releases. Reuses the existing validator services.
- **machine / any-concurrency** — already standalone dashboards; embed as modules (iframe first).
- **apps** — the `homepage` services grid becomes the shell's "apps" launcher, sourced from the same
  module registry that builds the nav.

---

## 7. Phased migration (small, verifiable steps — repo's "one perfect example → scale" rule)

1. **`connections` MVP, read-only.** Stand up Infisical; write the `connections` service + manifest;
   implement `resolve()` with the store→`.env`→unset chain; build the status list UI. Seed from `.env`.
   *Nothing else changes yet* — pure additive, zero blast radius. Validate that every existing service
   still boots with the seeder warming the store.
2. **Cut ONE consumer over.** Pick `inbox` (single app-password, low risk): it resolves
   `GMAIL_IMAP_APP_PW` via `connections` instead of raw env. Prove the sidecar/client path end-to-end.
3. **OAuth kind.** Implement Google via custom handler behind the Nango-shaped interface; move
   Drive/Gmail off the manual `setup-google-cloud-login.md` flow.
4. **paired kind.** Bring WhatsApp QR into the `connections` UI; mirror the Evolution session into the
   vault.
5. **`console` shell.** Build the portal chrome + design tokens; fold `homepage` in as the landing
   module; iframe wadmin/portainer/redisinsight/glitchtip under the shared nav.
6. **Federate first-party SPAs** (morning, localdrive, mailview) into the shell.
7. **Install wizard** on top of the now-complete manifest.
8. **Generalize `credential_overrides`.** Point n8n's seeder at `connections` so n8n creds and the
   rest of the estate share one source of truth — retire the duplicate mechanism.

Each step is independently shippable and independently reversible.

---

## 8. Open decisions for the owner

1. **OAuth broker:** start with a **custom Google handler** (Nango-shaped interface) and adopt full
   **Nango** later, or stand up Nango now? (Recommend custom-first; §4.5.)
2. **Secret store:** **Infisical** (recommended, Postgres+Redis you already run) vs. OpenBao vs. keep
   a bespoke encrypted table? (Recommend Infisical.)
3. **Shell integration depth:** iframe-everything first (fast, ugly seams) vs. invest in Module
   Federation for first-party SPAs up front? (Recommend iframe-first, federate the 3 first-party
   SPAs in phase 6.)
4. **Naming/branding** of the unified app (`console`? "BINA"? מרכז?) and its route (`home.<dom>` vs a
   new `app.<dom>`).
5. **Scope of v1:** is the real near-term win **just the `connections` service + install wizard**
   (the stated pain), deferring the full shell/federation? (I lean yes — ships the highest-value
   piece first.)

---

## Sources (research)

- Infisical — [Fetching Secrets / delivery](https://infisical.com/docs/documentation/platform/secrets-mgmt/concepts/secrets-delivery),
  [SDKs & Agent (DeepWiki)](https://deepwiki.com/Infisical/infisical/8.5-sdks-and-agent),
  [OSS secrets mgmt for DevOps 2026](https://infisical.com/blog/open-source-secrets-management-devops)
- OpenBao vs Vault — [2026 comparison](https://lalatenduswain.medium.com/openbao-vs-hashicorp-vault-the-secrets-management-showdown-every-devops-team-needs-to-read-in-2026-458ae0d9a408),
  [Vault alternatives 2026](https://wetheflywheel.com/en/comparisons/hashicorp-vault-alternatives/),
  [GitGuardian: top secrets tools](https://blog.gitguardian.com/top-secrets-management-tools/)
- Nango — [GitHub](https://github.com/nangohq/nango),
  [self-hosting](https://nango.dev/docs/guides/platform/self-hosting),
  [best self-hosted integration platforms](https://nango.dev/blog/best-self-hosted-api-integration-platforms-for-ai-agents/)
- Unified API / OAuth normalization — [normalizing OAuth across 460+ APIs](https://unified.to/blog/how_we_normalize_oauth_across_460_apis_at_unified),
  [bring-your-own secrets manager](https://unified.to/blog/credential_management_in_unified_bring_your_own_secrets_manager),
  [handling OAuth across many integrations](https://unified.to/blog/how_to_handle_oauth_across_many_integrations)
- QR/device pairing reference — [OpenClaw architecture](https://ppaolo.substack.com/p/openclaw-system-architecture-overview)

## Anchors in this repo (what we build on, not around)

- `production/n8n/blueprint.yml` → `credential_overrides:` — the existing `.env`→credential seeder to generalize.
- `production/morning/app.py` → `/api/me` reading `X-authentik-*` — the shared-identity pattern.
- `production/localdrive/app.py` docstring — "morning/פנקס-styled RTL SPA" — the informal design system.
- `production/homepage/config/services.yaml` + Docker labels — the module/apps auto-registry.
- `ai/context/deployment-context.txt` — service/route/auth inventory.
- `ai/context/setup-google-cloud-login.md`, `gmail-onboardin-imap-stmp.md` — the OAuth/app-password pain this replaces.
</content>
</invoke>
