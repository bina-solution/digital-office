-- 2026-09-03 — retire `tag_rules` (owner Decision N1: ONE rules store).
--
-- The label rules live in the mail app's organizer settings — the store the label engine
-- evaluates, mailapi's search resolves through, and the mail console edits. This table was a
-- second, drifting copy (27 rows here vs 23 in the store on 2026-09-02) read by the sync main
-- (KEY → label name), the feedback action and the test harness; all three now read the
-- organizer settings over HTTP. Nothing writes this table any more.
--
-- Renamed, not dropped: the rows stay for audit until the next schema sweep. Idempotent.
-- Per tenant:  psql -v schema=indox_<tenant> -f this-file
\set ON_ERROR_STOP on
set search_path to :"schema", public;
begin;

do $$
begin
  if to_regclass(current_schema() || '.tag_rules') is not null
     and to_regclass(current_schema() || '.tag_rules_retired_20260903') is null then
    execute 'alter table tag_rules rename to tag_rules_retired_20260903';
  end if;
end $$;

commit;
