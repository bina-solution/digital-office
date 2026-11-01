-- 2026-09-02 — the sync item's lag metric (sync best practice: expose the age of the oldest
-- undelivered item per source, poison items excluded, so a stalled pipe is visible as a number
-- and not as a bar that merely stopped moving).
--
-- Adds `oldest_waiting_at` (min discovered_at over discovered/failed/claimed items — needs_review
-- is a dead-letter state and deliberately NOT counted, the way SQS excludes poison messages from
-- ApproximateAgeOfOldestMessage) and `waiting` (that count) to the per-pipe view.
--
-- Per tenant:  psql -v schema=indox_<tenant> -f this-file
-- The columns are appended, so `create or replace view` is allowed; rows served to the BFF are
-- unchanged in shape apart from the two new fields.
\set ON_ERROR_STOP on
set search_path to :"schema", public;
begin;

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
       min(l.discovered_at) filter (where l.status in ('discovered', 'failed', 'claimed'))
                                                                    as oldest_waiting_at,
       count(*) filter (where l.status in ('discovered', 'failed', 'claimed'))::int
                                                                    as waiting
  from sync_ledger l
 group by l.source;

-- the DriveSearchConnection knob (which Drive find_link / check_from_office search: a catalog
-- connection id, or profile:<id> for the local engine; empty = the first enabled drive pipe's own
-- identity). The fixture seeds it for NEW tenants only (settings.json is read at onboarding), so
-- existing tenants get the row here — empty, which is the documented default.
insert into settings (instance, key, value)
values ('incoming-documents-main', 'DriveSearchConnection', '')
on conflict (instance, key) do nothing;

-- indoxOn — THE master toggle (owner 2026-09-02): off = no sync AND no scheduled drain; both
-- lanes read it beside their own switch (syncV3Main0001, indoxV2BaseDrain01), a missing row
-- reads as on. Seeded on for existing tenants so nothing changes until an operator flips it.
insert into settings (instance, key, value)
values ('incoming-documents-main', 'indoxOn', 'true')
on conflict (instance, key) do nothing;

commit;
