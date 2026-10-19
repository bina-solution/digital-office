-- [line-hash dup guard 2026-08-26, owner order] A DOUBLE ACTION IS A REPEAT ON AN UNCHANGED LINE.
--
-- WHY. The guard used to read existence only: "this action appears in ACTION_HISTORY and no
-- ACTION_RESTART came after it" => fatal. That rule cannot tell a stuck loop from a legitimate
-- re-run, and both legitimate cases fire it:
--
--   1. A PLAIN FIELD CHANGE re-opens a selection. decide re-proposes select_base whenever
--      indox_base_selection_hash() drifts from the stored BASE_SELECTION_HASH. Measured
--      2026-08-26: an ad-hoc DOC_DATE normalisation (1 call, 2,503 rows, still visible in
--      pg_stat_statements) left 1,306 rows with a stale hash -- 1,241 differing in DOC_DATE
--      alone -- so decide asked for select_base every sweep and the guard refused every sweep.
--      256 of 256 driver failures in the 24 h to 19:02Z were this, 7,216 blocked lines over
--      1,180 documents, 97 % of them select_base. Permanent deadlock: decide says re-select,
--      the guard says only ACTION_RESTART may re-run it, and nothing issues the restart.
--   2. RUNNING AN ACTION BY HAND, or clearing its *_COMPLETED mark to re-open it, leaves the
--      earlier dispatch unpaired in the history, so the next legitimate pass is blocked.
--
-- THE NEW LAW. A second dispatch of the same action counts as a double ONLY IF THE LINE HAS NOT
-- CHANGED since the first one. So every dispatch row records the hash of the whole line as it was
-- at dispatch time, and the guard compares that against the line's hash now. Changed line =>
-- different inputs => a re-run is legitimate work, not a loop. Unchanged line => the action ran
-- and did not move the document => exactly the loop this guard exists to catch, and it still
-- fires, hard.
--
-- FAIL-OPEN BY CONSTRUCTION, the same rule indox_base_selection_hash already follows: a
-- difference counts only when BOTH hashes exist. Rows written before this migration carry
-- LINE_HASH NULL and can never block anything -- which is also what clears the 1,180 documents
-- stuck today, with no backfill and no mass ACTION_RESTART. They self-heal: the next dispatch
-- carries a hash.
--
-- NOT BACKFILLED, DELIBERATELY. The hash of a line as it stood at a past dispatch is not
-- recoverable; inventing one would be a fabricated licence to block.
--
-- KNOWN PROPERTY: jsonb canonicalises key order, so ADDING OR DROPPING A COLUMN on
-- incoming_documents changes every row's line hash. The guard then fails open for one dispatch
-- per document, and re-arms on the next. That is the safe direction and it is cheap.

-- ── 1. the hash ────────────────────────────────────────────────────────────────────────────
-- ONE DEFINITION, IN SQL, READ BY EVERYONE -- same law as indox_priority_signature and
-- indox_base_selection_hash. The router writes it, the driver reads it; a JS copy would drift,
-- and drift here means either a guard that never fires or one that fires on healthy documents.
--
-- THE WHOLE LINE. Every column: STATUS, every *_COMPLETED flag, SOURCE_LIST, the debug columns,
-- the timestamps. If any of it moved, the action is entitled to run again.
--
-- ONE EXCLUSION, AND IT IS LOAD-BEARING: updated_at. It is bumped by every write, semantic or
-- not, so if it were in the hash NO TWO DISPATCHES COULD EVER SHARE ONE and the guard would be a
-- permanent no-op -- it would never fire again, on anything. Nothing else is excluded.
-- (Checked before excluding, not assumed: ITERATION_COUNT does NOT track dispatches --
-- correlation with dispatch-row count is -0.07 and 24,236 of 24,959 rows sit at 0 -- and
-- RETRY_COUNT / NEXT_RETRY_AT are ordinary fields. All three stay in.)
--
-- STABLE, not IMMUTABLE: to_jsonb() renders a timestamptz through the TimeZone GUC. The router
-- and the driver both reach this database through the one 'INDOX Supabase Postgres' credential,
-- so they cannot disagree on it. If that ever stops being true, pin it with SET timezone TO 'UTC'
-- on this function -- correct, but it blocks inlining: measured here, 742 ms per 2,000 rows with
-- the SET clause against 216 ms without.
create or replace function public.indox_line_hash(d public.incoming_documents)
returns text
language sql
stable
as $$
  select md5((to_jsonb(d) - 'updated_at')::text)
$$;

-- ── 2. the column ──────────────────────────────────────────────────────────────────────────
-- The line hash AT DISPATCH TIME. Written by indoxV2ActionRouter01 :: 'Log Action Start', which
-- reads it off the live row in the same statement that opens the bracket. NULL means "this
-- dispatch predates the rule" (or the row vanished between decide and dispatch) and can never
-- block -- see FAIL-OPEN above.
alter table public.indox_action_execution_log
  add column if not exists "LINE_HASH" text;

-- No index. The guard never filters by LINE_HASH -- it reads the newest rows for one document
-- (already served by idx_indox_ael_id_started) and compares the hash in the driver.
