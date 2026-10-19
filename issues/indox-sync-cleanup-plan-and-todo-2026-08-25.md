# INDOX sync — the full TODO and the full CLEANUP plan (2026-08-25)

Reconciled against every objective given today. Status is measured, not asserted.

---

# PART A — OBJECTIVES AND WHERE THEY STAND

| # | Objective (as given) | Status | Evidence / what remains |
|---|---|---|---|
| 1 | Sync UI is the operator's surface — see ground truth, restart fails, see what each scan has left, make everything green | **DONE (UI works)** | Board loads 82ms warm (was 5-10s/poll, columns dead); truthful empty/error states; real last-run per source; stale-run detection; restart + re-queue proven at the source. Green still needs PART B/C items. |
| 2 | Everything aligned + minimal + `monthsOld` everywhere | **DONE for the live lane** | Window enforced at the 3 enumeration points (gmail query, drive `createdAfter`, retry due-union `oldest_ms`) and in the whole read model. Legacy v1 lane still non-compliant → C-1. |
| 3 | Ground truth: what is missing, where it is, does sync see it | **DONE** | 2,746 missing located file-by-file; 1,876 in-window actionable; 851 out-of-window by your own rule; 373 alive outside any sync folder. |
| 4 | Every change in 12h | **DONE** | Reported; 21 items. |
| 5 | Preserve company identification from the mail source; can ALL selection move to two places | **DESIGN DONE + IMPLEMENTED** | Sync↔select contract shipped (see 7). Old BS logic mapped rule-by-rule and preserved. |
| 6 | % of mail documents without a company | **DONE** | 19.5% (1,463/7,493). gmail-link 46.3% · gmail-doc 15.7% · gmail-bs 7.4%. |
| 7 | Sync produces SENDER / SYNC_REGISTRY_ID / ATTACHMENT_TEXT; select derives COMPANY_BY_SENDER / TYPE_BY_SOURCE and uses them as options | **DONE, LIVE** | All 5 live writers carry the full contract (audited). Selector derives + stores both and uses them as legs. Proven in production audit lines: `{"COMPANY_ID":"BY_TEXT אורבונד","TYPE":"BY_SOURCE BALANCE_SHEET"}`. |
| 8 | Full sender LIST, not one address | **DONE, PROVEN** | Chain order beats "unambiguous": a chain with איטונג@9 + טמבור@29 resolves to איטונג; the old rule returned nothing. All 3 mail lanes emit the ordered chain with all 5 historical rules. |
| 9 | RECEIVED_DATE and SEND_DATE correct in every sync | **DONE** | Audit: 5/5 live writers emit both. Verified on live rows (mail = Date header; drive = file createdTime). |
| 10 | E2E proof: 5 mail scenarios + drive, 10 distinct documents, all reach COMPLETED | **PARTIAL — see PART B** | 11 documents generated; 5 real mails sent from your account; label engine routed all by content; 4 documents carry correct company+type; **0 at COMPLETED yet**. |
| 11 | Clean the huge duplication + general sync cleanup plan | **PLAN BELOW (PART C)** | Nothing deleted yet — deletion needs your go-ahead. |

---

# PART B0 — THE E2E RESULT (measured, end of run)

**Two documents completed the ENTIRE path** — mail sent from the owner's account → label engine
routed by content → sync picked it up under the new source contract → downloader → base
extraction → selection → **COMPLETED with company, type and date**:

| doc | scenario | STATUS | TYPE | COMPANY | selection debug |
|---|---|---|---|---|---|
| doc_mt8uac0wbrt0ca | E2E-1 invoice | **COMPLETED** | INVOICE | 511744450 אבני סלע | COMPANY=AGREE · TYPE=AI_ONLY · DATE=AGREE |
| doc_mt8ua80tkjdjvq | E2E-2 invoice+shipment | **COMPLETED** | SHIPMENT | 511212615 איטונג | COMPANY=AGREE · TYPE=AI_ONLY · DATE=AGREE |

Two landed **OLD**, and the cause is a real defect class, not a test artifact:

| doc | source dates | what terminalised it |
|---|---|---|
| doc_mt8u8wm386tnr5 (E2E-3 aging) | RECEIVED 25/08/2026 · SEND 25/08/2026 | `AI_DOC_DATE = 31/07/2024` (AI misread 2026 as 2024) |
| doc_mt8trot3mn4ntg (drive, real client doc) | RECEIVED 17/03/2026 | `AI_DOC_DATE = 26/02/2023` |

### DEFECT: a RAW engine leg can terminalise a current document
The old-doc gate applies `any_date_older_than_6_months` across
`[RECEIVED_DATE, DOC_DATE, AI_DOC_DATE, BS_LINE_DATE]` — so **one hallucinated year in a raw AI
leg sends a fresh document to OLD, which is terminal**. Measured live: **96 documents are OLD
where the ONLY old-date hit is `AI_DOC_DATE` while `RECEIVED_DATE` is explicitly in-window**
(5,698 OLD in total).

**Recommended fix, and it follows the same rule as everything else today:** terminal verdicts must
read the SELECTED value (`DOC_DATE`), never a raw engine leg — raw legs are evidence, not
verdicts. And now that every sync writes `SEND_DATE`/`RECEIVED_DATE` (source truth), the gate has
a trustworthy anchor: when the SOURCE says the item is in-window, an extracted date may
FLAG the row but must not terminalise it.

### Two more findings from the same run
- **A document arriving already TYPED never gets an `API_TOOLS_ID`.** Base extraction's gate
  accepts only TYPE-less rows, so a downloader-typed document skips extraction, then parks at
  `API_TOOLS_FAILED` because per-type cannot run without the id. The lane's own note names the
  workaround ("blank TYPE + ACTION_RESTART") — applied here, and all four immediately acquired an
  id and moved. This is a structural gap between the downloaders and the two-point selection
  model, and it deserves a real fix rather than an operator recipe.
- **Crashed actions leave their locks behind.** The transient graph break left two
  `doc_action` locks per document (TTL 4,000–5,400s), which blocked every retry for over an hour.
  549 such locks exist estate-wide.

# PART B — WHAT IS LEFT TO CLOSE THE E2E PROOF

| B# | Item | Detail |
|---|---|---|
| B-1 | 4 in-flight documents reach COMPLETED | אבני סלע / איטונג / אורבונד / ברייטקום all carry company+type. They are cycling ACTION_RESTART because a **transient broken edge** in `indoxV2ActionsGDoc01` ("Destination node not found", 15:53) killed the action mid-flight — the other session was editing those lanes. Graph is whole again (scanned all 9 lanes: 0 dangling); they should drain. |
| B-2 | E2E-5 (aging + invoice, 2 files) | The BS lane labelled it **FAILED_BS** — its 4-strategy attachment picker cannot choose between two files. This is the real, reproducible behaviour of that scenario, not a test artifact. Needs a decision: pick by type-hint, or split into 2 documents. |
| B-3 | E2E-4b (link to invoice) | The `DOC_LINK_TO_SYNC` rule is sender-gated to 18 provider addresses **by design**, so a self-sent link mail is never labelled. I applied the label manually to exercise the lane; it proves the downstream lane only. |
| B-4 | 4 Drive documents (one per active drive source) | **Blocked on you**: a service account cannot create files in Drive (no storage; the adapter refuses and Google would 403). Files staged at `scratchpad/e2e/` — drop them into the 4 to_sync folders. Both drive lanes are already proven with real owner-owned files. |
| B-5 | E2E-1/E2E-2 attachments typed UNKNOWN by the downloader | They still resolved via TYPE_BY_SOURCE. Worth checking why the classifier failed on a clean synthetic invoice. |

---

# PART C — THE CLEANUP PLAN

Ordered by (risk removed) ÷ (risk taken). Nothing here is done yet.

## C-1. Delete the dead v1 scan lane (highest value, lowest risk)
- `SyncScanner00001` (inactive, `lifecycle:legacy`) and `SyncScanUnit0001` (inactive) — duplicate `syncV3Main0001`→`syncV3Unit0001` down to the identical `Schedule 15m` node name, with **hardcoded/absent monthsOld** and **zero retained executions**.
- `SyncSource000001` is ACTIVE but reachable only through the `indox-manage` STATUS verb, which the product BFF never calls; it carries a hardcoded `newer_than:6m` and an unbounded drive listing.
- **Blocker:** referenced from `api/__init__.py`, `hooks/sync-engine`, `hooks/demo.py`. Remove those references first, then delete all three.
- **Removes:** 3 workflows, 2 of the 3 competing gmail-query builders, the last non-compliant monthsOld sites.

## C-2. Delete the dead half of `syncV3Deliver0001` (the canvas you flagged)
- 47 nodes; **~19 are a second, unused delivery implementation**: `Drive Row`, `Get Message`→`Split Attachments`→`Has Attachments?`→`Loop Attach`→`Upload Doc`→`Gmail Row`, `Get Link Msg`→`Extract Link`→`Download Link`→`Upload Link Doc`→`linked_`→`Link Row`, the three `Call DELIVER*` and their `Record Req*` twins.
- **Proof they are dead:** every registry pipe declares `processor_wf`, so `Route Mode` always leaves on `proc`; 6/6 sampled Deliver executions took `proc`; the inline nodes fired **zero** times.
- Also collapses: 4 near-identical `Record Req*` builders → 1; 3 label-op builders → 1.
- **Guard before deleting:** assert no registry entry can produce `mode≠proc` (i.e. every entry has `processor_wf`), and keep one pass of executions after the change.
- **Removes:** ~40% of the nodes and most crossing edges; the inline `Extract Link` (a naive regex duplicate of the link downloader's provider engine); the stale `SOURCE_ID = sender email` comment that is simply false.

## C-3. Registry hygiene (config, not code)
- `mail-private` is a **paused exact duplicate** of `gmail-doc` (same labels, same connection). Delete it, or give it a distinct purpose. It currently double-counts 1,040 mails on the board and owns 700 of the phantom ledger rows.
- `gmail-link.labels.failed = FAILED_BS` — **shared with gmail-bs**, so both lanes count the same 449 failures. Give the link lane its own failed label.
- `drive-bs` and `drive-whatsapp-bot` map **all four states to one folder**, so they can never show synced/failed and every dest file re-appears as to_sync. Give them real to_sync/synced/failed folders.
- Unify the two intermediary sender lists that have already drifted: `tag_rules` `DOC_LINK_TO_SYNC` (18 addresses) vs the link downloader's `KNOWN_STANDARD` (12) + provider `if`s.

## C-4. Selector/extractor de-duplication (coordinate with the data-quality session)
- Two copies of the `NAME Company Match` SQL (`SelectBase01` + `BaseDocEx01`) — keep one.
- `SELECTED_*` columns are legacy and being retired by that session; the three downloaders still declare them in their upsert schemas.
- `Action: Figure COMPANY_ID` in the link downloader is a **noOp** used only as a join point — rename or remove; the name lies.
- Stale `cachedResult*` ids pointing at `indoxDocBatchUpsert01`, a workflow that does not exist.

## C-5. Data cleanup (needs your approval, backups first)
- **95 `needs_review` ledger rows** — relics of a quarantine branch the engine itself retired on 2026-08-10; 19 of them are the census blockers. Delete the 19 now (scoped command already staged); rule on the other 76 (gmail-doc 4, mail-private 72).
- **1,932 phantom `delivered` rows with no doc** (≈220 upper-bound real gmail misses, 58 in-window). Surface in בדיקת התאמה + offer RELEASE; hash-verify before releasing.
- **1,334 `MISSING_COMPANY_ID` mail documents** — terminal in both feeders, so they will NOT re-process by themselves. Restart them **after** C-6, not before, or they re-park on the same gap.
- The two empty Gmail label shells my earlier bug created (`BS_TO_SYNC`, `DOC_LINK_TO_SYNC` as literal labels) can be deleted in Gmail.

## C-6. Fill the sender→company map (the ceiling on 100%)
- `companies."מייל 1"/"מייל 2"` is populated for **136 of 1,183** companies (11.5%). `trusted_suppliers` is empty.
- The `tag_rules` `SUPPLIER_MAIL` rule already holds a curated **~140-domain supplier list** that INDOX never reads — that is the seed data for this fill.
- Until this is filled, `COMPANY_BY_SENDER` can only answer for ~1 company in 9.

## C-7. Engine hygiene
- Reconcile lock TTL **5400s → ~1200s**: a canceled pass currently costs up to 90 minutes of dead passes (measured today: 09:15 pass canceled → every pass skipped until 10:54).
- `syncV3Main0001` stamps Run Start but not always Run End (units_total=0 on the `*` row) — the run journal under-reports.
- mailapi IMAP pool/semaphore: `/search` is taking **~44s** per call under load, which is what makes the label engine's 10-per-15-minutes the real intake ceiling.
- Active test/reset workflows with live webhooks in production: `syncV3FullTest01`, `drainPoolTest01`, `drainPoolTarget01`, `IndoxResetFull01`, `IndoxResetGml001`, `tVzFMkz18pCsXRyw`.

## C-8. Coverage question (not cleanup — a decision)
- Label `נמצא-מסמך-לא-ידוע-אוטומציה` holds **6,769 mails** that no registry scans. If those should become documents, that is the one genuinely missing sync registry. Every other intake surface is covered.

---

# PART D — DEFECTS FOUND AND FIXED TODAY (for the record)

1. `SyncProcGDoc0001` stamped the **terminal** `COMPLETED` on its own `Is OK` flag while its `REQUIRED_ACTION` said "Missing company name", and renames files to `unknown-*` — so `select_base` could never run. Proof: a document COMPLETED with no company whose `ATTACHMENT_TEXT` read "ברייטקום ב-35196.jpg" = company 515273175; after the fix + restart it resolved to exactly that. Now COMPLETED requires company AND type.
2. `indoxGmailBSDownloader01` **never wrote `LINK_CONNECTION`** (0 occurrences) — third writer in the family, missed by two earlier sweeps; every balance sheet through that lane failed extraction.
3. `SYNC_REGISTRY_ID` derived from the wrong ctx field (`drive` instead of the registry name) — caught by the first live run.
4. `SENDER` silently NULL in the doc/link lanes: n8n throws on `$('Node')` when the node is unexecuted, **even inside try/catch** — guarded with `isExecuted`.
5. My own regression: a regex `$` anchor inside the DIFF SQL — the n8n Postgres node reads a bare `$` as a dollar-quote opener; 18 ledger + 6 unit errors for ~30 minutes until rewritten anchor-free.
