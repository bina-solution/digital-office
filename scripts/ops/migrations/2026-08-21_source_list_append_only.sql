-- 2026-08-21 — SOURCE_LIST is APPEND-ONLY, enforced at the single write point.
--
-- THE PROBLEM
-- -----------
-- `Build Bulk Upsert SQL` writes every column as `col = EXCLUDED.col`, so any caller sending
-- SOURCE_LIST REPLACES the array wholesale. Two callers legitimately write it:
--
--   * the merge action, which APPENDS the loser's sources to the winner
--   * the source_feedback action, which PATCHES one element's completion fields
--
-- They take different doc_action locks (the lock key is `<ID>::<ACTION>`), so they can run
-- concurrently on one document. Whichever upserts second wipes the other's write. If the merge
-- loses, a source silently disappears and the loser's file can never be filed again. If feedback
-- loses, its element reverts to not-completed, is re-decided, finds its own per-source action name
-- already in ACTION_HISTORY with no restart between, and is parked as DOUBLE ACTION BLOCKED —
-- permanently, because only ACTION_RESTART clears that.
--
-- THE FIX
-- -------
-- Make the MERGE the database's job rather than each caller's. An incoming element either patches
-- the existing element with the same source identity, or is appended. An existing element the
-- incoming array does not mention is KEPT. Order is preserved, and preserving order is not
-- cosmetic: decide dispatches `source_feedback_<i>` by array index, so a reorder would point a
-- live action at a different file or mailbox. (The action re-verifies identity before acting and
-- refuses on mismatch — proven 2026-08-21 — but that is the seatbelt, not the road.)
--
-- IDENTITY is the same key the action verifies, plus the row the source belongs to:
--     source_kind | file_id-or-message_id | doc_row_id
-- `doc_row_id` alone is not unique: when a loser with several sources is merged, every one of its
-- elements is appended carrying that loser's id.
--
-- This also RETIRES the jsonb_set ship-blocker recorded on 'Build: Source Feedback'. That node
-- writes the whole array; with this function the write is a merge, so a concurrent append is no
-- longer lost and merging + source feedback can be enabled together.

\set ON_ERROR_STOP on

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

\echo '--- self-test ---'
WITH t(name, cur, inc, want) AS (VALUES
  ('patch in place',
   '[{"source_kind":"drive","file_id":"F1","doc_row_id":"A","sync_feedback_completed":false}]'::jsonb,
   '[{"source_kind":"drive","file_id":"F1","doc_row_id":"A","sync_feedback_completed":true}]'::jsonb,
   1),
  ('append a new source',
   '[{"source_kind":"drive","file_id":"F1","doc_row_id":"A"}]'::jsonb,
   '[{"source_kind":"mail","message_id":"M1","doc_row_id":"B"}]'::jsonb,
   2),
  ('an incoming array that omits an existing source KEEPS it',
   '[{"source_kind":"drive","file_id":"F1","doc_row_id":"A"},{"source_kind":"mail","message_id":"M1","doc_row_id":"B"}]'::jsonb,
   '[{"source_kind":"drive","file_id":"F1","doc_row_id":"A","sync_feedback_completed":true}]'::jsonb,
   2),
  ('null incoming never blanks',
   '[{"source_kind":"drive","file_id":"F1","doc_row_id":"A"}]'::jsonb, NULL, 1),
  ('empty existing takes incoming',
   '[]'::jsonb, '[{"source_kind":"mail","message_id":"M9","doc_row_id":"Z"}]'::jsonb, 1)
)
SELECT CASE WHEN jsonb_array_length(public.indox_merge_source_list(cur, inc)) = want
            THEN '  ok   ' ELSE '  FAIL ' END || name AS result,
       jsonb_array_length(public.indox_merge_source_list(cur, inc)) AS got, want
FROM t;

\echo '--- order is preserved, and the patch lands on the right element ---'
SELECT public.indox_merge_source_list(
  '[{"source_kind":"drive","file_id":"F1","doc_row_id":"A","n":1},
    {"source_kind":"mail","message_id":"M1","doc_row_id":"B","n":2}]'::jsonb,
  '[{"source_kind":"mail","message_id":"M1","doc_row_id":"B","sync_feedback_completed":true}]'::jsonb
) AS merged;
