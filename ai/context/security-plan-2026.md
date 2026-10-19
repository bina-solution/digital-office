# bbox — Penetration Test & Public-Security Blueprint (2026)

Role: acting security lead. Scope: the whole `deployment-hacohen` estate on a public VPS.
Method: source review + live probing of the running staging box. Every CRITICAL below was
**observed live or read at file:line**, not inferred. This document is the go-live gate.

---

## PART 1 — PENTEST FINDINGS (how a real attacker gets in)

A pentest firm ranks by *what an attacker needs first*. Three tiers:

### Tier A — Pre-auth, internet-facing, NO foothold needed (a scanner finds these day 1)

| ID | Finding | Proof | What it gives |
|----|---------|-------|---------------|
| **A1** | `apitools` publicly routed with **no authentik** | `compose.override.yml:328-347`; middleware is `apitools-retry`, not `authentik` | `GET /customers`, `/reports/pcn874` (VAT report), `POST /documents/<id>/send` (mails an invoice as the business) — the whole ledger, unauthenticated |
| **A2** | Supabase REST public over **plain HTTP**, **RLS off**, `anon` has DELETE/TRUNCATE | `supabase/docker-compose.yml:226-231`; live DB `rowsecurity=f` on all 19 tables | Unauthenticated read **and delete** of every business row, in cleartext |
| **A3** | **Email → total secret theft** (SSRF chain) | `syncV3Deliver0001.json:684,699` fetch the first URL in an email body with no allowlist → uploaded to the deliberately-public `/file/d/<oid>/view` | Email the mailbox a link to `http://connections:8990/api/export-all?format=env`; the platform fetches every secret and republishes it on a public Drive link |
| **A4** | Port 80 is a **parallel ungated ingress** | live: `machine`,`redisinsight`,`apitools` → **HTTP 200, no auth**; no global 80→443 redirect | SSO is bypassed by typing `http://`; also enables cleartext cookie/credential capture |
| **A5** | `machine` leaks host recon unauthenticated | live: `/api/overview` → hostname `srv908573`, exact kernel `6.1.0-49-cloud-amd64` | A CVE shopping list handed to anyone |

### Tier B — Post-foothold amplifiers (once an attacker is on the docker network — A3 or any RCE gets them there)

| ID | Finding | Proof | What it gives |
|----|---------|-------|---------------|
| **B1** | `connections` has **zero** app-layer auth ⟶ **partly remediated, see below** | `app.py`: 0 `before_request`, 0 token checks in 1004 lines | Any container: `GET /api/export-all?format=env` → **every secret** *(proven live: 200, 2953 bytes, from an unrelated container)* |

> **B1 status (credential broker, roadmap item 2).** `/api/export-all` is now **loopback-only** in
> every mode but `off`, which breaks the headline kill chain at its final step. `/api/export/<svc>`
> and the new `/api/broker/lease` identify the caller over the docker socket and refuse any request
> for another service's secrets or for a connection the caller's `app.json` does not declare — in
> `warn` mode as well as `enforce`. What is NOT yet closed: `CONN_BROKER_MODE` still defaults to
> `warn`, so a caller the broker cannot *identify at all* is still served (and logged as
> `unidentified`); container identity rests on source IP + a proved container id, neither of which is
> a cryptographic credential; and `/api/instances/*` is logged but not gated. See
> `platform-base/connections/README.md` for the full residual-risk statement.
| **B2** | Vault encrypted with a **repo-published constant** | `app.py:35` + `docker-compose.yml:20` default `dev-root-key-not-for-production`; **absent from `.env.ex`** | *(proven: auditor decrypted the live vault)* — encryption is decorative |
| **B3** | `Portainer` ungated on **both** schemes + `rw` docker.sock | `portainer/docker-compose.yml:15`; no authentik on `-http` or `-https` | Container escape → **root on the host** |
| **B4** | `browser42` runs untrusted internet JS **on the shared network** | `browser42/docker-compose.yml:63` joins `traefik-network` | A malicious page is already inside the trust boundary (feeds B1) |

### Tier C — Requires repo access (insider / supply-chain / if repo ever leaks)

| ID | Finding | Proof | What it gives |
|----|---------|-------|---------------|
| **C1** | **~30 real secrets committed to `.env.ex`, identical on every install** | commit `a52d811` (2026-07-12) added them **and deleted `scripts/secrets-ensure.sh`** (the per-install minting) | `AUTHENTIK_SECRET_KEY` (forge any session — defeats every edge gate), `N8N_ENCRYPTION_KEY`, `SUPABASE_SERVICE_KEY`, live `N8N_API_KEY` JWT, `akadmin` password |
| **C2** | Prompt-injection → **SQL injection** via `$$` dollar-quoting | `indoxV2ExtractInvoiceGemini01.json:368` writes `$${{JSON.stringify($json)}}$$` where `$json` is Gemini output; `JSON.stringify` escapes quotes but not `$` | A crafted invoice field runs arbitrary SQL under the n8n Postgres cred |
| **C3** | Filename alone re-attributes a document to any company | `indoxV2FigureCompanyId01.json:734` unanchored `NAME.includes()`, pre-OCR → routes to `Post Priority Table` (`ActionsGDoc01:856`, `jsonBody:{{$json.toJsonString()}}`) | `invoice-VictimCorp.pdf` posts into the **production Priority ERP** under the victim's company |
| **C4** | Real business PII committed to git | `production/n8n/demo-docs/` — 204 files: real Israeli company IDs, supplier emails, live Gmail/Drive links | Privacy breach the moment the repo is shared |

### The headline kill chain (all verified links)
> Attacker emails the office a link (A3) → platform fetches `connections/api/export-all` (B1),
> unauthenticated → gets every secret, incl. `AUTHENTIK_SECRET_KEY` (C1) → forges an admin SSO
> session → owns the estate. **No exploit, no CVE, no credential. One email.**

### What is genuinely NOT vulnerable (so we don't waste effort)
- Header spoofing of `X-authentik-*` — traefik strips+resets them (`compose.override.yml:462`). Defensive-fix only.
- SQLi in **application** code — absent; localdrive/notifications/supabase_transport are parameterized. (The one SQLi is C2, in a workflow.)
- Path traversal, `eval`/`pickle` sinks — absent.
- n8n credential blobs — `"data":""`, env-injected, not decryptable exports.
- Audit trail logs no secret values; `mask()` truncates; 5432/6379 have a real IP allowlist.

---

## PART 2 — REMEDIATION BY DOMAIN (with honest breakage risk)

Breakage scale: **NONE** (config an attacker sees but no legit caller uses) ·
**LOW** (one call path, easily verified) · **MED** (multiple consumers, needs a map first) ·
**HIGH** (touches a boot path or destroys data if wrong — stage it).

### DOMAIN 1 — Internet edge (closes A1, A4, A5)
| Change | Breakage risk | Why / how to de-risk |
|---|---|---|
| Add `authentik` middleware to `apitools-https` | **MED** | In-network callers use `http://apitools:8080` (bypass traefik) — unaffected. Risk = any consumer calling apitools via its **public** URL without a cookie. **De-risk:** grep every service for the public apitools host first; keep specific machine-to-machine paths on a token-authed route, not open. |
| Global 80→443 redirect **on domain deploys only** | **MED** | Local/CI run `*.localhost` over **http by design** — a blanket redirect breaks them. **De-risk:** gate the redirect on `DEPLOYMENT_DOMAIN != localhost` (env-driven), so local/CI are untouched. Also exempt the OAuth loopback + browser42's intentional http route. |
| Put `machine` behind authentik (both schemes); stop leaking kernel in `/api/overview` | **LOW** | `machine` is an operator dashboard; no service calls it machine-to-machine. Redact host/kernel in the API. |

### DOMAIN 2 — Data plane (closes A2)
| Change | Breakage risk | Why / how to de-risk |
|---|---|---|
| Enable RLS on all tables + revoke `anon` DML | **HIGH** | This is the one that can silently break writes. **De-risk (mandatory order):** (1) map every consumer's DB role — `service_role` bypasses RLS (safe), `anon` from a browser breaks. (2) INDOX writes to **Sheets**, not supabase (verified) — so INDOX is safe. (3) my-docs/ledger uses supabase — confirm it's server-side `service_role` before touching. (4) enable RLS with permissive policies first, watch for denials, then tighten. Never flip in one step. |
| Move supabase REST to `websecure` + authentik-or-JWT, kill the plain-http route | **MED** | Same-origin console embeds go through the proxy; direct browser use of the anon key must move to https. Verify no asset ships the anon key (audit says none does). |

### DOMAIN 3 — Credential plane (closes B1, B2) — *this is the secret-base work in Part 3*
| Change | Breakage risk | Why / how to de-risk |
|---|---|---|
| `CONNECTIONS_ROOT_KEY` mandatory, fail-closed, no default | **LOW** | Generated per-install by `secrets-ensure` (Part 3). **De-risk:** fail-closed means "refuse to boot without it", which is loud, not silent. Also fix `vault_read()` swallowing decrypt errors → surface them (a wrong key must error, not empty the vault). |
| Authenticate the `connections` API (service token) | **HIGH** | Every consumer boots by calling `connections` unauthenticated (`inject.sh:11`). **De-risk with a 2-phase rollout:** Phase 1 — accept BOTH authed + unauthed, log unauthed callers (find them all, zero breakage). Phase 2 — distribute the token to every consumer, verify logs are clean. Phase 3 — enforce (reject unauthed). Never flip straight to enforce. |

### DOMAIN 4 — Isolation (closes B3, B4)
| Change | Breakage risk | Why / how to de-risk |
|---|---|---|
| Portainer behind authentik (both schemes) | **LOW** | Operator-only UI. |
| Move `browser42` off `traefik-network` onto its own egress network | **MED** | It currently reaches services by hostname. **De-risk:** it only *needs* to reach the internet + its own MCP/caddy; give it a dedicated network and an explicit allowlist for the few internal hosts (if any) it must reach. Verify the MCP flow still works. |
| `inject.sh`: delete `/tmp/conn.env` after sourcing | **LOW** | It's read once at boot; removing it after removes a plaintext secret file from every consumer. |

### DOMAIN 5 — AI / document pipeline (closes A3, C2, C3)
| Change | Breakage risk | Why / how to de-risk |
|---|---|---|
| **`Download Link` URL allowlist** (block RFC1918 + internal docker hostnames + require https) | **LOW** | Legit provider links are public https — permitted. **This single change breaks the A3 kill chain.** De-risk: allow-by-default for public https, deny only private/internal targets. |
| Route the two cache-writer extractors through the **existing** parameterized writer (`indoxApiSupabase01.json:384`) | **MED** | Workflow surgery under active dev. **De-risk:** the correct pattern already exists in-repo — copy it; verify via the INDOX e2e suites that extraction cache still writes. Failure mode is a cache miss (re-OCR), not data loss. |
| Anchor `NAME.includes()`; a filename must never attribute alone; whitelist ERP fields instead of `toJsonString()` | **MED** | Changes attribution logic. **De-risk:** require filename match to agree with OCR/company-ID, not override it; send an explicit field list to Priority, not the whole object. Verify against known-good docs in the corpus. |
| Fence document text from instructions (wrap OCR text, keep it out of `role:model`) | **LOW** | Defense-in-depth; output is already lookup-bounded for company. |

### DOMAIN 6 — Privacy / compliance (closes C4 + regulatory) — *your decisions*
| Change | Breakage risk | Owner |
|---|---|---|
| Purge `production/n8n/demo-docs/` (204 real-PII files) from working tree **and history**; replace with synthetic | **LOW** (tests use fixtures) | me |
| Enable n8n execution pruning (config is inert — read un-prefixed) + set retention on `ocr_cache`/`ai_extraction_cache` | **LOW** | me |
| **Appoint a DPO** (mandatory since Oct 2025 — you are in violation now) | — | **you** |
| Commission a pen test (18-month cadence for large sensitive DBs) + a Google cross-border **data-transfer agreement** for Gemini | — | **you** |

### DOMAIN 7 — Recovery
| Change | Breakage risk | Why |
|---|---|---|
| Rotate every value currently in `.env.ex` on hacohen-vps | **HIGH** | Rotating `N8N_ENCRYPTION_KEY` orphans stored creds (re-consent Google); `AUTHENTIK_SECRET_KEY` logs everyone out; `CONNECTIONS_ROOT_KEY` empties the vault if not re-encrypted. **Must** be done by the orchestrated rotation flow (Part 3), never a blind value swap. |
| Verify git history for `GOCSPX-`/`AIzaSy`/`sk-ant-` (my scan timed out — unverified) | — | Before the repo is ever opened. History is forever. |

---

## PART 3 — SECRET-BASE CONSOLIDATION (your rotate-button vision)

**Principle:** secret-base owns the *lifecycle*; `.env` stays the *seed + escape hatch*. Both keep
working. The resolution order already in the code — **vault → .env seed → wizard** — is the whole
design; we make it authoritative and add lifecycle on top.

### Three secret classes (the catalog already has the metadata: `kind`, `consumers`, `impact`, `rotate_warn`)
1. **Machine secrets** — passwords/keys/tokens the platform owns. *Generatable.* → one-click rotate.
2. **External secrets** — Google OAuth, API keys. *User-provided.* → rotate = re-enter / re-consent.
3. **Meta secret** — `CONNECTIONS_ROOT_KEY`. Unlocks the vault, so it **cannot** live in the vault;
   lives in `.env` only, generated per-install, fail-closed.

### `secrets-ensure` (restore + extend the deleted script) — keeps env-driven alive
- On `bbox run`: for each machine secret that is empty/placeholder in `.env`, generate `openssl rand`
  and write it to `.env` (host-local, gitignored). **Values are stable per install, unique per
  customer** — exactly the stability `a52d811` wanted, without the shared-secret trade.
- **CI unchanged:** `ci-env.sh` still mints random per-run. **Local unchanged:** same script fills
  placeholders. So env-driven deploys (CI/CD, local PC) keep working with zero new steps.
- `.env.ex` becomes **100% placeholders** — committing it can never leak a real secret again.

### The UI (consolidate all secret logic into secret-base's console pane)
- **Per secret:** value (masked) · source badge (vault / env / generated) · health dot (live probe) ·
  `impact` ("unlocks: n8n creds") · **Rotate** button.
- **Rotate (single):** generate new value → write vault + `.env` → restart only the `consumers`
  listed in the catalog → re-probe → show green. For a coupled secret (e.g. `N8N_ENCRYPTION_KEY`)
  the button first shows the `rotate_warn` ("this re-consents Google") and runs the migration, not a
  blind swap.
- **"Rotate all machine secrets"** (your secure button): does the above for class-1 secrets in
  dependency order, skipping external/meta, with a dry-run preview of blast radius first.
- **Breach mode:** one action that rotates everything rotatable and lists what needs manual
  re-consent — the recovery capability that does not exist today.

### Why this satisfies every constraint
- Public-safe: no real secret in git, ever.
- Multi-tenant-safe: each install's secrets are unique → customer A can't touch customer B.
- Env-driven preserved: CI/CD + local still seed from `.env`.
- Consolidated: one pane owns view + health + rotate; no tribal knowledge.

---

## PART 4 — GO-LIVE GATE & TIMELINE

**"Public tomorrow" — the honest answer, split by what "public" means:**

- **Single-tenant Hacohen, private repo, tomorrow:** achievable IF Tier A closes first. Those are the
  internet-facing pre-auth holes (A1–A5) — mostly LOW/MED breakage, ~1 focused day. Without them,
  going public is negligent (A1/A2/A3 are exploitable by anyone, today).
- **Distribution to customers:** NOT tomorrow. Needs Domain 3 (connections auth) + Part 3 (secret
  rotation) + Domain 4 (isolation). The shared-secret model (C1) makes multi-tenant unsafe until
  then. Private repo buys time for single-tenant only.

### Gate order (each shippable, each verifiable)
1. **Tier A — internet edge** (Domains 1,2,5-Download-Link): authentik on apitools, 80→443 on
   domain, RLS staged, machine gated, SSRF allowlist. → *closes every pre-auth hole.*
2. **Tier B — credential plane** (Domain 3 + Part 3): root key fail-closed, secrets-ensure, connections
   auth (3-phase), `.env.ex` purged. → *makes an in-network foothold non-fatal + safe to distribute.*
3. **Tier C — hardening** (Domains 4,5-rest,6,7): browser42 isolation, ERP field whitelist, PII purge,
   retention, rotation UI, rotate live secrets. → *full public-product security.*

**Verify-after-each:** the INDOX e2e suites + a re-run of the live probes in this doc (export-all
must 401; `http://` must redirect; apitools must 302-to-SSO). Nothing merges to prod without a green
re-probe.

Related: [[fresh-vps-staging-bringup]], [[secret-base-plan-and-p0]], [[platform-service-contract]],
[[central-business-system-local-verify]].
