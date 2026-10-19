-- [completion flags 2026-08-20, owner order] apply_gmail_labels and file_to_failed_folder get
-- completion columns, like every other action.
--
-- WHY. The state machine's rule is that an action's "already done" evidence lives ON THE ROW:
-- 20 `*_COMPLETED` columns plus the legacy FROM_OFFICE_CHECK. These two actions were the ONLY
-- ones with no column at all, so their once-only gates in indoxV2ActionsGlobal01 ::
-- 'Decide DOC BASE Action' asked ACTION_LOG instead -- `la.includes('Apply Gmail Labels')` and
-- `la.includes('File To Failed Folder')`. That is a log doing a column's job, and it is the
-- last thing keeping decide tied to ACTION_LOG.
--
-- It is not academic. Switching those two reads to the dispatch log on 2026-08-20 immediately
-- re-dispatched file_to_failed_folder on documents already filed, and Google Drive answered
-- "File not found: 1FwcEBh6VAbnxu84Ny2g2xH_Bw5-dT7iq" -- the move is NOT idempotent. Two
-- executions failed that way within minutes.
--
-- NAMING follows the convention on purpose. The four 'Build: Restart (clear completed flags)'
-- nodes clear every key ending in `_COMPLETED` dynamically:
--     for (const k of Object.keys(j)) { if (k.endsWith('_COMPLETED')) o[k] = false; }
-- so ACTION_RESTART resets these two with no extra code, exactly like the other twenty.
--
-- TYPE is text, not boolean, to match the existing flags: the readers compare
-- `String(v).trim().toLowerCase() === 'true'` in JS and `lower(coalesce(col,'')) = 'true'` in
-- SQL. A boolean here would read false under both.
--
-- BACKFILL takes the UNION of both surviving sources, because neither is complete on its own:
--   * ACTION_LOG holds the full history but is about to be dropped, and its entry only appears
--     once the action's upsert landed;
--   * indox_action_execution_log starts 2026-08-17 but records the dispatch itself, so it
--     catches attempts whose upsert never landed.
-- Measured before this ran: ACTION_LOG knew 2,531 gmail-labelled documents to the dispatch
-- log's 1,827, and 1,637 failed-foldered to its 20 -- while the dispatch log knew 264
-- failed-folder documents ACTION_LOG did not. Taking either alone loses real history.

ALTER TABLE public.incoming_documents
  ADD COLUMN IF NOT EXISTS "GMAIL_LABELS_COMPLETED" text,
  ADD COLUMN IF NOT EXISTS "FAILED_FOLDER_COMPLETED" text;

UPDATE public.incoming_documents d
SET "GMAIL_LABELS_COMPLETED" = 'true'
WHERE coalesce(d."GMAIL_LABELS_COMPLETED", '') <> 'true'
  AND (d."ACTION_LOG" LIKE '%Apply Gmail Labels%'
       OR EXISTS (SELECT 1 FROM public.indox_action_execution_log e
                  WHERE e."ID" = d."ID" AND e."ACTION" = 'apply_gmail_labels'));

UPDATE public.incoming_documents d
SET "FAILED_FOLDER_COMPLETED" = 'true'
WHERE coalesce(d."FAILED_FOLDER_COMPLETED", '') <> 'true'
  AND (d."ACTION_LOG" LIKE '%File To Failed Folder%'
       OR EXISTS (SELECT 1 FROM public.indox_action_execution_log e
                  WHERE e."ID" = d."ID" AND e."ACTION" = 'file_to_failed_folder'));
