# Console (המרכז) — release sign-off

Prepared the night of **2026-07-13** for a **2026-07-14 morning** release. Autonomous PM
hardening + QA pass. Branch: `release-v2-lockin`.

## Verdict: **GREEN for release**, with ONE required pre-deploy step (apitools push).

The console — the unified Hebrew RTL business platform — is stable, consolidated, and
runtime-clean. All first-party surfaces embed in-shell; the estate passed a page-by-page QA,
a runtime error scan, a code audit, an RTL/Hebrew audit, a deploy-readiness audit, and a
core-flow functional test.

## Required before the deploy (1 item)

- **Push apitools + bump the submodule pointer.** The running document-extraction engine is
  `production/apitools` doc-models `7ff159b` (bidi-strip + one-call-per-value extraction), but it and
  3 prior commits are **not on any remote**, and the superproject records the older `68fb3a3`. A fresh
  `clone --recurse-submodules` + build would silently ship worse OCR/extraction. Recipe (order matters):
  `cd production/apitools && git push origin doc-models` → verify `origin/doc-models`=7ff159b →
  `cd ../.. && git add production/apitools && git commit` → push superproject. (Flagged as a task chip;
  see memory `apitools-submodule-pointer-race`.) Publishing code is an outward action left for the human.

## What shipped this pass (all committed on release-v2-lockin)

**Reliability**
- Install wizard no longer freezes when the connections plane is *reachable but erroring* (proxy
  returns a 502 JSON body → `fetch().json()` resolves → old `catch` never fired → `d.summary` threw).
  Now guards the shape. This screen is also the first-run landing.
- `boot()` catches a failing `/api/modules` instead of hanging the whole shell.
- `renderInstall` guards against clobbering a newer view when its slow probes resolve late.

**Security / correctness**
- Proxy rewrites app-absolute (`http://machine:8080/…`) redirect Locations, not just root-absolute —
  no internal hostnames leak to the client.
- `esc()` is attribute-safe (escapes quotes); KPI card values escaped; OAuth popup `noopener`.

**Consolidation / UX**
- Install wizard leads with the **human steps only**; 35-connection catalog collapsed behind
  "מתקדם"; Hebrew titles (`title_he`) for the Google/WhatsApp/Gmail onboarding surfaces + Hebrew
  group headers everywhere (incl. the "Apps & Data" group).
- "לוח בקרה" is the console's **native** live dashboard (KPI strip), not a new-tab homepage.
- **פנקס** embeds same-origin; document-creation editor verified working in-shell (RTL panel fix).
- De-duplicated embedded-app chrome (drive/mail/whatsapp no longer show a doubled brand).
- Launch cards (n8n/glitchtip/homepage — heavy SPAs that can't be path-prefixed or framed) are a
  polished centered hero.

**Cross-app polish** (morning RTL shadow, localdrive Hebrew placeholder, machine empty-state +
env-var-leak text, feature-validation neutral load banner, deleted dead mailview CSS).

## Verification evidence

- **Runtime error scan** (all 13 pages, fresh context): **0 console errors, 0 page errors.** The only
  2 network entries were `net::ERR_ABORTED` on pollers cancelled by navigation — benign.
- **Deploy-readiness audit**: console + morning images are byte-for-byte source==running; Dockerfiles
  COPY the right files; all 9 `/a/<name>/` embeds return HTTP 200 with real bodies.
- **Functional (through the embed proxy)**: פנקס new-document editor opens with the full Hebrew
  form; מייל lists real Gmail (2,207 messages, status pills, time grouping); דרייב folders API 200 +
  UI; מכונה live host metrics (CPU/mem/storage/44-of-46 containers); אימות loads the suite. Every
  checked API returned HTTP 200 through `/a/<name>/`.
- **Host note**: the deployment host sits at ~8.2/12 GB RAM (69.8%). Heavy parallel browser sessions
  can push Docker into memory pressure (see `stack-memory-pressure-flakiness`); the release host
  should have headroom, and the validation suite's extraction failures are apitools/Gemini-side
  (see the apitools push item + `gemini-billing-dunning-403`), not console defects.
- **Responsive**: **tablet (768px) is clean** (the stated target); phone (390px) is cramped by the
  fixed 238px sidebar — documented as out-of-scope for this business admin console.

## Session-2 additions (2026-07-13, later)

- **Bank-standard mutation safety (system-wide).** A double-click on פנקס's create button was minting
  duplicate invoices (no feedback → re-clicks → duplicate documents). Fixed exactly-once at both
  layers (frontend re-entrancy guard + disabled/loading buttons + idempotency key; morning BFF per-key
  lock + replay). **Verified: 5 concurrent identical submits → one document.** Then audited + guarded
  EVERY mutation across all self-developed apps (morning documents/converts/customers/issue-pay-cancel,
  drive delete/rename/move/upload, mail tags, install wizard) with idempotency keys on create paths.
- **Drive upload 500 fixed.** `/api/files` called `.isdigit()` on a bigint size → 500 (broke the
  listing). Fixed + uploads now fail gracefully per-file. **Full-system HTTP-error scan (every ≥400
  response across all apps + iframes, incl. navigation): CLEAN.**
- **INDOX UI — full four-section PM-harness experience** at /a/incoming/ (replaced the n8n launch
  card): the React SPA + Python BFF, embedded in-shell with a light 4-section nav (fixed the dark-
  topbar double-nav), reading LIVE supabase data. **מסמכים** (live 47-col documents) · **סנכרון**
  (live board polling the n8n STATUS webhook; gracefully lists the 5 registry syncs when n8n is down) ·
  **הגדרות** (live config: settings 45 / companies 60 / tag_rules 23; allowlist-guarded edits) ·
  **בדיקות** (test-suite runner proxying feature-validation — הרץ/הרץ-הכל with live progress; verified
  document-ocr 6/6). Fixed a real config bug: BFF now uses the INTERNAL kong:8000 supabase gateway.
  Live sync *counts* await the n8n encryption-drift fix (flagged).
- **התראות live**: self-developed notifications service, GlitchTip bootstrapped + read token minted
  declaratively (reproducible in glitchtip-push).
- **Double-navigation fixed across all 4 apps** (morning horizontal tabs; mail/drive light panels;
  wadmin light via console override). Plus a **2026 nav research + design doc**
  (ai/context/platform-navigation-design.md).

## Known, accepted limits (not blockers)

- n8n (מסמכים נכנסים/INDOX), glitchtip (התראות), homepage (אפליקציות) open as launch cards — they
  bake an empty basePath (blank under `/a/` proxy) and can't be cross-origin framed (glitchtip
  `X-Frame: DENY`; n8n needs its own login). A native INDOX page is the long-term answer.
- The connections plane can't DNS-resolve `authentik-postgres`/`glitchtip-postgres` (they sit on
  separate internal networks) → 2 cosmetic "degraded" rows that dent the readiness count. No functional
  impact.
- Deploy note: `connections` reads `ui.html` once at startup — a fresh image build bakes it correctly;
  only live hot-edits need a container restart.
- Phone (<640px) layout; native-dialog (prompt/confirm) vs Bina-modal in a few apps; proxy streams
  large bodies fully into memory — all documented as post-release polish.
