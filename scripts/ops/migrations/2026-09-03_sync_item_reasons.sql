-- 2026-09-03 — the sync item's REASONS, per pipe (owner order: every red item explains itself).
--
-- A pipe's card shows the top reasons among its failed + needs_review items; the items drawer
-- shows the reason on each row. The view groups `last_error` per source so the BFF stays a
-- single read (DB-only, no walk). Reasons are stored by RECORD (needs_review carries its reason
-- since 2026-09-03), FAIL, REAP and TAKE's [expired] / [unlisted] dead-letters.
--
-- Also backfills the one class of rows that predate reasons: the 2026-08-28 migration rows
-- (empty listing, no reason) get `[legacy] migrated from the retired engine without a listing`
-- so a card never shows a red count it cannot explain.
--
-- Per tenant:  psql -v schema=indox_<tenant> -f this-file
\set ON_ERROR_STOP on
set search_path to :"schema", public;
begin;

-- The reason is grouped with its identifiers FOLDED (an 18+ character token is a drive id, a
-- message id or a hash; "[line 3]" is a line number): measured 2026-09-02 on drive-gdoc-scanned,
-- 25 red items produced 25 chips of one — "drive item 122XgF…-oo has no md5 in its listing"
-- twenty-five times over — instead of the one chip that names the problem. The row keeps its
-- exact text (the items drawer shows it); only the CARD's grouping folds.
create or replace view sync_item_reasons as
select l.source,
       regexp_replace(l.source, '^[^/]*/', '')          as pipe,
       regexp_replace(regexp_replace(
         coalesce(nullif(btrim(l.last_error), ''), '(no reason recorded)'),
         '[A-Za-z0-9_-]{18,}', '<id>', 'g'),
         '\[line \d+\]', '[line n]', 'g')                  as reason,
       count(*)::int                                     as n,
       max(coalesce(l.delivered_at, l.discovered_at))    as last_at
  from sync_ledger l
 where l.status in ('failed', 'needs_review')
 group by l.source,
          regexp_replace(regexp_replace(
            coalesce(nullif(btrim(l.last_error), ''), '(no reason recorded)'),
            '[A-Za-z0-9_-]{18,}', '<id>', 'g'),
            '\[line \d+\]', '[line n]', 'g');

update sync_ledger
   set last_error = '[legacy] migrated from the retired engine without a listing'
 where status = 'needs_review'
   and listing = '{}'::jsonb
   and coalesce(btrim(last_error), '') = '';

commit;
