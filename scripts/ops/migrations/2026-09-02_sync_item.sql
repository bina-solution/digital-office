-- sync_ledger becomes the SYNC ITEM (owner Decision 1, 2026-09-02): one row per DISCOVERED item,
-- not one row per delivered item. No new table — the ledger already has the right key
-- (source, platform_id), doc_id, content_hash, claimed_at and instance; it gains the discovery
-- and retry columns, and sync_attempt folds into it.
--
-- status vocabulary (the single state field; "synced" == 'delivered'):
--   discovered   listed at the source, not yet taken            (written by syncDiscover*)
--   claimed      taken by a Run pass, delivery in flight          (TAKE)
--   delivered    document row created                             (RECORD)
--   failed       delivery failed, retry after not_before          (FAIL)
--   needs_review retry budget exhausted, needs an operator         (FAIL / REAP)
--
-- Run per tenant schema:
--   psql -U postgres -d postgres -v schema=indox_hacohen -f 2026-09-02_sync_item.sql
-- Idempotent: every statement is add-if-missing / on-conflict.

\set ON_ERROR_STOP on
set search_path to :"schema", public;

BEGIN;

alter table sync_ledger add column if not exists discovered_at timestamptz not null default now();
alter table sync_ledger add column if not exists listing       jsonb       not null default '{}'::jsonb;
alter table sync_ledger add column if not exists attempts      integer     not null default 0;
alter table sync_ledger add column if not exists not_before    timestamptz;
alter table sync_ledger add column if not exists last_error    text;

-- existing rows: the earliest timestamp we hold is the best "discovered" we can say
update sync_ledger
   set discovered_at = least(coalesce(claimed_at, delivered_at, now()), discovered_at)
 where delivered_at is not null or claimed_at is not null;

-- fold sync_attempt in: a retryable failure with no ledger row is a discovered item that failed;
-- one that already has a row keeps its status and just inherits the attempt bookkeeping.
insert into sync_ledger (source, platform_id, status, discovered_at, attempts, not_before, last_error)
select a.source, a.platform_id, 'failed', coalesce(a.updated_at, now()), a.attempts, a.not_before, a.last_error
  from sync_attempt a
on conflict (source, platform_id) do update
   set attempts   = excluded.attempts,
       not_before = excluded.not_before,
       last_error = excluded.last_error;

-- the Run pass's TAKE reads exactly this
create index if not exists idx_sync_ledger_pending
    on sync_ledger (source, status, not_before)
 where status in ('discovered', 'failed');

-- sync_attempt is retired; kept renamed for one release so nothing is lost if a reader was missed
do $$
begin
  if exists (select 1 from information_schema.tables
              where table_schema = current_schema() and table_name = 'sync_attempt') then
    execute 'alter table sync_attempt rename to sync_attempt_retired_20260902';
  end if;
end $$;

COMMIT;

-- verification
select current_schema() as schema,
       count(*)                                        as items,
       count(*) filter (where status = 'discovered')   as discovered,
       count(*) filter (where status = 'claimed')      as claimed,
       count(*) filter (where status = 'delivered')    as delivered,
       count(*) filter (where status = 'failed')       as failed,
       count(*) filter (where status = 'needs_review') as needs_review
  from sync_ledger;
