# Master plan — every objective from the owner's last 30 messages

**Date:** 2026-08-05 · **Scope:** get INDOX to a perfect, stable, best-practiced state AND prove it
live for hacohen, with every document from their mail and drive reaching `COMPLETED`.

This document is the single forward plan. It maps each of the owner's last 30 messages to a
numbered objective, states the objective's real status, names the work stream that closes it, and
gives the browser42 proof that will demonstrate it. Status marked `verifying` is being established
against the running system by the verification sweep, not asserted from reading code.

---

## Part 1 — The 30 messages, deduplicated into objectives

Twelve of the thirty messages were slash commands, model switches or task notifications. The
remaining eighteen carry twenty-four distinct objectives, several of which the owner raised more
than once — repetition is treated as escalation, not as new work.

| # | Objective | Raised in | Status |
|---|---|---|---|
| O1 | GitHub Actions all green | U04 (+2 earlier) | partial — 2 runs never re-triggered, 2 gate failures |
| O2 | Clean up duplicate n8n workflows | U05 | verifying — ghost `indoxSetupWF001` + dangling id known |
| O3 | Mail label engine working and applying tags | U20.1 | done — active, 20/20 recent executions success |
| O4 | Mail list shows processed / waiting indicator | U20.1 | **not done** |
| O5 | Everything properly tagged and caught by the registries | U20.2 | partial — depends on O7 |
| O6 | Nothing missed between tag and registry processing | U20.3 | partial — depends on O11 |
| O7 | The seven final sync registries | U24, U21.2 | partial — 3 mail exist, 4 drive are the gap |
| O8 | Mail registries deposit into local drive `automations/<sync-name>`, editable in config view | U21.1 | verifying |
| O9 | Everything reaches `COMPLETED` in the INDOX table | U20.4, U21 | **not done — 30.1% coverage** |
| O10 | Deep-scan all mail attachments in the 6-month window, one by one | U20.5 | done — 3,322 attachments / 1,734 messages / 991.6MB inventoried |
| O11 | Same for drive: get every folder documents must sync from | U20.6, U18, U17 | partial — 78,651 files / 443 folders mapped, registries pending |
| O12 | Move failing-sync files back to their to-sync folder and reprocess | U20.8 | **not done — 5,010 `(בוריס)` files** |
| O13 | Sync UI shows what is going on, the sources, and the work left | U22, U24 | partial — timeout fixed today, board still thin |
| O14 | Sync board enables full managing and re-run per sync | U24 | verifying |
| O15 | "Resolved" table gains a DONE column | U26 | **not done** |
| O16 | Explain INDOX 06/26 — the owner expects ≥3,000 docs/month | U26 | done — 3,110 in drive vs 526 in INDOX, confirmed the shortfall |
| O17 | Clear last month's labels to watch the engine regenerate them | U26 | **not done** |
| O18 | INDOX table: pagination past page 1 | U27 | verifying — code shipped, needs live proof |
| O19 | INDOX table: inline STATUS switching (e.g. `ACTION_RESTART`) | U27 | verifying |
| O20 | INDOX table: month navigation | U27 | verifying |
| O21 | INDOX table: mature production-grade filter and sort | U27 | partial — server-side filters wired today |
| O22 | Card view in bina-table using THUMBNAIL, generated as a state-machine step | U27 | verifying |
| O23 | Document page production grade, all features working | U27, latest | **in progress — draw + original both broken** |
| O24 | Deep review of the sync architecture + high-load compatibility | latest ×2 | **in progress** |

Cross-cutting, stated on almost every message: **full-coverage in-depth interactive browser42 QA**
as the proof layer (U27, U28, U29, latest). That is Part 3.

---

## Part 2 — Six parallel work streams

The streams are fenced so they never edit the same file. Everything inside a stream is sequential;
the streams themselves run concurrently.

### Stream A — Document page (O23)
Owns `DocumentDetailPage.tsx`, `DocumentViewer.tsx`.
Diagnose the two live breakages on `doc_msdd8aijxokav4` before touching anything: the `חילוץ מסומן`
tab renders a broken-image glyph, and the `מסמך מקורי` tab renders the literal string
`{"error":"not found"}` inside the viewer frame. Establish whether the document genuinely has no
apitools upload (in which case "not found" is *true* and the bug is that the UI leaks a raw API
error body to the user) or whether the URL is wrong. Then: honest Hebrew empty states, a THUMBNAIL
fallback, a placeholder for broken images, and a genuine visual pass so the preview is the hero of
the page rather than an afterthought.

### Stream B — Objective verification (all)
Read-only. Produces `OBJECTIVE-VERIFICATION-2026-08-05.md` with a DONE / PARTIAL / NOT DONE verdict
per objective, each backed by real command output. Nothing may be marked DONE from reading source —
the INDOX table features in particular are checked against the **bundle shipped inside the
container**, because the webapp is baked into the image and a source edit that was never rebuilt
looks identical to a working feature when you only read the repo.

### Stream C — Sync architecture review (O24)
Read-only. Produces `SYNC-ARCHITECTURE-REVIEW-2026-08-05.md`: one document's full journey with
`file:line` at every hop and a mermaid diagram; every remaining instance of this codebase's dominant
defect (a bounded query treated as the whole truth — twelve found so far, one of which hid 43,326 of
78,651 client files); and ranked high-load recommendations covering keyset pagination, incremental
sync via Gmail `historyId` and the Drive changes API instead of full re-scans, exactly-once claim
semantics, backpressure, cache invalidation, precomputed counts, and the observability that would
have caught the hidden files on day one.

### Stream D — Drive registries 4–7 (O7, O11)
Owns `settings.sync_registry` (backed up before every write). Discovers the real folder ids from the
live 443-folder tree rather than guessing at Hebrew names, creates the `מסמכים כללים` pair the owner
authorised, and wires `יצוא צט` as registry #6 — the owner explicitly corrected the earlier
whatsapp assumption ("7 yes, 6 no there is יצוא צט folder"). Each of the seven must resolve to a
real, non-zero source or an explained zero.

### Stream E — HIGH-severity backend caps (O6, O9, O13)
Owns `api/__init__.py`, `apps/drive/adapters/google.py`, the poller workflows. Six defects, each
proven broken with a live number *before* the fix and proven fixed after: the poller's 1000-cap that
loses work permanently rather than merely slowly; the 300-message reconcile window judging an
8,624-message mailbox; a "row count" that silently maxes out and that the whole UI trusts; drive
`folders()` capped at 600 with the client already at 443; a 20-minute settings cache that makes
edits look like failures; and a delete-guard whose comparison never matches, which must be made to
fail closed because it is the thing standing between an automation and the client's real mail.

### Stream F — Backfill and cutover (O9, O12, O5, O6)
**Deliberately blocked on D and E.** Backfilling 13,759 drive documents plus 1,310 mail documents
through a poller that drops everything past 1000 would silently re-lose the same rows and produce a
confident, wrong "done". Runs only once the caps are fixed and the registries resolve.

Sequenced after the streams: push the SOURCE_ID writer fixes live (they exist in the blueprint files
but the n8n database may still hold the old copies — a two-sources-of-truth split), clear the ghost
workflows, add the mail list indicator, add the DONE column, and get CI green.

---

## Part 3 — The browser42 proof plan

Every objective the owner can see must be proven **through `console.localhost`**, never against an
app host directly, and every step asserts the *effect* rather than that a page loaded. A screenshot
of a page that rendered is not proof that the feature works.

### Suite 1 — INDOX table (O18–O22)
1. Load the table. Assert row count and that the total is the real total, not the page size.
2. Click to page 2. Assert the first row's ID **differs** from page 1's first row — this is the
   exact bug the owner reported ("i can only see the first 100"), so paging must be proven by
   changed content, not by the control being clickable.
3. Open the STATUS cell on a row, switch it to `ACTION_RESTART`, reload the page, assert it stuck.
4. Navigate to a different month. Assert the row set changed and matches a direct SQL count for that
   month. Do this for a month with known volume (06/26 → 526 rows today, more after backfill).
5. Apply a text filter, an enum filter and a range filter. Assert each narrows the set and that the
   narrowing happened **server-side** (the returned total drops, not just the visible rows).
6. Sort by two different columns, ascending and descending, and assert the first row changes.
7. Switch to card view. Assert cards render and that a card whose row has a THUMBNAIL shows an
   actual image, not a placeholder — then assert a row *without* a THUMBNAIL degrades gracefully.

### Suite 2 — Document page (O23)
8. Open a document that has an original and a draw. Assert both tabs render real content.
9. Open `doc_msdd8aijxokav4` — the owner's own failing example. Assert neither tab shows a raw JSON
   error body or a broken-image glyph; assert an honest Hebrew empty state instead.
10. Exercise every action on the page (retry, status change, open original) and assert each has its
    effect in the database.

### Suite 3 — Sync board (O7, O13, O14, O15)
11. Load the sync page. Assert it renders **within the console's 40s proxy timeout** — this is the
    error the owner saw twice.
12. Assert all seven registries appear, each with a resolvable source.
13. Assert counts that were not measured render as "not measured", never as `0/0/0/0` — a zero the
    user reads as truth is worse than an admitted gap.
14. Assert the resolved table has the DONE column.
15. Run, pause, edit and delete a registry through the UI; assert each change persists.
16. Re-run one registry and assert it does real work (ledger rows move).

### Suite 4 — Mail (O3, O4)
17. Open the mail list. Assert the processed / waiting indicator appears and is correct against the
    live labels for at least one message of each state.
18. Assert the label engine's production label vocabulary is what the list reflects.

### Suite 5 — End-to-end live proof (O9)
19. Drop a new document into each of the seven sources for real.
20. Watch each one travel to `COMPLETED` in the INDOX table.
21. Assert the source-side artefact moved to its done location (label applied, or file moved to the
    success folder).

This last suite is the one that actually answers the owner's standing question. Everything else
proves a feature exists; suite 5 proves the machine works.

---

## Part 4 — Definition of done

The work is finished when, and only when:

- All seven registries resolve to real sources and are manageable from the board.
- INDOX coverage of the 6-month window is explained in full: every document either present, or
  accounted for by a stated rule (out of scope, duplicate, non-document).
- A document dropped into any of the seven sources reaches `COMPLETED` without intervention.
- Every browser42 suite above passes, asserting effects.
- `scripts/ci/gates.sh` is clean and GitHub Actions is green.
- No endpoint the UI depends on exceeds the 40s console proxy timeout.
