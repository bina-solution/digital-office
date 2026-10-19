# INDOX Duplication — State, Design Verdict, and Go/No-Go

**Generated:** 2026-08-13, from live measurement against `supabase-db-shlomo-laptop` / `public.incoming_documents`.
Every number below came from a query, not an estimate. Where a figure is uncertain it says so.

---

## 0. The two questions you asked, answered first

### "Is the system designed well, and not generating redundant duplications?"

**Detection: NO — it is structurally incapable of finding most duplicates.**
**Merge: NO — until today it could merge documents that visibly disagree, and it still cannot be undone.**
**Prevention: PARTLY — one real guard works perfectly; the guard that matters most does not exist.**

The single sentence that explains all of it:

> The only dedup key enforced at INSERT is `HASH` (the file's md5). The only key that expresses *business* identity — company + document number — does not exist until an AI extraction that runs **a median of 13.9 hours after the row is inserted** (p90 77.7h, max 9.8 days). Every ingest path therefore inserts first and learns identity later, and **nothing re-checks afterwards**.

### "Should we raise the batch to 30k so real duplication detection can run?"

**Your diagnosis is right; the batch is not the fix.** Detection today happens in `indoxV2Decide01 → Determine Action`, against `processedDocs` — an **in-memory Map scoped to one batch**. Two rows are only ever compared if they land in the same batch, which is why a BS-line child and its Drive twin, created days apart, were never compared.

Measured against the current 20,000 batch and the table's own `ORDER BY "ID"`:

| Batch size | Groups split across batches | Excess rows invisible |
|---|---:|---:|
| **20,000 (configured today)** | **583 of 4,173 — 14.0%** | 896 |
| 5,000 (the GET_ALL cap) | 2,675 of 4,173 — 64.1% | 3,716 |
| 32,565+ (one shot) | 0 | 0 |

So a 30k single-shot *would* work — but it means holding the whole table in n8n memory, and this box has already OOM-killed workers twice today. **The better answer is already built:** a set-based detection pass in Postgres (`indox_merge_groups`, `indox_refresh_merge_groups()`) that decides over the whole table in SQL and writes verdicts to a table. The adjudicator then *looks up* a verdict instead of *inferring* one from whatever happened to share a batch. No 32k n8n batch, no memory wall, and — critically — a **staleness fingerprint** the in-memory Map can never have.

**Recommendation:** keep the runtime batch where it is, make it settings-driven so it *can* be raised, and wire the adjudicator to the SQL detection pass. That is the remaining step.

---

## 1. Current state

| Measure | Value |
|---|---:|
| Total rows | 32,691 |
| Duplicate groups | 4,249 |
| Rows inside those groups | 9,784 |
| **Excess rows** | **5,535** |
| Already demoted (DOUBLE/MERGED) | 1,732 |
| Still to resolve | 3,803 |
| **Distinct real documents** | **~27,150** |

Identity key = `COMPANY_ID` + `coalesce(DOC_ID, COMPANY_DOC_ID)` under the pipeline's own validity filter (transcribed from `indoxApi01 → Resolve IDs._docIdKeyable`, not invented).

**The row count does not change after a merge.** A loser is tombstoned (`STATUS='MERGED'`, `MERGED_INTO` set) and keeps its `LINK`, `HASH`, `SOURCE_TYPE`, `SOURCE_ID` so `sync_ledger`, the board join and Drive matching keep resolving. Nothing is ever deleted.

### Tier breakdown (materialised, reconciles exactly)

| Tier | Rule | Groups | Excess | Action |
|---|---|---:|---:|---|
| **A** | ≤1 row has a real HASH | 988 | 1,253 | auto-MERGE |
| **B1** | ≥2 files, date AND amount present everywhere and identical | 860 | 1,115 | auto-MERGE |
| **B2** | one corroborator agrees, the other absent | 1,272 | 1,858 | **ATTACH** (see §4) |
| **C** | date and/or amount **conflict** | 1,012 | 1,222 | human only — never auto |
| **D** | no corroborator at all | 41 | 87 | human only |

**76.3% resolves automatically. 23.7% needs a human** — and that human queue is not optional; it is where invoices that genuinely share a document number live.

---

## 2. Where duplication actually comes from

### It is NOT the balance-sheet parser

| Check | Result |
|---|---|
| Children spawned | 6,864 from 528 parents (max 232) |
| Duplicate rows **within** one parent | **5** |
| Duplicate rows **across** parents | **0** |
| Re-processing a balance sheet re-spawns lines? | **No** |

### It is NOT re-scanning the same file

Of 4,525 Drive×Drive duplicate pairs:
- **0** share a physical Drive file id → not a re-read
- **4,403 (97.3%)** are in **different folders**
- **3,693 (81.6%)** share the same filename

**This is the client genuinely filing the same invoice twice**, typically once in a month folder and once under the supplier. It is 51–54% of all duplication and **cannot be prevented at ingest** — at ingest they are two real, different files.

### It IS the identity blind window

| Source | Born with a doc number? | Excess rate |
|---|---|---:|
| BALANCE_SHEET | **yes** | **7.3%** |
| INVOICE | **yes** | 7.9% |
| GOOGLE_DRIVE_FOLDER | no | **25.8%** |
| MAIL_ATTACHMENT | no | **31.1%** |
| GMAIL | no | **2.0%** ← the honest counter-example |

Same table, same upsert, same matcher — a 3–4× spread, discriminated by whether identity existed at insert. GMAIL has the same lag but only 2.0%, which proves duplication needs **two** ingredients: a *supply* of repeat copies **and** a *blind window*. Gmail has the window, not the supply. INDOX controls the window; the client controls the supply.

### The BS matcher works — it is starved, not broken

It attached to an existing row **3,289 times**. Of its 1,438 failures:

| Cause | Count | Share |
|---|---:|---:|
| Twin did not exist yet | 877 | 61.0% |
| Twin existed but was **not yet extracted** | 413 | 28.7% |
| **Genuine miss** | **147** | **10.2%** |

**89.7% is pure timing**, and the latch (`BS_LINK_DOCUMENTS_COMPLETED`, set on 523 of 528 parents and never cleared) guarantees the retry never happens. The 147 are under separate investigation.

---

## 3. Why detection misses almost everything

| SOURCE_TYPE | Rows | Ever adjudicated | Ever a merge winner |
|---|---:|---:|---:|
| GOOGLE_DRIVE_FOLDER | 16,668 | 1,733 (10.4%) | 279 |
| MAIL_ATTACHMENT | 5,170 | 369 (7.1%) | 38 |
| GMAIL | 2,792 | 268 (9.6%) | 16 |
| **BALANCE_SHEET** | **6,735** | **71 (1.05%)** | **0** |

The mechanism, from `Determine Action`:

```js
const hash = (doc.HASH && isBlank(doc.LINKED_BS)) ? processedDocs.byHash.get(doc.HASH) : undefined;
const comp = (doc.COMPANY_ID && doc.SHORT_DOC_ID && !isPlaceholderDocId(doc.SHORT_DOC_ID))
  ? processedDocs.byCompanyShortDoc.get(compositeKey(...)) : undefined;
```

`processedDocs` is per-batch. BS children have **no HASH** (56 of 6,864), so the hash lane never fires for them; and their Drive twins were created days earlier in a different batch, so the company lane never fires either. **3,146 of 4,249 groups (74%) have never been looked at.**

---

## 4. The merge — what it does, and what was wrong with it

**Three phases.** Detect (`Determine Action`) → adjudicate (`Adjudicate Merge`) → write (`indoxApi01 → PG Merge Write`). Winner = most `*_COMPLETED` flags → `STATUS='COMPLETED'` → earliest `created_at` → lowest `ID`. Absorption is **fill-only**: the winner's non-blank value always survives.

### The defect that made 13.6% of merges wrong — NOW FIXED

```js
const sameHash = realHashes.size <= 1;
if (sameHash || twoAgree) { MERGE }   // sameHash won ALONE, before any date/amount check
```

BS placeholders have no hash, so **every BS-vs-document group satisfied `sameHash` by construction**. And `fieldsAgree` could not catch it — it compared **raw** `DOC_DATE` strings, treated blank as agreement, and never read `BS_LINE_AMOUNT`; for a BS child both fields are empty, so it returned `true` unconditionally.

**Real damage:** company `511495996`, four *different* invoices (`99400626/27/29`, `99403246`) each merged into a winner — and **all four winners now carry the identical amount 15,463.00**, one sales-order total. The correct per-invoice amounts (1454.94, 130, 0, 445.75) survive only on the losers.

**Fixed 2026-08-13:** a conflict veto now overrides both paths, comparing normalised dates (parsed calendar days, since the same day is stored `07/07/2025` by Drive and `2025-07-07T…` by Gmail) and normalised amounts (`abs(round(x,2))`, since 39 pairs are sign-flipped). 7/7 tests pass, including the four cases that must **not** veto. A full sweep on the old code would have auto-merged **253 conflict groups**.

### Still true of the writer

- **Not transactional** — N independent updates, no `BEGIN`/`COMMIT`
- **Not reversible** — the loser's pre-merge `STATUS` was overwritten and never stored; 202 of 392 are unrecoverable
- Columns `STATUS_BEFORE_MERGE`, `MERGED_AT`, `MERGE_BATCH_ID` and a `merge_audit` table now exist, but **the workflow still calls the old writer**

### ATTACH — the third action, and why B2 gets it

`SOURCE_LIST` does not make B2 safe to merge (its risk is *false identity*, not lost provenance). But combined with the proven reversibility of `DOUBLE` it enables:

> **ATTACH** = record the relationship in `SOURCE_LIST` on both rows, mark the secondary `DOUBLE`, **suppress its ERP push**, **absorb nothing**.

Fully reversible, no field contamination, and it delivers the actual prize — one document reaching Priority instead of two — across **1,272 groups / 1,858 excess rows** that would otherwise sit in a human queue.

---

## 5. Prevention, ranked by measured impact

| # | Fix | Duplicates it would have prevented |
|---|---|---:|
| **0** | **`SOURCE_LIST` first** — prerequisite for #1 | enables everything below |
| **1** | **Post-extraction dedup hook** — re-run the existing probe once identity is known | **2,911 of 5,535 (53%)** |
| **2** | **Continuous BS↔document linking** instead of one-shot-and-latched | ~1,290 of 1,438 |
| **3** | **Fix the ERP re-sync channel** — 2,992 rows pushed >1× | 4,285 excess pushes |
| **4** | Gate the sweep by tier | the 253 bad merges |
| **5** | Normalise the key (punctuation, leading zeros) | 59 groups |
| **6** | Reject purely-alphabetic doc ids (`SHERIZLY` = 24 rows in one bogus group) | 48 rows |

### ⚠ Ordering is not negotiable

`Resolve IDs.logicalMatch` folds an incoming row onto an existing one and writes **every non-empty incoming field** — so the incoming `LINK`/`SOURCE_ID` **overwrite** the matched row's. Fix #1 works by making that fold fire ~2,911 more times. **Shipping the hook before `SOURCE_LIST` turns the best prevention into the largest provenance-destruction event in the system's history.**

### What a DB constraint can and cannot do

A partial unique index on `(COMPANY_ID, doc id)` would have rejected **5,535** rows — but **1,523 (28%)** are in conflict groups, i.e. **genuinely different documents that legitimately share a document number**. More than one in four rejections would have destroyed a real document at the door, with no human and no record.

> **Uniqueness belongs where identity is certain (the file hash). Where identity is inferred, use detection and review — never rejection.**

Keep `uq_incdoc_hash`. Add a **non-unique** index on the business key to make the probe fast. Use a deferred trigger that **flags**, never rejects.

---

## 6. The ERP problem is bigger than the database problem

| Measure | Count |
|---|---:|
| Rows ever pushed to Priority | 5,277 of 32,691 (**16.2%**) |
| Documents dated June 2026 onward, pushed | **469 of 5,357 (8.8%)** |
| Excess pushes from duplicate rows | 3,744 |
| Excess pushes from re-syncing the **same** row (2,992 rows, max 6×) | 4,285 |
| Demoted rows carrying an `API_TOOLS_ID` | 1,666 |

**~8,000 excess document pushes, and no INDOX merge retracts any of them.** Merging *before* the bulk push is therefore mandatory — otherwise 5,535 duplicate rows land in Priority permanently.

---

## 7. Go / No-Go

**Ready:** backup table (32,691 = live, verified) · `SOURCE_LIST` + GIN index, 1,025 winners / 2,758 entries backfilled · `merge_audit` with a 3,520-row dry run · 4,173 groups tiered with 0 unclassified · conflict veto live · transactional `indox_execute_merge_group()` installed and tested.

**Not ready:**
1. **The adjudicator still calls the old per-batch path.** The SQL detection exists; nothing invokes it. ← *the remaining wiring*
2. **The old writer is still what n8n uses** — non-transactional, non-reversible.
3. **The date corruption is unresolved.** 825 rows carry years wrong by 2–10, 579 of them COMPLETED. Merging on corrupt dates mis-tiers groups.
4. **Link recovery is mid-flight.** 5,779 rows still latched; each recovery either proves a duplicate (shared hash) or proves distinctness. Merging now discards evidence arriving within hours — and once merged, the loser stops searching, so that proof is never generated.

**Recommended order:** finish link recovery → fix dates → wire SQL detection → dry-run → Tier A → Tier B1 → Tier B2 as ATTACH → ERP reconciliation → release the sweep behind the tier gate.

---

## 8. What is not established

- **Whether `PRIORITY_SYNC_COUNT > 1` means "pushed N times" or "N attempts, possibly idempotent."** The 4,285 figure is an **upper bound** and needs confirming against Priority. Largest open question here.
- **The 147 genuine BS-matcher misses** — under investigation.
- **How many inserts `uq_incdoc_hash` has rejected**, and how many ingest-time folds already discarded a filing location. Neither leaves a trace; historical loss is real but unmeasurable. Both are trivially instrumentable going forward.
- **Insert-time field values** — no history table, so "born with identity" is inferred from `BASE_EXTRACTION_COMPLETED IS NULL AND COMPANY_DOC_ID IS NOT NULL` plus the lag distribution. Strong, but circumstantial.
