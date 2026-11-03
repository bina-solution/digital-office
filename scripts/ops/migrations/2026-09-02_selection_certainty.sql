-- companies.SELECTION_CERTAINTY (owner Decision 5, 2026-09-02): a per-company FIXED certainty
-- (0-100). SelectType01's corroboration score becomes max(computed, fixed) for documents of that
-- company — "ספקים עם אחוז ודאות גבוה" is a number the operator sets on the company row, visible
-- and editable in the companies editor. It subsumes the old trusted-suppliers membership list
-- (TRUSTED_SOURCE_TYPES + a SELECTION_CERTAINTY===100 gate over a column that never existed).
--
-- Run per tenant schema:
--   psql -U postgres -d postgres -v schema=indox_hacohen -f 2026-09-02_selection_certainty.sql

\set ON_ERROR_STOP on
set search_path to :"schema", public;

BEGIN;
alter table companies add column if not exists "SELECTION_CERTAINTY" integer;
do $$
begin
  if not exists (select 1 from pg_constraint
                  where conname = 'companies_selection_certainty_range'
                    and conrelid = (current_schema() || '.companies')::regclass) then
    alter table companies add constraint companies_selection_certainty_range
      check ("SELECTION_CERTAINTY" is null or ("SELECTION_CERTAINTY" between 0 and 100));
  end if;
end $$;
COMMIT;

select count(*) as companies, count("SELECTION_CERTAINTY") as with_fixed_certainty from companies;
