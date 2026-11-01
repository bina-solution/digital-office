-- PRIORITY_SKIP: a per-line opt-out of action_priority_sync. [2026-08-23, owner order]
--
-- The owner added FILTER_REQUEST / FILTER_REQUES_REASON via the console; the semantic is
-- priority-specific, so the columns are renamed to say what they do. decide (GDoc/Ship choosers)
-- skips both priority branches when PRIORITY_SKIP is true, and the line falls through to
-- mark_completed exactly as if the sync had happened.
--
-- BACKFILL RULE (owner): what is in indox_priority_local right now is what was synced LOCALLY in
-- this version. A line carrying PRIORITY_SYNC_COMPLETED=true that is NOT in the local table was
-- synced to the ONLINE Priority by the previous deployment -- re-sending it would duplicate a
-- record in the client's ERP, so it is skipped with reason 'synced in last version'.
-- Measured at apply time: 481 FILTER_REQUEST=true (owner-set), 4,625 synced-in-last-version,
-- 6,038 synced locally (NOT skipped -- they re-send into the cleaned local table on restart).

alter table public.incoming_documents rename column "FILTER_REQUEST" to "PRIORITY_SKIP";
alter table public.incoming_documents rename column "FILTER_REQUES_REASON" to "PRIORITY_SKIP_REASON";

-- previously-synced lines: skip, and append the reason to whatever the owner already wrote
update public.incoming_documents d
set "PRIORITY_SKIP" = true,
    "PRIORITY_SKIP_REASON" = case
      when coalesce(btrim("PRIORITY_SKIP_REASON"), '') = '' then 'synced in last version'
      else btrim("PRIORITY_SKIP_REASON") || ' ; synced in last version'
    end
where lower(coalesce(d."PRIORITY_SYNC_COMPLETED", '')) = 'true'
  and not exists (select 1 from public.indox_priority_local p where p."INCOMING_DOC_ID" = d."ID");
