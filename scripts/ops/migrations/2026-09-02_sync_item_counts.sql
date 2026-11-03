-- The sync board reads ONE view (owner rule 2026-09-02: the sync UI is DB-only — one bar per pipe,
-- blue = to sync, green = synced, red = failed — and the INDOX BFF never asks mail/drive anything).
-- Per pipe: counts by status straight off the sync item, the last time discovery/delivery touched
-- it, and the most recent error text. Everything the old live walk produced that the UI still
-- shows comes from here; everything else it produced is gone with the walk.
--
-- Also retires the two tables that walk fed: `indox_sync_stats` (the cached walk) and
-- `sync_pipe_state` (run journal — a pass is now visible as the ledger's own timestamps).
--
-- Run per tenant schema:
--   psql -U postgres -d postgres -v schema=indox_hacohen -f 2026-09-02_sync_item_counts.sql

\set ON_ERROR_STOP on
set search_path to :"schema", public;

BEGIN;

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
         order by coalesce(e.not_before, e.discovered_at) desc limit 1) as last_error
  from sync_ledger l
 group by l.source;

-- cascade: the sole-tenant era left `public.<table>` compatibility VIEWS over these; they go too
drop table if exists indox_sync_stats cascade;
drop table if exists sync_pipe_state cascade;

COMMIT;

-- verification
select pipe, discovered, claimed, delivered, failed, needs_review, total from sync_item_counts order by pipe;
