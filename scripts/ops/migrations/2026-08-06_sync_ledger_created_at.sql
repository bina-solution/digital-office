-- 2026-08-06_sync_ledger_created_at.sql
--
-- sync_ledger has no created_at or status-history, so queue depth over time cannot be
-- reconstructed from it — timeline-gaps.py's own "Queue depth vs activity" section already says so
-- explicitly ("point-in-time + cumulative-delivery view, not a backlog time series"). This is
-- additive and safe: a new nullable-then-defaulted column, no existing query, INSERT, or n8n node
-- touches it, so nothing can break.
--
-- WHY THIS IS SAFE TO ADD WITHOUT TOUCHING ANY n8n WORKFLOW NODE:
-- syncLedgerApi01's Build Claim / Build Record / Quarantine Code nodes all build explicit-column
-- INSERT statements (e.g. "insert into public.sync_ledger (source,platform_id,status,claimed_at,
-- delivered_at) values (...)") — they never do `insert into sync_ledger values (...)` or select *.
-- A column with a DEFAULT is filled in automatically by Postgres for any INSERT that doesn't name
-- it, so every existing CLAIM/RECORD/Quarantine call keeps working byte-for-byte unmodified and
-- created_at just starts getting populated for free.
--
-- THE executeWorkflowTrigger SCHEMA-DECLARATION TRAP (flagging, not fixing — see report):
-- this trap is about workflow-to-workflow calls, not this table. syncLedgerApi01's OWN trigger
-- ("When Called") uses inputSource:"passthrough", which does NOT filter fields — safe by
-- construction. But most CALLERS of Sync Ledger API (e.g. syncV3Main0001's "Try Lock"/"Unlock" calls
-- into processLock01) use Execute Workflow nodes in "defineBelow" mode with an explicit `schema`
-- array of declared field names — n8n silently DROPS any field not in that array. So if a future
-- caller wants to read/pass `created_at` through one of THOSE declared-schema calls (not this
-- table), the schema array must be updated to include it explicitly, or the field vanishes with no
-- error, no warning, nothing in the logs — exactly the "installed but silently incomplete" failure
-- class this whole codebase has already been bitten by once today (see Reaper Build Release's fixed
-- $input.first() bug in this same file, and the 42-workflow dangling errorWorkflow drift in
-- ai/context/archive/indox-pre-2026-09/ERROR-RCA-2026-08-05.md). This migration itself needs no such change (raw SQL, not a
-- declared-schema hop) — this note is for whoever builds the next thing on top of created_at.
--
-- WHAT THIS ENABLES:
--   - Reconstructing queue depth over time (arrivals vs delivered_at, per hour/day) instead of only
--     the current point-in-time status breakdown.
--   - Measuring time-to-delivery (delivered_at - created_at) per source/pipe as a real SLA metric.
--   - A genuine backlog time series for scripts/ops/timeline-gaps.py's "Queue depth vs activity"
--     section (already wired below, in a way that degrades gracefully if this migration has not
--     been applied yet on a given environment — same pattern as its existing delivered_at/claimed_at
--     checks).
--
-- Apply:
--   docker exec <supabase-db container> psql -U postgres -d postgres \
--     -f /path/to/this/file (bind-mounted) OR pipe via: cat this.sql | docker exec -i <container> psql -U postgres -d postgres

ALTER TABLE public.sync_ledger
  ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_sync_ledger_created_at ON public.sync_ledger (created_at);

-- Existing rows: Postgres evaluates now() once at ALTER time and backfills every existing row with
-- that single value (a metadata-only op on PG11+, since the default is applied lazily) — meaning
-- pre-migration rows will all show the SAME created_at (the migration's own run time), not their
-- true original arrival time. That is expected and documented, not a bug: the column only starts
-- being meaningful for rows created AFTER this migration runs. Called out explicitly so nobody
-- mistakes the backfilled timestamp for real history.
