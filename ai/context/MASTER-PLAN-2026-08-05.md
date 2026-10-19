# MASTER PLAN — INDOX perfect + Hacohen live (2026-08-05)

Supersedes `indox-perfect-and-hacohen-live-tasklist.md`. Everything here is MEASURED against the
live system unless explicitly marked as an assumption.

Status key: ✅ done & verified · 🔄 in flight · ⛔ blocked · ⬜ not started · ⚠️ found, not yet fixed

---

# PART 1 — What was asked (the last ~20 owner messages, condensed)

| # | Ask | Where it stands |
|---|---|---|
| 1 | Fix CI / GitHub Actions green | ⛔ runner registered, but 2 of 4 runs not re-triggered — no `gh` CLI, Chrome ext down |
| 2 | Clean up duplicate n8n workflows | ✅ 113 → 81, zero dupes |
| 3 | Scan the CLIENT's real accounts, not local engines | ✅ drive + mail both scanned live |
| 4 | Save the app password, gitignored | ✅ `secrets/` + `.gitignore` |
| 5 | Deep-scan the mailbox; confirm all documents synced | ✅ measured — they are NOT (see Part 3) |
| 6 | Deep-scan drive; list all 6-month documents | ✅ 78,651 files / 441 folders |
| 7 | Full folder tree via browser42 | ✅ obtained via Drive `type:folder` search |
| 8 | Deep scan the shared master folder, count documents | ✅ 78,651 |
| 9 | Share folders with the SA / use browser42 for it | ✅ owner shared; SA sees the tree |
| 10 | Ensure every client document is in INDOX | ✅ measured: **30.1%** coverage |
| 11 | Mail registries → local drive `automations/<name>` | ✅ implemented + provisioned |
| 12 | Make the sync UI genuinely usable | 🔄 rebuilt; blocked on deploy |
| 13 | Full task list to the desired state | ✅ this document |
| 14 | The final 7 sync registries | 🔄 3 mail rebound; drive 4 pending |
| 15 | `יצוא צט` is the chat-export folder (not WhatsApp) | ✅ corrected |
| 16 | Mail attachment inventory (sender/date/slug/name/size) | ✅ delivered (partial sample — see Part 3) |
| 17 | June 06/26 deep dive; "should be ≥3000/month" | ✅ confirmed — 3,110 in drive, 526 in INDOX |
| 18 | Add a "done" column to the registries table | ✅ Part 4 |
| 19 | INDOX table → production ERP grade | 🔄 4 agents |
| 20 | Full interactive browser42 QA | ⬜ Part 6 |

---

# PART 2 — Every defect found (the real inventory)

## 2A. SILENT TRUNCATION — a query treated as the whole truth
The single most damaging pattern in this codebase. Four instances in one day.

| # | Defect | Impact | Status |
|---|---|---|---|
| T1 | `google.py::_list()` never followed `nextPageToken` | **hid 43,326 of 78,651 documents.** Folders holding 17,066 files reported exactly 460 | ✅ fixed + **G36 gate** |
| T2 | `shared_folders()` capped at 200, no token | a SA's whole world is what's shared with it — silently invisible sources | ✅ fixed (found BY G36) |
| T3 | `PG Get All` `limit 5001` no `ORDER BY`, **and** `Guard Get Size` CAP=5000 vs 6,203 rows | the dedup sweep was **throwing on every run**, not merely truncating | ✅ fixed |
| T4 | `folders()` hard-caps at 600; the client already has 443 | latent — will silently lose folders as they grow | ⚠️ **not fixed** |

## 2B. TWO SOURCES OF TRUTH — four separate instances
| # | Defect | Status |
|---|---|---|
| D1 | `dest_folder`: registry vs `public.settings` (`GmailDownloadedDocumentsFolder`). Pipes with a `processor_wf` ignored the registry entirely | ✅ fixed |
| D2 | Tag rules: supabase `public.tag_rules` **vs** mail app `/data/organizer-defaults.json`. The supabase copy is stale legacy; seeded once, never re-read. **I corrected the wrong one first** | ✅ both aligned — ⚠️ duplication itself remains |
| D3 | Label KEY→name resolution: the n8n engine resolves it, the BFF did not | ✅ fixed (2 functions) |
| D4 | `app.json`'s `upload_folder` declaration vs the env var — agree by coincidence, not wiring | ⚠️ not fixed |

## 2C. IDENTITY / DATA MODEL
| # | Defect | Status |
|---|---|---|
| I1 | `SOURCE_ID` held the *folder id* (drive) and the *sender email* (gmail). 579 distinct values over 6,203 rows. **Live bug**, not just legacy | ✅ 5 writers fixed + **G37 gate** — ⬜ needs `bbox n8n push` |
| I2 | 5,477 historical rows still wrong. Both recoverable (drive from `LINK`, gmail from `SOURCE_LINK`, 2,324/2,324 matched) | ⬜ migration written, **not executed** |
| I3 | `slice(-5)` truncates doc ids from the **wrong end** — vendors whose numbers vary by *prefix* all collapse to one key | ⚠️ not fixed |
| I4 | Extraction writes **dates** into `COMPANY_DOC_ID` — every Feb-2026 date collapses to `'22026'` | ⚠️ not fixed |
| I5 | `DOUBLE` = 731 rows, ≥54% (DB) / ≥64% (Drive) false positives. 17 genuinely different invoices flagged as one | ✅ placeholder case (11 rows) + non-terminal — ⚠️ the rest needs I3/I4 |

## 2D. CONFIG / WIRING
| # | Defect | Status |
|---|---|---|
| C1 | All 4 gmail registries bound to the **demo** mailbox while the engine tagged the **client** | ✅ 3 rebound |
| C2 | Registry pointed at a 5-file dev sandbox, not the 78,651-file production tree | 🔄 mail done, drive pending |
| C3 | `FAILED_BS` cross-wired: doc failures stamped with the balance-sheet failure label | ✅ `FAILED_DOC` added |
| C4 | `mail-private` **cannot be edited at all** — validation demands `processor_wf` for every v3 entry, but thin-mode entries have none | ⚠️ not fixed (retire it) |
| C5 | `mail-private` uses `connection_id` where others use `connection`; drive `list_ctx` reads only `connection` | ⚠️ not fixed |
| C6 | Phantom local folders literally named after Google ids (`15As7by…` etc.) | ⚠️ not cleaned |
| C7 | Label engine throughput: **10 messages / 15 min** (~40/hr) against a 41,401-message backlog | ⚠️ **blocks any backfill** |

## 2E. UI
| # | Defect | Status |
|---|---|---|
| U1 | **Pagination broken** — 63 pages, only page 1 reachable (98% of data unreachable) | 🔄 |
| U2 | Filter popup mispositioned/immature | 🔄 |
| U3 | No inline STATUS editing | 🔄 |
| U4 | No month navigation; 3 disagreeing date columns | 🔄 |
| U5 | No card view / THUMBNAIL | 🔄 |
| U6 | Document detail page is 123 lines | 🔄 |
| U7 | Sync board showed raw folder ids + raw label keys | ✅ |
| U8 | Every gmail lane read 0/0/0/0 despite 919 waiting (root cause D3) | ✅ fixed — ⛔ **not deployed** |
| U9 | Items board reads only `sync_ledger`, so the 6,203-row corpus is invisible | ⚠️ not fixed |

## 2F. OPERATIONAL
| # | Item | Status |
|---|---|---|
| O1 | 47 test-fixture rows in the production table | ✅ purged (6,250 → 6,203) |
| O2 | 31 duplicate active n8n workflows | ✅ purged |
| O3 | indoxHealth 108 errors/day (SA can't create files) | ✅ fixed |
| O4 | `hasAttachment` structurally always false | ✅ fixed |
| O5 | `DOC_DATE` normalisation (63 rows) | ✅ — ⚠️ my "dates are corrupt" alarm was **wrong**; artefact of my own `LEFT(...,7)` |
| O6 | **Webapp build is RED** — 3 agents mid-edit | ⛔ blocks all deploys |
| O7 | `gallery-default-lint` + `browser42-site-neutrality-lint` failing | pre-existing, other session's files |

---

# PART 3 — The coverage truth

| Measure | Value |
|---|---|
| Drive files (441 folders) | **78,651** |
| 6-month window (2026-02..08) | **19,683** |
| In INDOX for that window | **5,924** |
| **Coverage** | **30.1%** — 13,759 missing |
| June 2026 alone | 3,110 drive vs 526 INDOX = **17%** |
| Monthly trend | 86% → 54% → 36% → 24% → 17% → ~0% (Jul/Aug) |
| Mailbox total / 6-month | 83,442 / 8,624 |
| Attachments measured | 3,322 across 1,734 messages (**1.92 per message**) — from a 28% sample |
| Attachments projected (6m) | **~11,000–12,000** |
| to_sync labelled messages | **41,401** |

**Conclusion:** real throughput is ~3,000 documents/month. INDOX holds a minority, and capture
collapsed entirely after June 2026.

---

# PART 4 — The seven registries (with done/failed)

| # | Registry | To sync | Done | Failed | Status |
|---|---|---|---|---|---|
| 1 | mail gdoc | `לטיפול-אוטומציה-שמירת-מסמכים` **38,618** (919 in 6m) | `אוטומציה-שמירת-מסמכים-טופל` 15,444 | `אוטומציה-שמירת-מסמכים-נכשל` 699 | ✅ rebound |
| 2 | mail bs | `לטיפול-אוטומציה-שמירת-דוחות-גיול` 520 (22) | `דוח-גיול-נשמר-אוטומציה` 2,338 | `אוטומציה-דוחות-גיול-נכשלה` 377 | ✅ rebound |
| 3 | mail gdoc link | `לטיפול-אוטומציה-קישור-למסמך` 2,263 (1) | shares SYNCED_DOC | shares FAILED_DOC | ✅ rebound |
| 4 | drive gdoc | `מסמכים כללים` — **create** | `בוצע` | `נכשל` | ⬜ |
| 5 | drive bs | `מסמכים כללים` — **create** | `בוצע` | `נכשל` | ⬜ |
| 6 | drive chat export | `יצוא צט 2026 לפני` 401 | `יצוא צט 2026 אחרי` 2,427 | `יצוא צט 2026 נכשל` 713 | ⬜ |
| 7 | drive warehouse scans | `סרוקות- לפני שמות` 380 | `סרוקות הצליח` 17,066 | `סרוקות- נכשל (בוריס)` 2,001 | ⬜ |

To retire: `mail-private`, `drive-invoices`, `drive-gdoc`, `drive-bs` (all sandbox-pointed).

---

# PART 5 — Forward plan, in dependency order

### Phase 0 — UNBLOCK (nothing ships until this is green)
- **P0.1** Land the 3 webapp agents; get `npx tsc -b` + `npm run build` green. ⛔ **blocks everything**
- **P0.2** Deploy the D3 label-resolution fix (written, compiles, undeployed)
- **P0.3** `bbox n8n push` for the I1 SOURCE_ID writer fixes
- **P0.4** Verify: gmail-doc reports `at_source≈919`, not 0

### Phase 1 — finish the registry set
- **P1.1** Create `מסמכים כללים` + `לסינכרון`/`בוצע`/`נכשל` under root `חשבוניות הכהנים`
- **P1.2** Build registries #4–#7; retire the four sandbox ones
- **P1.3** Fix C4 (thin-mode validation) so any entry is editable
- **P1.4** Normalise C5 (`connection` vs `connection_id`)

### Phase 2 — make the backlog movable
- **P2.1** Raise the label-engine batch limit (C7) — 40/hr cannot clear 41,401
- **P2.2** Prove one message end-to-end: label → registry → download → INDOX → COMPLETED
- **P2.3** Backfill mail (919 + 22 + 1 for the 6-month window)
- **P2.4** Backfill drive sources (#6: 401, #7: 380)
- **P2.5** Reprocess the failure buckets — `(בוריס)` folders, **5,010 files**

### Phase 3 — data correctness
- **P3.1** Execute the I2 SOURCE_ID migration (5,477 rows; both types recoverable)
- **P3.2** Fix I3 (`slice(-5)` wrong end) and I4 (dates in `COMPANY_DOC_ID`)
- **P3.3** Re-sweep DOUBLE; target ≪731
- **P3.4** Clean phantom folders (C6)
- **P3.5** Decide the ~67,000 historical archive: in scope or not

### Phase 4 — hardening
- **P4.1** Gate for T4 (`folders()` 600 cap) and a test for the 460 case
- **P4.2** Gate for D1/D2 — one source of truth for destinations and labels
- **P4.3** Test: `hasAttachment` true on a multipart message
- **P4.4** Full gate sweep green (26 gates)
- **P4.5** GitHub Actions green (O7 + re-trigger)

### Phase 5 — proof
- **P5.1** Drop a new document into EVERY source → reaches `COMPLETED`
- **P5.2** Re-run reconciliation; the four sources must show **0** absent
- **P5.3** Coverage for a fresh month ≥ 95%

---

# PART 6 — browser42 interactive QA (full coverage)

Run **after Phase 0**, via `./bbox b42 task ...` (see `ai/context/browser42-cli.md`). Every item is a
real click-through on `console.localhost`, not a code assertion.

### 6A. INDOX table (`מסמכים`)
1. Navigate to page 2, 33, 63 — assert row content **changes** (this is U1, the headline bug)
2. Rows-per-page 25/50/100/200 — count matches
3. Sort each visible column asc/desc — verify order and stability
4. Filter per type: text contains/equals/empty · enum multi-select · date range · number range
5. Two filters combined = AND; clear-all restores 6,203
6. Free-text search across name/company/type/status
7. Inline STATUS → `ACTION_RESTART`; reload; assert it persisted
8. Month navigation: pick 2026-06 → assert **526** rows; switch the date column; assert "no date" bucket
9. Card view toggle; THUMBNAIL renders; placeholder where absent; card→detail navigation
10. Column picker show/hide/reorder persists
11. Export produces a real file
12. Performance: page-change and sort < 1s at 100 rows

### 6B. Document detail
13. Open from table and by direct URL
14. Preview renders (PDF and image)
15. Extracted fields grouped and readable
16. Processing history / state visible
17. Actions work: retry · change status · open original
18. Back returns to the same page+filters

### 6C. Sync board (`סנכרון`)
19. All 7 registries listed with **folder names and Hebrew label names** — no raw ids/keys
20. `at_source` / `in_indox` / `remaining` are non-zero and match the DB
21. `≈` shown when `counted != exact`
22. Errors shown instead of silent zeros
23. Run-now on one pipe → progress → item count changes
24. Pause/resume, edit, delete
25. Items board: `to_sync`/`in_progress`/`synced`/`failed` reconcile with the source

### 6D. End-to-end live
26. Drop a file in each of the 4 drive sources → appears → `COMPLETED`
27. Send a mail with an attachment → labelled by the engine → synced → `COMPLETED`
28. Chat-app upload → lands in `automations/uploads` → INDOX
29. Move a failure-bucket file back to `to_sync` → reprocesses → `COMPLETED`

### 6E. Cross-app
30. Mail UI: label-engine indicator on/off states correct; **no INDOX concept leaks**
31. Drive UI: `automations/*` folders visible with the right contents
32. Settings: `default-upload-folder` editable and honoured
33. RTL correctness and no console errors on every page

**Exit criteria:** every item passes on the live stack, evidence captured via
`b42 task screenshot` + `finish`, and the reconciliation in P5.2 reports zero absent for the four
active sources.
