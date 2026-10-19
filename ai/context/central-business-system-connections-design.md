# The Connections Service — deep design: key-dependency model, the declarative contract, and a build plan

Companion to `central-business-system-plan.md` (the vision) and `-master-map.md` / `-keys.md` (the
inventory). This doc answers three questions the owner raised:
1. How do you **correctly manage key/credential dependencies** across different parts of a system?
2. How do the **different services know what credentials to expect**?
3. Can we build **one central, fully-declarative secrets service** that supports **text keys, OAuth,
   and QR/barcode keys**, and lets you **add a connection to any service in the world**?

Short answer to (3): **yes** — and the right shape is a **thin declarative orchestrator over proven
engines**, not a from-scratch crypto/OAuth rebuild. The design is below.

---

## 1. Managing key DEPENDENCIES correctly (the five mechanisms)

"Dependency in keys" shows up in five distinct forms. A correct system names and handles each; this repo
already does two of them by accident, which is the seed to generalize.

### (a) Secret composition / references — one secret derived from another
Some values are **not independent** — they're computed from a base secret. Professional stores make this
first-class via **secret referencing / interpolation**: Infisical resolves `${SECRET}` (same
env+folder), `${env.path.KEY}` (cross-env), and recursively (bounded depth), reconstructing the value
**client-side** so the reader must have permission to every base secret in the chain
([Infisical secret referencing](https://infisical.com/docs/documentation/platform/secret-reference),
[internals](https://deepwiki.com/Infisical/infisical/4.3-secret-references-and-interpolation)).
- **This repo already has derived secrets**, just hand-rolled: GlitchTip DSNs = `sha256(GLITCHTIP_SECRET_KEY:<project>)`; Supabase `ANON_KEY`/`SERVICE_KEY` = JWTs signed by `SUPABASE_JWT_SECRET`; `N8N_DB_DSN` assembled from `POSTGRES_*`. Today those are recomputed by imperative push scripts. **In a connections
service they become declared references** — store only the root (`GLITCHTIP_SECRET_KEY`,
`SUPABASE_JWT_SECRET`, `POSTGRES_PASSWORD`), and the derived ones are computed on read. Fewer secrets to
manage, and rotating the root auto-propagates.

### (b) Dependency ordering — who must be ready before whom
A service can't boot until *its* credentials exist **and** the services they point at are up. That's a
**DAG**, and the manifest's `required_by` is exactly the edge list:
`inbox → GMAIL_IMAP_APP_PW`; `incoming-docs → {google-workspace(oauth), gemini, supabase, redis}`;
`morning → {ledger-backend, authentik}`. The repo already encodes a hand-built version of this: `bbox
run` gives **Authentik a head start** and `--wait`s on the SSO readiness sentinel before other gated apps
are useful; `bbox onboarding` waits for n8n REST to truly serve before pushing. **Generalize:** the
connections manifest yields the dependency graph → the installer/orchestrator brings connections up in
topological order and only marks a service "ready" when its required connections are **healthy**, not
merely "present."

### (c) The bootstrap / "secret zero" problem
The central store itself needs one credential to unlock — *where does that come from?* Every serious
system faces this ([Infisical: the secret-zero problem](https://infisical.com/blog/solving-secret-zero-problem)).
Solutions, cheapest-first for a single self-hosted VPS:
- **Root key from the host** — one master key in the host `.env` / a `0600` file / systemd credential,
  used only to unlock the vault; everything else lives *in* the vault. (Vault/OpenBao formalize this as
  Shamir-split unseal keys + a master key.)
- **Machine identity** — Infisical's Universal Auth (Client ID + Client Secret) or cloud-native identity;
  a service authenticates *as itself* to fetch its own secrets, so no long-lived secret sits in the app
  ([Infisical machine identity / ESO](https://external-secrets.io/latest/provider/infisical/)).
- **Practical rule:** minimize secret-zero to exactly ONE value; never let "the key that unlocks the
  keys" be one of the ~30 hand-edited `.env` values.

### (d) Static vs dynamic secrets (and leasing)
- **Static** — an API key/password that exists until rotated (most of this estate: Gemini, OpenAI, app
  passwords). Store, inject, rotate on schedule.
- **Dynamic** — generated **on demand**, short-lived, **auto-revoked** by TTL. Vault/OpenBao **secret
  engines** do this: a client reads a DB cred, gets a `lease_id` + TTL; a background renews within the
  window; on expiry the engine revokes the underlying credential
  ([OpenBao/Vault dynamic secrets](https://developer.hashicorp.com/vault/docs/secrets/databases),
  [engines overview](https://www.infralovers.com/blog/2025-05-21-vault-secret-engines/)). Blast radius
  shrinks because a leaked cred dies in minutes.
- **Recommendation here:** static for almost everything (simplicity fits a single-business install).
  Consider dynamic **only** for Postgres/Supabase creds later, and only if you adopt OpenBao. Don't take
  on Vault's operational weight just for this.

### (e) Rotation & propagation
Rotating a base secret must invalidate caches and re-push to every consumer. Mechanisms: an **agent/
sidecar that re-fetches** on a poll/TTL (Infisical agent has caching + fallback); a **webhook** on
change; or **derived-secret recompute** (rotate `SUPABASE_JWT_SECRET` → ANON/SERVICE keys regenerate).
Consumers must tolerate a value changing under them (reconnect, not crash).

---

## 2. How services KNOW WHAT TO EXPECT (the declarative contract)

The clean answer everywhere: **each service ships a schema of the config/credentials it requires, and
validates it at boot.** In Node that's Zod/envalid/convict/znv; the pattern: define a schema, parse
`process.env` against it *before anything else runs*, and **the app refuses to boot on a missing/
misconfigured required var — a clear error in dev/CI, not a broken runtime**
([Zod env validation](https://catalins.tech/validate-environment-variables-with-zod/),
[znv](https://github.com/lostfictions/znv)). The schema doubles as documentation: it tells a human (and
the installer) exactly what the service accepts.

For a **connections** service this schema is elevated to a **per-service connection manifest** — the same
idea, but the "type" of each entry is a connection *kind*, and the manifest is machine-read by the
installer, the dependency graph, and the health dashboard, not just the app:

```yaml
# each consumer service declares what it needs — this IS "what to expect"
service: incoming-documents
requires:
  - id: google-workspace   kind: oauth   scopes: [drive, gmail]   required: true
  - id: gemini             kind: secret                            required: true
  - id: supabase           kind: derived  from: SUPABASE_JWT_SECRET required: true
  - id: redis              kind: secret                            required: true
optional:
  - id: document-ai        kind: oauth                             required: false
```

So "how does a service know what to expect" has one answer: **it declares it, in a schema the platform
reads.** Three payoffs from one declaration: (1) **fail-fast boot** if a required connection is
missing/unhealthy; (2) the **install wizard** builds its "only ask for the gaps" list from the union of
all `requires`; (3) the **dependency DAG** (§1b) is the union of `required_by`. This is the exact
generalization of the repo's existing `credential_overrides` (which already declares, per n8n credential,
which `${ENV}` fills it) — lifted from "n8n only" to "every service."

---

## 3. What the candidate tools ACTUALLY do (so we integrate them for the right reason)

Three tools, three **different layers** — they are complementary, not alternatives. Knowing precisely
what each does is what lets us decide build-vs-compose.

### Infisical — the text-secret vault + delivery layer
- Encrypted KV organized as **projects → environments → folders → secrets**, with **versioning, RBAC,
  audit**.
- **Secret referencing** (`${...}`, cross-env, recursive) — the composition mechanism from §1a, built in.
- **Machine identities** (Universal Auth / cloud-native) — the secret-zero answer from §1c.
- **Delivery**: `infisical run` injects secrets as env into a process (nothing on disk); the **agent/
  sidecar** renders to env or files with **caching + fallback**; **dotenv import** to seed from `.env`;
  **External Secrets Operator** integration ([ESO provider](https://external-secrets.io/latest/provider/infisical/)).
- **Dynamic secrets** for DBs, PKI/KMS. Stack: **Postgres + Redis** (already running here). MIT core.
- **What it does NOT do:** the OAuth consent dance, a provider catalog, or WhatsApp QR pairing.

### Nango — the OAuth broker + "any API in the world" catalog
- The heart is **`providers.yaml`** — a **declarative catalog of 800+ APIs**. Each entry declares
  `auth_mode ∈ {API_KEY, BASIC, OAUTH1, OAUTH2, OAUTH2_CC, APP, JWT, TWO_STEP, SIGNATURE, TBA, CUSTOM,
  NONE}`, plus `authorization_url` / `token_url` / `scopes`, proxy `base_url`, pagination, categories
  ([providers.yaml reference](https://nango.dev/docs/reference/api-configuration),
  [the file](https://github.com/NangoHQ/nango/blob/master/packages/providers/providers.yaml)). **This is
  precisely the "add a connection to any service in the world" primitive** — a new integration is a YAML
  entry, not code.
- **Managed OAuth**: runs the consent redirect, **stores + auto-refreshes tokens**, exposes them via a
  proxy or SDK; multi-connection model; encrypted at rest; self-hostable (Postgres control plane).
- **What it does NOT do:** be a general text-secret vault for the *rest* of your infra secrets, or QR
  device pairing.

### OpenBao / HashiCorp Vault — the heavy dynamic-secrets engine
- **Secret engines** (KV, **database**, **PKI**, **transit** = encryption-as-a-service) + **dynamic
  secrets with leasing** (TTL, renew, auto-revoke) + Shamir-unseal master key
  ([engines](https://www.infralovers.com/blog/2025-05-21-vault-secret-engines/),
  [OpenBao vs Vault 2026](https://wetheflywheel.com/en/comparisons/openbao-vs-hashicorp-vault/)).
- OpenBao = MPL-2.0 fork, same API, community namespaces. **Powerful but operationally heavy** (Raft,
  unseal) — overkill for one VPS unless you specifically want dynamic DB creds/PKI.

**The gap none of them fills alone:** our three kinds (text + oauth + **QR**) don't live in a single
product, and WhatsApp QR pairing has no off-the-shelf broker. That gap is the reason to build a thin
orchestrator — see §5.

---

## 4. Can we build ONE fully-declarative central service for text + oauth + qr + "any service"? — Yes

The architecture is four declarative layers + one small runtime. Nothing here is speculative — each layer
maps to a proven primitive above.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 1. PROVIDER CATALOG  (git, declarative — the "any service in the world" layer)      │
│    providers/*.yaml — one entry per provider, Nango-model:                           │
│      auth_mode ∈ { text | api_key | basic | oauth2 | oauth1 | qr_pair | derived |    │
│                    none }                                                            │
│      + authorize_url/token_url/scopes (oauth) | pair_endpoint/session_path (qr) |    │
│        derive:{from, fn} (derived) | health_probe                                    │
│    Adding "connect to X" = adding one YAML entry. Seeded from Nango's providers.yaml.│
├──────────────────────────────────────────────────────────────────────────────────┤
│ 2. CONSUMER MANIFEST (git, declarative — the "what to expect" layer, §2)             │
│    per service: requires:[{id, kind, scopes?, required, env?}]  → wizard + DAG +     │
│    fail-fast boot validation.  Generalizes n8n credential_overrides.                 │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 3. CONNECTION STORE  (per business — the VALUES; the only non-git state)             │
│    connection = {id, provider, kind, status, value_ref, derived?, health, updated}   │
│    values live in the vault; the service stores refs + status, never raw values.     │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 4. RESOLVER + INJECTOR  (runtime)                                                    │
│    resolve(id): STORE → .env-seed → wizard-prompt   (the friction-free chain)        │
│    inject: sidecar (env) for legacy | client lib for first-party                     │
└──────────────────────────────────────────────────────────────────────────────────┘
        backends it delegates to (don't rebuild):
        text/derived/rotation → Infisical (or OpenBao)   oauth → Nango-model broker
        qr → custom Baileys pairing module (session mirrored into the vault as a secret)
```

**Why this is "fully declarative":** the two things that define behavior — the **provider catalog** and
the **consumer manifest** — are git YAML (source of truth, exactly the repo's blueprint ethos). The only
non-declarative state is the **values**, and even those are *seeded declaratively from `.env`* and, once
set, versioned + auditable in the vault. So `clone → up` still works with zero clicks (values warm-start
from `.env`), and the install wizard only appears for genuinely-absent required connections.

**Why it supports "any service in the world":** because a provider is *data*, not code — `auth_mode`
covers every real pattern (Nango's enum is the proof it generalizes to 800+ APIs). Text key? one entry.
New OAuth SaaS? one entry with `authorize_url`/`scopes`. A QR device? `auth_mode: qr_pair` with a pairing
module. Odd bespoke auth? `auth_mode: custom` + a tiny handler. You never touch the core to add a
connection.

---

## 5. Build vs compose — the honest recommendation

**Don't rebuild crypto, OAuth refresh, or a token DB — those are commodity and dangerous to hand-roll.
Do build the thin orchestration + the QR module + the manifest/catalog contract + the one UI.** Concretely:

| Layer | Decision | Rationale |
|---|---|---|
| text-secret storage, encryption, versioning, references, rotation, secret-zero | **Compose: Infisical** | It already does §1a/§1c/§1e; Postgres+Redis already run here; MIT. |
| oauth broker + provider catalog (any-service) | **Adopt the Nango model** — start with a small custom OAuth handler behind a Nango-shaped interface + seed the catalog from Nango's `providers.yaml`; swap in full Nango when providers > ~2 | Owning Google's client + refresh is ~200 lines; Nango's catalog is the reusable asset. |
| qr-session (WhatsApp) | **Build** a small pairing module (keep Baileys) that surfaces the QR and **mirrors `auth_info` into the vault** | No product does this; it's small and specific. |
| dynamic DB creds / PKI | **Defer** (optionally OpenBao later) | Not worth the ops now. |
| the `connections` orchestrator: catalog + manifest loader, resolver chain, dependency DAG, health probes, install wizard, one RTL UI | **Build** (this is the actual product surface) | This is the glue no tool provides; it's where "our" value is. |

So "can *you* develop a central secrets service that supports all we need, fully declarative, add-any-
connection?" — **Yes**, and the smallest correct version is a ~single-service orchestrator (Python/Flask
to match the estate, or Node to reuse Nango's providers.yaml + Zod schemas) that **delegates storage to
Infisical and OAuth to a Nango-model broker**, owns a QR module, and is driven by two git YAML files
(catalog + manifest). That is buildable incrementally and each piece is independently shippable.

---

## 6. Concrete data model + resolution algorithm

```jsonc
// provider (catalog, git)
{ "provider": "google-workspace", "auth_mode": "oauth2",
  "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
  "token_url": "https://oauth2.googleapis.com/token",
  "scopes": ["https://www.googleapis.com/auth/drive", ".../gmail.modify"],
  "health_probe": "gmail:/labels" }

// connection (store, per business)
{ "id": "google-workspace", "provider": "google-workspace", "kind": "oauth",
  "status": "healthy", "value_ref": "nango://prod/google-workspace",
  "source": "store", "health": {"ok": true, "checked": "2026-07-09T…"} }
```

```
resolve(id):
  c = store.get(id)
  if c and vault.has(c.value_ref):      return vault.read(c.value_ref)        # 1. STORE
  if manifest[id].env and env[manifest[id].env]:                              # 2. .env seed
        v = env[manifest[id].env]; vault.upsert(id, v); store.mark(id,'env'); return v
  if derived(id):                        return recompute(id)                 # derived, never asked
  if manifest[id].required:              store.mark(id,'missing'); wizard.enqueue(id); raise Missing
  return null                                                                 # optional, absent
```

Health for `status`: run the provider's `health_probe` (gmail `/labels`, redis `PING`, gemini tiny call,
whatsapp = is `auth_info` paired). Green = actually works; red ≠ merely unset.

---

## 7. Minimal buildable v1 (what can be scaffolded now)

1. `connections` service (read-only) + `providers/*.yaml` (start: google-workspace, gmail-app-password,
   gemini, openai, supabase[derived], redis, whatsapp[qr]) + `manifests/*.yaml` for 2–3 consumers.
2. Stand up Infisical (compose stack next to authentik); implement the `resolve()` chain with `.env` seed
   (generalizing `credential_overrides`).
3. Status-list RTL UI (source badge store/.env/unset + health pill) — the single "is everything wired?"
   view that doesn't exist today.
4. Cut `inbox` over as the first consumer (one app-password, low risk); prove sidecar injection.
5. Add the OAuth handler (google) and the QR module (whatsapp) behind their catalog entries.

Each step is additive and reversible; nothing existing changes until a consumer opts in.

---

## Sources
- Nango providers.yaml: [reference](https://nango.dev/docs/reference/api-configuration) · [file](https://github.com/NangoHQ/nango/blob/master/packages/providers/providers.yaml) · [auth guide](https://nango.dev/docs/guides/auth/auth-guide)
- Infisical: [secret referencing](https://infisical.com/docs/documentation/platform/secret-reference) · [interpolation internals](https://deepwiki.com/Infisical/infisical/4.3-secret-references-and-interpolation) · [secret-zero](https://infisical.com/blog/solving-secret-zero-problem) · [ESO/machine identity](https://external-secrets.io/latest/provider/infisical/)
- OpenBao/Vault: [database secrets engine](https://developer.hashicorp.com/vault/docs/secrets/databases) · [engines overview](https://www.infralovers.com/blog/2025-05-21-vault-secret-engines/) · [OpenBao vs Vault 2026](https://wetheflywheel.com/en/comparisons/openbao-vs-hashicorp-vault/)
- Config schema contract: [Zod env validation](https://catalins.tech/validate-environment-variables-with-zod/) · [znv](https://github.com/lostfictions/znv)
</content>
