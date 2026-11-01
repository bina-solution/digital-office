-- A LOCAL MIRROR OF THE CLIENT'S PRIORITY TABLE, so action_priority_sync can be switched on and
-- exercised for real without a single byte reaching the client's ERP.
--
-- WHY IT IS APPEND-ONLY, not an upsert.
-- The temptation is to key this table on (IDSUP, DOCNAME, DATEDOC) and upsert, which would look
-- tidy. That would be a mirror of what we WISH Priority did, and it would hide the exact defect
-- we are trying to rehearse. Measured on the live data 2026-08-22: 72 business keys have more
-- than one record in the client's ERP, 90 records in excess of one-per-document. Priority's
-- SHIM_RECEIVE_SUPDOC therefore CREATES a record per POST -- it does not merge on the business
-- key. So this table inserts one row per POST too. Post the same document twice and you get two
-- rows here, exactly as the client would get two records.
--
-- Reading it: v_indox_priority_local_dupes is the whole point -- it shows what the client's ERP
-- would look like after a run. If that view is empty after a full sync, the duplication problem
-- is genuinely solved end to end.

create table if not exists public.indox_priority_local (
  id             bigserial primary key,
  received_at    timestamptz not null default now(),

  -- the SHIM_RECEIVE_SUPDOC payload, field for field, same names the client's endpoint receives
  "IDSUP"              text,
  "DATEDOC"            text,
  "DOCNAME"            text,
  "DOCSHORT"           text,
  "TOTPRICE"           double precision,
  "DOC_INV"            text,
  "PORDNAME"           text,
  "LINKDOC"            text,
  "TYPEDOC"            text,
  "SOURCE"             text,
  "FROMWAREHOUSE"      text,
  "PROPORTZ_CERTAINTY" text,
  "N8N_EXEID"          text,
  "INCOMING_DOC_ID"    text,

  raw jsonb                       -- the untouched body, so a payload change is visible even if
                                  -- this table's columns lag behind Map Request
);

comment on table public.indox_priority_local is
  'Local stand-in for the client Priority SHIM_RECEIVE_SUPDOC endpoint. APPEND-ONLY on purpose: '
  'the real endpoint creates a record per POST (proven: 72 duplicate business keys / 90 excess '
  'records in the client ERP, 2026-08-22), so a duplicate POST must show up here as two rows.';

create index if not exists indox_priority_local_key_idx
  on public.indox_priority_local ("IDSUP", "DOCNAME", "DATEDOC");
create index if not exists indox_priority_local_doc_idx
  on public.indox_priority_local ("INCOMING_DOC_ID");
create index if not exists indox_priority_local_received_idx
  on public.indox_priority_local (received_at desc);

-- THE ACCEPTANCE VIEW. Empty after a full run == no document was delivered twice.
create or replace view public.v_indox_priority_local_dupes as
select "IDSUP", "DOCNAME", "DATEDOC",
       count(*)                              as records_created,
       count(*) - 1                          as excess_records,
       count(distinct "TOTPRICE")            as distinct_amounts,
       count(distinct "INCOMING_DOC_ID")     as distinct_source_rows,
       min(received_at)                      as first_post,
       max(received_at)                      as last_post,
       string_agg(distinct "INCOMING_DOC_ID", ' | ') as source_row_ids
from public.indox_priority_local
where coalesce("IDSUP",'') <> '' and coalesce("DOCNAME",'') <> ''
group by 1,2,3
having count(*) > 1;

comment on view public.v_indox_priority_local_dupes is
  'What the client ERP would hold after a local run. Empty = every document delivered exactly '
  'once. Non-empty rows are duplicates we would have shipped.';

-- The toggle. Named exactly as the owner asked (indox.actions.priority_sync.local). Dotted keys
-- are new to this table, which is fine: settings.key is free-form TEXT and every reader
-- COALESCEs a default, so an absent row can never dark-stop a lane.
insert into public.settings (instance, key, value)
select 'default', 'indox.actions.priority_sync.local', 'true'
where not exists (
  select 1 from public.settings where key = 'indox.actions.priority_sync.local');

-- Default TRUE deliberately: while this lands, the safe state is local. Flipping it to false is
-- the deliberate act of pointing the lane at the client's live ERP.
