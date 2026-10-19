# Incoming-Documents Onboarding — One-Click Company/User Setup

> **Goal:** Onboard a new company/user to the incoming-documents pipeline so it is
> **fully operational** with the only human action being a **single Google login/consent
> inside browser42**. Everything else (GCP review, API enablement, key/credential
> provisioning, GSheet + Drive folders + Gmail label creation, n8n credential wiring,
> workflow parameterization, run + verify) is automated.
>
> Status: **STRATEGY / RUNBOOK** (drafted 2026-06-17). Live execution is gated on Google
> access + operator greenlight. Recommended path = **Model A** (§3).

---

## 0. TL;DR

A company is "operational" when documents arriving in its **Gmail** (label
`לטיפול-אוטומציה-שמירת-מסמכים`) are downloaded, OCR'd, classified, field-extracted, and
upserted into its **Incoming-Documents Google Sheet** (52-col `מסמכים נכנסים` tab), with
files filed into **Google Drive**. The n8n workflow set (`Incoming Documents 0.1.6` +
helpers) drives this; OCR is `apitools` (Google Vision), extraction is Gemini.

The **only un-automatable Google step** is creating an OAuth *client* + consent screen.
We sidestep it by **reusing the existing shared n8n OAuth clients** and having each new
company just **consent** (the "one Google login"). Everything else is API/CLI/UI-automatable.

---

## 1. What makes a company "operational" — the dependency set

| # | Dependency | Today's value (prod reference) | Per-company? |
|---|---|---|---|
| 1 | Gmail inbox receiving docs | `person9@example.com` | yes (their account) |
| 2 | Gmail label for automation | `לטיפול-אוטומציה-שמירת-מסמכים` | yes (create in their Gmail) |
| 3 | Drive folder tree (filed docs) | per company/type | yes (create in their Drive) |
| 4 | Incoming-Documents GSheet | `AutomationValues` / `מסמכים נכנסים` (gid 542119184), id `1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo`, 52 cols, PK `ID` | yes (create per company) |
| 5 | n8n OAuth credentials (Gmail, Sheets, Sheets-Trigger, Drive) | `person17@example.com` / `person9@example.com` creds | yes (new refresh token per company, **shared client**) |
| 6 | Google Cloud OAuth **client** (id+secret) | shared, in `.env` | **NO — reused** (see §3) |
| 7 | Vision API key (OCR) | `GOOGLE_VISION_API_KEY` in apitools (default hardcoded) | shared mgmt project |
| 8 | Gemini API key (extraction) | `GEMINI_API_KEY` in `.env` | shared mgmt project |
| 9 | Enabled GCP APIs | Gmail, Sheets, Drive, Cloud Vision, Generative Language | per project that owns the keys/client |
| 10 | n8n workflow set | `Incoming Documents 0.1.6` (`xWM5NQjGxl0qAhHg`) + helpers | parameterized per company |
| 11 | (new arch) repo registry entry | `prod_gsheet` via `POST /incomingDocuments/repos` | yes (`prod_gsheet_<company>`) |

### Existing shared GCP footprint (from `.env`)
- `N8N_GOOGLE_OAUTH_CLIENT_ID = 797786976065-...apps.googleusercontent.com` (Sheets/Drive/Sheets-Trigger) → **project number 797786976065**
- `N8N_GMAIL_OAUTH_CLIENT_ID = 650016969327-...apps.googleusercontent.com` (Gmail, separate project) → **project number 650016969327**
- `GEMINI_API_KEY` (placeholder in `.env`), `GOOGLE_VISION_API_KEY` (apitools default)

---

## 2. The pipeline (current, in production) — how a document flows

```
Gmail (label לטיפול-אוטומציה-שמירת-מסמכים)
  → [0A1RI9wHlm3j9eA4] GmailAutomation legacy (query label, extract attachments)
  → [indoxGmailDocDownloader01] Gmail Documents Downloader (per attachment → Drive upload)
  → [xWM5NQjGxl0qAhHg] Incoming Documents 0.1.6  (MAIN orchestrator, 213 nodes)
       ├ [indoxV2FigureDocType01] Figure Document Type      → apitools /documentOcr
       ├ [indoxV2FigureCompanyId01] Figure Document COMPANY_ID → apitools /documentOcr
       ├ Query INVOICE_ID / PURCHASE_ID / SHIPMENT_ID / DOC_DATE / TOTAL_AMOUNT / IS_BALANCE_SHEET
       │      → apitools /documentJsonQuery
       ├ [indoxV2ExtractInvoiceGemini01] invoice Extractor (Gemini)
       ├ [mphF5Nf028u8sIix] Balance Sheet Extractor v2 → apitools
       └ [indoxDocBatchUpsert01] Batch Upsert (~32 call sites)
              ├ [processLock01] process_lock (Redis)
              └ Google Sheets batchUpdate/append → מסמכים נכנסים
```

**New architecture (dev, `development/incoming-documents/`, NOT deployed):** a Python Flask
blueprint on apitools (`/incomingDocuments`) + Redpanda (Kafka). `POST /repos` is a single,
**transactional, idempotent provisioning entry point** that already does most of onboarding's
Google-side resource work for the GSheet backend:

> create spreadsheet → add tab → write 52-col header → share with editors → ensure Kafka
> topic → persist registry → emit `REPO_CREATED`. Re-run with same config = no-op (200);
> drifted config = 409; any failure rolls back only what it created.

This `POST /repos` provisioner is the **backbone primitive** for one-click onboarding of the
data store. (Gmail label + Drive folders + n8n credential/workflow wiring are still outside it.)

---

## 3. The two onboarding models (KEY DECISION)

### Model A — Shared OAuth client + per-company consent  ✅ RECOMMENDED (enables true "one-click")
- Keep **one** OAuth client (the existing shared n8n clients) and **one** management GCP
  project owning the Vision + Gemini API keys.
- A new company onboards by **logging into their Google account in browser42 and consenting**
  to the shared n8n client's scopes (Gmail + Sheets + Drive). n8n captures the **refresh
  token** into a new credential. **This is the single Google login.**
- Then automation provisions per-company resources (GSheet, Drive folders, Gmail label),
  creates n8n credential records, and clones/parameterizes the workflow set.
- **Pros:** No per-company OAuth-client creation (the one step Google does NOT fully automate
  via API). Genuinely one-click for the end user.
- **Cons / gotchas:**
  - Consent screen must be **published** (or company users added as **test users**) — Gmail
    read is a **restricted scope**; external use beyond test users needs Google verification.
    For a handful of companies, **Testing mode + added test users** is sufficient.
  - All companies share one client's quota (fine at this scale; Sheets/Gmail quotas are
    per-user, not per-client, for the heavy calls).

### Model B — Per-company GCP project (literal reading of the brief)
- Each company gets its own project `bina-incdocs-<company>` with its own OAuth client,
  API keys, enabled APIs.
- **Pros:** Hard isolation, per-company quota/billing.
- **Cons:** Creating an OAuth **client + consent screen** is **not reliably API-automatable**
  → requires **browser42 driving the Cloud Console UI** per company (slow, brittle). This
  breaks "one-click" unless we accept browser-driven console clicks as part of automation.

### Reconciliation (recommended hybrid)
Use **Model A for OAuth** (shared client, per-company consent) and apply the **"prefix
naming pattern"** to the **per-company resources** (GSheet / Drive / repo / Kafka topic),
not to GCP projects. One shared **management project** holds Vision + Gemini keys with all
required APIs enabled. This delivers one-click and still gives clean, reusable naming.

---

## 4. Naming convention (prefix pattern)

| Resource | Pattern | Example (`acme`) |
|---|---|---|
| Company slug | `[a-z0-9-]` from legal/display name | `acme` |
| GCP mgmt project (Model A, one shared) | `bina-incdocs-mgmt` | `bina-incdocs-mgmt` |
| GCP project (Model B, per company) | `bina-incdocs-<slug>` | `bina-incdocs-acme` |
| Incoming-Documents GSheet title | `IncDocs — <Company>` | `IncDocs — Acme` |
| GSheet tab | `מסמכים נכנסים` (constant) | `מסמכים נכנסים` |
| Drive root folder | `IncDocs/<Company>` | `IncDocs/Acme` |
| Gmail label | `לטיפול-אוטומציה-שמירת-מסמכים` (constant) | same |
| repo registry name | `prod_gsheet_<slug>` | `prod_gsheet_acme` |
| Kafka topic | `incoming-documents.prod_gsheet_<slug>` | `incoming-documents.prod_gsheet_acme` |
| n8n credential names | `Gmail <email>`, `Google Sheets <email>`, `Google Sheets Trigger <email>`, `Google Drive <email>` | as today |

**"Figure if already existing" rule:** before creating, look it up — `gcloud projects list`,
Drive/Sheets search by title, n8n credential list by name, `GET /repos/<name>`. Idempotent:
reuse on match, create only if absent. (`POST /repos` is already idempotent.)

---

## 5. The one-click onboarding sequence (target runbook)

**Inputs:** company display name → derive `slug`; the company's Google account.

1. **Google login (the only human step).** Drive browser42 page-0 to the n8n OAuth consent
   URL (or Google sign-in), prompt the user via `http://browser42.localhost/view/`, poll
   until consented/logged-in. (Pattern: `ai/context/setup-google-cloud-login.md`.)
2. **GCP review + ensure (automated, gcloud/API or browser42).**
   - `gcloud projects list` → find/create `bina-incdocs-mgmt` (Model A).
   - Ensure APIs enabled: `gmail.googleapis.com`, `sheets.googleapis.com`,
     `drive.googleapis.com`, `vision.googleapis.com`, `generativelanguage.googleapis.com`.
   - Ensure/create API keys (Vision, Gemini) — fully scriptable via gcloud/apikeys API.
   - Confirm the shared OAuth client + consent screen exist; add company user as test user
     if consent screen is in Testing mode.
3. **n8n credentials.** Create/refresh the 4 Google OAuth2 credentials for the company's
   account using the **shared client id/secret** + the refresh token from step 1.
4. **Provision per-company resources (idempotent).**
   - GSheet + tab + 52-col header + share — via new arch `POST /incomingDocuments/repos`
     (`prod_gsheet_<slug>`) **or**, until that service is deployed, via the existing n8n
     Sheets nodes / Sheets API directly.
   - Drive folder tree `IncDocs/<Company>`.
   - Gmail label `לטיפול-אוטומציה-שמירת-מסמכים`.
5. **Wire workflows.** Clone/parameterize the `Incoming Documents 0.1.6` set to point at the
   company's sheet id, Drive folder, label, and credentials. Activate triggers.
6. **Run + verify (end-to-end, no skipping).** Seed/identify a real invoice in Gmail/Drive,
   trigger the pipeline, confirm a row lands in `מסמכים נכנסים` with extracted fields
   (INVOICE_ID, DOC_DATE, DOC_TOTAL_AMOUNT, COMPANY_ID, STATUS=processed) and the file is
   filed in Drive. Drive to terminal state; mark any blocked step OPEN.

---

## 6. Automatable vs manual — the honest matrix

| Action | Mechanism | Automatable? |
|---|---|---|
| Enable GCP APIs | `gcloud services enable` / serviceusage API | ✅ yes |
| Create API keys (Vision, Gemini) | `gcloud services api-keys create` / apikeys API | ✅ yes |
| Create GCP project | `gcloud projects create` | ✅ yes (billing link may need 1 manual step) |
| **Create OAuth client + consent screen** | Cloud Console UI | ⚠️ **not reliably via API** → browser42, or reuse shared (Model A) |
| Add test user to consent screen | Console UI / `gcloud alpha iap oauth-brands` (limited) | ⚠️ usually browser42 |
| OAuth **consent** (get refresh token) | browser42 interactive login | ✅ human one-click, then captured |
| Create GSheet/tab/header/share | Sheets+Drive API / `POST /repos` | ✅ yes |
| Create Drive folders | Drive API / n8n | ✅ yes |
| Create Gmail label | Gmail API / n8n | ✅ yes |
| Create n8n credentials | n8n REST API / DB / `n8n-push` | ✅ yes |
| Clone/parameterize workflows | n8n REST API / `n8n-pull`/`n8n-push` | ✅ yes |

**Bottom line:** with Model A, **every step except the human's one consent is automatable.**

---

## 7. Execution mechanics (this environment)

- **browser42** (running: `browser42-browser-shlomo-laptop`): drive via CDP/Playwright
  `connect_over_cdp("http://localhost:9222")` from inside the browser container; own-your-tab
  pattern; live view `http://browser42.localhost/view/` (VNC password empty locally). See
  `ai/context/browser42-cli.md`, `setup-google-cloud-login.md`.
- **State dump:** `data/browser42-state-autopilot.tar.gz.enc` (encrypted, may hold a Google
  login). Restore with `production/browser42/browser42-state.sh load <file>` +
  `BROWSER42_STATE_PASSPHRASE`. **Passphrase needed from operator.**
- **gcloud:** installed on host (v529). Needs `gcloud auth login` (browser) or a service-
  account key to manage the mgmt project.
- **n8n:** running (`n8n-shlomo-laptop`, queue mode). Sync via `./n8n-pull` / `./n8n-push`;
  REST API for credentials/workflows. Shared OAuth client already in `.env`.
- **New arch not deployed locally:** no redpanda / incoming-documents container. Until
  deployed, do GSheet provisioning via Sheets API / n8n, not `POST /repos`.

---

## 8. Open decisions (need operator input before live execution)

1. **Model A vs B** (§3). Recommend A (hybrid). Affects whether we create per-company GCP
   projects + OAuth clients (browser42-driven) or reuse the shared client.
2. **Google access for execution:** passphrase for the encrypted state dump, OR do the
   interactive browser42 login now, OR `gcloud auth login` for CLI provisioning.
3. **Which company/account to onboard first** (the pilot) — name → slug, and is it a
   consumer Gmail or a Google Workspace domain (Workspace enables service-account domain-wide
   delegation = an even cleaner path).
4. **Deploy the new Python incoming-documents + Redpanda service?** If yes, `POST /repos`
   becomes the provisioner; if no, provision via existing n8n/Sheets API.

---

## 8b. RUN LOG — fresh from-scratch onboarding (2026-06-17, person8@example.com)

Executed end-to-end on the local `shlomo-laptop` stack to validate the flow:

**Done & verified:**
1. Secrets split — all 35 real secrets → `env.secrets-temp` (git-ignored); fresh infra secrets generated into `.env`; Google/onboarding keys left empty.
2. `docker compose down -v` (full wipe incl. browser42 `cloakprofile`) → `up -d --build`; all services healthy.
   - Local fix needed again: authentik embedded-outpost token is broken on a fresh stack → forward-auth 404s, so the **local** `browser42.localhost` router's `middlewares=authentik` was commented out (see `production/compose.override.yml`) so the operator can reach `/view`. Re-add once the outpost is fixed.
3. `scripts/n8n-push` → owner `shlomo@local.dev` bootstrapped, 36 creds + 113 workflows imported, 61 reactivated. **Credential secrets do NOT decrypt** (new `N8N_ENCRYPTION_KEY` ≠ blueprint key) → every Google credential must be re-authed (expected for fresh onboarding).
4. Operator Google login in browser42 (`person8@example.com`); gcloud CLI re-authed via browser42 consent (operator/agent click).
5. **GCP provisioned under `person8@example.com`:**
   - Project **`shlomo-laptop-deployment`** (proj # 936853307928), billing `014F8D-7253FC-52F745` linked.
   - APIs enabled: gmail, sheets, drive, vision, generativelanguage, apikeys.
   - API keys created (values in `env.secrets-temp`): **Vision** `incdocs-vision` (→ wired into apitools env `GOOGLE_VISION_API_KEY` + `.env`), **Gemini** `incdocs-gemini` (→ `.env` `GEMINI_API_KEY`).
   - Discovered: existing OAuth clients live in `lotterybot-445417` (#797786976065 = Sheets/Drive) and `apitools-422811` (#650016969327 = Gmail).

**BLOCKER reached — n8n Google OAuth redirect URI on local:**
- n8n derives its OAuth callback from `N8N_EDITOR_BASE_URL` → **`http://n8n.localhost/rest/oauth2-credential/callback`**.
- Google rejects `http://` redirect URIs for non-`localhost` hosts (`n8n.localhost` is a subdomain → not accepted). So the Sheets/Drive/Gmail OAuth credentials **cannot be re-authed as-is** locally.
- A new OAuth 2.0 **client ID also cannot be created via gcloud/API** — it requires Console UI (consent screen + client).

**Options to finish locally (pick one):**
- **(A) Service-account for Sheets/Drive** — create an SA + JSON key (gcloud-scriptable), share the Sheet/Drive folder with it; switch those n8n nodes to `googleApi` cred type. Avoids OAuth redirect entirely. Gmail still can't use SA (consumer account) → for the first end-to-end, ingest a doc via the **Drive** watched folder instead of Gmail. Cleanest local; needs node-auth rewiring.
- **(B) OAuth via `127.0.0.1:5678`** — publish n8n's port to host, set editor base to `http://127.0.0.1:5678`, register that redirect on a new OAuth client; do the consent in the **host browser** (not browser42). Keeps OAuth; adds one host-browser consent.
- **(C) Reuse existing shared OAuth clients** (`lotterybot`/`apitools`) with secrets from `env.secrets-temp` — fastest, but not "fresh", and the `n8n.localhost` redirect still won't validate without (B)'s port trick.
- **On a real VPS with `https://<svc>.<domain>` the whole thing works in browser42** with no redirect hack — this blocker is local-only.

## 8c. SOLVED — automated Google OAuth onboarding (2026-06-17, the breakthrough)

The local OAuth blocker (§8b) is **solved**; all four n8n Google credentials (Sheets, Drive,
Sheets-Trigger, Gmail) were connected on the fresh stack **fully automatically** — the only human
step was the initial Google login in browser42. The working recipe (Option B, refined):

1. **OAuth client** (Console UI, browser42-driven, the one non-API step): create an OAuth client
   (Web app) in the project with redirect URIs `http://127.0.0.1:5678/rest/oauth2-credential/callback`
   (+ `localhost:5678`). Configure the consent screen (External) and **add the operator as a Test
   user** (Audience → Test users → +Add users — *scroll down first; it lazy-renders below the fold*).
2. **n8n callback base** → `http://127.0.0.1:5678` (local-only, via `N8N_OAUTH_BASE` in `.env`;
   compose default stays prod-safe). Set `N8N_GOOGLE/GMAIL_OAUTH_CLIENT_*` to the new client; recreate n8n.
   - **Why the IP, not `n8n.localhost`? (tested 2026-06-17, definitive.)** Google's OAuth client form
     **rejects** `http://n8n.localhost/...` with *"Invalid redirect: Must end with a public top-level
     domain (such as .com or .org)"* (`.localhost` is a reserved TLD). The only http hosts Google accepts
     are `localhost` / `127.0.0.1`. So the registered redirect **must** be `127.0.0.1:5678`. A human's
     manual "rewrite the failed callback URL to n8n.localhost" trick works only because n8n's *server-side*
     `redirect_uri` stays `127.0.0.1:5678` (matching registration) — the browser just needs to reach n8n.
3. **Make `127.0.0.1:5678` reach n8n in BOTH consent contexts (Option 2 — the supported design):**
   - **browser42** (automated): in-container forwarder `data/browser42/fwd.py` (persistent) — `127.0.0.1:5678
     → n8n-…:5678`. Start with `docker exec -d … python3 /data/fwd.py` (restart per run; dies on container restart).
   - **host browser** (manual re-auth in the n8n UI): publish n8n on host loopback — `ports: ["127.0.0.1:5678:5678"]`
     on the n8n service (compose.override, local-only, bound to 127.0.0.1 → harmless on the VPS, and the
     `n8n.localhost` Traefik route is untouched). **Then open the n8n UI at `http://127.0.0.1:5678` (NOT
     `n8n.localhost`) and log in there before connecting the credential** — n8n's OAuth callback needs the
     session cookie on the *same* origin as the callback (`127.0.0.1`); using `n8n.localhost` returns
     `Unauthorized` because the cookie is on a different origin. **On a real VPS none of this is needed**
     (the https public callback works, same origin as the UI). See issue `n8n-google-oauth-localhost-callback`.
4. **Per credential** (the data won't decrypt under the new key, so first reset it):
   - `PATCH /rest/credentials/<id>` with `data:{}` (re-encrypts empty under the current key).
   - **Run the whole flow inside browser42** (critical: the OAuth `state` is bound to the n8n
     session cookie, so the *same* browser must log in AND consent):
     a. `goto http://127.0.0.1:5678/`; `fetch('/rest/login', …)` (sets n8n cookie in browser42).
     b. `fetch('/rest/oauth2-credential/auth?id=<id>')` → `authUri`.
     c. `goto(authUri)` → click the account tile (`[data-identifier="…"]`) → **"Google hasn't
        verified this app" → Continue** → scope screen: **tick all checkboxes** (first one is
        "Select all" — granular consent; un-ticked scopes = `access_denied`) → Continue →
        consent summary → Continue → callback shows **"Connection successful"** → token stored.
   - Verify: `GET /rest/credentials/<id>?includeData=true` → `data.data.oauthTokenData == true`.

**Gotchas learned:** (a) test-user changes can need a scroll to even find the control; (b) granular
consent requires ticking every scope box; (c) the callback must hit n8n with the n8n session cookie
(run login+consent in the same browser context); (d) Google redacts `oauthTokenData` via the API —
you cannot extract the access token, so provision resources *through* n8n (node execution) or by
decrypting `credentials_entity` from n8n-postgres with `N8N_ENCRYPTION_KEY`.

**On a real VPS** (`https://n8n.<domain>`), steps 2–3 are unnecessary — the public HTTPS callback works
directly in browser42; only the client+consent-screen+test-user setup (step 1) remains, once per deployment.

**Skip the Google login on future runs:** after logging in once, dump the browser profile —
`BROWSER42_STATE_PASSPHRASE=… bash production/browser42/browser42-state.sh dump data/browser42-state-autopilot.tar.gz.enc`
(passphrase in `env.secrets-temp`). Before a fresh onboarding, restore it with `… browser42-state.sh
load data/browser42-state-autopilot.tar.gz.enc` so browser42 is already signed in — then the OAuth
consent automation runs with zero manual steps. (`down -v` wipes the `cloakprofile` volume, so reload after it.)

**Verified 2026-06-17 (2nd fresh cycle):** after `down -v` → up → n8n-push → one Google login →
automated re-auth of Gmail/Sheets/Drive creds → the **`Google Integration Health`** workflow
(`gwaHealthCheck01`: Gmail get + Sheets read + Drive create/download/delete) executed with
**status: success**. Note: after n8n-push, toggle the workflow active off→on (PATCH `/rest/workflows/<id>`)
to force the webhook to register, then `POST /webhook/trigger-google-health` (CICD basic auth).

### Provisioned this run (recorded in env.secrets-temp)
- GCP project `shlomo-laptop-deployment` (#936853307928), billing linked, 6 APIs enabled.
- Vision key (→ apitools `GOOGLE_VISION_API_KEY`), Gemini key (→ `.env` + googlePalmApi cred `6mfcsdRaqQ4IdQ8Y`).
- OAuth client `936853307928-45cu0mhcctmved55mocqs0njmldv9152` (redirects 127.0.0.1:5678/localhost:5678).
- n8n creds connected: `e2knIZpw8YF0QBAB` (Sheets), `KirWFwoFdEFmnN0R` (Drive), `DfQPc6wpof8GdkFo` (Sheets-Trigger), `jft0CdgvgPNvaLNn` (Gmail).
- Schema for the repo: 68 columns (see `context-collection/config/incoming-documents-main.repo.json`), tab `מסמכים נכנסים`, PK `ID`.

### Remaining to be "fully operational" (mechanical)
- Provision per-company resources: new GSheet (68-col `מסמכים נכנסים`), Drive folder tree, Gmail
  label `לטיפול-אוטומציה-שמירת-מסמכים` — via n8n node execution (creds are connected).
- Re-point `Incoming Documents 0.1.6` + helpers (Sheets-Trigger, Batch Upsert, Gmail Downloader)
  to the new sheet/folder/label.
- Seed a real invoice in Gmail/Drive → run → verify a processed row in the sheet.

## 8d. AI/LLM document creds — Gemini ✅ / Vision ⛔ (2026-06-18, person2@example.com)

Two shared keys power doc intelligence: **`GEMINI_API_KEY`** (AI extractors — invoice / balance-sheet,
via n8n googlePalmApi/`ai-studio-bs-extraction` cred) and **`GOOGLE_VISION_API_KEY`** (apitools
`/documentOcr`). Both belong to the tenant's GCP project (`Bina IncDocs Onboard`, #831351881172).

### GEMINI_API_KEY — DONE (browser42 as solutionsbina)
Recipe (one human Google login already in browser42; driven via the Playwright MCP, `data/browser42/mcp.py`):
1. `navigate https://aistudio.google.com/apikey` → first visit shows a **ToS modal**: tick the agreement
   checkbox + **Continue** (operator-pre-authorized onboarding ToS, same as gcloud ToS in §8c).
2. **Create API key** → dialog pre-selects the imported GCP project (`Bina IncDocs Onboard`) → **Create key**.
3. Copy the key from the "API key details" dialog → write to `.env` `GEMINI_API_KEY`.
   ⚠️ **New AI Studio keys are `AQ.…` format** (≈53 chars), NOT the old `AIza…` — grep accordingly.
4. Apply: `bbox n8n push` reseeds the env-managed Gemini cred (or recreate n8n for CREDENTIALS_OVERWRITE_DATA).

### GOOGLE_VISION_API_KEY — BLOCKED on billing (operator decision)
Could not auto-create: the project has an **org policy requiring every API key be restricted to an
*enabled* API**, and **Cloud Vision isn't enabled** — and Vision **requires a billing account** (the
console only offers the "$300 free trial / Start free" — no billing linked). Enabling billing / starting
a paid trial is a **financial action left to the operator**. When billing is set up, the recipe is:
1. Enable **Cloud Vision API** (APIs & Services → Library → Cloud Vision API → Enable).
2. Credentials → **Create credentials → API key** → **Restrict key → Cloud Vision API** (org policy needs it).
3. Copy the `AIza…` key → `.env` `GOOGLE_VISION_API_KEY` → recreate apitools so it picks it up.

Until then `bbox n8n verify` flags `GOOGLE_VISION_API_KEY EMPTY` and apitools OCR (`/documentOcr`) fails;
Gemini-based extraction still works (the AI extractors don't need Vision).

## 9. Related context
- `ai/context/setup-google-cloud-login.md` — browser42 Google login recipe.
- `ai/context/browser42-cli.md` — CDP/Playwright driving guide.
- `development/incoming-documents/app/incoming_documents/IMPLEMENTATION-PLAN.md` — `POST /repos` provisioner contract.
- `development/incoming-documents/app/incoming_documents/ARCHITECTURE.md` — old vs new system.
- `development/incoming-documents/app/incoming_documents/context-collection/config/production-config.md` — prod sheet ids/creds.
- `production/n8n/workflows/` — `xWM5NQjGxl0qAhHg` (0.1.6), `indoxDocBatchUpsert01` (Batch Upsert), `indoxGmailDocDownloader01` (Gmail Downloader), etc.

---

## §9 — Fresh-account onboarding run (2026-06-18) + full architecture/product plan

A complete brand-new-tenant test was executed: stack wiped (`down -v`), new `N8N_ENCRYPTION_KEY`
(fp `77aee1e8`), brand-new Google account `person2@example.com`, new GCP project
`bina-incdocs-onboard` (#831351881172), new OAuth client, all creds re-authed.

**Verified GREEN:** env-driven local creds survive key drift (6/6); 4 Google OAuth creds re-authed
(read+write proven); Settings workflow reads a newly-provisioned settings sheet; `/webhook/setting`
returns new Drive folders; Gmail Documents Scanner runs green.

**Blocked (→ the "big refactor"):** Mail Label Engine / Downloader aren't fully green on a fresh
account because workflows embed **account-specific Gmail label IDs** (`Label_6556…`) and the Label
Engine assumes existing label state. De-hardcode (resolve labels by name) is Phase 1 of the plan.

**New resources provisioned this session (owned by `solutionsbina`):** settings spreadsheet
`1Y5JYUcbVe0CnqPUnA5ISmqSUPO28YbZpAHnGbFqnZSM` (tabs Settings/Companies/Tag-Settings), Drive parent
`1nyWOzGNacjyVuJddiZFc5wQaba4Lj_jr` (+5 subfolders, gmail-docs `163H-S4XSo4uqA0FRUziu0wCUiHcF9rZU`).
Scripts: `data/browser42/provision.js` (create folders+sheet), `data/browser42/rewire.js` (REST repoint).

**Full write-up** (system map, responsibilities, exact provisioning steps to become an automated
"indocs setup" workflow, hardcoded-coupling list, and the phased productization plan):
→ [incoming-documents-architecture-and-productization.md](incoming-documents-architecture-and-productization.md)
