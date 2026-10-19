-- [loop-breaker durability 2026-08-10] ACTION_LOG is APPEND-ONLY.
--
-- WHY. Several decide clauses store their one-shot loop breaker as a marker inside
-- ACTION_LOG -- 'BASE APITOOLS RETRY' (docBaseDecide's API_TOOLS_ID retry, in
-- indoxV2ActionsGlobal01 'Decide DOC BASE Action') and 'FIGURE COMPANY OFFLINE' (the
-- linkless company resolver). Roughly 40 router "Build:" nodes across
-- indoxV2ActionsGlobal01 / GDoc01 / Ship01 / BS01 rebuild the row from an action response
-- with includeOtherFields:false and read $json.ACTION_LOG off that response, where the key
-- is absent -- so they write '' back over the column and erase the breaker.
--
-- Measured 2026-08-10: only 8 of 380 rows in the retry cohort still carried the marker;
-- 322 of them sat at EXTRACTION_FAILED with an ACTION_LOG of ~2 characters, re-entering
-- extract_base_doc on every sweep forever.
--
-- A loop breaker stored in a column that other writers wipe is not a breaker. Rather than
-- edit ~40 nodes across four workflows and hope the 41st is never added, the invariant is
-- enforced once, below every writer: a write that does not carry the existing log forward
-- is treated as an ADDITION to it, never as a replacement. Writers that legitimately extend
-- the log (old value is a substring of the new one) pass through untouched, so the normal
-- append path is unchanged.
--
-- No workflow in the fleet deliberately resets ACTION_LOG to empty (verified: zero nodes
-- assign it a literal empty value), so nothing legitimate is broken by refusing a shrink.
--
-- This is a schema fix, not a data edit: it changes how future writes are applied and
-- rewrites no existing row.

create or replace function public.incdoc_action_log_append()
returns trigger
language plpgsql
as $$
declare
  old_log text := coalesce(OLD."ACTION_LOG", '');
  new_log text := coalesce(NEW."ACTION_LOG", '');
  merged  text;
  cap     constant int := 6000;
begin
  -- untouched by this statement, or nothing to protect yet
  if NEW."ACTION_LOG" is not distinct from OLD."ACTION_LOG" or old_log = '' then
    return NEW;
  end if;

  -- the writer carried the existing log forward (normal append) -> accept as-is
  if position(old_log in new_log) > 0 then
    return NEW;
  end if;

  -- the writer replaced or blanked the log -> preserve history, fold in anything new
  if new_log = '' or position(new_log in old_log) > 0 then
    merged := old_log;                       -- blank, or a fragment we already have
  else
    merged := old_log || ', ' || new_log;    -- genuinely new text, appended
  end if;

  -- bound the column: keep the head (earliest markers) and the most recent tail
  if length(merged) > cap then
    merged := left(merged, 1500) || ' ...[trimmed]... ' || right(merged, 4000);
  end if;

  NEW."ACTION_LOG" := merged;
  return NEW;
end;
$$;

drop trigger if exists trg_incdoc_action_log_append on public.incoming_documents;

create trigger trg_incdoc_action_log_append
  before update on public.incoming_documents
  for each row
  execute function public.incdoc_action_log_append();
