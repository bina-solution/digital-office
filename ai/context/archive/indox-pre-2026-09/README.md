# INDOX — archived plans, reports and reviews (before 2026-09-02)

Everything in this folder is **history**: the plans, reviews, RCAs, cut-over work lists and design
drafts that led to the INDOX final consolidation of 2026-09-02. They describe designs that were
superseded — the sync v3 unit/deliver family, the Gmail downloaders, the run-progress table, the
label-as-state model, the ACTION_LOG era, the GDoc lane — and they name workflows that no longer
exist. Nothing here is an instruction.

**The current design is one document: [`apps/indox/indox solution.md`](../../../apps/indox/indox%20solution.md)**
(sync + the state machine, as built). The living work list is `apps/indox/NEXT.md`. The
onboarding runbook stays live at `ai/context/incoming-documents-onboarding.md`; the expected
behaviour spec at `ai/context/indox-expected-behaviour.md`; the per-type fixture architecture at
`ai/context/indox-per-type-fixture-architecture.md`.

Sync best-practice sources consulted for the 2026-09-02 verdict (Part A10 of the solution
document): Google Drive API `changes.list` / `files.list` guides and the search-terms reference;
Gmail API sync / push guides and the IMAP extensions page; RFC 3501 (UIDs, UIDVALIDITY) and RFC
2177 (IDLE); Gmail's IMAP connection and bandwidth limits; AWS SQS visibility timeout, dead-letter
queue and "Exponential Backoff and Jitter" (full vs equal jitter); Google Pub/Sub failure handling;
PostgreSQL `INSERT … ON CONFLICT` and `SELECT … FOR UPDATE SKIP LOCKED`; Airbyte / Databricks
incremental-sync lookback windows.
