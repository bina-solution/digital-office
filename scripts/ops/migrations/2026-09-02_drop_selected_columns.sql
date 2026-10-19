-- SELECTED_* is gone (owner order, 2026-09-02). The seven columns were the retired "selected"
-- generation of the base/type selectors — every writer moved to COMPANY_ID / DOC_ID / TYPE /
-- DOC_TOTAL_AMOUNT / DOC_DATE / SHIPMENT_DOC_ID / PURCHASE_ID on 2026-08-31, and the last readers
-- (the three action gates, the views catalog, the acceptance script, the fixtures' Step-0 targets)
-- were repointed in the same change as this file. Dropped from the live table AND its archive.
--
-- CASCADE is deliberate: the only dependents are the sole-tenant-era `public.incoming_documents`
-- / `public.incoming_documents_archive` compatibility views (retired at the 2026-08-31 cutover —
-- no workflow or BFF path reads them) and four ad-hoc analysis views someone left in public
-- (v_indox_doubles, amt_restart, amt_shape, resend_set, sane_plan). They go with the columns.
--
-- Run per tenant schema:
--   psql -U postgres -d postgres -v schema=indox_hacohen -f 2026-09-02_drop_selected_columns.sql

\set ON_ERROR_STOP on
set search_path to :"schema", public;

BEGIN;
alter table incoming_documents
  drop column if exists "SELECTED_COMPANY_ID"      cascade,
  drop column if exists "SELECTED_DOC_ID"          cascade,
  drop column if exists "SELECTED_DOC_TIPE"        cascade,
  drop column if exists "SELECTED_DOC_AMOUNT"      cascade,
  drop column if exists "SELECTED_DOC_DATE"        cascade,
  drop column if exists "SELECTED_DOC_SHIPMENT_ID" cascade,
  drop column if exists "SELECTED_DOC_ORDER_ID"    cascade;
alter table incoming_documents_archive
  drop column if exists "SELECTED_COMPANY_ID"      cascade,
  drop column if exists "SELECTED_DOC_ID"          cascade,
  drop column if exists "SELECTED_DOC_TIPE"        cascade,
  drop column if exists "SELECTED_DOC_AMOUNT"      cascade,
  drop column if exists "SELECTED_DOC_DATE"        cascade,
  drop column if exists "SELECTED_DOC_SHIPMENT_ID" cascade,
  drop column if exists "SELECTED_DOC_ORDER_ID"    cascade;
-- the fixture rows this tenant already holds: the Step-0 targets and the old-date guard
update settings set value = replace(value, ',SELECTED_DOC_DATE,', ',') where key = 'fixture_GLOBAL';
update settings set value = replace(replace(replace(replace(replace(replace(replace(value,
  'SELECTED_DOC_SHIPMENT_ID', 'SHIPMENT_DOC_ID'), 'SELECTED_DOC_ORDER_ID', 'PURCHASE_ID'),
  'SELECTED_DOC_AMOUNT', 'DOC_TOTAL_AMOUNT'), 'SELECTED_DOC_DATE', 'DOC_DATE'),
  'SELECTED_DOC_TIPE', 'TYPE'), 'SELECTED_COMPANY_ID', 'COMPANY_ID'), 'SELECTED_DOC_ID', 'DOC_ID')
 where key like 'fixture\_%' and value like '%SELECTED\_%';
COMMIT;

select table_name, count(*) filter (where column_name like 'SELECTED\_%') as selected_left
  from information_schema.columns
 where table_schema = current_schema() and table_name in ('incoming_documents','incoming_documents_archive')
 group by 1 order by 1;
