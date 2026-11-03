-- The documents grid's free-text search is `col::text ilike '%term%'` over the catalog's
-- searchable columns (display.json: NAME, TYPE, STATUS, SOURCE_TYPE, COMPANY_NAME, SHORT_DOC_ID,
-- REQUIRED_ACTION). Without a trigram index every keystroke is a sequential scan of ~26k wide
-- rows per column — the "INDOX table timeouts" (owner issue, 2026-09-02). GIN trigram indexes on
-- the free-text columns make the ilike an index scan; the three enum-like columns are left to
-- their btree-able equality (a trigram index on a 6-value column buys nothing).
--
-- Run per tenant schema:
--   psql -U postgres -d postgres -v schema=indox_hacohen -f 2026-09-02_documents_search_trgm.sql

\set ON_ERROR_STOP on
create extension if not exists pg_trgm with schema public;
set search_path to :"schema", public;

create index if not exists incdoc_name_trgm            on incoming_documents using gin ("NAME" public.gin_trgm_ops);
create index if not exists incdoc_company_name_trgm    on incoming_documents using gin ("COMPANY_NAME" public.gin_trgm_ops);
create index if not exists incdoc_short_doc_id_trgm    on incoming_documents using gin ("SHORT_DOC_ID" public.gin_trgm_ops);
create index if not exists incdoc_required_action_trgm on incoming_documents using gin ("REQUIRED_ACTION" public.gin_trgm_ops);

select indexname from pg_indexes where schemaname = current_schema() and indexname like 'incdoc_%_trgm' order by 1;
