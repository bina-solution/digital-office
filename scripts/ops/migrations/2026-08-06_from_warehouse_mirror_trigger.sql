-- 2026-08-06 — FROM_OFFICE <-> FROM_WAREHOUSE mirror. Applied live AND codified in
-- apps/indox/blueprint/fixtures/schema.sql so a fresh clone + `bbox run` reproduces it.
--
-- WHY THIS EXISTS. scripts/ops/indox-column-consolidation.sql §5 states the dual-write window
-- plainly: "Because NO writer has been repointed yet, these numbers WILL drift apart again after
-- each backfill." The one-time backfill (2026-08-06_from_office_to_warehouse_backfill.sql) seeds
-- 5,756 existing rows; every document ingested after it is written with FROM_OFFICE only, so
-- FROM_WAREHOUSE goes NULL again on each new row. A one-time UPDATE is therefore NOT a permanent
-- fix, and re-running it on a schedule would be a cron-shaped workaround, not a fix.
--
-- The mirror is SYMMETRIC on purpose, so it is correct on BOTH sides of the rename:
--   * before `scripts/ops/rename-from-office-to-warehouse.py --apply` + `bbox n8n push`:
--     writers set FROM_OFFICE      -> FROM_WAREHOUSE follows.
--   * after:  writers set FROM_WAREHOUSE -> FROM_OFFICE follows, so every reader that has not
--     been repointed yet (and the §5 drift watch) keeps seeing the value.
-- It never clobbers an explicit write: on UPDATE a side is mirrored only when the OTHER side
-- changed and this one did not. If a statement writes both, both are left exactly as written.
--
-- RETIREMENT: drop these two triggers in the SAME phase that drops FROM_OFFICE /
-- FROM_OFFICE_CHECK (consolidation §4's "final, separate phase"). Until then they are what keeps
-- the two spellings from diverging.
--
-- STYLE CONSTRAINT: single-quoted function bodies, NOT dollar-quoted. The n8n postgres node
-- (pg-promise) reads `$` as its own variable syntax and schema.sql is applied through that node —
-- same reason apps/n8n/schema/01_platform.sql:46 writes touch_updated_at() this way.

\set ON_ERROR_STOP on

BEGIN;

create or replace function public.incdoc_mirror_from_warehouse_ins() returns trigger as
'begin
   if new."FROM_WAREHOUSE" is null then new."FROM_WAREHOUSE" = new."FROM_OFFICE"; end if;
   if new."FROM_OFFICE" is null then new."FROM_OFFICE" = new."FROM_WAREHOUSE"; end if;
   if new."FROM_WAREHOUSE_CHECK" is null then new."FROM_WAREHOUSE_CHECK" = new."FROM_OFFICE_CHECK"; end if;
   if new."FROM_OFFICE_CHECK" is null then new."FROM_OFFICE_CHECK" = new."FROM_WAREHOUSE_CHECK"; end if;
   return new; end;' language plpgsql;

create or replace function public.incdoc_mirror_from_warehouse_upd() returns trigger as
'begin
   if new."FROM_OFFICE" is distinct from old."FROM_OFFICE"
      and new."FROM_WAREHOUSE" is not distinct from old."FROM_WAREHOUSE"
   then new."FROM_WAREHOUSE" = new."FROM_OFFICE"; end if;
   if new."FROM_WAREHOUSE" is distinct from old."FROM_WAREHOUSE"
      and new."FROM_OFFICE" is not distinct from old."FROM_OFFICE"
   then new."FROM_OFFICE" = new."FROM_WAREHOUSE"; end if;
   if new."FROM_OFFICE_CHECK" is distinct from old."FROM_OFFICE_CHECK"
      and new."FROM_WAREHOUSE_CHECK" is not distinct from old."FROM_WAREHOUSE_CHECK"
   then new."FROM_WAREHOUSE_CHECK" = new."FROM_OFFICE_CHECK"; end if;
   if new."FROM_WAREHOUSE_CHECK" is distinct from old."FROM_WAREHOUSE_CHECK"
      and new."FROM_OFFICE_CHECK" is not distinct from old."FROM_OFFICE_CHECK"
   then new."FROM_OFFICE_CHECK" = new."FROM_WAREHOUSE_CHECK"; end if;
   return new; end;' language plpgsql;

drop trigger if exists trg_incdoc_mirror_warehouse_ins on public.incoming_documents;

create trigger trg_incdoc_mirror_warehouse_ins before insert on public.incoming_documents
  for each row execute function public.incdoc_mirror_from_warehouse_ins();

drop trigger if exists trg_incdoc_mirror_warehouse_upd on public.incoming_documents;

create trigger trg_incdoc_mirror_warehouse_upd before update on public.incoming_documents
  for each row execute function public.incdoc_mirror_from_warehouse_upd();

COMMIT;

\echo '--- post-check: triggers present ---'
select tgname from pg_trigger
 where tgrelid = 'public.incoming_documents'::regclass and not tgisinternal
 order by tgname;

\echo '--- post-check: drift must be 0 ---'
select count(*) as from_warehouse_drift
  from public.incoming_documents
 where "FROM_WAREHOUSE"       is distinct from "FROM_OFFICE"
    or "FROM_WAREHOUSE_CHECK" is distinct from "FROM_OFFICE_CHECK";
