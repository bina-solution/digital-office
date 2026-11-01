-- ============================================================================
-- 2026-08-06 — DOC_ID category-E resolution (the 287 left NULL by the first pass)
--
-- Follows 2026-08-06_doc_id_consolidation.sql. That migration resolved 5,585 rows
-- and correctly left 287 with DOC_ID NULL: every one has AI_DOC_ID populated and the
-- AI value matched NEITHER stored column, so no rule in the first pass could fire.
--
-- *** NO LATERAL ANYWHERE IN THIS FILE. *** The first migration's `FROM LATERAL (...)`
-- form is rejected by Postgres in UPDATE ... FROM — a LATERAL subquery may not reference
-- the update target ("invalid reference to FROM-clause entry for table d"). Every
-- normalisation below is inlined into the predicate instead. The same defect is present
-- in the reference file scripts/ops/indox-column-consolidation.sql §2.7 and is corrected
-- there too.
--
-- BACKUP: data/_registry_backup/incoming_documents.pre-docid.sql (9.4 MB) covers the
-- pre-DOC_ID state. Take a fresh one before running this if that dump has aged.
-- ============================================================================
--
-- METHOD — same corpus-consistency principle as the first 35, mechanised.
-- DIGITS ARE THE INVARIANT. OCR drops and garbles LETTERS far more often than digits, so
-- "the two readings share a digit string" is the signal that they are the same document,
-- and the LETTER COUNT then says which reading is more complete. That single idea
-- classifies 279 of 287 without opening a document.
--
-- Corroboration that it is the stored value losing letters and not the AI inventing them
-- (per-company, against rows the first migration already resolved):
--     גולמט         dominant stored prefix IKG (23 rows)  -> 'KG2601293'  lost the I
--     דור רפאל      dominant stored prefix SI  (58 rows)  -> 25 of 26 AI values match
--     רויאל לתעשיה  dominant stored prefix INV            -> 18 of 18 AI values match
--     וויז אלקטריק  dominant stored prefix INV (6 rows)   -> 6 of 6 match
-- Same supplier, same series, some rows stored correctly and some with a letter missing.
--
-- OUTCOME       take AI 125 · keep COMPANY_DOC_ID 159 · quarantine 3   (= 287)
-- ============================================================================


\echo '=== PRE-CHECK: must report 287 ==='
select count(*) as unresolved_before
from public.incoming_documents
where coalesce("DOC_ID",'') = ''
  and (coalesce("COMPANY_DOC_ID",'') <> '' or coalesce("INVOICE_ID",'') <> '');


-- ---------------------------------------------------------------------------
-- STEP 1 — TAKE AI_DOC_ID  (expect UPDATE 125)
--
-- 1a. same digits, AI carries MORE letters -> AI restored a dropped prefix/infix.
--     Covers both 'KG…'->'IKG…' (front) and 'S26…'->'SI26…' (infix), which is why a
--     plain "AI extends at the front" test was not enough — the infix family failed it.
-- 1b. stored value is provably not a document id at all (the company's own ח.פ.,
--     an amount like '1.00', a date like '01/25').
-- 1c. eight explicitly-listed rows adjudicated by hand, below.
--
-- EXCLUDES the anagram/rotation rows (see step 2b) — those are AI reordering the same
-- characters, not adding information.
-- ---------------------------------------------------------------------------
-- BEGIN;
-- update public.incoming_documents
--    set "DOC_ID" = nullif("AI_DOC_ID",'')
--  where coalesce("DOC_ID",'') = ''
--    and coalesce("AI_DOC_ID",'') <> ''
--    and (
--      -- 1a: same digit string, AI has strictly more letters
--      (    regexp_replace(upper(regexp_replace(coalesce("AI_DOC_ID",''),      '[^a-zA-Z0-9]','','g')),'[^0-9]','','g')
--         = regexp_replace(upper(regexp_replace(coalesce("COMPANY_DOC_ID",''), '[^a-zA-Z0-9]','','g')),'[^0-9]','','g')
--       and length(regexp_replace(upper(regexp_replace(coalesce("AI_DOC_ID",''),      '[^a-zA-Z0-9]','','g')),'[^A-Z]','','g'))
--         > length(regexp_replace(upper(regexp_replace(coalesce("COMPANY_DOC_ID",''), '[^a-zA-Z0-9]','','g')),'[^A-Z]','','g'))
--      )
--      -- 1b: stored value is not an identifier
--      or "COMPANY_DOC_ID" ~ '^[0-9]+\.[0-9]{2}$'                    -- amount, e.g. '1.00'
--      or "COMPANY_DOC_ID" ~ '^[0-9]{1,2}/[0-9]{2}$'                 -- date,   e.g. '01/25'
--      or (coalesce("COMPANY_ID",'') <> ''
--          and regexp_replace(coalesce("COMPANY_DOC_ID",''),'[^0-9]','','g')
--            = regexp_replace(coalesce("COMPANY_ID",''),   '[^0-9]','','g'))   -- the company's own ח.פ.
--      -- 1c: hand-adjudicated
--      or "ID" in (
--           '17810875569799xndcg',  -- גולמט IKC2605600 -> IKG2605600; company's 23 resolved rows all read IKG
--           '17778912778256ohm5e',  -- בי גי 26002558 -> 02TSI26002558; siblings 02TS26005278/9 resolved the same way
--           '1777328022306a2pruv',  -- פרומט 2600004031 -> 12600004031; AI restores a leading 1
--           '177384541570816bkvn',  -- רויאל לתעשיה 04152 -> INV/2026/04152; company prefix INV matched 18/18
--           '17740514336647htug7',  -- סמארט - כשר: stored is the literal string 'ACTION_REQUIRED'
--           '17738434805847sn6hk'   -- מ.צ. שלטים:  stored is the literal string 'ACTION_REQUIRED'
--         )
--    )
--    -- never let a pure reordering win (step 2b)
--    and "ID" not in ('17713194840013kme1b','17784895746302c2pit',
--                     '1781602885578c6e4a0','17720211885492nyz4t');
-- COMMIT;


-- ---------------------------------------------------------------------------
-- STEP 2 — KEEP COMPANY_DOC_ID  (expect UPDATE 159)
--
-- 2a. The AI dissents but the TWO stored columns agree with each other. 278 of the 287
--     have COMPANY_DOC_ID = INVOICE_ID — two independently-written sources agreeing
--     against one dissenting reader. Where the AI has not demonstrably restored missing
--     letters (step 1), the agreeing pair wins.
-- 2b. Four rows where the AI merely ROTATED the stored value — same character multiset,
--     prefix moved to the end. That is an AI formatting artifact, not new information,
--     and the stored value is the correct one:
--         אלי אנגל    IN2640677   -> AI '2640677IN'
--         אלי אנגל    IN2641628   -> AI '2641628IN'
--         ע.ד.א פלסט  A26003826   -> AI '26003826A'
--         איטונג      SI266003783 -> AI '266003783SI'
-- ---------------------------------------------------------------------------
-- BEGIN;
-- update public.incoming_documents
--    set "DOC_ID" = nullif("COMPANY_DOC_ID",'')
--  where coalesce("DOC_ID",'') = ''
--    and coalesce("COMPANY_DOC_ID",'') <> ''
--    and "ID" not in (   -- the 3 genuinely unresolvable rows, step 3
--         '17786676480693hcasc','17763491884512jzhmi','17695845798568tky6i');
-- COMMIT;


-- ---------------------------------------------------------------------------
-- STEP 3 — QUARANTINE. 3 rows keep DOC_ID NULL. Do not guess these.
--
--   17786676480693hcasc  דפוס תכלת     15513 / 15355 / AI 14849
--       Three unrelated 5-digit numbers, no corroborating pattern. Unresolved since the
--       first pass; still the honest answer.
--   17763491884512jzhmi  מכוורת ארקין  'ACTION_REQUIRED' / — / AI '234'
--       Stored is a STATUS string, so it is certainly wrong — but AI '234' is too short
--       to trust as a document id on its own. Both sides unusable.
--   17695845798568tky6i  סאן דק        34385 / — / AI 36558
--       Two different plausible ids, nothing to choose between them.
-- ---------------------------------------------------------------------------


\echo '=== POST-CHECK (run after steps 1 and 2): must report exactly 3 ==='
select count(*) as still_unresolved
from public.incoming_documents
where coalesce("DOC_ID",'') = ''
  and (coalesce("COMPANY_DOC_ID",'') <> '' or coalesce("INVOICE_ID",'') <> '');

\echo '=== POST-CHECK: the 3 must be exactly these ==='
select "ID", "COMPANY_NAME", "COMPANY_DOC_ID", "INVOICE_ID", "AI_DOC_ID"
from public.incoming_documents
where coalesce("DOC_ID",'') = ''
  and (coalesce("COMPANY_DOC_ID",'') <> '' or coalesce("INVOICE_ID",'') <> '')
order by "ID";


-- ============================================================================
-- SEPARATE FINDING, NOT FIXED HERE — 'ACTION_REQUIRED' IS LEAKING INTO A DATA COLUMN.
-- Three rows carry the literal STATUS string 'ACTION_REQUIRED' in COMPANY_DOC_ID:
--   17740514336647htug7 (סמארט - כשר) · 17738434805847sn6hk (מ.צ. שלטים) ·
--   17763491884512jzhmi (מכוורת ארקין)
-- A status value written into a document-identifier column is a writer bug, and the
-- rows above are only the ones that also reached category E — the true count of
-- ACTION_REQUIRED-in-COMPANY_DOC_ID should be measured table-wide and the writer found.
-- Worth its own issue; deliberately out of scope for this migration.
-- ============================================================================
