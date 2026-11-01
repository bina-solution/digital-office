-- ============================================================================
-- REGISTRY FIX — drive-gdoc-warehouse.  PREPARED, NOT APPLIED.
--
--   *** settings.sync_registry IS PRODUCTION CONFIG. DO NOT RUN WITHOUT THE     ***
--   *** OWNER'S APPROVAL.                                                        ***
--
-- BACKUP TAKEN BEFORE ANY OF THIS:
--   data/_registry_backup/sync_registry.20260806T111544Z.json
--   7,358 bytes · sha256 ade8c44fc6d7932db31c11c5f493090aa04feef11a3310236d5673b24e88fa2b
--   11 entries, re-parses to valid JSON, checksum verified identical after rename.
-- ============================================================================


-- ============================================================================
-- 1. FOLDER RESOLUTION — both ids resolved by walking the tree, not by name-guessing.
--
--   SOURCE  1stuMSjbnyUTCtbq6KIzooHCGXpEey_7P  'סרוקות- לפני שמות'
--   DEST    1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu  'סרוקות הצליח'
--   both under parent 1zTQxUKtm1h7GUcGdb3ltSY0HjEsINzEV
--                     ('סרוקות / ווטסאפ ראשי - אוטומציות')
--
-- They are SIBLINGS in the naming pipeline's own before/succeeded/failed tri-state,
-- which is what makes source->destination coherent:
--     1stuMSjbnyUTCtbq6KIzooHCGXpEey_7P  'סרוקות- לפני שמות'          <- before names
--     1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu  'סרוקות הצליח'               <- succeeded
--     1m25RdFEkfv_5KjSqFGM8gpjupXWZuUW2  'סרוקות- נכשל (בוריס)'       <- failed
--     1bR2EDqDUtLMSiHKQkL25DacK0ptzH_40  'סרוקות- שינוי ידני (בוריס)'
--     11rj5zDw2lhYnc8zMUxmYADKIJaPaunhb  'אחרי שמות, סרוקות בוריס נכשל'
--     1GsIcPPh4wzpue7FH3Omeast9I-_aZBFX  'כשלון נוסף לבדיקה'
--
-- SPELLING NOTE: the real folder name carries a hyphen bound to the first word —
-- 'סרוקות- לפני שמות', not 'סרוקות לפני שמות'. Matched on the substring 'לפני' across
-- both parent subtrees: 8 folders matched, 7 rejected as צט exports under
-- 'יצוא צט מאגר' ('יצוא צט 2026 לפני', 'יצוא צט 12.25 - לפני', 'יצוא צט 11.25 לפני',
-- 'צט 10 קרית 4 - לפני', 'צט 10 שילה - לפני', 'צט שילה 09.25 לפני',
-- 'צט קרית 09.25 לפני'). Exactly one candidate remains, in the right parent.
-- ============================================================================


-- ============================================================================
-- 2. *** THE RULE-OUT CHECK: 'סרוקות- לפני שמות' IS **NOT** 1Lmhka14. ***
--
--   proposed to_sync  1stuMSjbnyUTCtbq6KIzooHCGXpEey_7P  'סרוקות- לפני שמות'
--   current  to_sync  1Lmhka14VGQMVGr4VQFRpF1YDEdOUnUhM  'סרוקות מהמחסן 2026'
--
-- Different ids, different names, and different PARENTS — 1Lmhka14 sits under
-- 1258rEdcULbnIFBMyDLowqAP4yjou9PbD (alongside 'סרוקות שנים קודמות'), a separate
-- lineage from the naming-pipeline parent above. So the source was NOT already
-- correct, and this edit IS needed.
--
-- 1Lmhka14 file count: **0**, total and in-window. Trustworthy because 0 is below any
-- page cap. The current pipe genuinely discovers nothing.
-- ============================================================================


-- ============================================================================
-- 3. COUNTS — two measurements, two different questions, both correct.
--
--   folder                              via op_list      via the Google API directly
--   ----------------------------------  ---------------  ---------------------------
--   1Lmhka14… 'סרוקות מהמחסן 2026'      0                0
--   1stuMS…   'סרוקות- לפני שמות'       >=100 (capped)   not separately walked
--   1Ypap…    'סרוקות הצליח'            >=100 (capped)   17,067  (86 pages walked to
--                                                        completion, corpora=allDrives;
--                                                        prior run 17,066, +1 new)
--
-- USE 17,067. It is the real folder size, measured by the ground-truth lane straight
-- against Google with full pagination. My >=100 is NOT a competing estimate of the
-- folder and must not be read as one — it is a measurement OF `op_list`, which stops
-- at one page. The two findings answer different questions and do not conflict:
--   * "how big is 'סרוקות הצליח'?"          -> 17,067, verified.
--   * "what does op_list report it as?"      -> 100, which is the bug (see below).
--
-- 1Lmhka14's 0 is trustworthy from either path: 0 is below any cap, and the direct
-- walk agrees. That is what makes the source-folder rule-out in §2 safe.
--
-- THE op_list DEFECT (filed separately as issues/drive-op-list-single-page.yaml):
-- `op_list` (apps/drive/adapters/google.py:335-364) issues ONE request and returns
-- `.get("files")` from it — it never follows nextPageToken. Its sibling `_list()`
-- (:201-215) does paginate, and that one's own docstring warns a single request
-- "silently truncates any folder bigger than that" — but op_list, the canonical op
-- behind driveApi01, does not use it. Three unrelated folders each returned EXACTLY
-- 100 at both limit=100 and limit=1000: a cap signature, not a coincidence of totals.
-- limit=100000 fails outright (Drive rejects pageSize > 1000). Sync discovery is
-- unaffected in practice (`take: 50` bounds each pass), but any caller asking "how
-- many files are here" through that path is told 100 and believes it.
-- ============================================================================


-- ============================================================================
-- 4. WITHDRAWN FINDING — recorded so nobody re-derives it.
--
-- An earlier version of this file argued that indoxV2SearchWarehouse01.json:27
-- hardcoding 1YpapJ3v… was corroborating evidence that the sync pipe was misconfigured,
-- and hence that "FROM_OFFICE has been decided against a folder the pipe never ingested
-- from". **That inference was WRONG and is withdrawn.**
--
-- Per the owner: indoxV2SearchWarehouse01 is not a sync source and never was. Its only
-- job is a lookup — *is this document present in 'סרוקות הצליח'? then it came from the
-- warehouse.* Checking the DESTINATION folder is exactly the right way to answer that:
-- if the document landed there, it came through the warehouse scanning pipeline. The
-- hardcoded id is correct, deliberate, and unrelated to the sync registry.
--
-- Nothing about FROM_OFFICE / FROM_WAREHOUSE is defective here. That rename stays a
-- pure naming change (scripts/ops/rename-from-office-to-warehouse.py), not a bug fix.
-- ============================================================================


-- ---- THE WRITE. Requires owner approval. -----------------------------------
-- Surgical jsonb edit of the one entry, by name; the other 10 entries are untouched.
-- to_sync/from and synced/to move TOGETHER: _normalise_entry reconciles the two
-- vocabularies on every BFF write, and raw SQL bypasses that reconciliation, so
-- updating one spelling and not its twin leaves the entry internally inconsistent for
-- any reader that does not go through the BFF (e.g. SyncScanner00001's raw SQL read).
--
-- Side effect, intended: this also clears the three-way alias on
-- 1HoBifHSHmzk4cuaw6L98lwwTfQvyIdvH — warehouse stops sharing a `synced` folder with
-- drive-bs (and with the BalanceSheetDestFolder1 / ProcessedDocumentsFolder settings).
--
-- BEGIN;
-- update public.settings s
--    set value = (
--      select jsonb_agg(
--               case when e->>'name' = 'drive-gdoc-warehouse'
--                    then jsonb_set(jsonb_set(jsonb_set(jsonb_set(e,
--                           '{pairs,0,to_sync}', '"1stuMSjbnyUTCtbq6KIzooHCGXpEey_7P"'),
--                           '{pairs,0,from}',    '"1stuMSjbnyUTCtbq6KIzooHCGXpEey_7P"'),
--                           '{pairs,0,synced}',  '"1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu"'),
--                           '{pairs,0,to}',      '"1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu"')
--                    else e end
--             order by ord)
--      from jsonb_array_elements(s.value::jsonb) with ordinality t(e, ord)
--    )::text
--  where s.key = 'sync_registry';
-- COMMIT;
--
-- POST-CHECK after applying: re-run both queries below. Expect drive-gdoc-warehouse to
-- read to_sync=from=1stuMS… and synced=to=1Ypap…, and the second query to return
-- ZERO rows (no two pipes sharing a synced folder).

\echo '--- PRE/POST CHECK: warehouse vs the pipes it currently collides with ---'
select e->>'name' as pipe,
       e->'pairs'->0->>'to_sync' as to_sync,
       e->'pairs'->0->>'from'    as from_alias,
       e->'pairs'->0->>'synced'  as synced,
       e->'pairs'->0->>'to'      as to_alias
from public.settings s, jsonb_array_elements(s.value::jsonb) e
where s.key = 'sync_registry'
  and e->>'name' in ('drive-gdoc-warehouse','drive-bs','drive-gdoc-tzat','drive-gdoc');

\echo '--- any pipes still SHARING a synced folder? (any row = collision) ---'
select e->'pairs'->0->>'synced' as synced_folder,
       count(*) as pipes, string_agg(e->>'name', ', ') as which
from public.settings s, jsonb_array_elements(s.value::jsonb) e
where s.key = 'sync_registry' and e->'pairs'->0->>'synced' is not null
group by 1 having count(*) > 1;
