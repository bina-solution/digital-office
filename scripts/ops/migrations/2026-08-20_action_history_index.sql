-- [action history 2026-08-20, owner order] Index for the driver's ACTION_HISTORY join.
--
-- indoxV2Driver01 :: 'Get Action History' asks, once per 2,000-document batch, for the newest
-- 10 dispatches of each document:
--
--   SELECT ... FROM public.indox_action_execution_log x
--   WHERE x."ID" = $doc ORDER BY x."STARTED_AT" DESC LIMIT 10
--
-- The primary key ("ID","ACTION","EXECUTION_ID") already locates the rows -- measured at 33 ms
-- for 2,000 documents without this index -- but its ordering is by ACTION, not by time, so every
-- document pays a sort. Rows per document: avg 8.4, p95 17, max 344; the sort is small but it is
-- paid 2,000 times per batch and it is pure waste.
--
-- This is the ONLY access pattern this index serves. idx_indox_ael_started ("STARTED_AT" DESC)
-- stays: it serves the dashboard's window scans, which have no "ID" predicate and cannot use a
-- leading-"ID" index.
--
-- CONCURRENTLY: the table is written on every action dispatch. A plain CREATE INDEX takes an
-- ACCESS EXCLUSIVE lock and would stall every in-flight lane for the duration.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_indox_ael_id_started
  ON public.indox_action_execution_log ("ID", "STARTED_AT" DESC);
