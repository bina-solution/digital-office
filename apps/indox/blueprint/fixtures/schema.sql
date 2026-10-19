-- INDOX schema — owned by apps/indox (layer 3).
--
-- This lived in apps/n8n/fixtures/01_schema.sql, where layer 2 declared a layer-3 app's
-- entire data model. It got there by accident rather than design: the file was production/n8n/
-- fixtures/01_schema.sql before the three-layer refactor, and that refactor moved production/n8n/
-- wholesale into platform-base. Nobody re-homed the tables. G9's layering lint did not catch it
-- because "/fixtures/" is in its SKIP_DIRS.
--
-- Idempotent: create-minimal + add-column-if-not-exists, so it patches an existing database and
-- provisions a fresh one with the same statements. ALL document columns are TEXT to preserve the
-- string semantics of the Google Sheet this table replaced.
--
-- NOT applied through the n8n Postgres node any more, and it cannot be: that node hands the whole
-- file to pg-promise, which reads `$` as its own variable syntax, and this file now contains
-- dollar-quoted plpgsql bodies ($fn$ ... $fn$). That mismatch is the root cause recorded in
-- issues/fixture-seeding-cannot-apply-the-schema-through-n8n.yaml (100% E2E seeding loss, with a
-- misleading "Syntax error at line 295" that is n8n's own prettifier, not postgres). The applier
-- is apps/indox/hooks/apply-schema, which sends it through psql.

-- ── APPLY CONTRACT ───────────────────────────────────────────────────────────────────────────
-- THIS FILE IS APPLIED INTO AN INSTANCE SCHEMA, NOT INTO `public`.
--
-- An INDOX instance is a tenant and its data lives in its own schema (`platform.state.yaml` →
-- indox.entries[].schema, e.g. `indox_hacohen`). The applier — apps/indox/hooks/apply-schema —
-- creates that schema and sets `search_path` before sending a byte of this file, so every
-- unqualified table name below resolves to the tenant's own table.
--
-- WHAT STAYS QUALIFIED, AND WHY. Functions and views keep their `public.` prefix on purpose:
-- every function here is PURE (it reads its arguments, never a table), so it is tenant-agnostic
-- code rather than tenant data, and 25+ live callers — indoxApi01, indoxV2Driver01, Decide,
-- ActionRouter, the five JQExV3 extractors, priorityLocalApi01, extraction.py — name them as
-- `public.X`. Moving them would break every one of those at once for no correctness gain.
-- `public.touch_updated_at()` belongs to platform-base (01_platform.sql), not to this app.
--
-- WHY THE GUARD BELOW. Applying this file with `search_path` left at `public` would build a
-- second, shadow copy of every table in the wrong schema, and — since 2026-08 `public` holds
-- COMPAT VIEWS over the tenant tables — the first `alter table` would fail with the unhelpful
-- "is not a table". Both failures are silent about their real cause, so this refuses up front.
--
-- APPLY ORDER: platform-base 01_platform.sql (touch_updated_at) -> this -> 99_grants.sql.
DO $indox_apply_guard$
BEGIN
  IF current_schema() = 'public' THEN
    RAISE EXCEPTION
      'INDOX schema.sql must be applied INTO AN INSTANCE SCHEMA, but search_path resolves to public.'
      USING HINT = 'Use apps/indox/hooks/apply-schema <instance>, or SET search_path = "indox_<id>", public; first.';
  END IF;
END
$indox_apply_guard$;

-- INDOX schema (no-logic-loss reconciled union; ALL columns TEXT to preserve Sheets string semantics)
-- Idempotent: create-minimal + add-column-if-not-exists (patches existing table + fresh installs).
create table if not exists incoming_documents ("ID" TEXT primary key);

alter table incoming_documents add column if not exists "NAME" TEXT;

alter table incoming_documents add column if not exists "COMPANY_ID" TEXT;

alter table incoming_documents add column if not exists "COMPANY_NAME" TEXT;

alter table incoming_documents add column if not exists "SHORT_DOC_ID" TEXT;

-- COMPANY_DOC_ID retired 2026-08-17 (owner order): DOC_ID is the one canonical doc number.

alter table incoming_documents add column if not exists "TYPE" TEXT;

alter table incoming_documents add column if not exists "STATUS" TEXT;

alter table incoming_documents add column if not exists "LINK" TEXT;

alter table incoming_documents add column if not exists "SOURCE_TYPE" TEXT;

alter table incoming_documents add column if not exists "SOURCE_ID" TEXT;

alter table incoming_documents add column if not exists "SOURCE_LINK" TEXT;

alter table incoming_documents add column if not exists "SIZE" TEXT;

alter table incoming_documents add column if not exists "HASH" TEXT;

alter table incoming_documents add column if not exists "TIMESTAMP" TEXT;

alter table incoming_documents add column if not exists "RECEIVED_DATE" TEXT;

alter table incoming_documents add column if not exists "DOC_DATE" TEXT;

alter table incoming_documents add column if not exists "DOC_TOTAL_AMOUNT" TEXT;

alter table incoming_documents add column if not exists "TOTAL_AMOUNT" TEXT;

alter table incoming_documents add column if not exists "PURCHASE_ID" TEXT;

alter table incoming_documents add column if not exists "SHIPMENT_DOC_ID" TEXT;

alter table incoming_documents add column if not exists "REQUIRED_ACTION" TEXT;

alter table incoming_documents add column if not exists "FROM_OFFICE" TEXT;

alter table incoming_documents add column if not exists "FROM_OFFICE_CHECK" TEXT;

alter table incoming_documents add column if not exists "EMPTY" TEXT;

alter table incoming_documents add column if not exists "LINKED_BS" TEXT;

alter table incoming_documents add column if not exists "BS_LINE_DATE" TEXT;

alter table incoming_documents add column if not exists "BS_LINE_AMOUNT" TEXT;

alter table incoming_documents add column if not exists "BS_LINE_NOTE" TEXT;

alter table incoming_documents add column if not exists "BS_EXTRACTED_LINES" TEXT;

alter table incoming_documents add column if not exists "BS_EXTRACTION_VERIFIED" TEXT;

alter table incoming_documents add column if not exists "BS_EXTRACTION_USE_CACHE" TEXT;

alter table incoming_documents add column if not exists "BS_LINK_DOCUMENTS_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "SEARCH_IN_DRIVE_COMPLETED" TEXT;

-- 2026-08-20, owner order: apply_gmail_labels and file_to_failed_folder were the ONLY two
-- actions in the state machine with no completion column; their once-only gates in
-- indoxV2ActionsGlobal01 :: 'Decide DOC BASE Action' read substrings out of ACTION_LOG instead.
-- The '_COMPLETED' suffix is load-bearing: the four 'Build: Restart (clear completed flags)'
-- nodes clear every key ending in it, so ACTION_RESTART resets these two for free.
-- file_to_failed_folder in particular is NOT idempotent -- re-running it asks Google Drive to
-- move a file that has already moved, and Drive answers "File not found".
alter table incoming_documents add column if not exists "GMAIL_LABELS_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "FAILED_FOLDER_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "DOC_DATE_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "DOC_TOTAL_AMOUNT_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "PURCHASE_ID_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "SHIPMENT_ID_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "COMPANY_NAME_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "API_TOOLS_ID_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "API_TOOLS_ID" TEXT;

alter table incoming_documents add column if not exists "BS_EXTRACTED_LINES_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "INVOICE_ID_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "INVOICE_ID" TEXT;

alter table incoming_documents add column if not exists "INV_ID_FOR_SHIP" TEXT;

alter table incoming_documents add column if not exists "EX_INVOICE_ID" TEXT;

alter table incoming_documents add column if not exists "EX_IS_BS" TEXT;

alter table incoming_documents add column if not exists "EX_IS_BS_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "FIGURE_TYPE_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "FIGURE_COMPANY_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "DOUBLE_LINE_CONTEXT" TEXT;

-- [source contract 2026-08-25, owner order] THE SPLIT BETWEEN SYNC AND SELECT, AS COLUMNS.
--
-- THE SYNC settles what only the source can know, and decides nothing:
--   SENDER            who sent it, settled per sync. For mail this is the ORDERED candidate chain
--                     (gaviti-unwrapped -> forwarded chain -> raw From), comma-joined: the
--                     forwarded sender outranks the From, and dropping the chain is what loses
--                     the answer for forwarded supplier mail.
--   SYNC_REGISTRY_ID  which registry entry delivered it — the pipe is itself evidence about type
--                     and company (a BS pipe only ever carries balance sheets).
--   ATTACHMENT_TEXT   the text that came WITH the item: "<subject> | <first 100 chars of body>".
--                     Measured need: intermediary mail (invoice-one / morning) prints the SaaS
--                     letterhead on the PDF and names the real supplier only in the subject, so
--                     no OCR of the page can ever recover it.
--   SEND_DATE         when the source itself says it was sent/created (mail Date header, drive
--                     createdTime). RECEIVED_DATE stays "when it reached us".
--
-- THE SELECTOR derives, from those, two more candidates — and then treats them as ordinary legs
-- alongside LOCAL_*/AI_*, so every datum is chosen from ALL its options rather than from OCR only:
--   COMPANY_BY_SENDER company resolved from SENDER (companies."מייל 1"/"מייל 2", address or bare
--                     domain). The map has existed since this schema was written and nothing has
--                     ever read it.
--   TYPE_BY_SOURCE    type implied by the source itself (ATTACHMENT_TEXT vocabulary +
--                     SYNC_REGISTRY_ID), the same evidence the label engine already routes on.
alter table incoming_documents add column if not exists "SENDER" TEXT;

alter table incoming_documents add column if not exists "SYNC_REGISTRY_ID" TEXT;

alter table incoming_documents add column if not exists "ATTACHMENT_TEXT" TEXT;

alter table incoming_documents add column if not exists "SEND_DATE" TEXT;

alter table incoming_documents add column if not exists "COMPANY_BY_SENDER" TEXT;

alter table incoming_documents add column if not exists "TYPE_BY_SOURCE" TEXT;

alter table incoming_documents add column if not exists "AI_COMPANY_ID" TEXT;

alter table incoming_documents add column if not exists "AI_TYPE" TEXT;

alter table incoming_documents add column if not exists "AI_DOC_ID" TEXT;

alter table incoming_documents add column if not exists "AI_DOC_DATE" TEXT;

alter table incoming_documents add column if not exists "AI_DOC_AMOUNT" TEXT;

alter table incoming_documents add column if not exists "AI_SHIPMENT_IDS" TEXT;

alter table incoming_documents add column if not exists "AI_ORDER_IDS" TEXT;

alter table incoming_documents add column if not exists "AI_EXTRACTION_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "PRIORITY_SYNC_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "PRIORITY_SYNC_COUNT" TEXT;

-- SELECTED_COMPANY_ID / SELECTED_DOC_ID / SELECTED_DOC_TIPE / SELECTED_DOC_AMOUNT / SELECTED_DOC_DATE /
-- SELECTED_DOC_SHIPMENT_ID / SELECTED_DOC_ORDER_ID were REMOVED 2026-09-02 (owner order): the
-- retired "selected" generation. COMPANY_ID / DOC_ID / TYPE / DOC_TOTAL_AMOUNT / DOC_DATE /
-- SHIPMENT_DOC_ID / PURCHASE_ID are the selectors' only outputs. Existing tenants:
-- scripts/ops/migrations/2026-09-02_drop_selected_columns.sql (drops from the table and the archive).

alter table incoming_documents add column if not exists "SELECTION_CERTAINTY" TEXT;

alter table incoming_documents add column if not exists "SELECTION_SOURCE" TEXT;

alter table incoming_documents add column if not exists "SELECTION_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "SELECTION_SCORE_DEBUG" TEXT;

alter table incoming_documents add column if not exists "SELECTION_VALUES_HASH" TEXT;

alter table incoming_documents add column if not exists "IS_OLD" TEXT;

alter table incoming_documents add column if not exists "EXTRACT_SHIPMENT_COMPLETED" TEXT;


alter table incoming_documents add column if not exists "created_at" timestamptz default now();

alter table incoming_documents add column if not exists "updated_at" timestamptz default now();

-- the dashboard's time-window toggle (GET /dashboard/stats?win=…&basis=…) filters
-- on ONE of these columns server-side; at ERP scale (spec: 180k rows) that WHERE
-- clause needs an index to stay off a sequential scan. One index per offered
-- `basis` (api/__init__.py `_DASH_BASES`) — an offered basis without an index is
-- a sequential scan wearing a dropdown.
--
-- Measured on the live 16,237-row table, 2026-08-10, before vs after:
--   count(created_at >= now()-30m)  27.4 ms / 2,208 buffers  ->  0.17 ms /  26
--   count(updated_at >= now()-30m)  27.6 ms / 2,208 buffers  ->  5.97 ms / 263
--   the endpoint's own paged read    40.4 ms / 2,211 buffers  ->  2.35 ms / 171
-- The buffer count is the number that matters: a sequential scan's grows with
-- the TABLE, an index scan's with the MATCH, so the gap widens on the way to
-- 100k+ rows rather than staying at today's ~10x.
create index if not exists incoming_documents_created_at on incoming_documents ("created_at");

create index if not exists incoming_documents_updated_at on incoming_documents ("updated_at");

-- [table timeouts 2026-09-02] The grid's free-text search is `col::text ilike '%term%'` over the
-- catalog's searchable free-text columns; a trigram GIN index turns each from a sequential scan of
-- the whole table into an index scan. Existing tenants: 2026-09-02_documents_search_trgm.sql.
create extension if not exists pg_trgm with schema public;
create index if not exists incdoc_name_trgm            on incoming_documents using gin ("NAME" public.gin_trgm_ops);
create index if not exists incdoc_company_name_trgm    on incoming_documents using gin ("COMPANY_NAME" public.gin_trgm_ops);
create index if not exists incdoc_short_doc_id_trgm    on incoming_documents using gin ("SHORT_DOC_ID" public.gin_trgm_ops);
create index if not exists incdoc_required_action_trgm on incoming_documents using gin ("REQUIRED_ACTION" public.gin_trgm_ops);

-- "TIMESTAMP" is TEXT, but every filled value in the live table is strictly
-- `YYYY-MM-DDTHH:MM:SS.mmmZ` (15,032/15,032, fixed 24 chars). For a fixed-width
-- ISO-8601 format lexicographic ordering IS chronological ordering, so a plain
-- btree serves `>=` exactly — verified by EXPLAIN: Index Only Scan, 0.32 ms.
-- The BFF renders the window's start instant into that same 24-char shape
-- before comparing (`_dash_since_for_basis`); like-for-like is what makes this
-- exact rather than lucky.
create index if not exists incoming_documents_timestamp_txt on incoming_documents ("TIMESTAMP");


-- ===========================================================================
-- doc_date_norm — the BUSINESS date, normalised, so the dashboard can window on it
-- (2026-08-10).
--
-- THE PROBLEM THIS SOLVES. `DOC_DATE` is the document's own printed date and is
-- the question operators actually ask ("what did we receive dated last month"),
-- but it is TEXT in three live shapes, measured on the 16,257-row table:
--     8,360 filled = 5,114 ISO (`YYYY-MM-DD...`) + 2,806 `DD/MM/YYYY` + 440 `DD/MM/YY`
-- A lexicographic `>=` across those is not merely imprecise, it is BACKWARDS for
-- the 39% in slash form: '25/06/2026' > '2026-08-10' (they differ at index 1,
-- '5' > '0'), so every slash-format row reports as inside every window, forever.
-- That is why `DOC_DATE` was offered to the UI as an explicitly DISABLED basis
-- rather than a working one. This column is the fix, and the dashboard's
-- `_DASH_BASES` entry `doc_date_norm` is its only consumer.
--
-- WHY A TRIGGER AND NOT `GENERATED ALWAYS AS ... STORED`. A stored generated
-- column is not writable, and `indoxApiSupabase01`'s `Build Merge Write` node
-- does `select *` on the rows it merges and re-emits
-- `update incoming_documents set "<col>" = <param>` for EVERY column outside a
-- hardcoded 24-name skip list. A generated column reached by that loop is a
-- runtime SQLSTATE 428C9 ("column can only be updated to DEFAULT") on a live
-- merge path — an outage, not a lint failure. A plain column stays writable, so
-- that write succeeds; and because the trigger below recomputes the value
-- unconditionally on BEFORE INSERT **OR UPDATE**, whatever the merge writer
-- happened to put there is immediately replaced by the value derived from that
-- row's own `DOC_DATE`. The column is therefore derived-in-effect without ever
-- being un-writable. Do NOT convert it to a generated column.
--
-- PARSE RULES — the two live formats, and NULL for everything else.
-- Deliberately the same two `_month_key_of` handles in
-- `apps/indox/app/incoming_documents/api/__init__.py`, including its 2-digit-year
-- rule, so the month navigator and the dashboard window never disagree about
-- which month a document belongs to:
--   * ISO      leading `YYYY-MM-DD` (a trailing `T00:00:00.000Z` is ignored).
--   * DMY      `D/M/YY`, `D/M/YYYY`, and the same with `.` separators.
--              A 2-DIGIT YEAR IS ALWAYS `20YY`, never `19YY`. Naive parsers read
--              `23/06/26` as 1926 and silently file a current document a century
--              back; `2000 + yy` is the rule the extractor's own output implies
--              (`q_v3_date_base` copies the year exactly as printed, 2 or 4
--              digits, and never normalises it).
--   * anything else -> NULL. Never a guessed date. This is what catches
--              `RECEIVED_DATE`-style junk (477 rows there are the literal string
--              `true`) and the 6 live `DOC_DATE` values that parse to a
--              nonexistent day: 35/09/2003, 0/06/2026, 05/24/2026, 06/23/2026,
--              11/26/0185, 11/26/0153. Note 05/24/2026 and 06/23/2026 are almost
--              certainly US-order MM/DD — they are still NULL, because a column
--              whose meaning is "the document's date" must not contain a date
--              nobody can defend. NULL is visible: the endpoint counts these as
--              `basis_excluded` and the UI prints the count.
--   Out-of-range years are NULL too (1990..2100), which is what makes the
--   0185/0153 rows drop rather than land in the middle ages.
--
-- ANCHORED AT 00:00 UTC. A business date has no time of day and no timezone, but
-- the window it is compared against is an instant. Storing midnight UTC and
-- having the BFF floor the window's start to the start of the viewer's LOCAL
-- calendar day (`_dash_since_for_basis`, kind `business_day`) makes the pair
-- exact in every timezone; the alternative — a `date` column compared against a
-- raw instant — is off by one whole day for every viewer east of Greenwich,
-- which is where this deployment's viewers are.
--
-- HISTORICAL ROWS STAY NULL. A trigger fires on write. Every row that existed
-- before this migration keeps `doc_date_norm = NULL` until something touches it,
-- so this basis under-reports the back catalogue on day one and converges as the
-- pipeline works. That is deliberate and it is REPORTED, not hidden: the
-- endpoint's `basis_excluded`/`basis_eligible`/`basis_rows` counters state
-- exactly how many rows the basis cannot place, and the UI renders the number.
-- Filling them would be a one-off bulk UPDATE across every document row, which
-- is an owner decision, not a migration's to make.
--
-- Single-quoted bodies, never dollar-quoted, and no dollar sign anywhere in
-- these statements — not even a regex end-of-string anchor, which is why the
-- DMY branch tests the value's SHAPE with translate() instead of using an
-- anchored pattern. This whole file is sent to the n8n Postgres node as ONE
-- multi-statement query, and pg-promise reads that character as its own
-- variable syntax. See the file header and 01_platform.sql:46.
-- ===========================================================================
alter table incoming_documents add column if not exists "doc_date_norm" timestamptz;

create or replace function public.incdoc_doc_date_norm(raw text) returns timestamptz as
$fn$declare
   s     text := btrim(coalesce(raw, ''));
   t     text;
   parts text[];
   d int; m int; y int; eom int;
 begin
   if s = '' then return null; end if;
   t := replace(s, '.', '/');
   if s ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' then
     y := substr(s, 1, 4)::int; m := substr(s, 6, 2)::int; d := substr(s, 9, 2)::int;
   elsif translate(t, '0123456789', '') = '//' then
     -- exactly two separators and nothing but digits besides them; the length
     -- test is what rejects `2026/08/10` (4-digit first field) the same way
     -- `_month_key_of`'s anchored DMY pattern does.
     parts := string_to_array(t, '/');
     if length(parts[1]) between 1 and 2 and length(parts[2]) between 1 and 2
        and length(parts[3]) in (2, 4) then
       d := parts[1]::int; m := parts[2]::int;
       y := case when length(parts[3]) = 2 then 2000 + parts[3]::int
                 else parts[3]::int end;
     else
       return null;
     end if;
   else
     return null;
   end if;
   if y < 1990 or y > 2100 or m < 1 or m > 12 or d < 1 then return null; end if;
   -- last day of that month, so 31/02 and 35/09 are NULL instead of rolling over
   -- into March / October the way to_date() would silently do.
   eom := extract(day from (make_date(y, m, 1) + interval '1 month'
                                               - interval '1 day'))::int;
   if d > eom then return null; end if;
   return make_date(y, m, d)::timestamp at time zone 'UTC';
 end;$fn$ language plpgsql immutable;

create or replace function public.incdoc_sync_doc_date_norm() returns trigger as
$fn$begin
   new."doc_date_norm" := public.incdoc_doc_date_norm(new."DOC_DATE");
   return new; end;$fn$ language plpgsql;

drop trigger if exists trg_incdoc_doc_date_norm on incoming_documents;

-- INSERT **OR UPDATE**, unconditionally: that is what keeps the column derived
-- even though it is writable (see the merge-writer note above).
create trigger trg_incdoc_doc_date_norm before insert or update on incoming_documents
  for each row execute function public.incdoc_sync_doc_date_norm();

-- Same reason as the three indexes above: an offered `basis` without an index is
-- a sequential scan wearing a dropdown.
create index if not exists incoming_documents_doc_date_norm
  on incoming_documents ("doc_date_norm");


-- trusted suppliers (2nd sheet tab gid 663229729) — TRUSTED_SUPPLIER certainty=100 override
create table if not exists trusted_suppliers (
  "id" bigint generated always as identity primary key,
  "COMPANY_ID" TEXT, "SOURCE_TYPE" TEXT, "extra" JSONB default '{}'::jsonb,
  "created_at" timestamptz default now());

create index if not exists trusted_suppliers_company on trusted_suppliers ("COMPANY_ID");


-- companies / settings / app_logs (sheet-tab replacements)
create table if not exists companies (
  "id" bigint generated always as identity primary key,
  "שם חברה" TEXT, "מזהה 1" TEXT, "מזהה 2" TEXT, "שם ספק מפריוריטי" TEXT,
  "מייל 1" TEXT, "מייל 2" TEXT, "הוראות לAI לחילוץ דוח גיול" TEXT,
  "extra" JSONB default '{}'::jsonb, "created_at" timestamptz default now());

-- tag_rules: RETIRED 2026-09-03 (owner Decision N1). The label rules have one store, the mail app's
-- organizer settings; the sync main, the feedback action and the harness read it over HTTP. Existing
-- tenants keep the rows as tag_rules_retired_20260903 (scripts/ops/migrations/2026-09-03_retire_tag_rules.sql).
create table if not exists settings (
  "key" TEXT primary key, "value" TEXT, "updated_at" timestamptz default now());

drop trigger if exists trg_incdoc_touch on incoming_documents;

create trigger trg_incdoc_touch before update on incoming_documents
  for each row execute function public.touch_updated_at();

-- (the 'drive' storage bucket is ensured by the indox-v2 Test Fixtures workflow —
--  a dollar-quoted DO block here would break the n8n postgres driver, and at initdb
--  time the storage schema does not exist yet anyway)

-- columns added live over time — codified so a fresh machine matches (2026-07-07 audit)
-- 2026-08-21, owner order: ACTION_LOG was DROPPED. It held each document's whole history as
-- one comma-separated string (20 MB of a 180 MB table, 535 bytes on the average row, paid again
-- on every GET and every executeWorkflow hop). Everything the state machine derived from it now
-- has a direct answer: dispatch history in indox_action_execution_log, step budget in
-- ITERATION_COUNT, and the last two log-only gates in GMAIL_LABELS_COMPLETED /
-- FAILED_FOLDER_COMPLETED. Archive of the column as it stood: _actionlog_backup_20260820.
-- Migration: scripts/ops/migrations/2026-08-21_drop_action_log.sql

alter table incoming_documents add column if not exists "ERROR" TEXT;

alter table incoming_documents add column if not exists "ITERATION_COUNT" integer;

alter table incoming_documents add column if not exists "RETRY_COUNT" integer default 0;

alter table incoming_documents add column if not exists "NEXT_RETRY_AT" timestamptz;

alter table incoming_documents add column if not exists "SYNC_NAME" TEXT;


-- THUMBNAIL (owner request, 2026-08-05): a private drive-engine link to a jpg preview
-- of the document, for the frontend's card view. Same *_COMPLETED convention as every
-- other state-machine step (SEARCH_IN_DRIVE_COMPLETED, FIGURE_TYPE_COMPLETED, ...):
-- THUMBNAIL_COMPLETED is stamped whether or not a THUMBNAIL was actually produced (a
-- render/upload failure is a nicety failing soft, not a pipeline block) — so the step is
-- idempotent and terminal on the first attempt either way.
--
-- 2026-08-06 (owner request): there is no separate "generate_thumbnail" action and no
-- thumbnail sub-workflow. The preview is rendered inside indoxV2UploadApiTools01, in
-- parallel with the apitools OCR upload, and returned to indoxV2ActionsGlobal01's
-- figure_company_id action. Because that workflow short-circuits on an apitools
-- /docExists hash hit, a document whose bytes were already uploaded gets no THUMBNAIL
-- (17 of 5,775 uploaded rows had one on 2026-08-06) — a backfill is needed for the
-- existing corpus. See ai/context/lane-d-n8n-consolidation-2026-08-06.md.
alter table incoming_documents add column if not exists "THUMBNAIL" TEXT;

alter table incoming_documents add column if not exists "THUMBNAIL_COMPLETED" TEXT;


-- priority_sync (lowercase, boolean — NOT the TEXT PRIORITY_SYNC_COMPLETED/PRIORITY_SYNC_COUNT
-- columns above; a third, separate thing). Added directly to the live table at some point and
-- never codified here, so schema.sql was STALE against the running database: verified live
-- 2026-08-06, `information_schema.columns` reports 98 columns on incoming_documents and this was
-- the ONLY one absent from this file. A fresh install built from schema.sql alone therefore
-- lacked it entirely, which breaks two live writers on first use:
--   * core/diff.py::_apply_priority_sync — adds {"priority_sync": True} to EVERY STATUS /
--     REQUIRED_ACTION PATCH, including the operator "Retry" button (STATUS -> ACTION_RESTART).
--   * indoxV2ActionsGDoc01's "Build: Batch Update - priority_sync" node.
-- It is also already baked into indoxDataGateway01's generated KNOWN_FIELDS allow-list, so
-- codifying it here is additionally what keeps gen-gateway-trigger-schema.py --apply from
-- STRIPPING it out of that allow-list on the next regeneration. Declared at this position so
-- schema.sql's column order matches the live table's ordinal order exactly.
alter table incoming_documents add column if not exists "priority_sync" boolean;

alter table companies add column if not exists "TRUSTED_SOURCE_TYPES" TEXT;
-- SELECTION_CERTAINTY (owner Decision 5, 2026-09-02): a per-company FIXED certainty, 0-100.
-- SelectType01 scores a document max(computed corroboration, this value) when the document's
-- company carries one — the operator's "high-certainty suppliers", as a number on the row
-- (visible + editable in the companies editor). Migration for existing tenants:
-- scripts/ops/migrations/2026-09-02_selection_certainty.sql.
alter table companies add column if not exists "SELECTION_CERTAINTY" integer;


-- company id must be unique (dedup + ON CONFLICT upserts key on it; added live 2026-06,
-- codified here so a fresh machine gets it)
create unique index if not exists companies_mzhe1_uniq on companies ("מזהה 1");


-- AI extraction cache (invoice Gemini + BS lines): key = <kind>:<md5-of-file-bytes>
create table if not exists public.ai_extraction_cache (cache_key TEXT primary key);

alter table public.ai_extraction_cache add column if not exists kind TEXT;

alter table public.ai_extraction_cache add column if not exists value TEXT;

alter table public.ai_extraction_cache add column if not exists created_at timestamptz default now();


-- ============ sync-v3: reconciliation sync layer (ai/context/sync-v3-plan.md) ============
-- ledger: row exists <=> item delivered (or quarantined needs_review). NO pending rows, ever —
-- the live diff (source listing minus ledger) IS the todo list.
create table if not exists sync_ledger (
  source TEXT not null,
  platform_id TEXT not null,
  status TEXT not null,
  doc_id TEXT,
  content_hash TEXT,
  delivered_at timestamptz default now(),
  primary key (source, platform_id));
-- NOTE: claimed_at and instance are NOT declared here on purpose -- they are added further down
-- by `alter table sync_ledger add column if not exists ...` (see the claimed_at/STUCK note),
-- which is this file's idiom for a column introduced after the original table. A reader who greps
-- only the create-table block will conclude they are missing; they are not. I made exactly that
-- mistake on 2026-08-23 and reported a fresh-deploy breakage that did not exist.


-- The CLAIM (indox-final-plan phase 3). The comment above is no longer the whole truth: a ledger row
-- now means "delivered OR IN FLIGHT", distinguished by status. status='claimed' is written BEFORE
-- delivery and promoted to 'delivered' after, which is what finally makes `in_progress` a state the
-- system can occupy instead of a column that could only ever read zero.
--
-- It costs nothing in the diff: the anti-join subtracts any ledger row regardless of status, so a
-- claimed item is already excluded from the next pass — that IS the mutual exclusion, using the
-- existing primary key rather than a lock.
--
-- claimed_at is what makes STUCK computable (claim age vs the pipe's batch.timeout_min). A claim is
-- released on delivery failure so `sync_attempt` can retry it; a claim that outlives its timeout
-- therefore means the workflow died between claiming and either outcome — the genuine crash case,
-- and the only thing that should ever be shown as תקוע.
alter table sync_ledger add column if not exists claimed_at timestamptz;


-- Added here rather than in phase 6 so tenancy is a PRIMARY KEY change and not also a column
-- migration. Duplicating an INDOX gives the copy the same pipe names, so two instances would both
-- define `drive-gdoc` and — keyed on (source, platform_id) alone — would share ledger rows and read
-- each other's deliveries as already done. Nothing uses this column until phase 6; it exists so the
-- change that does is one statement.
alter table sync_ledger add column if not exists instance TEXT;

-- THE SYNC ITEM (owner Decision 1, 2026-09-02). A ledger row now exists from DISCOVERY, not from
-- delivery: status walks discovered -> claimed -> delivered | failed | needs_review, and "synced"
-- means status='delivered'. sync_attempt folded in (attempts/not_before/last_error live here);
-- `listing` carries the source's own metadata (md5, name, size, link, createdTime, sender, subject)
-- so a delivery never needs the live page again. Migration: scripts/ops/migrations/2026-09-02_sync_item.sql.
alter table sync_ledger add column if not exists discovered_at timestamptz not null default now();
alter table sync_ledger add column if not exists listing jsonb not null default '{}'::jsonb;
alter table sync_ledger add column if not exists attempts integer not null default 0;
alter table sync_ledger add column if not exists not_before timestamptz;
alter table sync_ledger add column if not exists last_error text;
create index if not exists idx_sync_ledger_pending on sync_ledger (source, status, not_before)
  where status in ('discovered', 'failed');

-- THE SYNC BOARD'S ONE READ (owner rule 2026-09-02: the sync UI is DB-only). Per pipe: counts by
-- status, when discovery/delivery last touched it, and the most recent error. The BFF reads this
-- view and nothing else for sync state — no mail/drive walk, no cached copy of one.
-- Migration for an existing tenant: scripts/ops/migrations/2026-09-02_sync_item_counts.sql.
create or replace view sync_item_counts as
select l.source,
       regexp_replace(l.source, '^[^/]*/', '')                      as pipe,
       max(l.instance)                                              as instance,
       count(*) filter (where l.status = 'discovered')::int        as discovered,
       count(*) filter (where l.status = 'claimed')::int           as claimed,
       count(*) filter (where l.status = 'delivered')::int         as delivered,
       count(*) filter (where l.status = 'failed')::int            as failed,
       count(*) filter (where l.status = 'needs_review')::int      as needs_review,
       count(*)::int                                                as total,
       max(l.discovered_at)                                         as last_discovered_at,
       max(l.delivered_at)                                          as last_delivered_at,
       max(l.claimed_at)                                            as last_claimed_at,
       (select e.last_error from sync_ledger e
         where e.source = l.source and e.last_error is not null
           and e.status in ('failed', 'needs_review')
         order by coalesce(e.not_before, e.discovered_at) desc limit 1) as last_error,
       -- the lag metric (sync best practice): age of the oldest item still owed, poison items
       -- (needs_review) excluded the way a queue excludes its dead-letter messages
       min(l.discovered_at) filter (where l.status in ('discovered', 'failed', 'claimed'))
                                                                    as oldest_waiting_at,
       count(*) filter (where l.status in ('discovered', 'failed', 'claimed'))::int
                                                                    as waiting
  from sync_ledger l
 group by l.source;

-- RETIRED 2026-09-02 (both dropped by the sync_item_counts migration): `sync_pipe_state` (run
-- journal — a pass is visible as the ledger's own timestamps now) and `sync_attempt` (folded into
-- sync_ledger.attempts/not_before/last_error by the sync_item migration).


-- discovery position (pure optimization — losing it = wasted list calls, never lost docs)
create table if not exists sync_cursor (
  source TEXT primary key,
  mode TEXT not null default 'walk',
  walk_token TEXT,
  steady_cursor TEXT,
  updated_at timestamptz default now());


-- P0a: content identity enforced by the DB. Delivery inserts use
-- ON CONFLICT ("HASH") WHERE <same predicate> DO NOTHING. Pre-flight audit 2026-07-09: 0 violations.
-- uq_incdoc_hash REMOVED 2026-08-17 (owner order): the dedup ACTION owns dedup; the table
-- must accept same-hash rows (find_link writes the found file hash and the duplicator
-- resolves later). Index dropped live the same day.


-- gmail label-engine rules (settings-centric label architecture)












-- ===========================================================================
-- TENANCY (indox-final-plan phase 6.2) — a discriminator column on the three
-- INDOX-owned config tables. Documents stay table-per-instance; these do not.
--
-- Why a column here and a table there, in one sentence each:
--   settings/companies         uniform shape, small, read on every request,
--                                 and already the grain a discriminator fits.
--   incoming_documents            84 columns that differ per client, a gsheet
--                                 backend with no concept of a discriminator,
--                                 per-client export/delete, and uq_incdoc_hash
--                                 whose dedupe semantics would have to change.
--
-- The DEFAULT is the existing instance name, which is what makes this rollout
-- additive rather than a cutover: every existing row acquires the right value
-- with no backfill, no downtime, and no window in which a reader sees nothing.
-- An n8n node that has not yet been converted keeps reading the default
-- instance — wrong only once a second instance exists, versus reading a table
-- that no longer exists, which is what schema-per-instance or a name prefix
-- would have done to all 112 SQL strings at push time.
--
-- NOTE: no `DO $$ ... $$` blocks — see the comment above about the n8n postgres
-- driver. The constraint swaps below are written drop-then-add precisely so
-- they are re-runnable without one.
-- ===========================================================================

alter table settings  add column if not exists instance TEXT not null default 'incoming-documents-main';

alter table companies add column if not exists instance TEXT not null default 'incoming-documents-main';


-- settings is keyed BY its key, so the key has to widen. Drop-then-add rather
-- than a conditional: re-running this file must be a no-op, and `if exists` on
-- the drop is what buys that without a DO block.
alter table settings drop constraint if exists settings_pkey;

alter table settings add constraint settings_pkey primary key ("instance", "key");

-- company id is unique PER INSTANCE, not globally. Two clients legitimately
-- have a supplier with the same מזהה; under the old global index the second
-- instance to see it would collide on upsert and silently take the first
-- instance's row.
drop index if exists companies_mzhe1_uniq;

create unique index if not exists companies_instance_mzhe1_uniq on companies ("instance", "מזהה 1");


create index if not exists settings_instance_idx on settings ("instance");


-- CONNECTION (indox-final-plan phase 7) — which platform connection a document
-- actually came from.
--
-- `platform_id` is unique only WITHIN a connection: file id `123` can exist in
-- both a local drive and a google drive, and both can legitimately feed one
-- INDOX table. Three things break quietly without this column — any dedupe or
-- join on platform_id alone, the meaning of LINK (which used to be an absolute
-- URL baked from whichever backend delivered the row, so the column meant
-- different things on different rows), and "open the original", which had no
-- way to know which drive it meant.
--
-- Nullable on purpose: rows written before phase 7 genuinely do not know, and a
-- default would assert an origin nobody recorded. `null` reads as "unknown",
-- which is the truth, and the link resolver falls back to the stored LINK for
-- exactly those rows.
alter table incoming_documents add column if not exists "CONNECTION" TEXT;

create index if not exists incdoc_connection_platform_idx
  on incoming_documents ("CONNECTION", "SOURCE_ID");


-- ===========================================================================
-- COLUMNS THE STATE MACHINE READS THAT THIS FILE NEVER CREATED
-- ---------------------------------------------------------------------------
-- [2026-08-21] Found by diffing every `doc.X` / `row.X` reference in the four
-- action blueprints and syncV3Deliver0001 against information_schema on the
-- running deployment: 43 distinct fields referenced, 8 of them not columns.
-- Two were transient (DOUBLE_CONTEXT and NEW_COMPANY_DOC_ID are set on the doc
-- object mid-pass and read downstream in the same pass); the six below are
-- genuinely persisted, and NOTHING created them. A fresh deploy runs this file
-- and got none of them.
--
-- LINK_CONNECTION is the severe one. The drive-connection guard of 2026-08-13
-- ("A LINK WE CANNOT OPEN IS A MISSING LINK") reads:
--
--     linkMissing = !doc.LINK || [...].includes(doc.LINK)
--                             || !String(doc.LINK_CONNECTION || '').trim()
--
-- in gdocDecide, shipmentDecide and bsDecide. On a deployment without the
-- column the field is permanently undefined, so EVERY linked document is
-- classified unopenable and routed to find_link / update_status_missing_link
-- instead of extraction. Measured on this box before the fix: 83 rows, 0 with
-- an API_TOOLS_ID -- nothing had ever been uploaded, because nothing could be
-- opened. It is written at ingest by syncV3Deliver0001 from the drive
-- connection id, and read in 30 places across the four action blueprints.
--
-- BS_LINK_DOCUMENTS_AT has a tracked one-off migration
-- (scripts/ops/migrations/2026-08-21_bs_relink_rounds.sql). BS_LINK_ROUND came from the same
-- migration and was DROPPED on 2026-08-23 (2026-08-23_drop_bs_link_round.sql) together with the
-- per-round link_documents action names it existed to feed. That migration is
-- applied by hand to an EXISTING database; this file is what a FRESH one gets,
-- so both need them and `if not exists` makes carrying them here harmless.
-- That divergence -- ops migrations advancing the live schema while the fixture
-- schema stays behind -- is how all six went missing. See
-- issues/schema-drift-fixture-vs-live.md.
alter table incoming_documents
  add column if not exists "LINK_CONNECTION"      TEXT,
  add column if not exists "SYNC_CONNECTION"      TEXT,
  add column if not exists "SOURCE_LIST"          jsonb,
  add column if not exists "OLD_REASON"           TEXT,
  add column if not exists "BS_LINK_DOCUMENTS_AT" timestamptz,
  add column if not exists "PRIORITY_SYNC_SIGNATURE" TEXT,
  -- [2026-08-23, owner] opt this line out of action_priority_sync; decide falls through to
  -- mark_completed. Set by the owner (BLOCKLIST_* reasons) and by the one-off backfill marking
  -- lines the previous deployment already delivered to the online Priority
  -- (2026-08-23_priority_skip.sql, reason 'synced in last version').
  add column if not exists "PRIORITY_SKIP"        boolean default false,
  add column if not exists "PRIORITY_SKIP_REASON" TEXT;

-- The link resolver and the drive guard both filter on it, and every document
-- carrying a link carries one.
create index if not exists incdoc_link_connection_idx
  on incoming_documents ("LINK_CONNECTION");


-- ===========================================================================
-- SOURCE_LIST MERGE FUNCTIONS
-- ---------------------------------------------------------------------------
-- [2026-08-22] The column fix above was half the story. `PG Bulk Upsert` -- the
-- one write path every document takes -- calls indox_merge_source_list, and on
-- a deployment provisioned from this file that function did not exist:
--
--   SyncProcGDoc0001 exec 73259, node 'PG Bulk Upsert'
--     function public.indox_merge_source_list(jsonb, jsonb) does not exist
--
-- so the upsert threw, no document row was ever created, the ledger's
-- `delivered` stayed 0, and ALL FIVE proc-* lanes of the sync_sources suite
-- failed with COMPANY_ID / TYPE / DOC_ID / STATUS null. One missing function,
-- five red lanes, and a failure that reads like an extraction problem.
--
-- Copied VERBATIM from scripts/ops/migrations/2026-08-21_source_list_append_only.sql,
-- which is tracked, correct, and applied by hand to an EXISTING database. This
-- file is what a FRESH one gets. Same divergence as the six columns above --
-- ops migrations advance the live schema while the fixture schema stays behind,
-- and nothing compares the two. See issues/schema-drift-fixture-vs-live.md; the
-- gate proposed there must cover FUNCTIONS as well as columns, which is the
-- lesson of this one.
--
-- CREATE OR REPLACE, so re-running over a database the migration already
-- touched replaces the definition with an identical one.
CREATE OR REPLACE FUNCTION public.indox_source_key(el jsonb)
RETURNS text
LANGUAGE sql IMMUTABLE
AS $fn$
  SELECT COALESCE(el->>'source_kind', '') || '|' ||
         COALESCE(el->>'file_id', el->>'message_id', '') || '|' ||
         COALESCE(el->>'doc_row_id', '')
$fn$;

CREATE OR REPLACE FUNCTION public.indox_merge_source_list(cur jsonb, inc jsonb)
RETURNS jsonb
LANGUAGE sql IMMUTABLE
AS $fn$
  SELECT CASE
    -- A caller that sends nothing must not blank the column.
    WHEN inc IS NULL OR jsonb_typeof(inc) <> 'array' THEN cur
    -- Nothing to merge into: take the incoming array as-is.
    WHEN cur IS NULL OR jsonb_typeof(cur) <> 'array' OR jsonb_array_length(cur) = 0 THEN inc
    ELSE (
      WITH c AS (
        SELECT e AS el, ord FROM jsonb_array_elements(cur) WITH ORDINALITY t(e, ord)
      ), i AS (
        SELECT e AS el, ord FROM jsonb_array_elements(inc) WITH ORDINALITY t(e, ord)
      ), kept AS (
        -- existing elements, in their existing order, patched where the incoming array names them
        SELECT c.ord, CASE WHEN m.el IS NULL THEN c.el ELSE c.el || m.el END AS el
          FROM c
          LEFT JOIN LATERAL (
            SELECT i.el FROM i
             WHERE public.indox_source_key(i.el) = public.indox_source_key(c.el)
             ORDER BY i.ord LIMIT 1) m ON true
      ), appended AS (
        -- incoming elements naming a source this row does not have yet, in incoming order
        SELECT i.el, i.ord FROM i
         WHERE NOT EXISTS (
           SELECT 1 FROM c WHERE public.indox_source_key(c.el) = public.indox_source_key(i.el))
      )
      SELECT COALESCE((SELECT jsonb_agg(el ORDER BY ord) FROM kept),     '[]'::jsonb)
          || COALESCE((SELECT jsonb_agg(el ORDER BY ord) FROM appended), '[]'::jsonb)
    )
  END
$fn$;


-- ===========================================================================
-- LEDGER NAMESPACING (indox-final-plan phase 6b) — the sharpest constraint in
-- the whole tenancy design, and the one that cannot be fixed after the fact.
--
-- `sync_ledger` is keyed (source, platform_id) where `source` is the PIPE NAME.
-- Duplicating an INDOX gives the second instance a pipe called `drive-gdoc`
-- too — that is what duplication MEANS. Both instances would then share ledger
-- rows, and each would read the other's deliveries as already-done: instance B
-- never receives a document because instance A delivered "it". Silently, and
-- with every count on both boards looking correct.
--
-- The instance therefore has to be part of that key. It is added by namespacing
-- the name — `<instance>/<pipe>` — rather than by widening the primary key,
-- because `source` is already the discriminator these three tables are built
-- around: sync_cursor is keyed on it alone, sync_attempt shares the same pair.
-- One namespaced string keeps all three consistent with no DDL and no second
-- concept to keep in step.
--
-- The one-time migration below is NOT optional and NOT cosmetic. `source` is a
-- primary key component, so leaving old rows un-namespaced while the engine
-- starts writing namespaced ones orphans every existing ledger row — and an
-- orphaned ledger row means the diff stops subtracting that document, which
-- means the entire source is delivered a second time. That is precisely the
-- catastrophic-rename failure the plan flags in §5; doing it here, once,
-- deliberately, and in the same commit as the engine change, is what stops it
-- happening by accident later.
--
-- Idempotent by construction: the predicate excludes anything already
-- containing '/', so re-running is a no-op rather than a double prefix.
-- ===========================================================================

-- COLLISION-SAFE, because this file is re-applied on every fixture setup rather than run once.
-- A plain row whose namespaced twin already exists is a leftover from before the rename (or from a
-- suite that wrote directly to the kernel under its own short name, which the suites legitimately
-- do). Renaming it onto the twin violates the primary key and takes the whole fixture step down —
-- which is exactly how this was found: `Ensure Schema` died on
-- (incoming-documents-main/sv3f_chaos, sv3f_ch_bad1). The twin is authoritative, so the stale plain
-- row is dropped rather than merged: keeping it would mean two ledger rows for one delivery.
delete from sync_ledger a
 where a.source not like '%/%'
   and exists (select 1 from sync_ledger b
                where b.source = 'incoming-documents-main/' || a.source
                  and b.platform_id = a.platform_id);

delete from sync_cursor a
 where a.source not like '%/%'
   and exists (select 1 from sync_cursor b
                where b.source = 'incoming-documents-main/' || a.source);

update sync_ledger  set source = 'incoming-documents-main/' || source where source not like '%/%';

update sync_cursor  set source = 'incoming-documents-main/' || source where source not like '%/%';



-- ===========================================================================
-- LIVE RUN STATE — so "הרץ הכל" can show progress instead of a spinner.
--
-- A run used to be invisible while it happened: the BFF POSTed to the manage
-- webhook and blocked for up to two minutes, and the only thing on screen was
-- a disabled button. The operator could not tell a slow run from a hung one,
-- and when it finished there was no way back to the execution that produced
-- the number.
--
-- The obvious fix — poll n8n for execution status — is the wrong one here.
-- INDOX is deliberately NOT coupled to n8n's database or API (see
-- apps/indox/docker-compose.yml: "N8N_DB_DSN intentionally NOT set"), and
-- buying a progress bar with that coupling would be a bad trade: it makes the
-- documents app depend on the automation engine's credentials forever.
--
-- So the ENGINE reports its own progress, into the table that already exists
-- for per-pipe run state. It stamps `execution_id` when the pass STARTS, which
-- is what lets the UI offer "open in n8n" while the run is still going rather
-- than only after it returns, and updates the counters as it goes. Progress is
-- then derived from the work actually done — units planned vs units finished —
-- which is a truer thing to show than n8n's own node-level progress anyway.
--
-- `run_status` is the only field the UI polls on:
--   'running' | 'ok' | 'error' | 'skipped'
--
-- 'skipped' was added 2026-08-06 (tasks #66/#69) and is the whole lesson of this table in one
-- word. Three values could not hold what actually happens: a pass that never started, because
-- another reconcile pass still held the mutex, is not 'ok' and is not 'error' — and this
-- deployment's passes fill 848–1223s of their own 900s cycle, so the lock is held nearly all the
-- time and this is the COMMON outcome of pressing the run button, not an edge case. Written as
-- 'ok' it drew a finished green bar for a run that never began; written as 'error' it sent two
-- debugging sessions after a pipeline that was working. Deliberately NOT a CHECK constraint: this
-- column is written by n8n (SyncApi0000000001's `Mark Run End`) and read by the SPA, and a
-- constraint here would turn a future fourth state into a failed UPDATE inside a workflow rather
-- than an unknown word in a UI — the UI degrades to "הסתיים", the workflow would not.
-- ===========================================================================

-- [2026-09-02] The sync_pipe_state run journal the block above describes was RETIRED with the
-- sync item: a pass is visible as sync_ledger's own timestamps (sync_item_counts view), and the
-- manage door reports ran / skipped / error per request. Dropped by 2026-09-02_sync_item_counts.sql.


-- ===========================================================================
-- EXTRACTION REFACTOR — Phase 1/2, additive only (ai/context/EXTRACTION-REFACTOR-PLAN.md).
--
-- Nothing here is renamed or dropped, and no existing writer is touched. This
-- lays the groundwork for a later cutover (§3 Phase 5 of the plan): every
-- extraction step will do BOTH an AI pass and a local pass, writing AI_<F> and
-- LOCAL_<F> side by side, and a later shared selection step will pick a winner
-- into the plain bare column (already the writer of that field today, unchanged
-- for now). Until that selection step lands, these columns just sit empty.
--
-- LOCAL_* mirrors the existing AI_* set exactly (plan §2.2) — same 7 fields,
-- same suffix shape, so the pairing (AI_X / LOCAL_X / X) stays obvious at a
-- glance. AI_EXTRACTION_COMPLETED is a completion flag, not a value field, so
-- it has no LOCAL_ counterpart.
-- ===========================================================================
alter table incoming_documents add column if not exists "LOCAL_COMPANY_ID" TEXT;

alter table incoming_documents add column if not exists "LOCAL_TYPE" TEXT;

alter table incoming_documents add column if not exists "LOCAL_DOC_ID" TEXT;

alter table incoming_documents add column if not exists "LOCAL_DOC_DATE" TEXT;

alter table incoming_documents add column if not exists "LOCAL_DOC_AMOUNT" TEXT;

alter table incoming_documents add column if not exists "LOCAL_SHIPMENT_IDS" TEXT;

alter table incoming_documents add column if not exists "LOCAL_ORDER_IDS" TEXT;

-- DOC_ID — the new consolidated canonical identifier column (plan §2.2b). This
-- phase only ADDS the column; COMPANY_DOC_ID/INVOICE_ID are neither renamed nor
-- dropped, and no writer is repointed at DOC_ID yet — that dual-write step and
-- the backfill are later, separately-sequenced work per the plan.
alter table incoming_documents add column if not exists "DOC_ID" TEXT;

-- LINKED_INVOICE_ID — owner ruling 2026-08-06, after live measurement showed that
-- COMPANY_DOC_ID and INVOICE_ID are NOT two names for one value:
--
--     TYPE           both populated   agree   disagree
--     INVOICE                  3259    2955        304   (9.3%)
--     SHIPMENT                  212       1        211   (99.5%)  <-- structural
--
-- On INVOICE rows the pair is one identifier in two normalisations (COMPANY_DOC_ID
-- punctuation-stripped, INVOICE_ID raw) and collapsing them is lossless. On SHIPMENT
-- rows they are two DIFFERENT documents: COMPANY_DOC_ID is the shipment's own id and
-- INVOICE_ID is the id of the invoice it is linked to. A blanket merge into DOC_ID
-- would have destroyed that link on ~211 live rows.
--
-- The ruling: DOC_ID always means "this document's OWN id", for every type. The
-- shipment->invoice pointer moves out to this explicitly-named column instead of
-- hiding inside a general-purpose id field. INV_ID_FOR_SHIP (305 populated) already
-- encodes the same relationship from the invoice side and should be reconciled with
-- this column before either is dropped -- see scripts/ops/indox-column-consolidation.sql §2.
--
-- Additive only in this phase: nothing writes it yet, and COMPANY_DOC_ID/INVOICE_ID
-- are neither renamed nor dropped.
alter table incoming_documents add column if not exists "LINKED_INVOICE_ID" TEXT;

-- FROM_WAREHOUSE / FROM_WAREHOUSE_CHECK (plan §2.8, owner-ruled rename target for
-- FROM_OFFICE/FROM_OFFICE_CHECK — "office" was always wrong: these documents come
-- from the WAREHOUSE where goods are physically received, never from an office).
-- Additive only in this phase: FROM_OFFICE/FROM_OFFICE_CHECK keep being the only
-- columns any workflow actually writes/reads until the dual-write phase lands.
alter table incoming_documents add column if not exists "FROM_WAREHOUSE" TEXT;

alter table incoming_documents add column if not exists "FROM_WAREHOUSE_CHECK" TEXT;

-- FROM_OFFICE <-> FROM_WAREHOUSE mirror, for the duration of the dual-write window.
-- scripts/ops/indox-column-consolidation.sql §5 states the problem: "Because NO writer has been
-- repointed yet, these numbers WILL drift apart again after each backfill." A one-time backfill
-- (scripts/ops/migrations/2026-08-06_from_office_to_warehouse_backfill.sql, 5,756 rows) fixes only
-- the rows that existed when it ran; every document ingested afterwards is written with
-- FROM_OFFICE alone and leaves FROM_WAREHOUSE NULL again. These two triggers are what makes the
-- backfill hold, and what makes it survive a fresh clone rather than needing a re-run.
--
-- SYMMETRIC on purpose, so it is correct on BOTH sides of the pending rename
-- (scripts/ops/rename-from-office-to-warehouse.py): today's writers set FROM_OFFICE and
-- FROM_WAREHOUSE follows; after the rename + `bbox n8n push` they set FROM_WAREHOUSE and
-- FROM_OFFICE follows, so readers not yet repointed keep working. On UPDATE a side is mirrored
-- only when the OTHER side changed and this one did not — a statement that genuinely changes both
-- to different values is stored verbatim and the mirror stands down.
--
-- Verified live 2026-08-06 in a rolled-back transaction against the real writer shapes:
-- INSERT..ON CONFLICT DO UPDATE naming only FROM_OFFICE (today) and only FROM_WAREHOUSE
-- (post-rename) each propagate to the other spelling, for both the value and the _CHECK column.
--
-- RETIRE these together with FROM_OFFICE/FROM_OFFICE_CHECK in the final phase of §4.
-- Single-quoted bodies, never dollar-quoted — see the file header and 01_platform.sql:46.
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

drop trigger if exists trg_incdoc_mirror_warehouse_ins on incoming_documents;

create trigger trg_incdoc_mirror_warehouse_ins before insert on incoming_documents
  for each row execute function public.incdoc_mirror_from_warehouse_ins();

drop trigger if exists trg_incdoc_mirror_warehouse_upd on incoming_documents;

create trigger trg_incdoc_mirror_warehouse_upd before update on incoming_documents
  for each row execute function public.incdoc_mirror_from_warehouse_upd();


-- 2026-08-21: incdoc_action_log_append() and trg_incdoc_action_log_append REMOVED with the
-- ACTION_LOG column. The trigger existed (migration 2026-08-10) because ~40 router 'Build:'
-- nodes rebuilt the row without carrying the column forward and wrote '' over it, erasing loop
-- breakers stored inside the string -- 322 of 380 documents in the retry cohort looped forever
-- on a 2-character log. A breaker kept in a column other writers wipe is not a breaker, so the
-- append-only invariant was enforced below every writer instead of in ~40 nodes. With the column
-- gone the whole class of bug goes with it: the facts those breakers encoded are columns now.


-- Extraction-refactor completion/audit columns (2026-08-06). PER_TYPE_EXTRACTION_COMPLETED
-- is load-bearing: invoiceDecide/shipmentDecide in indoxV2ActionsGDoc01/Ship01 gate the
-- new 'extract_per_type' action on `!doc.PER_TYPE_EXTRACTION_COMPLETED` — without this
-- column declared on the write path, the flag would never persist and the action would
-- re-fire every driver sweep. BASE_EXTRACTION_COMPLETED is EQUALLY load-bearing: docBaseDecide
-- (indoxV2ActionsGlobal01, "Decide DOC BASE Action") gates 'extract_base_doc' on
-- `if (doc.LINK && !doc.BASE_EXTRACTION_COMPLETED)` ahead of every other docBase branch.
--   This comment previously said "audit-only today (not read by any decide function)". That was
--   stale, and on 2026-08-06 it nearly got the working gate "fixed" into the exact runaway the
--   PER_TYPE sentence above warns about: a lane read it, concluded the flag was never read and
--   the column absent, and proposed correcting a defect that did not exist. Measured at the time:
--   the column exists (text), 92 rows carry 'true', it is in indoxDataGateway01's KNOWN_FIELDS
--   (103 fields), and ACTION_LOG shows 'Extract Base Doc' exactly ONCE per document — i.e. the
--   flag persists and the gate closes. A stale comment that contradicts live code is as
--   dangerous as a stale test: both are read as evidence. Re-verify before editing this block.
-- SELECTION_DEBUG_BASE/SELECTION_DEBUG_PERTYPE are audit
-- text only (which source won each field), never read for control flow.
alter table incoming_documents add column if not exists "BASE_EXTRACTION_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "PER_TYPE_EXTRACTION_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "SELECTION_DEBUG_BASE" TEXT;

alter table incoming_documents add column if not exists "SELECTION_DEBUG_PERTYPE" TEXT;


-- Selection is its own step (2026-08-25, owner order). Extraction depends only on the document
-- and writes only its engine's versions (LOCAL_*/AI_*); SelectBase01 and SelectType01 read the
-- whole row -- every version plus the filename, the source and the supplier's ledger line -- and
-- decide the final unprefixed value. Two flags per point, on the same value+flag pattern every
-- other stage uses: the flag says the step ran, the hash says what it ran ON.
--   BASE_SELECTION_COMPLETED  -- its own column rather than reusing SELECTION_COMPLETED, which is
--     the PER-TYPE flag and is live in the pickup's fairness slices (indoxApi01).
--   *_SELECTION_HASH / SELECTION_VALUES_HASH -- the inputs the decision was made from. When a
--     version changes later (an aging report links and writes BS_LINE_*), the live hash stops
--     matching the stored one and decide re-dispatches the selection: no file, no model, pure
--     re-decision over columns the row already holds. This is what makes a late ledger line
--     reach the ERP instead of dying on a COMPLETED document.
alter table incoming_documents add column if not exists "BASE_SELECTION_COMPLETED" TEXT;

alter table incoming_documents add column if not exists "BASE_SELECTION_HASH" TEXT;


-- bs_extracted_lines — per-line child table for balance-sheet transaction rows
-- (plan §2.2a). BS has two different things, not one: a document-level summary
-- (date/total — already covered by the universal DOC_DATE/TOTAL_AMOUNT columns
-- every doc type gets, so no new document-level column is needed for that), and
-- N transaction lines per document, which is why THIS is a child table rather
-- than more columns on incoming_documents. Same AI/LOCAL/bare triad as every
-- other field in this refactor, just applied per line instead of per document —
-- the owner's ruling was explicit that BS must follow the same pattern, not a
-- special-cased one, so that local extraction can be added for BS later without
-- redesigning this table. Additive only: the legacy BS_EXTRACTED_LINES JSON
-- column on incoming_documents is untouched and still the only thing any
-- workflow writes/reads today; nothing backfills into this table yet.
create table if not exists bs_extracted_lines (
  "id" bigint generated always as identity primary key,
  "document_id" TEXT not null references incoming_documents("ID"),
  "line_index" integer not null,
  "AI_DATE" TEXT, "LOCAL_DATE" TEXT, "DATE" TEXT,
  "AI_AMOUNT" TEXT, "LOCAL_AMOUNT" TEXT, "AMOUNT" TEXT,
  "AI_NOTE" TEXT, "LOCAL_NOTE" TEXT, "NOTE" TEXT,
  "created_at" timestamptz default now());

create index if not exists bs_extracted_lines_doc on bs_extracted_lines ("document_id");


-- MERGED_INTO / ALSO_SEEN_AS — resolve_double merge linkage (final-indox.md CHANGE 3,
-- 2026-08-06). A merge NEVER deletes. The losing row keeps every provenance column
-- (SOURCE_TYPE/SOURCE_ID/SOURCE_LINK/HASH/LINK/CONNECTION/SYNC_NAME/SIZE) so every
-- existing join stays intact — sync_ledger.doc_id points at it, the sync board joins
-- items on (CONNECTION, SOURCE_ID), and the Drive-file match parses the file id out of
-- LINK. The loser gets STATUS='MERGED' plus MERGED_INTO = the surviving row's ID; the
-- winner gains ALSO_SEEN_AS, a JSON array of loser IDs, so "this document also arrived
-- as ..." renders without a table scan. Reversal = clear MERGED_INTO + restore STATUS;
-- nothing is destroyed by construction. Writers: the MERGE branch in indoxApiSupabase01
-- (the one writer) and scripts/ops/migrations/2026-08-06_resolve_double_backfill_t1_t2.sql
-- (the backfill, backup-first). MERGED rows are tombstones: 'Determine Action'
-- (indoxV2Decide01) excludes them from every identity map, and docBaseDecide returns
-- 'no_action_merged' before any other branch can touch them.
alter table incoming_documents add column if not exists "MERGED_INTO" TEXT;

alter table incoming_documents add column if not exists "ALSO_SEEN_AS" TEXT;

-- [schema drift 2026-08-23] MERGE PROVENANCE. These four exist on the live database and were in
-- NEITHER this schema NOR any migration -- they were applied by hand, so a freshly provisioned
-- deployment had no way to obtain them at all. Found by scripts/ops/lint_schema_columns_vs_live.py,
-- which builds a database from this file and diffs its columns against the live one.
--
-- They are not decorative. The comment above says "Reversal = clear MERGED_INTO + restore STATUS"
-- and STATUS_BEFORE_MERGE is what "restore STATUS" reads: on 2026-08-22 it is how 54 merges that
-- had absorbed a COMPLETED row into a lesser survivor were reverted, and on 2026-08-23 it is the
-- named reversal path for the merges the owner is still deciding about. Without these columns a
-- merge on a new deployment is IRREVERSIBLE, and the adjudicator writes to them unconditionally.
--   STATUS_BEFORE_MERGE  the loser's status at merge time -- the only record of what to restore
--   MERGED_AT            when, so a cascade (a survivor demoted later) can be told from a bad merge
--   MERGE_BATCH_ID       which adjudication did it, so one batch can be reverted without the rest
--   DUP_CAUSE            why the group was a duplicate; the ranked defect list behind the backlog
alter table incoming_documents add column if not exists "STATUS_BEFORE_MERGE" TEXT;
alter table incoming_documents add column if not exists "MERGED_AT" timestamptz;
alter table incoming_documents add column if not exists "MERGE_BATCH_ID" uuid;
alter table incoming_documents add column if not exists "DUP_CAUSE" TEXT;


-- ─────────────────────────────────────────────────────────────────────────────
-- company_registry — THE one definition of "what the company option lists are"
-- ─────────────────────────────────────────────────────────────────────────────
-- Company identification is a keyed lookup against the companies TABLE. Before
-- this view there were three separate answers to "what identifiers exist":
--   1. `Load V3 Config` (JQExV3* extractors) — distinct 9-digit מזהה 1/2 only.
--   2. the `Companies` code node in indoxSettings01 — all three identifier
--      columns, with the 'פריוריטי' blacklist, as `all_companies_identifiers`.
--   3. the two `fallbacks` frozen into the q_v3_company settings row — a
--      hand-copied whitelist of 57 names + a 57-entry option_map, i.e. 4.8% of
--      the 1,183 companies the tenant actually has, going stale the moment a
--      company is added.
-- Three definitions cannot agree, and (3) cannot be maintained at all. This view
-- replaces all three: every consumer selects the SAME four arrays from here, and
-- a company added to the table is in the extraction queries on the next run with
-- no edit anywhere. This is the SQL equivalent of the gsheet formula that used to
-- pull the companies tab into the extraction queries.
--
-- The four arrays, and why each exists (they map 1:1 onto the match_mode the
-- consuming query uses — see apps/apitools/src/ocr_core/ocr_json_query.py):
--   registry_ids    9-digit tax ids only → match_mode "id" (exact, positional).
--                   Deliberately the same set `Load V3 Config` built before, so
--                   the q_v3_company PRIMARY is byte-for-byte unchanged.
--   registry_idents every identifier, including the Priority supplier names →
--                   match_mode "id" again, as the first fallback: exact
--                   whitespace-insensitive substring, ranked by position in the
--                   document so the ISSUER's letterhead wins over a second id.
--   registry_names  the non-9-digit identifiers (Priority supplier names) →
--                   match_mode "name_substring", which is punctuation- and
--                   ktiv-insensitive, for letterheads that carry a name but no id.
--   registry_name_map  name → that company's primary identifier, so a name match
--                   returns a COMPANY_ID and not a name (query key "option_map").
--
-- Identifier semantics are copied EXACTLY from the `Companies` node so this view
-- is a drop-in for `all_companies_identifiers`: the three identifier columns in
-- column order, blank/NULL dropped, any value containing 'פריוריטי' dropped (the
-- sheet uses that word as a placeholder, not a supplier), and the company's
-- "primary" identifier is the first surviving one in that same order.
-- [cutover 2026-08-31] TENANT-LOCAL, no longer `public.`. These used to be declared as shared
-- public views, which forced apply-schema to STRIP them (an apply under search_path=<tenant>
-- would have silently repointed the shared copy at whichever tenant ran last), which in turn
-- left every fresh tenant WITHOUT them — the hand-made indox_hacohen copies were the only
-- reason extraction worked. Unqualified, each tenant gets its own copy bound to its own tables
-- by the apply preamble's search_path, which is exactly what the hand-made copies were.
create or replace view company_registry as
with ident as (
  select c.instance,
         c.id as company_row,
         v.ord,
         v.ident,
         c."שם חברה" as company_name
    from companies c
    cross join lateral (values (1, c."מזהה 1"), (2, c."מזהה 2"), (3, c."שם ספק מפריוריטי")) v(ord, ident)
   where v.ident is not null
     and btrim(v.ident) <> ''
     and position('פריוריטי' in v.ident) = 0
), primary_ident as (
  select distinct on (instance, company_row) instance, company_row, ident as primary_ident
    from ident order by instance, company_row, ord
)
select i.instance,
       coalesce(jsonb_agg(distinct i.ident) filter (where i.ident ~ '^[0-9]{9}$' and i.ord < 3),
                '[]'::jsonb) as registry_ids,
       coalesce(jsonb_agg(i.ident order by i.company_row, i.ord), '[]'::jsonb) as registry_idents,
       coalesce(jsonb_agg(i.ident order by i.company_row, i.ord)
                  filter (where i.ident !~ '^[0-9]{9}$'), '[]'::jsonb) as registry_names,
       coalesce(jsonb_object_agg(i.ident, p.primary_ident)
                  filter (where i.ident !~ '^[0-9]{9}$'), '{}'::jsonb) as registry_name_map,
       coalesce(jsonb_object_agg(i.ident, i.company_name)
                  filter (where i.company_name is not null), '{}'::jsonb) as company_name_by_ident,
       coalesce(jsonb_object_agg(i.ident, p.primary_ident), '{}'::jsonb) as primary_ident_by_ident
  from ident i
  join primary_ident p on p.instance = i.instance and p.company_row = i.company_row
 group by i.instance;


-- bind_registry — the ONE substitution of a "@registry_*" sentinel by its live
-- company-table value. A query may write the sentinel anywhere a literal
-- action_value/option_map would go, INCLUDING inside `fallbacks`; this walks the
-- whole tree and replaces it. Recursive, so nesting depth is not a limit.
-- An unknown "@..." string is left alone rather than nulled — a query that names
-- a sentinel that does not exist reaches apitools as the literal string, matches
-- nothing, and is caught by `Fan Fields`' bindRegistry assert in the extractors,
-- which throws instead of returning a silent-green "no company found".
create or replace function public.bind_registry(j jsonb, reg jsonb)
returns jsonb language plpgsql immutable as $bind$
declare
  out_j jsonb;
begin
  case jsonb_typeof(j)
    when 'string' then
      return coalesce(reg -> (j #>> '{}'), j);
    when 'array' then
      select coalesce(jsonb_agg(public.bind_registry(e, reg)), '[]'::jsonb)
        into out_j from jsonb_array_elements(j) e;
      return out_j;
    when 'object' then
      select coalesce(jsonb_object_agg(k, public.bind_registry(v, reg)), '{}'::jsonb)
        into out_j from jsonb_each(j) as t(k, v);
      return out_j;
    else
      return j;
  end case;
end
$bind$;


-- extraction_queries — what every consumer reads. One row per q_v3_* settings
-- key, with the company registry already bound in. This is the "excel formula
-- that pulls the companies tab into the extraction queries", expressed once, in
-- SQL: the settings row holds the SHAPE of the query and never a company list,
-- the companies table holds the companies, and this view is the only place the
-- two meet. Adding a company to the table changes the query on the next read,
-- with no workflow edit and no settings edit.
-- It is also the UI's preview surface: `select key, jsonb_pretty(query) from
-- public.extraction_queries` shows exactly what will be sent to apitools.
-- `resolver_gen` on each row is the identity of the RESOLVER that produced a
-- result: a short digest of the fully-bound query. It moves when the query shape
-- changes OR when the companies table changes, and not otherwise — which is
-- exactly the state-machine property "this document was judged against an older
-- resolver". docBaseDecide can therefore re-fire the company gate for a document
-- whose last attempt predates the current generation, without anyone editing a
-- row: a resolver improvement re-opens the gate by itself, each document retries
-- at most once per generation, and a document with genuinely no resolvable
-- company comes to rest again as soon as it has been judged by the current one.
-- [cutover 2026-08-31] TENANT-LOCAL, no longer `public.`. These used to be declared as shared
-- public views, which forced apply-schema to STRIP them (an apply under search_path=<tenant>
-- would have silently repointed the shared copy at whichever tenant ran last), which in turn
-- left every fresh tenant WITHOUT them — the hand-made indox_hacohen copies were the only
-- reason extraction worked. Unqualified, each tenant gets its own copy bound to its own tables
-- by the apply preamble's search_path, which is exactly what the hand-made copies were.
create or replace view extraction_queries as
select q.instance,
       q.key,
       q.query_template,
       q.query,
       left(md5(q.query::text), 8) as resolver_gen
  from (
    select s.instance,
           s.key,
           s.value::jsonb as query_template,
           public.bind_registry(
             s.value::jsonb,
             jsonb_build_object(
               '@registry_ids',         coalesce(r.registry_ids, '[]'::jsonb),
               '@registry_idents',      coalesce(r.registry_idents, '[]'::jsonb),
               '@registry_names',       coalesce(r.registry_names, '[]'::jsonb),
               '@registry_name_map',    coalesce(r.registry_name_map, '{}'::jsonb),
               '@registry_primary_map', coalesce(r.primary_ident_by_ident, '{}'::jsonb))) as query
      from settings s
      -- [cutover 2026-08-31] UNQUALIFIED, deliberately: this binds to THE TENANT's own
      -- company_registry (created above in this same apply, first on the search_path). The
      -- qualified `public.company_registry` that stood here bound every tenant's extraction
      -- queries to instance one's registry — measured: indox_test.extraction_queries joined
      -- public.company_registry, i.e. the test tenant's extraction read hacohen's companies.
      left join company_registry r on r.instance = s.instance
     where s.key like 'q\_v3\_%'
  ) q;

-- ── ACTION DISPATCH BRACKETS (live-created 2026-08-16; DDL here so a fresh machine
--    provisions it out of the box) ───────────────────────────────────────────────────────
-- The Action Router brackets every real dispatch with one row per (doc, action, execution):
-- Log Action Start INSERTs, Log Action End stamps ENDED_AT. A row without ENDED_AT is a
-- dispatch in flight (or one that died between the brackets). A second COMPLETED row for
-- the same (doc, action) with no ACTION_RESTART between them is a real double-run — the
-- dup monitor queries this table for exactly that signature.
create table if not exists indox_action_execution_log (
  "ID" text not null,
  "ACTION" text not null,
  "EXECUTION_ID" text not null,
  "NAME" text,
  "DOC_STATUS" text,
  "TRIGGER" text,
  "ORIGIN_EXECUTION" text,
  "STARTED_AT" timestamptz not null default now(),
  "ENDED_AT" timestamptz,
  -- [line-hash dup guard 2026-08-26] indox_line_hash() of the document AS IT STOOD when this
  -- dispatch opened. The guard calls a repeat a double ONLY when this equals the line's hash
  -- now; NULL (a dispatch that predates the rule, or one whose row vanished between decide and
  -- dispatch) can never block -- fail-open, both hashes must exist, exactly like the selection
  -- hashes. 'Log Action Start' writes it; 'Log Action End' never touches it.
  "LINE_HASH" text,
  primary key ("ID","ACTION","EXECUTION_ID"));
-- for a database created before 2026-08-26, when the table above already exists
alter table indox_action_execution_log
  add column if not exists "LINE_HASH" text;
create index if not exists idx_indox_ael_started
  on indox_action_execution_log ("STARTED_AT" desc);
-- [schema drift 2026-08-23] Added by scripts/ops/migrations/2026-08-20_action_history_index.sql
-- and missing here, so a freshly provisioned database never had it. ACTION_HISTORY is read as a
-- lateral "newest 10 per document" join by the double-action guard on every decide pass; without
-- this index that is a scan per document. The migration creates it CONCURRENTLY because it runs
-- against a live table; here the table is empty and CONCURRENTLY cannot run inside a transaction,
-- so it is created plainly. Same index, same columns, same order.
create index if not exists idx_indox_ael_id_started
  on indox_action_execution_log ("ID", "STARTED_AT" desc);


-- ===========================================================================
-- LOCAL PRIORITY MIRROR — a fresh database needs this table and view, or the
-- priorityLocalApi01 webhook errors on its first call and action_priority_sync
-- cannot be rehearsed at all. Kept in step with
-- scripts/ops/migrations/2026-08-22_priority_local_mirror.sql.
-- ===========================================================================
create table if not exists indox_priority_local (
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

comment on table indox_priority_local is
  'Local stand-in for the client Priority SHIM_RECEIVE_SUPDOC endpoint. APPEND-ONLY on purpose: '
  'the real endpoint creates a record per POST (proven: 72 duplicate business keys / 90 excess '
  'records in the client ERP, 2026-08-22), so a duplicate POST must show up here as two rows.';

create index if not exists indox_priority_local_key_idx
  on indox_priority_local ("IDSUP", "DOCNAME", "DATEDOC");
create index if not exists indox_priority_local_doc_idx
  on indox_priority_local ("INCOMING_DOC_ID");
-- [schema drift 2026-08-23] Both added by migrations and missing here; see
-- scripts/ops/lint_schema_drift.py, which now fails the build if a migration creates an object the
-- fixture schema lacks. A fresh deployment without these does not break, it just gets slow in two
-- specific places, which is the hardest kind of difference to attribute.
--   NOT added: idx_sync_ledger_created_at. Its migration
--   (2026-08-06_sync_ledger_created_at.sql) ALTERs in a `created_at` column and then indexes it,
--   and that column exists in NEITHER this schema NOR the live database -- the migration has
--   never been applied anywhere. Adding the index alone fails with 'column "created_at" does not
--   exist', which is how this was found. Applying an eighteen-day-old unapplied migration is a
--   decision, not a lint fix, so the drift is left visible instead.
--   from scripts/ops/migrations/2026-08-21_bs_relink_rounds.sql -- the partial predicate is part
--   of the index: the BS re-link EXISTS probe asks only about live rows that carry a real hash.
create index if not exists idx_incdoc_company_created_real
  on incoming_documents ("COMPANY_ID", created_at)
  where "STATUS" <> 'MERGED' and "HASH" is not null and "HASH" <> '';

create index if not exists indox_priority_local_received_idx
  on indox_priority_local (received_at desc);

-- THE ACCEPTANCE VIEW. Empty after a full run == no document was delivered twice.
-- [cutover 2026-08-31] TENANT-LOCAL, no longer `public.`. These used to be declared as shared
-- public views, which forced apply-schema to STRIP them (an apply under search_path=<tenant>
-- would have silently repointed the shared copy at whichever tenant ran last), which in turn
-- left every fresh tenant WITHOUT them — the hand-made indox_hacohen copies were the only
-- reason extraction worked. Unqualified, each tenant gets its own copy bound to its own tables
-- by the apply preamble's search_path, which is exactly what the hand-made copies were.
create or replace view v_indox_priority_local_dupes as
select "IDSUP", "DOCNAME", "DATEDOC",
       count(*)                              as records_created,
       count(*) - 1                          as excess_records,
       count(distinct "TOTPRICE")            as distinct_amounts,
       count(distinct "INCOMING_DOC_ID")     as distinct_source_rows,
       min(received_at)                      as first_post,
       max(received_at)                      as last_post,
       string_agg(distinct "INCOMING_DOC_ID", ' | ') as source_row_ids
from indox_priority_local
where coalesce("IDSUP",'') <> '' and coalesce("DOCNAME",'') <> ''
group by 1,2,3
having count(*) > 1;

-- Unqualified, like the view itself (tenant-local since the 2026-08-31 cutover). The stale
-- `public.` here made every FRESH apply die with "relation public.v_indox_priority_local_dupes
-- does not exist" — the view had just been created inside the tenant, not in public — so a
-- clean install never finished the schema (measured 2026-09-17, first run on a new machine).
comment on view v_indox_priority_local_dupes is
  'What the client ERP would hold after a local run. Empty = every document delivered exactly '
  'once. Non-empty rows are duplicates we would have shipped.';

-- ARCHIVE (official feature, 2026-08-24): cold storage for rows moved out of the live table via
-- the console (repo incoming-documents-archive). Structural twin of incoming_documents — LIKE at
-- apply time copies every column, default, PK and index built by the statements above, so this
-- MUST stay at the end of the file. Rows only enter/leave through the BFF archive/unarchive
-- endpoints (one transaction: insert + delete); no workflow reads or writes this table.
-- If a later migration adds a column to incoming_documents, add it here too — the BFF moves the
-- column INTERSECTION, so a missing column degrades to data loss on that field, not an error.
create table if not exists incoming_documents_archive
  (like incoming_documents including all);

alter table incoming_documents_archive
  add column if not exists archived_at timestamptz default now();

-- ── THE TWIN MIRRORS THE MAIN TABLE, STRUCTURALLY ────────────────────────────────────────────
-- `create table if not exists … (like incoming_documents including all)` clones ONCE. Every
-- column the main table gained afterwards was therefore absent from the twin — 8 of them by
-- 2026-08: ATTACHMENT_TEXT, SENDER, SEND_DATE, SYNC_REGISTRY_ID, COMPANY_BY_SENDER,
-- TYPE_BY_SOURCE, BASE_SELECTION_COMPLETED, BASE_SELECTION_HASH.
--
-- That was DATA LOSS, not cosmetics: the archive move copies BY NAME INTERSECTION, so archiving
-- a document silently dropped whatever the twin lacked. 15,366 rows were already archived that
-- way; this closes the hole going forward and cannot recover what those rows lost.
--
-- Mirroring is a loop rather than a list on purpose — a list is the same one-time clone with
-- extra steps, and would fall behind again on the next migration. `format_type` is used instead
-- of information_schema.data_type so a type modifier (numeric(10,2), varchar(50)) survives.
DO $mirror_archive$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT a.attname AS col, format_type(a.atttypid, a.atttypmod) AS typ
      FROM pg_attribute a
     WHERE a.attrelid = (current_schema() || '.incoming_documents')::regclass
       AND a.attnum > 0 AND NOT a.attisdropped
       AND NOT EXISTS (
             SELECT 1 FROM pg_attribute b
              WHERE b.attrelid = (current_schema() || '.incoming_documents_archive')::regclass
                AND b.attnum > 0 AND NOT b.attisdropped AND b.attname = a.attname)
  LOOP
    EXECUTE format('alter table incoming_documents_archive add column if not exists %I %s',
                   r.col, r.typ);
    RAISE NOTICE 'archive twin: added missing column %', r.col;
  END LOOP;
END
$mirror_archive$;


-- ── FOUR TABLES A REAL TENANT HAS AND THIS FILE DID NOT ──────────────────────────────────────
-- [2026-08-28, reported by the tenancy session] hacohen holds 17 tables; this fixture built 13.
-- The four below reached production through migrations and by hand and never came back here, so
-- a tenant provisioned from the fixture was missing tables indoxApi01 addresses — the exact
-- "fresh deploy is not compared to a migrated one" mechanism issues/schema-drift-fixture-vs-live.md
-- leaves open. Definitions taken from the live indox_hacohen, not reconstructed from memory.

-- The dedup audit trail. 10,184 rows on hacohen, and it was undeclared everywhere — found only
-- because ownership was traced by REFERENCE rather than by name prefix.
create table if not exists merge_audit (
  id                   bigserial primary key,
  batch_id             uuid        not null,
  dry_run              boolean     not null default true,
  merged_at            timestamptz not null default now(),
  action               text        not null,
  winner_id            text,
  loser_id             text,
  company_id           text,
  doc_key              text,
  tier                 text,
  reason               text,
  loser_status_before  text,
  loser_snapshot       jsonb,
  absorbed_fields      jsonb,
  conflicting_fields   jsonb,
  erp_synced_before    boolean,
  loser_api_tools_id   text,
  dup_cause            text
);
create index if not exists merge_audit_batch_idx  on merge_audit (batch_id);
create index if not exists merge_audit_winner_idx on merge_audit (winner_id);
create index if not exists merge_audit_loser_idx  on merge_audit (loser_id);
create index if not exists merge_audit_group_idx  on merge_audit (company_id, doc_key);

-- Settings audit trail. `settings` had NO updated_at trigger before 2026-08 — the column was set
-- once on insert and never maintained — so this table plus the trigger are what make a settings
-- change traceable at all.
create table if not exists settings_history (
  id          bigserial   primary key,
  instance    text        not null,
  key         text        not null,
  old_value   text,
  new_value   text,
  op          text        not null,
  changed_at  timestamptz not null default now(),
  db_user     text        not null default session_user,
  app_name    text                 default current_setting('application_name', true)
);
create index if not exists idx_settings_history_key on settings_history (instance, key, changed_at desc);

-- The two live aggregates the console reads. `dirty` is the recompute flag; a statement-level
-- trigger sets it (scripts/ops/dashboard-stats-schema.sql), which is why the table alone is not
-- the whole story — it is declared here so a fresh tenant HAS it, not so it self-populates.
-- [drift-gate catch, 2026-08-28] Found on the drift gate's FIRST run, and the history is worth
-- keeping: the owner added FILTER_REQUEST / FILTER_REQUES_REASON through the console, and
-- migration 2026-08-23_priority_skip.sql later renamed them to PRIORITY_SKIP /
-- PRIORITY_SKIP_REASON — but only on `incoming_documents`. `indox_priority_local` kept the ORIGINAL
-- names, and neither name ever reached this file. 5,919 rows have a FILTER_REQUEST value only
-- because it is NOT NULL DEFAULT false — it is true on ZERO of them, and the reason column is
-- non-null on zero. The live successor is PRIORITY_SKIP (true on 4,996 documents, 4,168 reasons),
-- so these two carry no signal; they are declared because they EXIST, not because they are wanted.
--
-- The missing T in `FILTER_REQUES_REASON` is preserved deliberately. It is spelled that way in
-- production, and a fixture that silently "fixes" a live column name builds a tenant that does not
-- match the one we run — the exact failure this file is being held to. Renaming is a migration
-- plus its callers, not a typo fix.
--
-- SCHEDULED FOR REMOVAL, not now. Ruled 2026-08-28 with the tenancy session: dropping them is a
-- migration with a blast radius, not a tidy-up — priorityLocalApi01 INSERTs into this table and
-- the columns are NOT NULL DEFAULT false, so the drop must be sequenced against a deploy of that
-- workflow. They go in the cleanup batch alongside the dead "סימון כרטסת עדכנית" column, whose
-- recipe is the same shape: drop the dependents and the column together, in ONE transaction.
alter table indox_priority_local add column if not exists "FILTER_REQUEST"       boolean not null default false;
alter table indox_priority_local add column if not exists "FILTER_REQUES_REASON" text;

create table if not exists indox_dashboard_stats (
  doc_table   text        primary key,
  payload     jsonb       not null default '{}'::jsonb,
  dirty       boolean     not null default true,
  updated_at  timestamptz not null default now(),
  error       text
);

-- [cutover 2026-08-31] THE DIRTY-MARKING MACHINERY LIVES HERE NOW, per tenant. It used to be
-- scripts/ops/dashboard-stats-schema.sql creating a public-only copy — which meant the read
-- model existed wherever someone had once run that file by hand and nowhere else (measured
-- 2026-08-24: present on the laptop, absent on the portable). The fixture is the one owner of
-- what a tenant contains, so the trigger ships with the tables it serves.
--
-- One function serves every tenant: the trigger fires on <tenant>.incoming_documents, so
-- TG_TABLE_SCHEMA names the tenant, and the insert targets THAT schema's stats row — never a
-- search_path guess at execution time (a trigger runs under the CALLER's search_path, which is
-- exactly how an unqualified insert here would have marked one tenant dirty for another's
-- write). Statement-level: a 500-row batch write costs ONE firing. Dollar-quote-free, matching
-- this file's convention.
create or replace function indox_mark_dashboard_stats_dirty() returns trigger
language plpgsql as
'begin
  execute format(
    ''insert into %I.indox_dashboard_stats (doc_table, dirty) values ($1, true) ''
    ''on conflict (doc_table) do update set dirty = true'', TG_TABLE_SCHEMA)
  using TG_TABLE_NAME;
  return null;
end;';

drop trigger if exists trg_stats_dirty on incoming_documents;
create trigger trg_stats_dirty
  after insert or update or delete on incoming_documents
  for each statement execute function indox_mark_dashboard_stats_dirty();

-- `indox_sync_stats` (the cached mail/drive walk behind the old sync board) was RETIRED 2026-09-02:
-- the board reads the `sync_item_counts` view (defined next to sync_ledger above) and the BFF makes
-- no cross-app call. Dropped for existing tenants by 2026-09-02_sync_item_counts.sql.


-- ── ROW-TYPE FUNCTIONS MUST BE DEFINED LAST ──────────────────────────────────────────────────
-- These four take `incoming_documents` as a COMPOSITE PARAMETER, so their bodies are compiled
-- against the table's row type AS IT STANDS AT CREATION TIME. Defined earlier in the file they
-- compile against a half-built table and fail with postgres's least helpful message —
-- `missing FROM-clause entry for table "d"` — because an attribute lookup on a composite that
-- lacks the attribute is reported as if `d` were a missing table.
--
-- That was latent for as long as nobody could provision from nothing: `indox_priority_signature`
-- sat at line 822 reading d."DOC_ID", which this file does not add until line 1092. It surfaced
-- the moment the schema became applyable to an empty instance schema. Keep them here, after
-- every `add column`, and add new row-type functions here too.

-- PRIORITY_SYNC_SIGNATURE fingerprints the Priority payload so a line re-sends only when
-- the client-visible record actually changed. A FRESH database needs the function as well as
-- the column: indoxV2Driver01 SELECTs it on every sweep, so without it the driver errors on
-- its first query. Byte-identical to scripts/ops/migrations/2026-08-22_priority_sync_signature.sql
-- (which is how an EXISTING database gets it). The two copies are kept honest by
-- scripts/ops/verify_priority_signature.mjs, which diffs them and fails on drift -- the same
-- fixture-vs-live divergence that lost six columns (issues/schema-drift-fixture-vs-live.md).
-- THE TWO HASHES MUST BE COMPUTED THE SAME WAY IN SQL AND IN JS, or the gate oscillates: the
-- selector writes a hash the driver never reproduces, decide sees a mismatch every sweep, and the
-- dup guard raises DOUBLE ACTION on a document that is behaving perfectly. Same lesson the
-- priority signature already carries below -- one definition, in SQL, read by everyone.
-- Field order is fixture_INVOICE.json's resync_fields, verbatim; the JS side is
-- SelectType01/'Select'.selectionHash and SelectBase01/'Select'.baseHash.
create or replace function public.indox_selection_hash(d incoming_documents)
returns text language sql immutable as $$
  select concat_ws('|',
    coalesce(d."AI_COMPANY_ID", ''), coalesce(d."COMPANY_ID", ''),
    coalesce(d."AI_DOC_ID", ''),     coalesce(d."DOC_ID", ''),
    coalesce(d."AI_DOC_DATE", ''),   coalesce(d."BS_LINE_DATE", ''), coalesce(d."DOC_DATE", ''),
    coalesce(d."AI_DOC_AMOUNT", ''), coalesce(d."BS_LINE_AMOUNT", ''), coalesce(d."DOC_TOTAL_AMOUNT", ''),
    coalesce(d."AI_SHIPMENT_IDS", ''), coalesce(d."AI_ORDER_IDS", ''),
    coalesce(d."SHIPMENT_DOC_ID", ''), coalesce(d."PURCHASE_ID", ''))
$$;

create or replace function public.indox_base_selection_hash(d incoming_documents)
returns text language sql immutable as $$
  select concat_ws('|',
    coalesce(d."LOCAL_COMPANY_ID", ''), coalesce(d."AI_COMPANY_ID", ''), coalesce(d."COMPANY_ID", ''),
    coalesce(d."LOCAL_TYPE", ''),       coalesce(d."AI_TYPE", ''),       coalesce(d."TYPE", ''),
    coalesce(d."LOCAL_DOC_DATE", ''),   coalesce(d."AI_DOC_DATE", ''),   coalesce(d."DOC_DATE", ''))
$$;

-- [line-hash dup guard 2026-08-26, owner order] THE WHOLE LINE, AS ONE HASH.
-- The double-action guard is not allowed to call a repeat a fault unless the line is UNCHANGED
-- since the earlier dispatch: a field that moved (a corrected date, a cleared *_COMPLETED mark,
-- an operator running an action by hand) gives the action new inputs, so re-running it is work,
-- not a loop. indoxV2ActionRouter01 :: 'Log Action Start' stamps this onto every dispatch row
-- ("LINE_HASH" below); indoxV2Driver01 :: 'Enrich Double Lines' recomputes it and
-- 'Dup Guard: Double Action' compares. Same one-definition law as the two selection hashes
-- above -- the formula lives HERE and nowhere else, because a JS copy would drift and drift here
-- means either a guard that never fires or one that fails healthy documents every sweep.
-- Full rationale + the measurement that forced it:
-- scripts/ops/migrations/2026-08-26_action_log_line_hash.sql
--
-- THE WHOLE LINE -- every column. ONE EXCLUSION, and it is load-bearing: updated_at is bumped by
-- every write, semantic or not, so with it in the hash no two dispatches could ever share one and
-- the guard would be a permanent no-op. Nothing else is excluded.
-- STABLE, not immutable: to_jsonb renders timestamptz through the TimeZone GUC, and the writer
-- and reader share one Postgres credential so they cannot disagree on it.
create or replace function public.indox_line_hash(d incoming_documents)
returns text language sql stable as $$
  select md5((to_jsonb(d) - 'updated_at')::text)
$$;

create or replace function public.indox_priority_signature(d incoming_documents)
returns text
language sql
immutable
as $fn$
  -- Canonical form: the mapped values joined by the ASCII unit separator (chr 31), a
  -- byte that cannot occur in any of these fields. jsonb_build_array was the obvious
  -- choice and was WRONG: Postgres renders jsonb::text with a space after every comma
  -- while JSON.stringify is compact, so SQL and JS hashed different bytes from
  -- identical values -- 0/559 rows agreed. concat_ws is reproducible on both sides.
  -- INVARIANT, and concat_ws makes it load-bearing: concat_ws SKIPS null arguments, so a NULL
  -- element would shift every later field one position left and let two different documents
  -- collapse onto one signature -- a missed re-send, the silent half of the failure mode.
  -- EVERY element below is therefore total: each `case` arm returns a literal or btrim() of a
  -- value it has already established is not null, and each numeric is wrapped in coalesce.
  -- Adding an element that can return NULL silently breaks the whole column -- coalesce it.
  select md5(concat_ws(chr(31),

    -- [selection split 2026-08-25, owner order] THE SIGNATURE FOLLOWS THE PAYLOAD, AND THE PAYLOAD
    -- NOW READS THE FINALS. Seven of these elements used to read SELECTED_*, a parallel value set
    -- written by the retired select_invoice_values step. Nothing writes those columns any more, so
    -- leaving the fingerprint on them would freeze it: a document could change every value the ERP
    -- can see and still hash the same, which is precisely the missed re-send this column exists to
    -- prevent. The mapping mirrored below is 'Map Request' in indoxV2ActionsGDoc01/Ship01, which
    -- also lost its `String(null) -> 'null'` casts in the same change -- a missing value is now the
    -- empty string on both sides, so there is no 'null' literal left to mirror.
    -- Already-synced rows had their stored signature recomputed with this formula in the same
    -- deployment, so the change did not re-send anything by itself.

    -- IDSUP  <= String($json.COMPANY_ID ?? "").trim()
    btrim(coalesce(d."COMPANY_ID", '')),

    -- DATEDOC <= v.length >= 10 ? v.substring(0,6) + v.slice(-2) : v   (v already trimmed)
    -- JS substring(0,6) == substr(x,1,6); JS slice(-2) == right(x,2).
    case
      when length(btrim(coalesce(d."DOC_DATE", ''))) >= 10
        then substr(btrim(d."DOC_DATE"), 1, 6) || right(btrim(d."DOC_DATE"), 2)
      else btrim(coalesce(d."DOC_DATE", ''))
    end,

    -- DOCNAME <= String($json.DOC_ID ?? "").trim()
    btrim(coalesce(d."DOC_ID", '')),

    -- DOCSHORT <= String($json.SHORT_DOC_ID ?? "").trim()
    btrim(coalesce(d."SHORT_DOC_ID", '')),

    -- TOTPRICE <= parseFloat(String(DOC_TOTAL_AMOUNT ?? TOTAL_AMOUNT ?? "").replace(/,/g,"")) || 0
    -- parseFloat takes the longest leading numeric prefix and yields NaN otherwise; NaN||0 and
    -- 0||0 both give 0. The regex is that prefix rule; anything unparseable falls to 0.
    -- ?? falls through on NULL only, so an empty-string amount does NOT reach TOTAL_AMOUNT.
    coalesce(
      (substring(replace(btrim(coalesce(d."DOC_TOTAL_AMOUNT", d."TOTAL_AMOUNT", '')), ',', '')
                 from '^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'))::double precision,
      0),

    -- DOC_INV <= String($json.SHIPMENT_DOC_ID ?? "").trim()
    btrim(coalesce(d."SHIPMENT_DOC_ID", '')),

    -- PORDNAME <= String($json.PURCHASE_ID ?? "").trim()
    btrim(coalesce(d."PURCHASE_ID", '')),

    -- LINKDOC <= String($json.LINK ?? "").trim()
    btrim(coalesce(d."LINK", '')),

    -- TYPEDOC <= String($json.TYPE ?? "").trim()
    btrim(coalesce(d."TYPE", '')),

    -- SOURCE <= String($json.SOURCE_TYPE ?? "").trim()
    btrim(coalesce(d."SOURCE_TYPE", '')),

    -- FROMWAREHOUSE <= $json.FROM_OFFICE == true ? 'Y' : ""
    -- LOOSE equality against a TEXT column. JS coerces both sides to Number, so this is 'Y' only
    -- when the text is numerically 1 — never for the literal 'true' the column actually holds
    -- (Number('true') is NaN). Mirrored faithfully rather than corrected: this function must hash
    -- what the lane SENDS, not what it ought to send. The mapping defect is tracked separately;
    -- when it is fixed, these signatures change and the affected lines re-send, which is exactly
    -- the behaviour this column is for.
    -- [2026-08-23] UPDATED TO THE FIXED MAPPING. The arm below used to mirror a DEFECT on
    -- purpose (see the note above): the node compared FROM_OFFICE loosely against true, JS
    -- coerced both sides to Number, and Number('true') is NaN -- so a column that literally holds
    -- 'true' never produced 'Y'. That note said, in as many words, that when the mapping was
    -- fixed these signatures would change and the affected lines would re-send, and that this is
    -- exactly what the column is for.
    --
    -- The mapping WAS fixed in both 'Map Request' nodes (Ship and GDoc, verified live:
    -- String(...).trim().toLowerCase() === 'true' ? 'Y' : ""), and this copy was not updated with
    -- it. The fingerprint therefore disagreed with the payload on 409 of 520 sampled rows -- not
    -- a wrong hash, but a hash of the wrong thing, which is the one failure this function exists
    -- to prevent.
    case when lower(btrim(coalesce(d."FROM_OFFICE", ''))) = 'true' then 'Y' else '' end,

    -- PROPORTZ_CERTAINTY <= String(parseInt($json.SELECTION_CERTAINTY) || 0)   (a STRING)
    (coalesce((substring(btrim(coalesce(d."SELECTION_CERTAINTY", '')) from '^[+-]?[0-9]+'))::bigint,
              0))::text,

    -- N8N_EXEID is deliberately absent — see the header.

    -- INCOMING_DOC_ID <= $json.ID || ""
    coalesce(d."ID", '')

  ))
$fn$;


-- ── VIEW-TYPED OVERLOADS — TEMPORARY, AND DELIBERATELY SO ────────────────────────────────────
-- [2026-08-28, agreed with the tenancy session] The four functions above are typed on the
-- INSTANCE TABLE's row type. While `public.<table>` compat views still stand, a caller can just
-- as easily hand one a VIEW row — and postgres resolves overloads by exact type, so it answers
-- "function does not exist" AT RUNTIME, ON A CLIENT. That is how a drain failed during the
-- tenancy cutover, and a freshly provisioned second tenant would hit it the same way, because
-- the view-typed halves were added to the live database by hand and were never in this file.
--
-- A dead overload after the views come down is harmless; a missing one is an outage. So these
-- exist until indoxApi01 stops falling back to `public`, and then they can be deleted outright.
--
-- ORDER MATTERS AT CUTOVER — DROP THESE BEFORE THE VIEWS, NOT AFTER.
-- A function typed on a view DEPENDS on that view's composite type, so `drop view` does not
-- quietly succeed and leave an orphan — it REFUSES. Demonstrated 2026-08-28 on a throwaway pair:
--
--     ERROR:  cannot drop view dv_test.v because other objects depend on it
--     DETAIL:  function dv_test.f(dv_test.v) depends on type dv_test.v
--     HINT:  Use DROP ... CASCADE to drop the dependent objects too.
--
-- So the cutover that removes the 17 compat views must first
--     drop function public.indox_priority_signature(public.incoming_documents);   -- and the
--     drop function public.indox_selection_hash(public.incoming_documents);       -- other three
-- or accept `drop view ... cascade`, which takes whatever else depends on the view along with it
-- — a wide blast radius for a change whose whole point is that it is exact.
--
-- GROWTH, for whoever revisits this: there is one overload per TENANT plus one for the view, so
-- these four functions are 1+N objects each — 12 at two tenants, 44 at ten, every one a copy of
-- the same body. Typing them on the columns they actually hash instead of on a whole row type
-- would make each exactly one definition regardless of tenant count. That is a larger change than
-- the cutover and is deliberately not bundled with it; it is written down here so the cost is
-- visible when someone counts tenants rather than functions.
--
-- DERIVED, NOT DUPLICATED. Each overload is built from the body of the table-typed function
-- rather than copy-pasted, so the two can never drift: edit the definition above and this block
-- re-emits the twin on the next apply. Skipped entirely when no view exists (a from-nothing
-- provision that never had one), which is why it is a guard rather than four DDL statements.
DO $view_typed_overloads$
DECLARE r record; view_rel oid;
BEGIN
  view_rel := to_regclass('public.incoming_documents');
  IF view_rel IS NULL THEN
    RAISE NOTICE 'no public.incoming_documents view — skipping view-typed overloads';
    RETURN;
  END IF;
  IF (SELECT relkind FROM pg_class WHERE oid = view_rel) <> 'v' THEN
    RAISE NOTICE 'public.incoming_documents is not a view — skipping view-typed overloads';
    RETURN;
  END IF;

  FOR r IN
    SELECT p.proname,
           p.prosrc,
           l.lanname,
           pg_get_function_result(p.oid) AS result_type,
           CASE p.provolatile WHEN 'i' THEN 'immutable' WHEN 's' THEN 'stable' ELSE '' END AS vol
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
      JOIN pg_language  l ON l.oid = p.prolang
     WHERE n.nspname = 'public'
       AND p.proname IN ('indox_priority_signature', 'indox_selection_hash',
                         'indox_base_selection_hash', 'indox_line_hash')
       AND p.pronargs = 1
       AND p.proargtypes[0] = (SELECT c.reltype FROM pg_class c
                                WHERE c.oid = (current_schema() || '.incoming_documents')::regclass)
  LOOP
    EXECUTE format(
      'create or replace function public.%I(d public.incoming_documents) returns %s language %s %s as %L',
      r.proname, r.result_type, r.lanname, r.vol, r.prosrc);
    RAISE NOTICE 'view-typed overload ready: public.%(public.incoming_documents)', r.proname;
  END LOOP;
END
$view_typed_overloads$;
