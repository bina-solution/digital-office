# Incoming-Documents — Architecture, Fresh-Tenant Provisioning & Productization Plan

> Written 2026-06-18 after a full fresh-account onboarding test (new `N8N_ENCRYPTION_KEY`,
> brand-new Google account `person2@example.com`, new GCP project + OAuth client, all wiped).
> Companion to [incoming-documents-onboarding.md](incoming-documents-onboarding.md) (the strategy/runbook)
> and the v2 Python API plan. This doc adds: (1) the verified system map + responsibilities, (2) the
> **exact** provisioning steps executed this session (so they can become an automated "indocs setup"
> n8n workflow), and (3) a phased plan to make the whole thing productable for any new company.

---

## Part A — Architecture & responsibilities (who does what)

### A.1 End-to-end pipeline
```
Gmail inbox (the company's Google account)
  │  ① Mail Label Engine [mailLabelEngine01]  (poll 5 min)
  │     reads Tag-Settings sheet (cached in Redis) → creates missing Gmail labels →
  │     classifies new mail by rules → applies labels
  ▼
② Gmail Documents Scanner [vBcSCddTDnvbuOZi]  (schedule)
   Gmail search for `has:attachment AND label:<to-handle> AND -label:<done>` →
   tags "processing" → for each mail calls ↓
  ▼
③ Gmail Documents Downloader [indoxGmailDocDownloader01]  (executeWorkflow)
   loads Settings (folder IDs, companies) → filters attachments (PDF/img, 10KB–10MB) →
   for each attachment calls Process Document ↓ ; uploads file to Drive
   (gmail_docs_dest_folder_id) ; tags mail saved-invoice/saved-shipment/unknown ;
   upserts a row to the Incoming-Documents data sheet + logs
  ▼
④ Process Document [indoxProcessDocument01]  (executeWorkflow)
   apitools /documentOcr (OCR) → Figure Document COMPANY_ID [indoxV2FigureCompanyId01] →
   Figure Document Type [indoxV2FigureDocType01] → extract invoice_id / shipment_id /
   purchase_id via apitools /documentJsonQuery → returns {company_id, document_type, ids, is_ok}
```
Sibling intake variants reuse ③/④: **Gmail Balance Sheet Downloader** [indoxGmailBSDownloader01]
(forwarded-email/accounting flows → `gmail_balance_docs_dest_folder_id`) and
**Gmail Link Documents Downloader 2.0** [indoxGmailLinkDownloader01] (invoices delivered as links —
Morning/EzCount/Invoice-One/Rivhit/… provider-specific link extraction).

### A.2 Component responsibilities
| Layer | Component | Responsibility |
|---|---|---|
| **Orchestration** | n8n (queue mode: main + 2 workers + task-runners) | All pipeline logic, triggers, Google API calls, retries, tagging, upserts. Workflows are the "code". |
| **Config plane** | n8n **Settings** workflow [indoxSettings01] | Single source of runtime config. Reads the settings spreadsheet (tabs **Settings**, **Companies**, **Tag-Settings**) and serves it over **local webhooks**: `/setting`, `/company`, `/query`, `/queries`, `/all_settings` (httpBasic = Settings Auth cred). Caches in KV/Redis. |
| **Doc intelligence** | **apitools** (Flask+Gunicorn, `production/apitools/`) | The irreplaceable OCR/extraction core. `/documentOcr` (Google Vision OCR, MD5-cached), `/documentJsonQuery` (position-relative "find after/above" text queries), `/pdfToJpeg`. Stateless except OCR cache. Uses shared `GOOGLE_VISION_API_KEY`. |
| **State/queue** | Redis (`BoJE…` cred) + Postgres-n8n (`tJ19…` cred) | Redis = Bull queue + process locks + settings cache. Postgres = workflows, credentials (AES-encrypted), executions. |
| **Data sink** | Google Sheets (Incoming-Documents data sheet, 52 cols) + Google Drive (folder tree) | Where extracted rows + saved files land. Owned by the company's Google account. |
| **Edge/infra** | Traefik, Authentik, Homepage, Portainer, Machine, Any-Concurrency, GlitchTip | Routing/TLS, SSO gate for operator tools, dashboards, concurrency backpressure, error tracking. Not in the doc path. |
| **Onboarding tooling** | browser42 (stealth Chromium + CDP + VNC) | Drives the one human step (Google login/consent) and all GCP-console automation during onboarding. |

**One-line split:** *n8n owns the workflow/orchestration; apitools owns OCR + field extraction; Google
(Gmail/Sheets/Drive) is the per-tenant data substrate; everything else is infra/observability.*

---

## Part B — What makes a tenant "operational" (dependency matrix)
1. The company's **Google account** + OAuth consent → 4 n8n creds (Gmail, Sheets, Drive, Sheets-Trigger).
2. **Gmail label taxonomy** present in that account (to-handle / processing / saved-* / done).
3. **Settings spreadsheet** owned by that account with tabs **Settings / Companies / Tag-Settings**, populated.
4. **Drive folder tree** owned by that account (source / processed / fails / gmail-docs / gmail-balance).
5. **Incoming-Documents data sheet** (the 52-col sink) — separate from the settings sheet.
6. Shared infra: `GOOGLE_VISION_API_KEY` (apitools OCR), `GEMINI_API_KEY` (extraction), the shared OAuth client.
7. All workflow node references (sheet documentIds, Drive folder IDs, Gmail **label IDs**, settings webhook URL) pointing at THIS tenant's resources.

---

## Part C — Fresh-tenant provisioning runbook (executed this session)

Context: stack wiped (`down -v`), new `N8N_ENCRYPTION_KEY` (fp `77aee1e8`), brand-new
`person2@example.com`, new GCP project `bina-incdocs-onboard` (#831351881172), new OAuth client.

### C.1 Credential key-drift model (works; already productized)
- Local/infra creds (`redis, postgres, httpBasicAuth ×3, googlePalmApi`) are **env-driven** via the
  `credential_overrides:` block in `blueprint.yml` and reseeded by `scripts/n8n-push` (PATCH per id →
  re-encrypts under the current key). These **survive key drift** by design — verified.
- Google OAuth creds are NOT env-managed (they hold per-tenant refresh tokens). On key drift their old
  blobs can't decrypt; even *starting* re-auth 500s ("could not be decrypted"). **Fix that must be in the
  setup workflow:** before re-auth, `PATCH /rest/credentials/<id>` with `{name,type,data:{}}` to reset the
  blob under the current key, THEN run OAuth. (Done for all 4 ids: `41BK…, e2kn…, KirW…, DfQP…`.)
- The shared OAuth **client id/secret** are injected per-type via `CREDENTIALS_OVERWRITE_DATA`
  (compose → from `.env` `N8N_GOOGLE_OAUTH_*` / `N8N_GMAIL_OAUTH_*`). Recreate n8n after editing `.env`.

### C.2 GCP setup (browser42-automated; ~one human login)
1. Google login (human, once) → browser42 `cloakprofile`.
2. `gcloud` project create (accept **gcloud ToS** for fresh accounts — pre-authorized by operator).
3. Enable APIs: gmail, sheets, drive (+ vision, generativelanguage when billing).
4. OAuth **consent screen** wizard (`/auth/overview/create`): app name, support+contact email, External.
   ⚠️ The "Get started" / wizard controls are Angular **links** and Material buttons — Playwright
   `.click()`/force-click often no-ops; **a real mouse-coordinate click is required** (esp. the test-user
   **Save**). The Add-users field is a single role=textbox in a right-side panel (x≈822), chip with Enter.
5. Create OAuth **client** (Web app) with redirect URIs `http://127.0.0.1:5678/rest/oauth2-credential/callback`
   **and** `http://localhost:5678/...` (Google rejects `http://n8n.localhost`; see closed issue).
6. Add the account as a **Test user** (app stays in Testing). Without this, OAuth → `403 access_denied`.

### C.3 Re-auth the 4 Google creds (browser42, on the `127.0.0.1:5678` origin)
- Reset old-key blobs (C.1), then drive consent via the auth URL from
  `GET /rest/oauth2-credential/auth?id=<id>` (returns `{"data":"<google url>"}`), navigate top-level,
  pick account → tick **all** scope checkboxes → Continue → callback stores `oauthTokenData`. All 4 ✓.
- The in-container forwarder `data/browser42/fwd.py` (127.0.0.1:5678 → n8n) must be running.

### C.4 Provision Google resources owned by the new account (script: `data/browser42/provision.js`)
Uses the freshly-stored Drive cred's **refresh token** → mints an access token → Drive/Sheets REST.
- **5 Drive folders** under a parent: To-Process, Processed, Fails, **Gmail-Downloaded-Documents**,
  Gmail-Downloaded-Balance. (This session: parent `1nyWOzGN…`, gmail-docs `163H-S4XS…`.)
- **Settings spreadsheet** (this session `1Y5JYUcb…`) with 3 tabs + headers:
  - **Settings**: cols `הגדרה | ערך`. Rows keyed by name → value is a Drive **folder URL**:
    `DocumentsToProcessFolder, ProcessedDocumentsFolder, ProcessedDocumentsFailsFolder,`
    `GmailDownloadedDocumentsFolder, GmailDownloadedBalanceDocsFolder, GmailDocsDownloadIgnoredMails, WhatsappAdmins`.
  - **Companies**: cols `שם חברה | מזהה 1 | מזהה 2 | שם ספק מפריוריטי | מייל 1 | מייל 2 | הוראות לAI לחילוץ דוח גיול`.
  - **הגדרות תגיות במייל** (Tag-Settings): cols `LABEL | on_create_settings`.

### C.5 Rewire workflows to the new resources (script: `data/browser42/rewire.js`, REST PATCH)
> Do **NOT** run `n8n-push` here — it re-imports the old-key credential blobs and re-breaks OAuth.
> Edit live via REST instead.
- **Settings** [oomGi…]: `Load Settings Table` → new SS + Settings gid; `Load Companies Table` → Companies gid.
- **Label Engine** [qdWik…]: `Get Tags Settings` / `…1` → new SS + Tag gid.
- **Settings webhook URL** was **hardcoded to prod** `https://n8n.hacohen.bina-solutions.co.il/webhook/setting`
  in **6 workflows** — repointed host → `http://n8n:5678` (also caught `/webhook/company`, `/process-document`).
- **Publish model (n8n 2.17):** a PATCH only updates the *draft*; the live trigger runs the *published*
  snapshot. Must set `activeVersionId = versionId` (SQL) **and restart n8n** to re-register webhooks/triggers.

### C.6 Verification results (this session)
| Check | Result |
|---|---|
| Env-driven local creds survive key drift (6/6 reseeded) | ✅ |
| 4 Google OAuth creds re-authed (read+write proven: email **sent** via API, sheets **created**) | ✅ |
| Settings workflow reads NEW sheet; `/webhook/setting?key=gmail_docs_dest_folder_id` → new folder | ✅ |
| Gmail Documents Scanner runs green | ✅ |
| Mail Label Engine / Downloader fully green on the fresh account | ❌ — blocked by Part D |

---

## Part D — Hardcoded couplings that block a fresh tenant (the refactor targets)
These are why a brand-new account isn't "fully operational" even after C:
1. **Account-specific Gmail label IDs** baked into nodes — Scanner search + all `addLabels/removeLabels`
   use literals like `Label_6556344690922078687`, `Label_5797810481362495187`, … (11+ across Scanner,
   Downloader, Balance Downloader). A fresh Gmail has different IDs → search matches nothing, tags fail.
2. **Label-engine bootstrap logic** assumes existing label state — on a fresh inbox it errored with
   `Node 'Tag Settings' hasn't been executed` (a branch that should populate labels was skipped).
3. **Business taxonomy must be seeded per tenant** — the real Tag-Settings rows (label names + ON_CREATE
   rules) and Companies registry are business data, not derivable from code (the old sheet is private).
4. **Settings webhook URL was hardcoded** (now fixed to `n8n:5678`, but should be an env/`$vars` value).
5. **Hebrew extraction keyword sets** + the 52-col data-sheet schema are locale/business-specific.
6. **apitools endpoints** were absolute prod URLs in some nodes (`apitools.hacohen…`) — should be env-driven.

---

## Part E — Productization plan (make it work for any new company)

**Goal restated:** one human Google login in browser42 → everything else automated → incoming-documents
fully operational for that company.

### Phase 0 — Foundations (mostly DONE)
- ✅ Env-driven local creds + key-drift reseed (`credential_overrides` + `n8n-push`).
- ✅ Declarative blueprint pull/push.
- ✅ browser42 GCP/OAuth automation recipe (with the mouse-coordinate-click + 127.0.0.1 redirect gotchas).
- ✅ Fresh-resource provisioner primitives (`provision.js`, `rewire.js`).

### Phase 1 — De-hardcode the workflows (the "big refactor"; unblocks Part D #1,2,4,6)
- Replace literal **Gmail label IDs** with **resolve-by-name at runtime**: the Label Engine already builds
  `final_lable_ids_by_name`; expose it (Redis/Settings) and have Scanner/Downloader look up IDs by stable
  label *names*. Remove every `Label_…` literal.
- Make the Label Engine **bootstrap-safe** on an empty inbox (always create the base taxonomy first; never
  reference a node that a branch may skip).
- Move **settings webhook base** and **apitools base** to env/workflow `$vars` (no absolute hostnames).
- Acceptance: a fresh account with only the base label set + seeded sheets runs Scanner→Downloader→Drive green.

### Phase 2 — A "Tenant Setup" n8n workflow (turn Part C into one click)
Author an orchestrator workflow (or extend `Settings`) that, given a freshly-consented Google account, does
C.4–C.6 itself: create Drive folder tree → create the settings spreadsheet (3 tabs, seeded with base
Tag-Settings + the company row + folder URLs) → create the Incoming-Documents data sheet → create base Gmail
labels → write all new IDs into the tenant's Settings → (no manual rewire needed once Phase 1 makes node
refs come from Settings, not literals). Inputs: company slug, display name, primary email. Idempotent
(check-before-create). This is the artifact the operator asked to "later build".

### Phase 3 — Tenant registry + multi-tenant config
- A **company registry** (Supabase table or a master GSheet): slug, display name, Google account, status,
  pointers to its settings sheet / data sheet / Drive root / repo name. List/get/create API.
- Per-tenant Settings selection so one n8n instance can serve many companies (today Settings is single-sheet).
- Tie into the v2 Python incoming-documents API `POST /repos` (already specced) as the provisioner of record.

### Phase 4 — Productization hardening
- Multi-tenant auth on the Python API (JWT/scope per company), audit logs.
- Replica/dedup policy across tenants (HASH / COMPANY_ID+SHORT_DOC_ID composite keys — see plan.txt TODO).
- RepoConfig schema versioning + rollback. Per-company Kafka topics (already named per slug).
- Security: stop publicly exposing n8n Postgres (open issue), Authentik hardening/CVEs.

### Sequencing
Phase 1 is the unlock (without de-hardcoding, every onboarding needs manual label-ID surgery). Phase 2
makes onboarding one-click. Phases 3–4 make it a multi-tenant product.

---

## Part F — Verified coupling matrix + MINIMAL config-routing plan (2026-06-18)

Full re-read of **all 114 workflows** (58 keep / 56 prune). Conclusion: making a fresh account work is a
**config-routing problem, not a logic rewrite**. Every per-tenant/per-env value is a literal; for a new
account they're all wrong. Operator constraint: *"minimal to get everything up and running — auto setup +
properly routed config."*

### Coupling matrix (the literals that break a fresh tenant)
| # | Coupling | Prod literal | Where (#files) | Minimal fix |
|---|---|---|---|---|
| 1 | n8n webhook base | `https://n8n.hacohen.bina-solutions.co.il` | 35 wf (Settings, Process Document, all Downloaders, Create/Actions/Find/GDriveSync, **My workflow 15 MCP URLs**) | → internal `http://n8n:5678` (verified 200) / `$env` |
| 2 | apitools base | `https://apitools.hacohen.bina-solutions.co.il` | 20 wf (Process Document + all Query/Figure) | → internal `http://apitools:8080` (verified 200) / `$env` |
| 3 | Sheet ID (settings **and** data — same sheet, many tabs) | `1Wu3hyF_4TvfU41xCGaINtJD81Or0wBSwD1djp4tVJEo` | ~15 wf | one config source, written by setup |
| 4 | 14 Gmail label IDs | `Label_6556…` ×6 + 13 more | Scanner/Downloader/Balance/Links/Actions | resolve-by-name via Label Engine's `final_lable_ids_by_name` (Redis `n8n.label-engine.settings`) |
| 5 | tab gids | data `542119184`, settings `1467881049`, companies `749586510`, 4 log gids | API + Logger | config / by-name |
| 6 | Gemini model / business VAT `515561520` / Hebrew keyword sets | — | AI extractors, Figure/Query | LEAVE (business logic, not per-tenant) |

### Minimal change set (M1–M5)
- **M1** — route base URLs #1/#2 → internal hostnames (or `$env`). Biggest unlock, mechanical, low-risk: restores all inter-workflow webhook calls + all extraction on a local/fresh account.
- **M2** — sheet ID #3/#5 from one config source (combined one-spreadsheet model: data is a tab of the settings spreadsheet → one ID to route).
- **M3** — Gmail labels #4 resolve-by-name; make Label Engine bootstrap-safe on an empty inbox.
- **M4** — `indox/main/setup` workflow: provision Drive tree + settings spreadsheet (3 tabs seeded) + data sheet (52-col schema) + base Gmail labels → write IDs into config. Turns Part C into one click.
- **M5** — bug: `Snooze Incoming Document` calls the OLD `Incoming Documents 0.1.3`; repoint to active `0.1.7` [sv5xxRBVGxvV0kXx].

### Final verification loop (the acceptance test, after reset→onboarding)
creds gmail/gsheet/gdrive/gemini ✓ · docs **saved** from gmail+drive · **organized** in main table · **extracted** (ai+kw) ·
marked **completed** · **balance sheets** extracted → rows in main table · **label engine** organizing inbox ·
**google-workspace-agent** reachable via api / n8n chat. → M1 lights up most of it; M2/M3 complete it; M4 makes it self-provisioning.

### Prune (defer): 56 of 114 — [Example]×9, [Smoke Test]×4, scratch/test/eval ×~26, superseded versions
(0.1.3/0.1.4, Link Downloader 1.0, invoice -AI DOCUMENT, BS v2-shmuel), legacy ProcessGmail×2, MCP dup copies.

## Part G — 2026-06-19 progress + revised priorities (autopilot run)

**State now (active sheet `1SfWUiXCpzGcfgfqbd1xogN1sUpMIlsVajL-sKH4y11U`, account solutionsbina):**
- ✅ **Working Gemini billing key** (`.env` GEMINI_API_KEY, cred `6mfcsdRaqQ4IdQ8Y`) — invoice + BS extractors run.
- ✅ **End-to-end proven**: a real INVOICE reaches `STATUS=COMPLETED` with full extraction + auto-created
  linked SHIPMENT rows (invoice→shipment relationship).
- ✅ **M1 done** (base URLs internal) — confirmed inter-workflow + extraction calls work locally.
- ✅ **GDRIVE FOLDER SYNC repointed** to solutionsbina `1M9h`→`1HoB`; trigger is live (auto-polls ~15 min);
  solutionsbina's existing Drive balance sheets auto-ingest.
- ✅ **Google Workspace agent verified** (Gemini + Gmail/Drive/Sheets MCP all functional).
- ✅ **Robustness fix shipped**: `Determine Action` adopts Gemini `AI_TYPE` when local figure-type = UNKNOWN
  + routes UNKNOWN docs to the Gemini extractor (local keyword = fast-path, Gemini = reliable fallback).
- ✅ Created missing `suppliers` tab (gid 663229729).

**Critical n8n 2.17 op-note:** editing a workflow only updates the *draft*; you must
`n8n publish:workflow --id=<id>` **then restart n8n** for the active version to run the change.
(`bbox n8n push` must do publish+restart, not just import.)

**#1 revised priority — DATA, not code: populate the `Companies` tab** (name + ח.פ.). It is empty
(only header). `figure_company_id` maps doc→company via this table; with it empty, **balance sheets from
Drive stall at MISSING_COMPANY_ID** (invoices still complete via the embedded ח.פ.). This is the single
gating step for full BS processing. Pairs with M3 (labels) and the existing Part D refactors.

**Remaining new issues (non-blocking):** Error Handler→Telegram unconfigured (alerts undelivered);
`figure_company_id` OCR-fallback download fails for some Drive rows (isolate access vs pinData); duplicate
*inactive* MCP server workflows (Drive, Sheets) — prune; ancillary `DocumentUploader` / `Search File In
Warehouse` / `Google Integration Health` still ref prod folders.

**Deferred polish:** persist resolved `TYPE` to the sheet when adopted from `AI_TYPE` (cosmetic;
`SELECTED_DOC_TIPE` already carries the real type).
