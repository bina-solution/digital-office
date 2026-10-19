# The full task list — perfect INDOX + Hacohen live (2026-08-05)

Two tracks, run in parallel. Every item is either MEASURED (evidence in
[hacohen-cutover-plan-2026-08-05.md](hacohen-cutover-plan-2026-08-05.md)) or explicitly flagged as
unverified. Status: ✅ done · 🔄 in flight · ⛔ blocked · ⬜ not started

---

# TRACK 1 — INDOX app: stable, best-practiced, no gaps

## 1A. Correctness defects (must fix — these cause silent data loss)

| # | Item | Status | Notes |
|---|---|---|---|
| 1A.1 | **Drive listing truncated at ~460 files/folder** — `_list()` never followed `nextPageToken` | ✅ | Fixed. Hid **43,326** files (35,325 → 78,651). `folders()` already paginated; `_list` now matches. |
| 1A.2 | **`hasAttachment` structurally always false** — search never fetched `BODYSTRUCTURE` | ✅ | Fixed + rebuilt. 226/400 client messages now correct. |
| 1A.3 | **indoxHealth probed Drive via the SA** (which cannot create) → 108 errors/day | ✅ | Pinned to `profile_id: admin`; pushed live. |
| 1A.4 | **`dest_folder` has TWO sources of truth** — any pipe with `processor_wf` ignores the registry and reads `public.settings` instead | 🔄 | Agent implementing. Means editing the destination in the UI silently does nothing for gmail-doc/bs/link. |
| 1A.5 | **`SOURCE_ID` stores the wrong identity** — folder id for drive rows, *sender email* for gmail rows. 579 distinct values over 6,250 rows | ⬜ | The single worst data-model defect. Blocks all per-document reconciliation; forced use of `LINK`/`HASH` instead. Fix the writers, then migrate. |
| 1A.6 | `indoxGmailLinkDownloader01` node **Upload file** hardcodes `folderId: "root"` | 🔄 | Bundled into 1A.4. |
| 1A.7 | **`FAILED_BS` cross-wired** — `gmail-doc` and `gmail-link` stamp general-document failures with the *balance-sheet* failure label | ⬜ | No `FAILED_DOC` key exists in `tag_rules`; needs one added. |
| 1A.8 | **`mail-private` uses key `connection_id`**, the other three use `connection`; drive `list_ctx` reads only `s.connection` | ⬜ | Normalise to one key; `Build Units` already tolerates both for gmail only. |
| 1A.9 | Local `create_folder` has **no dedupe** — same name twice ⇒ two folders | ⬜ | Get-or-create lives in the caller; drive app should be idempotent itself. |
| 1A.10 | `_ensure_upload_folder` name-matches against `folders()`, which includes **phantom** folders | ⬜ | Cannot distinguish provisioned from phantom. Minor, but note it. |
| 1A.11 | **Phantom local folders** named after Google ids (`15As7by…` 3 files, `1UMGaSMm…` 3 files) | ⬜ | Cleanup once 1A.4 lands and real folders exist. |

## 1B. Regression protection (so none of the above comes back)

| # | Item | Status |
|---|---|---|
| 1B.1 | **Gate: no unpaginated Drive list.** Lint that any `_json(... "/files" ...)` list call either follows `nextPageToken` or passes an explicit bounded `limit` | ⬜ |
| 1B.2 | **Test: folder with >1000 files returns all of them** (fixture or mock) — directly pins 1A.1 | ⬜ |
| 1B.3 | **Test: `hasAttachment` true for a multipart message** — pins 1A.2 | ⬜ |
| 1B.4 | **Gate: one source of truth for sync destinations** — fail if a processor reads a destination from anywhere but the registry | ⬜ |
| 1B.5 | **Gate: `SOURCE_ID` must be a per-document id**, never a folder id or an email address | ⬜ (after 1A.5) |
| 1B.6 | Existing 23 gates still green after all of the above | ⬜ |

## 1C. Data hygiene

| # | Item | Status | Notes |
|---|---|---|---|
| 1C.1 | Purge 47 test-fixture rows (`sv3f_*`,`sv3s_*`,`mailorg_*`) from `incoming_documents` | ⛔ | Backed up (`testfixture_backup.csv`); DELETE blocked by the local permission classifier on every attempt. Needs owner to run or to grant. |
| 1C.2 | `DOC_DATE` normalisation (63 rows: `DD/MM/YYYY` + Excel serials → ISO) | ✅ | NOTE: my earlier "dates are corrupt" alarm was **wrong** — 98.9% were already clean; the artefact was my own `LEFT(...,7)` truncation. |
| 1C.3 | **`DOUBLE` = 731 rows** (530 of the matched drive set) — largest defect class among ingested docs | ⬜ | Investigate duplicate detection: is it real duplication, or a hashing/matching bug? |
| 1C.4 | ~720+ **orphan legacy labels** on real client mail that no rule produces and no registry consumes | ⬜ | Decide: migrate into `tag_rules`, or treat that mail as historical and let backfill catch it by attachment. |
| 1C.5 | n8n duplicate workflows (31 active pairs from the id rename) | ✅ | 113 → 81, zero duplicate names, backup kept. |

## 1D. Observability / UX

| # | Item | Status |
|---|---|---|
| 1D.1 | **`GET /sync/inventory`** — per-source at_source / in_indox / remaining, with `counted: exact\|approx\|cached` (never a silent approximation) | 🔄 |
| 1D.2 | **Sync sources UI rebuild** — folder NAMES not raw ids, Hebrew label NAMES not keys, real progress, totals strip, visible errors instead of silent zeros | 🔄 |
| 1D.3 | Items board shows only `sync_ledger`; the 6,250-row corpus is invisible there | ⬜ |
| 1D.4 | Mail UI per-row processed/waiting indicator | ⛔ | **Conflicts with a documented decision** (`app.js:31-36`: "Mail is a MAIL app. It has no opinion about INDOX"). Needs an explicit owner call before reversing. |
| 1D.5 | Surface *why* a source is unreachable rather than rendering 0 | 🔄 (part of 1D.1/1D.2) |

## 1E. CI / release

| # | Item | Status |
|---|---|---|
| 1E.1 | 2 of 4 GH Actions re-runs for `dc2ef35` not re-triggered | ⬜ (Chrome extension kept dropping) |
| 1E.2 | Self-hosted `portable-ssd` runner — was offline all session; now registered | ⬜ verify green |
| 1E.3 | Commit + push everything from this session | ⬜ |

---

# TRACK 2 — Hacohen live, proven

## 2A. Connect the real sources

| # | Item | Status | Detail |
|---|---|---|---|
| 2A.1 | **Rebind 4 gmail registries** from demo `…-83db1e42` (`person2@example.com`) to client `…-51185288` (`person9@example.com`) | ⛔→ | THE mail blocker. Engine tags client box; registries scan demo box. Must land *with* 2A.2. |
| 2A.2 | **Destination → local drive `automations/<sync-name>`** (owner's model) | 🔄 | Blocks 2A.1: flipping the connection alone would deposit client documents into the dev sandbox. |
| 2A.3 | **Create 4 drive sync registries** for the confirmed sources | ⬜ | `שמירת מסמכים אוטומטית- מייל ודואר` (50) · `מסמכים מהבוט בווצאפ` (584) · `סרוקות- לפני שמות` (380) · `שמירת דוחות אוטומטית` (7) |
| 2A.4 | Decide done/failed folder per source | ⬜ | Natural pairs exist for 3 of 4; the WhatsApp bot folder has no obvious pair — needs owner input |
| 2A.5 | Retire the sandbox registries (`סינכרון` tree, 5 files) | ⬜ | |

## 2B. Backfill — the measured work

| # | Item | Count | Status |
|---|---|---|---|
| 2B.1 | **The four sources** | **977 missing of 1,021** | ⬜ THE immediate, tractable job |
| 2B.2 | Failure buckets — the `(בוריס)` manual backlog | **5,010** | ⬜ goal 8: move back to `to_sync`, reprocess |
| 2B.3 | Mail 6-month window, attachment-by-attachment | 908 messages | ⬜ only 550/908 enumerated (IMAP pool throttles deliberately) |
| 2B.4 | Historical archive (2021-2024 trees, automation output) | ~67,000 | ⬜ **OUT OF SCOPE unless owner says otherwise** |

## 2C. Prove it works

| # | Item | Status |
|---|---|---|
| 2C.1 | Drop a new file in EACH source → watch it reach `COMPLETED` | ⬜ |
| 2C.2 | Send a new mail with an attachment → labelled → synced → `COMPLETED` | ⬜ |
| 2C.3 | WhatsApp bot document → `COMPLETED` | ⬜ |
| 2C.4 | Scanner drop → `COMPLETED` | ⬜ |
| 2C.5 | All of the above **visible and manageable** in the sync state view | ⬜ (needs 1D.1/1D.2) |
| 2C.6 | Re-run reconciliation; assert absent-count for the 4 sources is **0** | ⬜ |

---

## Ordering (what unblocks what)

```
1A.4 (dest_folder) ──┐
                     ├──> 2A.1 (rebind) ──> 2B.1 (backfill 977) ──> 2C.* (prove) ──> 2C.6 (assert 0)
2A.3 (drive regs) ───┘
1D.1 (inventory API) ──> 1D.2 (UI) ──> 2C.5 (manageable)
1A.5 (SOURCE_ID) ──> 1B.5 (gate)          [independent, but required for "perfect"]
```

## Open decisions needed from the owner

1. Done/failed folder for `מסמכים מהבוט בווצאפ` (no natural pair in the tree).
2. Is the ~67,000-document historical archive in scope, or is 6-months-forward enough?
3. Reverse the "mail app has no INDOX opinion" decision to add the per-row indicator? (1D.4)
4. Run the blocked test-fixture DELETE (1C.1).
