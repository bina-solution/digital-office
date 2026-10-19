# Local-Setup PM Assessment — "clone → run → wizard → all apps → inject demo → watch it flow"

*Authored 2026-07-13. Owner: local-setup PM lens. Scope: the fully-local product experience for an
**average, non-technical user** on a **fresh machine** — no manual commands, no complicated setup.*

Companion docs: `incoming-documents-architecture-and-productization.md` (§ADDENDUM 2026-07-08 = the
single-business local model), `indox-demo-onboarding-architecture.md`, `release-lockin-plan.md`,
`indox-expected-behaviour.md`.

---

## 1. The north-star experience (what we're grading against)

A person who just heard about the platform:

1. Clones / downloads on a fresh machine, runs **`bbox`**, opens a **console in the browser** (via browser42).
2. Sees an **onboarding wizard**, chooses **"local setup"**.
3. All apps work locally (local drive, mail, OCR): **My Docs (פנקס)**, **Drive (דרייב)**, **Mail (מייל)**,
   **Inbox / indox** (with table, settings, sync state), **Notifications (התראות)** — every surface.
4. The **Inbox UI has an "inject demo" button** that injects **2 docs per sync registry**.
5. Those docs appear in the **Drive / Mail** UIs, and the **indox engine syncs + processes them naturally**,
   with full observability while it runs.

---

## Update — 2026-07-13 (post-monorepo): Wall 1 resolved, OCR verified live

Since the first pass, the two private submodules were **baked into the repo as a monorepo** (on
`release-v2-lockin`; `apitools` = 130 files in-tree, `.gitmodules` removed). This **resolves Wall 1** and
is the single highest-value fix for real users. Verified this session:

- **Compose parses to 46 services** with the real `apitools`/`chat` in-tree (was: fails).
- **OCR core builds and runs**: `apitools` image built here (Tesseract **5.5.0** with `heb`+`eng`,
  poppler, WeasyPrint), `/health` 200.
- **Hebrew OCR works locally, zero cloud**: `POST /documentOcr` on a real demo invoice
  (`demo-docs/invoice/files/mvral-1.pdf`, `OCR_ENGINE=local`) returned **1918 chars** with correct
  structured fields — company `מוראל לב מוצרי איכות לבניה בע"מ`, `ח.פ 516711157`, invoice date `30/04/25`.
  No Google Vision / Gemini billing needed (demo relies on the pre-seeded AI-extraction cache).

Net: the flow no longer breaks at step 0 on a normal machine. **On plain internet, `bbox run` now builds +
runs.** Walls 2–3 (secret bootstrap, auth gate) and the §5 product-shell gaps still stand. What remains to
demonstrate the *integrated* flow is the n8n orchestration bring-up (blueprint push → activate → demo inject
→ watch sync/process), which is heavy but now unblocked.

> Sandbox-only note (not repo issues): this managed session's proxy allows HTTPS/CONNECT egress only, so
> in-sandbox image builds need `--network=host` + apt pointed at HTTPS Debian mirrors, and the daemon needs
> `HTTPS_PROXY` for pulls. None of this applies on a normal host.

---

## 2. Verdict (headline)

**As-is, an average user on a fresh machine cannot reach this experience. The flow breaks at step 0 —
before any app renders — and several of the described product surfaces do not exist yet.**

The **bones are real and good**: three genuine, polished RTL-Hebrew app UIs exist and render, local
backends exist (GreenMail, inbox local mode, localdrive on Supabase storage, local Tesseract OCR),
and there is a clean declarative demo system. What's missing is the **first-run product shell** (wizard,
unified app console, in-inbox inject button, notifications app, no-touch bootstrap) **and** a hard
dependency on **private repos** that makes the public fresh-clone path impossible.

---

## 3. What actually exists today (verified)

### 3a. The local apps are real (screenshotted this session, booted locally)

| User's app | Service | Local route | Reality (verified render) |
|---|---|---|---|
| **My Docs** | `production/morning` | `morning.localhost` | ✅ "פנקס · ניהול מסמכים עסקיים" — RTL invoicing/accounting SPA: לוח בקרה, מסמכים, לקוחות, פריטים, הגדרות עסק, + מסמך חדש. BFF proxies apitools. |
| **Drive** | `production/localdrive` | `drive.localhost` | ✅ "דרייב · מסמכים וסנכרון" — upload / folders (labeled from `sync_registry`) / trash / new-folder / search / preview. Backed by Postgres `drive_files` + Supabase storage. |
| **Mail** | `production/mailview` | `mail.localhost` | ✅ "מייל · תיבת האוטומציה" — דורש טיפול (attention queue) / כל הדואר / sync-labels / reader+tagging. Reads `mailapi:8970`. |
| (extra) | `production/localmail` | `email.localhost` | ✅ Roundcube webmail over GreenMail (the only **un-gated** UI). |

Screenshots captured: `01-morning.png`, `02-localdrive.png`, `03-mailview.png` (booted the images
directly on their container ports this session — the SPAs render even before backends answer).

### 3b. Local backends exist
- `localmail` = GreenMail (IMAP 3143 / SMTP 3025), the local mail substrate.
- `inbox` selects backend by `GMAIL_IMAP_MODE` (`local` → GreenMail, `gmail` → real). Identical HTTP contract.
- `localdrive` writes storage-object + `drive_files` row → the Sync Scanner treats uploads like any file.
- `.env` local toggles exist: `OCR_ENGINE=local` (Tesseract), `DRIVE_API=local`, `GMAIL_IMAP_MODE=local`,
  `AUTH_EXTERNAL_URL=auth.localhost`.
- Declarative demo system: `bbox indox demo run <welcome|small|large>` + blueprints under
  `production/n8n/demo/` (1 / 5 / 30 docs per sync) driven through the INDOX API + an n8n workflow.

---

## 4. The three fresh-machine walls (why step 0 fails)

**Wall 1 — the compose graph can't parse. [RESOLVED 2026-07-13 via monorepo — see Update above.]**
`production/compose.yml` `include:`s two **private** submodules:
`apitools` (the OCR core) and `chat`. On a fresh clone both are empty dirs → `docker compose
config` fails outright → `bbox run` cannot start. An average user cloning the public repo has **no access**
to those private repos, so `git submodule update` doesn't save them. `apitools` is also the OCR engine, so
even stubbed, the indox engine cannot extract a document to `COMPLETED`.

**Wall 2 — `.env` ships non-runnable.** `cp .env.ex .env` yields **32 placeholder secrets**
(`change_me_to_random_32_hex...`) plus required-empty tokens (`BROWSER42_MCP_TOKEN`, `AUTHENTIK_SECRET_KEY`,
`SUPABASE_JWT_SECRET`, `N8N_ENCRYPTION_KEY`, `GOOGLE_OAUTH_*`, …). Compose won't even validate until ~15+
are hand-generated with `openssl`. There is no local `.env` bootstrap/keygen wired to do this automatically
(`scripts/supabase-keygen.py` exists but only covers the Supabase keys and isn't called by first-run).

**Wall 3 — everything is Authentik-gated.** `localdrive`, `mailview`, `morning` all carry
`middlewares=authentik`. Even after a boot, a non-technical user hits SSO before seeing any app. (Only the
Roundcube webmail is un-gated.)

> This session proved Walls 1–2 are the true blockers: after stubbing the two submodules and generating a
> valid `.env` (all secrets + Supabase JWTs + local toggles), `docker compose config` went from **fail** to
> **OK (42 services)**, and the three app images built + rendered. A real user has neither the submodule
> access nor the secret-generation know-how.

---

## 5. Product-shell gaps (vision vs. reality)

| Described surface | Status | Reality |
|---|---|---|
| Onboarding **wizard → "choose local setup"** (local vs cloud/VPS) | ❌ **Missing** | No browser wizard for deployment mode. Mode is chosen via the **bash** `bbox onboarding` + manual `.env` toggles. morning's onboarding overlay is only a *business-profile* form (name / ח.פ / VAT). |
| **Console** with end-user app tiles | ⚠️ **Partial** | `home.localhost` exists but is a **gethomepage infra/admin dashboard**; `localdrive`/`mailview`/`morning` carry **no `homepage.*` labels**, so they don't appear. No app launcher a naive user can navigate. |
| **Inbox / indox UI** (table, settings, sync-state) | ⚠️ **Backend only** | The inbox engine is entirely **n8n workflows + Supabase tables**. There is **no standalone indox UI**. mailview is only the mail view; drive rows live in localdrive. |
| **"Inject demo" button inside the inbox UI** (2 docs/registry) | ❌ **Missing** | No inject button / `/inject` / `/demo` endpoint in any frontend. Injection is CLI (`bbox indox demo`) + n8n workflow. Blueprints are **1/5/30** per sync — no "2 per registry" variant. |
| **Notifications / התראות** app | ❌ **Missing** | No frontend serves a notifications app. Closest signal is mailview's "דורש טיפול" attention queue. |
| Docs flow into **Drive/Mail** + indox **processes naturally** | ⚠️ **Blocked here** | Requires n8n + Supabase + blueprint push + the **apitools OCR core** (private) to reach `COMPLETED`. Not runnable on a public fresh clone. |

---

## 6. What could / couldn't be verified in this environment

- **Verified:** app images build (via the agent proxy) and render real UIs; `.env` can be made valid;
  compose parses to 42 services once submodules are stubbed + secrets generated.
- **Could not verify end-to-end** (honest OPEN items): the full indox sync→OCR→COMPLETED pipeline, because
  `apitools` (OCR) is a private submodule unreachable from this scope, and the full Authentik+Supabase+n8n
  stack + blueprint push + demo inject was out of proportion to the marginal visual value (empty inbox).

---

## 7. Prioritized backlog to reach the north star

**P0 — make a fresh machine actually run local (kills Walls 1–2). This is the whole ballgame.**
1. ~~**A real `local` compose profile that does NOT depend on the private submodules.**~~ **DONE
   2026-07-13** — submodules baked into the monorepo; graph parses (46 services) and the OCR core builds +
   runs local Hebrew Tesseract with no cloud. (Optional follow-up: a `--local` profile that also excludes
   `chat` / other non-local services for a leaner boot.)
2. **`bbox` first-run `.env` bootstrap**: auto-generate every secret (extend `supabase-keygen.py` to cover
   all `change_me*` + required-empty tokens) and set local toggles — zero manual `openssl`.
3. **Local auth path**: a `--local` mode that bypasses/auto-provisions Authentik (or a single seeded local
   user) so the apps open without an SSO detour.

**P1 — the first-run product shell (the "wizard + console" the user pictured).**
4. **Browser onboarding wizard** with an explicit **Local vs Cloud/VPS** choice that writes the toggles P0.2
   sets today by hand, then runs the bring-up and lands the user on the console.
5. **Unified app console**: add `homepage.*` labels (or a purpose-built launcher) so My Docs / Drive / Mail /
   Inbox / Notifications appear as tiles — the thing the user "opens" after setup.

**P2 — the inbox product surface + the demo loop.**
6. **Standalone Inbox/indox UI** surfacing the `incoming_documents` **table**, **settings/sync_registry**,
   and per-sync **sync-state** — the observability the user wants to watch while it runs.
7. **In-inbox "Inject demo" button** → calls the existing `INDOX Inject Demo` workflow; add a **welcome-2**
   blueprint (2 docs per sync registry) to match the requested demo size.
8. **Notifications (התראות) app** — or explicitly fold "needs-attention" into the inbox and drop it from the
   promised surface list.

**Recommendation:** do **P0 first and alone** — until a public fresh clone can `bbox run --local` to a
working set of apps without private access or manual secrets, every P1/P2 surface sits behind an
impossible first step. P0 is also the highest-leverage, most mechanical work.
