-- 2026-08-06 — SHORT_DOC_ID: fill the EMPTY labels with the canonical formula.
--
-- This is scripts/ops/indox-column-consolidation.sql §1.4, DELIBERATELY NARROWED after live
-- measurement disproved the blanket form that file drafted. §1.4 as written would repair every row
-- that disagrees with the canonical formula. Measured 2026-08-06 at 6,405 rows, that is 70 rows —
-- and 16 of them must NOT be rewritten. §1.3's own guard says so: the blanket write creates 3 new
-- collision groups, and its precondition is that it create ZERO.
--
-- THE CANONICAL FORMULA (unchanged, this file does not invent one):
--     lpad(right(regexp_replace(COMPANY_DOC_ID, '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0')
-- the SQL equivalent of indoxIdentity01's "Compute Identity" node, which is the single identity
-- owner:  String(seed).replace(/[^a-zA-Z0-9]/g,'').slice(-5).padStart(5,'0')
--
-- ─── WHY THE 16 LABEL-HOLDING ROWS ARE EXCLUDED (evidence, not caution) ───────────────────────
-- On every one of them the label is NOT the untrustworthy field — COMPANY_DOC_ID is:
--
--   (a) 3 GMAIL rows carry the literal sentinel COMPANY_DOC_ID = 'ACTION_REQUIRED'. The canonical
--       formula turns that into the label 'UIRED'. Their CURRENT labels (08714 / 98932 / 00234)
--       each reproduce exactly from AI_DOC_ID (02/008714, 02/198932, 234) — verified per row. So
--       the stored label is already right and COMPANY_DOC_ID is the corrupted column. Repairing
--       here would destroy a correct label and write a garbage one, on three real client documents
--       (COMPANY_ID 516128592 / 558283362 / 036973469).
--
--   (b) 13 drive-gdoc rows ingested 2026-08-06 10:10-11:27 (ids doc_msh*, STATUS ACTION_RESTART or
--       OLD). Three of them share COMPANY_DOC_ID '1600326381' while holding three DIFFERENT labels
--       (67569 / 03716 / 59655); four share '862237' while holding four different labels
--       (01232 / 72227 / 01540 / 03420). Their NAME column embeds the current label
--       ("<COMPANY_NAME>-<SHORT_DOC_ID>") and the names differ accordingly, so the labels descend
--       from distinct source values while COMPANY_DOC_ID has been overwritten with a shared one.
--       Applying the formula would collapse seven distinct documents into two label buckets — the
--       exact collision §1.3 exists to prevent. These rows are real (real Hebrew supplier names,
--       LINK and HASH both populated), NOT load-test residue, despite the generated doc_* id.
--
-- So this file writes ONLY rows whose SHORT_DOC_ID is currently EMPTY: a fill that destroys no
-- existing label. The 16 are reported for a human decision, not guessed at.
--
-- ─── GUARDS PROVEN LIVE BEFORE THIS RAN ──────────────────────────────────────────────────────
--   fill candidates                                        54
--   of those, canonical would be the '00000' placeholder     0
--   of those, canonical contains no digit                    0
--   NEW (COMPANY_ID, SHORT_DOC_ID) collision groups created  1
--     -> the single group is 1778122125202117s2p + 1778134212410g7y6gy, which hold the SAME
--        COMPANY_DOC_ID 'IN264004296'. An identical document id SHOULD produce an identical label;
--        that is the truncation property §1(b) documents as unfixable by any formula, and here it
--        is not even truncation — the two ids are literally equal.
--
-- The '00000' and digit-free exclusions are kept in the predicate, not just asserted, so this file
-- stays correct if it is re-run later against a table that has moved.
--
-- Backup taken before this ran:
--   data/_registry_backup/incoming_documents.pre-shortdocid.20260806T150000Z.sql
--   9,550,625 bytes · 6,405 data rows
--   sha256 5b19df58cf8aad71dc81d8a3281b173b885980e9f248217e92bee353578b28ef
--
-- NOT FIXED HERE (workflow change, needs `bbox n8n push`): the formula itself still emits '00000'
-- from an EMPTY seed, and that placeholder is then used as a match key. See the report.

\set ON_ERROR_STOP on

BEGIN;
update public.incoming_documents
   set "SHORT_DOC_ID" =
         lpad(right(regexp_replace("COMPANY_DOC_ID", '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0')
 where coalesce("COMPANY_DOC_ID",'') <> ''
   and coalesce("SHORT_DOC_ID",'') = ''
   and lpad(right(regexp_replace("COMPANY_DOC_ID", '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0') <> '00000'
   and lpad(right(regexp_replace("COMPANY_DOC_ID", '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0') ~ '[0-9]';
-- expect: UPDATE 54
COMMIT;

\echo '--- POST-CHECK 1: rows still empty-labelled but holding a COMPANY_DOC_ID (expect 0) ---'
select count(*) as still_unlabelled
  from public.incoming_documents
 where coalesce("COMPANY_DOC_ID",'') <> '' and coalesce("SHORT_DOC_ID",'') = '';

\echo '--- POST-CHECK 2: remaining divergence = the 16 excluded rows, and ONLY those (expect 16) ---'
with c as (
  select "ID", "SHORT_DOC_ID",
         lpad(right(regexp_replace(coalesce("COMPANY_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0') as canonical
  from public.incoming_documents where coalesce("COMPANY_DOC_ID",'') <> ''
)
select count(*) as remaining_divergent,
       count(*) filter (where coalesce("SHORT_DOC_ID",'') = '') as of_which_still_empty
  from c where "SHORT_DOC_ID" is distinct from canonical;

\echo '--- POST-CHECK 3: the placeholder was never written as a NEW value (expect 12, unchanged) ---'
select count(*) as short_doc_id_00000 from public.incoming_documents where "SHORT_DOC_ID" = '00000';
