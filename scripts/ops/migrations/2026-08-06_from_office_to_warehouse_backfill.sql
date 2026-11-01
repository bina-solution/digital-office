-- 2026-08-06 — FROM_OFFICE -> FROM_WAREHOUSE backfill. Executable form of
-- scripts/ops/indox-column-consolidation.sql SECTION 4 (§4.1), whose write is commented out
-- because that file is a reference/analysis document.
--
-- Pure copy, no semantic decision: "office" was always the wrong word — these documents come
-- from the WAREHOUSE where goods are physically received. "FROM_WAREHOUSE"/"FROM_WAREHOUSE_CHECK"
-- already exist in schema.sql and in the live DB, and were 100% NULL before this ran.
--
-- SEQUENCE (from rename-from-office-to-warehouse.py's docstring): this backfill runs BEFORE
-- `python3 scripts/ops/rename-from-office-to-warehouse.py --apply`. Otherwise every writer is
-- repointed at a column that is still entirely NULL and the pipeline reads empty values.
--
-- DUAL-WRITE WINDOW: until the rename is applied AND the n8n blueprints are pushed, every live
-- writer still writes FROM_OFFICE only, so FROM_WAREHOUSE drifts again on each new document.
-- That drift is closed declaratively by the mirror trigger in
-- apps/indox/blueprint/fixtures/schema.sql (trg_incdoc_mirror_from_office), NOT by re-running
-- this file. This file is the one-time seed for rows that predate the trigger.
--
-- Backup taken before this ran:
--   data/_registry_backup/incoming_documents.pre-backfills.20260806T143308Z.sql
--   9,520,998 bytes · 6,405 data rows
--   sha256 2121eaa7fef5d987083cc792ae59593795ed00860fbae24fd85aa8663c83f485
--
-- Measured immediately before the write (2026-08-06T14:33Z, 6,405 rows):
--   FROM_OFFICE       non-empty 5,735   FROM_WAREHOUSE       non-null 0
--   FROM_OFFICE_CHECK non-empty 5,756   FROM_WAREHOUSE_CHECK non-null 0

\set ON_ERROR_STOP on

BEGIN;
update public.incoming_documents
   set "FROM_WAREHOUSE"       = "FROM_OFFICE",
       "FROM_WAREHOUSE_CHECK" = "FROM_OFFICE_CHECK"
 where "FROM_OFFICE" is not null
    or "FROM_OFFICE_CHECK" is not null;
COMMIT;

-- Post-check — mismatched_rows must be exactly 0 (§4.2 of the consolidation file).
\echo '--- POST-CHECK: mismatched_rows must be 0 ---'
select count(*) as mismatched_rows
  from public.incoming_documents
 where "FROM_WAREHOUSE"       is distinct from "FROM_OFFICE"
    or "FROM_WAREHOUSE_CHECK" is distinct from "FROM_OFFICE_CHECK";

\echo '--- population, both spellings ---'
select count(*)                                                          as total,
       count(*) filter (where coalesce("FROM_OFFICE",'')          <> '') as from_office,
       count(*) filter (where coalesce("FROM_WAREHOUSE",'')       <> '') as from_warehouse,
       count(*) filter (where coalesce("FROM_OFFICE_CHECK",'')    <> '') as from_office_check,
       count(*) filter (where coalesce("FROM_WAREHOUSE_CHECK",'') <> '') as from_warehouse_check
  from public.incoming_documents;
