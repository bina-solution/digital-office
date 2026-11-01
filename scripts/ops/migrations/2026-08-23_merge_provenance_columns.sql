-- 2026-08-23  MERGE PROVENANCE COLUMNS
--
-- WHY THIS EXISTS
-- These four columns are what makes a merge reversible, and they existed on exactly one database:
-- this one, applied by hand. They were in NO migration and NOT in apps/indox/blueprint/fixtures/
-- schema.sql, so neither a fresh deployment nor any other existing deployment had a route to them.
--
-- Found 2026-08-23 by scripts/ops/lint_schema_columns_vs_live.py, which builds a database from the
-- fixture schema and diffs its columns against the live one:
--
--     fresh has merge provenance? 0 of 4
--     live  has merge provenance? 4 of 4
--
-- The fixture schema has since been corrected, which fixes FRESH deployments. This migration is
-- for the ones that already exist -- schema.sql never runs against a database that is already
-- there, so without this they stay without merge provenance indefinitely.
--
-- WHAT DEPENDS ON THEM
--   STATUS_BEFORE_MERGE  the loser's status at merge time. `Reversal = clear MERGED_INTO +
--                        restore STATUS` (schema.sql's own words) reads this and nothing else.
--                        It is how 54 merges that had absorbed a COMPLETED row into a lesser
--                        survivor were reverted on 2026-08-22.
--   MERGED_AT            when. Distinguishes a bad merge from a CASCADE -- a survivor demoted to
--                        OLD 13-39 seconds AFTER its merge is not a merge fault, and without a
--                        timestamp the two are indistinguishable and the safety gate false-alarms.
--   MERGE_BATCH_ID       which adjudication did it, so one batch can be reverted without the rest.
--   DUP_CAUSE            why the group was a duplicate. Turns an undifferentiated backlog into a
--                        ranked defect list; it is what identified the mis-extracted doc-ids.
--
-- Idempotent, additive, and safe to run on a database that already has them.

\echo '--- state before ---'
SELECT '  merge provenance columns present: ' || count(*) || ' of 4'
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'incoming_documents'
  AND column_name IN ('STATUS_BEFORE_MERGE','MERGED_AT','MERGE_BATCH_ID','DUP_CAUSE');

ALTER TABLE public.incoming_documents
  ADD COLUMN IF NOT EXISTS "STATUS_BEFORE_MERGE" TEXT;
ALTER TABLE public.incoming_documents
  ADD COLUMN IF NOT EXISTS "MERGED_AT" timestamptz;
ALTER TABLE public.incoming_documents
  ADD COLUMN IF NOT EXISTS "MERGE_BATCH_ID" uuid;
ALTER TABLE public.incoming_documents
  ADD COLUMN IF NOT EXISTS "DUP_CAUSE" TEXT;

\echo '--- state after ---'
SELECT '  merge provenance columns present: ' || count(*) || ' of 4'
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'incoming_documents'
  AND column_name IN ('STATUS_BEFORE_MERGE','MERGED_AT','MERGE_BATCH_ID','DUP_CAUSE');

-- The invariant these enable, for whoever runs this on another deployment: after any merge run,
--     select count(*) from public.incoming_documents
--      where "STATUS"='MERGED' and ("MERGED_INTO" is null or "STATUS_BEFORE_MERGE" is null
--                                   or "MERGED_AT" is null)
-- must be 0. A non-zero result means merges happened that cannot be undone.
