-- ============================================================================
-- INDOX column consolidation + SHORT_DOC_ID repair — MIGRATION, NOT YET RUN
-- ============================================================================
--
--   *** DO NOT RUN ANY SECTION OF THIS FILE WITHOUT THE OWNER'S EXPLICIT     ***
--   *** PER-SECTION APPROVAL. Every UPDATE here is a mass write against the  ***
--   *** live `incoming_documents` table. Sections are ordered but INDEPENDENT ***
--   *** — approve and run them one at a time, re-running the PREFLIGHT block  ***
--   *** immediately before each one.                                          ***
--
-- Written 2026-08-06. Every count below was MEASURED against the live table on
-- that date (supabase-db-shlomo-laptop, 6,318 rows, 98 columns). Re-run the
-- preflights before acting: the numbers WILL have moved.
--
-- WHAT IS ALREADY DONE (do not redo):
--   * schema.sql already ADDS "DOC_ID", "FROM_WAREHOUSE", "FROM_WAREHOUSE_CHECK"
--     and the 7 LOCAL_* columns. They exist live and are 100% NULL.
--   * indoxDataGateway01's KNOWN_FIELDS allow-list has been regenerated so those
--     columns are no longer silently dropped on write
--     (scripts/refactor/gen-gateway-trigger-schema.py --check → OK).
--   * indoxDocBatchUpsert01's trigger jsonExample gained `priority_sync` (G39 PASS).
--
-- WHAT THIS FILE DOES NOT DO: it does not repoint a single writer. Every n8n /
-- Python / TS writer still writes the OLD column names. These backfills are the
-- "additive-first, dual-write, then cut over" middle step — running them makes the
-- NEW columns correct AS OF THE MOMENT THEY RUN, and they will immediately start
-- going stale again until the writers are migrated. Do not treat a green backfill
-- as "the rename is done".
--
-- ============================================================================


-- ============================================================================
-- SECTION 0 — PREFLIGHT. Read-only. Safe to run any time. RUN THIS FIRST.
-- ============================================================================
\echo '--- 0.1 table size + new-column emptiness (expect the 3 new cols at 0) ---'
select count(*)                                                        as total_rows,
       count(*) filter (where coalesce("DOC_ID",'')              <> '') as doc_id_pop,
       count(*) filter (where coalesce("FROM_WAREHOUSE",'')      <> '') as from_warehouse_pop,
       count(*) filter (where coalesce("FROM_WAREHOUSE_CHECK",'')<> '') as from_warehouse_check_pop,
       count(*) filter (where coalesce("COMPANY_DOC_ID",'')      <> '') as company_doc_id_pop,
       count(*) filter (where coalesce("INVOICE_ID",'')          <> '') as invoice_id_pop,
       count(*) filter (where coalesce("DOC_TOTAL_AMOUNT",'')    <> '') as doc_total_amount_pop,
       count(*) filter (where coalesce("TOTAL_AMOUNT",'')        <> '') as total_amount_pop,
       count(*) filter (where coalesce("FROM_OFFICE",'')         <> '') as from_office_pop,
       count(*) filter (where coalesce("FROM_OFFICE_CHECK",'')   <> '') as from_office_check_pop
from public.incoming_documents;
-- Measured 2026-08-06: 6318 total | DOC_ID 0 | FROM_WAREHOUSE 0 | FROM_WAREHOUSE_CHECK 0
--                    | COMPANY_DOC_ID 5842 | INVOICE_ID 3549
--                    | DOC_TOTAL_AMOUNT 3760 | TOTAL_AMOUNT 152
--                    | FROM_OFFICE 5697 | FROM_OFFICE_CHECK 5719


-- ============================================================================
-- SECTION 1 — SHORT_DOC_ID formula repair.
--
-- CONTEXT, AND THE MOST IMPORTANT THING IN THIS FILE:
-- There are two SEPARATE defects that have been conflated under "SHORT_DOC_ID
-- collisions". This section fixes only the FIRST one.
--
--   (a) FORMULA DIVERGENCE — three+ different derivations of the same label
--       across ingestion paths, so one logical id yields different strings
--       depending on which lane ingested it. MEASURED LIVE: 48 of 5,842 rows
--       (0.82%) disagree with the canonical formula. THIS SECTION FIXES THAT.
--
--   (b) TRUNCATION COLLISION — the label keeps only the last 5 alphanumeric
--       characters, so genuinely different documents legitimately collapse to
--       the same string. MEASURED LIVE: 364 collision groups on the live dedupe
--       key (COMPANY_ID, SHORT_DOC_ID) covering 786 rows; of those, 94 groups /
--       202 rows hold genuinely DIFFERENT full document ids. Example, real:
--         COMPANY_ID 511705477, SHORT_DOC_ID '55526' <- 6 distinct documents
--           125587D55526 / 126587055526 / 141717D55526 /
--           160040D55526 / 166944D55526 / 169420D55526
--       *** NO FORMULA FIXES THIS. *** All six collapse to '55526' under the
--       canonical formula too. Section 1 will NOT reduce the 202. The only fix
--       for (b) is to stop using SHORT_DOC_ID as a matching key — which is
--       exactly what indoxIdentity01 already mandates ("SHORT_DOC_ID is NEVER a
--       key here ... it is returned ONLY as a display label"). That is a
--       workflow change, not a data change, and it is NOT in this file.
-- ============================================================================

\echo '--- 1.1 PREFLIGHT: how many rows diverge from the canonical formula ---'
with c as (
  select "ID", "SHORT_DOC_ID", "COMPANY_DOC_ID", "SYNC_NAME", "SOURCE_TYPE",
         lpad(right(regexp_replace(coalesce("COMPANY_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0')
           as canonical
  from public.incoming_documents
  where coalesce("COMPANY_DOC_ID",'') <> ''
)
select count(*)                                                        as rows_considered,
       count(*) filter (where "SHORT_DOC_ID" = canonical)              as already_canonical,
       count(*) filter (where "SHORT_DOC_ID" is distinct from canonical) as would_change
from c;
-- Measured 2026-08-06: 5842 considered | 5794 canonical | 48 would change

\echo '--- 1.2 PREFLIGHT: the exact rows that would change (REVIEW BEFORE RUNNING 1.3) ---'
with c as (
  select "ID", "SHORT_DOC_ID", "COMPANY_DOC_ID", "SYNC_NAME", "SOURCE_TYPE", "STATUS",
         lpad(right(regexp_replace(coalesce("COMPANY_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0')
           as canonical
  from public.incoming_documents
  where coalesce("COMPANY_DOC_ID",'') <> ''
)
select "ID", "COMPANY_DOC_ID", "SHORT_DOC_ID" as current_value, canonical as new_value,
       "SOURCE_TYPE", "STATUS"
from c
where "SHORT_DOC_ID" is distinct from canonical
order by "SOURCE_TYPE", "ID";

\echo '--- 1.3 PREFLIGHT: would the repair CREATE any new collision? (must be 0) ---'
-- Guards against the repair itself merging two currently-distinct dedupe keys.
with c as (
  select "ID", coalesce("COMPANY_ID",'') as cid, "SHORT_DOC_ID",
         lpad(right(regexp_replace(coalesce("COMPANY_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0')
           as canonical
  from public.incoming_documents
  where coalesce("COMPANY_DOC_ID",'') <> ''
),
after as (select "ID", cid, canonical as sid from c)
select count(*) as new_collision_groups
from (select cid, sid from after group by cid, sid having count(*) > 1) x
where not exists (
  select 1 from c where c.cid = x.cid and c."SHORT_DOC_ID" = x.sid
);

-- ---- 1.4 THE WRITE. Requires owner approval. -------------------------------
-- BACK UP FIRST:
--   pg_dump -U postgres -d postgres -t public.incoming_documents \
--     > incoming_documents.pre-shortdocid-repair.$(date +%Y%m%dT%H%M%S).sql
--
-- BEGIN;
-- update public.incoming_documents
--    set "SHORT_DOC_ID" =
--          lpad(right(regexp_replace("COMPANY_DOC_ID", '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0')
--  where coalesce("COMPANY_DOC_ID",'') <> ''
--    and "SHORT_DOC_ID" is distinct from
--          lpad(right(regexp_replace("COMPANY_DOC_ID", '[^a-zA-Z0-9]', '', 'g'), 5), 5, '0');
-- -- expect: UPDATE 48   <-- if this number is wildly different, STOP and re-review
-- -- ROLLBACK;   <-- run this first and confirm the count, THEN re-run with COMMIT
-- COMMIT;


-- ============================================================================
-- SECTION 2 — DOC_ID consolidation (COMPANY_DOC_ID + INVOICE_ID -> DOC_ID).
--
-- *** THIS SECTION NEEDS AN OWNER DECISION BEFORE IT CAN BE WRITTEN CORRECTLY. ***
--
-- The two columns are NOT redundant copies of one value. MEASURED LIVE:
--   COMPANY_DOC_ID populated : 5,842
--   INVOICE_ID     populated : 3,549  (a strict subset of the above)
--   both populated           : 3,549
--     -> identical           : 3,030
--     -> DIFFERENT           :   519   <-- the whole problem
--
-- 519 live rows hold two different identifiers in these two columns. Collapsing
-- them into one DOC_ID silently discards one of the two values on 8.9% of the
-- rows that have both. Which one wins is a BUSINESS decision, not a technical
-- one, and it is not recorded anywhere in the repo.
--
-- *** MEASURED 2026-08-06: THE DISAGREEMENT IS NOT UNIFORM. It splits by TYPE, ***
-- *** and the two halves mean COMPLETELY DIFFERENT THINGS:                     ***
--
--   TYPE           both_populated   agree   disagree     disagreement rate
--   INVOICE                  3259    2955        304                  9.3%
--   SHIPMENT                  212       1        211                 99.5%   <-- !!
--   BALANCE_SHEET               4       1          3
--   UNKNOWN                    74      73          1
--
--   (1) On INVOICE rows the two values are, in the sampled cases, THE SAME
--       IDENTIFIER IN TWO NORMALISATIONS — COMPANY_DOC_ID is the punctuation-
--       stripped form, INVOICE_ID the raw extracted form:
--            26600025502  vs  26600025502-
--            01060522     vs  01/060522
--            FD1926001605 vs  FD19.26001605
--            1126009591   vs  11.26.009591
--       These are safe to consolidate. COMPANY_DOC_ID is the better survivor.
--
--       BUT a minority of INVOICE rows show COMPANY_DOC_ID as a LOSSY TRUNCATION
--       of INVOICE_ID, i.e. genuine corruption where leading digits were dropped:
--            COMPANY_DOC_ID 74043    vs INVOICE_ID 99474043
--            COMPANY_DOC_ID 472242   vs INVOICE_ID 99472242
--            COMPANY_DOC_ID 9472241  vs INVOICE_ID 99472241
--            COMPANY_DOC_ID 999403247 vs INVOICE_ID 99403247
--       On these, blindly preferring COMPANY_DOC_ID PRESERVES the corruption.
--       Section 2.4 below isolates them so they can be handled separately.
--
--   (2) On SHIPMENT rows the two columns are NOT the same concept at all.
--       99.5% disagree — that is a structural difference, not extraction noise.
--       The shipment lane uses COMPANY_DOC_ID for the SHIPMENT's own document id
--       and INVOICE_ID for the id of the INVOICE it is linked to (the same
--       relationship INV_ID_FOR_SHIP also encodes). Merging them into one DOC_ID
--       DESTROYS THE SHIPMENT->INVOICE LINK on ~211 live rows.
--
-- *** RECOMMENDATION: do NOT apply a single global DOC_ID rule. Consolidate the ***
-- *** GDoc/INVOICE lane only; leave the SHIPMENT lane's INVOICE_ID alone (or     ***
-- *** rename it to something honest like LINKED_INVOICE_DOC_ID) until the owner  ***
-- *** rules on it. A blanket "COMPANY_DOC_ID + INVOICE_ID -> DOC_ID" is a data-  ***
-- *** loss event for shipments.                                                  ***
-- ============================================================================

\echo '--- 2.1 PREFLIGHT: the 519 disagreeing rows — SHOW THESE TO THE OWNER ---'
select "ID", "TYPE", "STATUS", "COMPANY_DOC_ID", "INVOICE_ID", "SOURCE_TYPE", "SYNC_NAME"
from public.incoming_documents
where coalesce("COMPANY_DOC_ID",'') <> ''
  and coalesce("INVOICE_ID",'')     <> ''
  and "COMPANY_DOC_ID" is distinct from "INVOICE_ID"
order by "TYPE", "ID"
limit 100;

\echo '--- 2.2 PREFLIGHT: does the disagreement cluster by TYPE? (hints at the rule) ---'
select "TYPE",
       count(*)                                                              as both_populated,
       count(*) filter (where "COMPANY_DOC_ID" =  "INVOICE_ID")              as agree,
       count(*) filter (where "COMPANY_DOC_ID" is distinct from "INVOICE_ID") as disagree
from public.incoming_documents
where coalesce("COMPANY_DOC_ID",'') <> '' and coalesce("INVOICE_ID",'') <> ''
group by "TYPE" order by disagree desc;

\echo '--- 2.4 PREFLIGHT: INVOICE rows where COMPANY_DOC_ID looks like a LOSSY'
\echo '        truncation of INVOICE_ID (preferring COMPANY_DOC_ID keeps the bug) ---'
select "ID", "TYPE", "COMPANY_DOC_ID", "INVOICE_ID", "SOURCE_TYPE"
from public.incoming_documents
where coalesce("COMPANY_DOC_ID",'') <> ''
  and coalesce("INVOICE_ID",'')     <> ''
  and "COMPANY_DOC_ID" is distinct from "INVOICE_ID"
  -- same digits, but one is strictly shorter and is a suffix of the other
  and length(regexp_replace("COMPANY_DOC_ID", '[^0-9]', '', 'g'))
        < length(regexp_replace("INVOICE_ID", '[^0-9]', '', 'g'))
  and regexp_replace("INVOICE_ID", '[^0-9]', '', 'g')
        like '%' || regexp_replace("COMPANY_DOC_ID", '[^0-9]', '', 'g')
order by "TYPE", "ID";

-- ============================================================================
-- OWNER RULING, 2026-08-06 — this is the decision Section 2 was blocked on:
--
--   * "DOC_ID" means THE DOCUMENT'S OWN ID, uniformly, for every TYPE.
--   * The shipment's pointer to its linked invoice moves OUT of INVOICE_ID and
--     into the explicitly-named "LINKED_INVOICE_ID" (added in schema.sql).
--
-- So: one simple doc id everywhere, and nothing is lost.
--
-- VALUE-SELECTION RULE (which of the two source values becomes DOC_ID) --------
--
-- SUPERSEDED RULE (do not use): an earlier draft picked "the longer value when one
-- digit-string is a suffix of the other". Adjudicating its 8 hits individually showed
-- it is WRONG ON 3 OF 8, because OCR letter/digit confusion fools a digits-only test:
--     S1266001385 vs 266001385   -- the '1' is a misread 'I'; the digits-only test
--                                   counts the corrupted value as "longer" and prefers it
--     999403247   vs 99403247    -- a doubled leading digit reads as "more complete"
-- A digits-only comparison cannot see letters, which is exactly where the corruption
-- lives. It has been replaced.
--
-- ACTUAL RULE — AI AGREEMENT. AI_DOC_ID is an INDEPENDENT third reading of the same
-- document, so it breaks the tie on evidence instead of on string shape. Normalise all
-- three to uppercase-alphanumeric, then:
--
--   A. AI matches BOTH            -> COMPANY_DOC_ID   (punctuation-only difference)
--   B. AI matches COMPANY_DOC_ID  -> COMPANY_DOC_ID
--   C. AI matches INVOICE_ID      -> INVOICE_ID
--   D. no AI value at all         -> COMPANY_DOC_ID   (the resolved field; decide code
--                                    does COMPANY_DOC_ID = INVOICE_ID || AI_DOC_ID)
--   E. AI matches NEITHER         -> *** DO NOT AUTO-RESOLVE. LEAVE DOC_ID NULL. ***
--
-- MEASURED 2026-08-06 over all 308 disagreeing non-shipment rows:
--     A  236 | B  6 | C  10 | D  21 | E  35
-- So 273 of 308 (88.6%) resolve on independent evidence, and the 35 that do not are
-- quarantined rather than guessed at.
--
-- THE 35 CATEGORY-E ROWS, ADJUDICATED INDIVIDUALLY (2.6 lists them):
--   E1  (9 rows)  AI strictly EXTENDS one column at the front -- the stored value lost
--                 a leading prefix ('74043' vs '99474043', 'H2640018232' vs
--                 'NH2640018232'). AI_DOC_ID is the complete value.
--   E2a (19 rows) 'S<digits>' stored vs 'SI<digits>' from AI -- a single 'I' dropped
--                 after the S, consistent across EIGHT unrelated suppliers (נוברנד פלס,
--                 גולן פלסטיק, ניצבים עצמה, פרקט פוריו, מצרפלס, מילסטון, ארקו, צינומטל).
--                 Eight suppliers failing the same way is a systematic local-extraction
--                 defect, not eight coincidences; 'SI' is a standard sales-invoice
--                 prefix. ONE document check settles all 19.
--   E2b (4 rows)  '32/00570x' stored vs 'J2/00570x' from AI, one supplier (קרמיק דיפו).
--                 A classic 3-vs-J OCR confusion; the two readings are equally plausible
--                 from the string alone. ONE document check settles all 4.
--   E3  (3 rows)  All three sources disagree -- genuine extraction failure, no pattern:
--                   17735646311186svn69  41300 / 413.00 / 100953   (the '413.00' looks
--                                        like an AMOUNT misread as a document id)
--                   1774623286132fpkm8g  570117No / 570117_No / 12/570117
--                   17786676480693hcasc  15513 / 15355 / 14849
--                 Three rows, three separate hand decisions. No rule should touch them.
--
-- ADJUDICATED 2026-08-06 — all three classes settled from the corpus (full evidence
-- beside step 3 of 2.7). E1, E2a and E2b ALL resolve to AI_DOC_ID, as do 2 of the 3
-- E3 singletons. **34 of the 35 are now decided; exactly ONE row stays quarantined**
-- (17786676480693hcasc, three unrelated 5-digit numbers, needs a human to open the PDF).
--
-- So the final position for all 308 disagreeing non-shipment rows:
--     307 resolved by rule or adjudication · 1 awaiting a human
-- ============================================================================

\echo '--- 2.5 PREFLIGHT: which rule fires on each disagreeing non-shipment row ---'
with p as (
  select "ID",
         upper(regexp_replace(coalesce("COMPANY_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g')) as cd,
         upper(regexp_replace(coalesce("INVOICE_ID",''),     '[^a-zA-Z0-9]', '', 'g')) as iv,
         upper(regexp_replace(coalesce("AI_DOC_ID",''),      '[^a-zA-Z0-9]', '', 'g')) as ai
  from public.incoming_documents
  where coalesce("COMPANY_DOC_ID",'') <> '' and coalesce("INVOICE_ID",'') <> ''
    and "COMPANY_DOC_ID" is distinct from "INVOICE_ID"
    and coalesce("TYPE",'') is distinct from 'SHIPMENT'
)
select case when ai = ''             then 'D. no AI value        -> COMPANY_DOC_ID'
            when ai = cd and ai = iv then 'A. AI matches both    -> COMPANY_DOC_ID'
            when ai = cd             then 'B. AI matches CDI     -> COMPANY_DOC_ID'
            when ai = iv             then 'C. AI matches INV     -> INVOICE_ID'
            else                          'E. AI matches neither -> QUARANTINE'
       end as rule_fired,
       count(*) as rows
from p group by 1 order by 1;
-- Measured 2026-08-06: A 236 | B 6 | C 10 | D 21 | E 35   (total 308)

\echo '--- 2.6 PREFLIGHT: the 35 category-E rows, bucketed (see header for the ruling) ---'
with p as (
  select "ID", "STATUS", "COMPANY_DOC_ID", "INVOICE_ID", "AI_DOC_ID", "COMPANY_NAME",
         upper(regexp_replace(coalesce("COMPANY_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g')) as cd,
         upper(regexp_replace(coalesce("INVOICE_ID",''),     '[^a-zA-Z0-9]', '', 'g')) as iv,
         upper(regexp_replace(coalesce("AI_DOC_ID",''),      '[^a-zA-Z0-9]', '', 'g')) as ai
  from public.incoming_documents
  where coalesce("COMPANY_DOC_ID",'') <> '' and coalesce("INVOICE_ID",'') <> ''
    and "COMPANY_DOC_ID" is distinct from "INVOICE_ID"
    and coalesce("TYPE",'') is distinct from 'SHIPMENT'
), e as (select * from p where ai <> '' and ai <> cd and ai <> iv)
select case
         when (ai like '%'||cd and length(ai) > length(cd))
           or (ai like '%'||iv and length(ai) > length(iv)) then 'E1 lost-prefix -> AI_DOC_ID'
         when ai = 'SI' || substr(cd, 2) or ai = replace(cd, 'S', 'SI') then 'E2a S -> SI'
         else 'E2b / E3 -> HAND REVIEW'
       end as bucket,
       "ID", "STATUS", "COMPANY_DOC_ID", "INVOICE_ID", "AI_DOC_ID", "COMPANY_NAME"
from e order by 1, "ID";

-- ---- 2.7 THE WRITE. Requires owner approval. -------------------------------
-- BACK UP FIRST:
--   pg_dump -U postgres -d postgres -t public.incoming_documents \
--     > incoming_documents.pre-docid.$(date +%Y%m%dT%H%M%S).sql
--
-- Step 1 of 4 — SHIPMENT rows: own id -> DOC_ID, linked invoice -> LINKED_INVOICE_ID.
-- BEGIN;
-- update public.incoming_documents
--    set "DOC_ID"            = nullif("COMPANY_DOC_ID",''),
--        "LINKED_INVOICE_ID" = nullif("INVOICE_ID",'')
--  where "TYPE" = 'SHIPMENT'
--    and coalesce("DOC_ID",'') = '';
-- COMMIT;
--
-- Step 2 of 4 — every other TYPE, rules A-D only. Category E is deliberately NOT
-- matched here, so those 35 rows keep DOC_ID NULL and stay visible in 2.8.
-- BEGIN;
-- *** DO NOT reintroduce a LATERAL here. *** An earlier draft of this step factored the
-- three normalisations into `from lateral (select ... from d) r`. Postgres REJECTS that:
-- in UPDATE ... FROM, a LATERAL subquery may not reference the update target —
--     ERROR: invalid reference to FROM-clause entry for table "d"
-- The normalisations must be inlined into the predicate, verbosely, as below. Same rules,
-- same result, and it actually executes. (Confirmed the hard way on 2026-08-06.)
--
-- update public.incoming_documents
--    set "DOC_ID" = case
--          when upper(regexp_replace(coalesce("AI_DOC_ID",''), '[^a-zA-Z0-9]','','g')) <> ''
--           and upper(regexp_replace(coalesce("AI_DOC_ID",''), '[^a-zA-Z0-9]','','g'))
--             = upper(regexp_replace(coalesce("INVOICE_ID",''),'[^a-zA-Z0-9]','','g'))
--           and upper(regexp_replace(coalesce("AI_DOC_ID",''), '[^a-zA-Z0-9]','','g'))
--            <> upper(regexp_replace(coalesce("COMPANY_DOC_ID",''),'[^a-zA-Z0-9]','','g'))
--            then "INVOICE_ID"                                  -- rule C
--          else coalesce(nullif("COMPANY_DOC_ID",''),
--                        nullif("INVOICE_ID",''))               -- rules A, B, D
--        end
--  where coalesce("DOC_ID",'') = ''
--    and coalesce("TYPE",'') is distinct from 'SHIPMENT'
--    and (coalesce("COMPANY_DOC_ID",'') <> '' or coalesce("INVOICE_ID",'') <> '')
--    -- exclude category E: AI present and matching NEITHER stored column
--    and not (
--          upper(regexp_replace(coalesce("AI_DOC_ID",''),      '[^a-zA-Z0-9]','','g')) <> ''
--      and upper(regexp_replace(coalesce("AI_DOC_ID",''),      '[^a-zA-Z0-9]','','g'))
--       <> upper(regexp_replace(coalesce("COMPANY_DOC_ID",''), '[^a-zA-Z0-9]','','g'))
--      and upper(regexp_replace(coalesce("AI_DOC_ID",''),      '[^a-zA-Z0-9]','','g'))
--       <> upper(regexp_replace(coalesce("INVOICE_ID",''),     '[^a-zA-Z0-9]','','g')));
-- COMMIT;
--
-- Category E is then resolved by the follow-up migration
-- scripts/ops/migrations/2026-08-06_doc_id_category_e.sql (125 take-AI / 159 keep-stored
-- / 3 quarantined), which is written LATERAL-free for the same reason.
--
-- Step 3 of 4 — category E. ADJUDICATED 2026-08-06 against the corpus itself (see
-- the ADJUDICATION block below). 34 of the 35 resolve to AI_DOC_ID; 1 cannot be
-- settled from data and stays quarantined.
--
-- BEGIN;
-- update public.incoming_documents
--    set "DOC_ID" = nullif("AI_DOC_ID",'')
--  where coalesce("DOC_ID",'') = ''
--    and coalesce("AI_DOC_ID",'') <> ''
--    and "ID" in (
--      '17735646311186svn69','17739763446248fpo03','1774623286132fpkm8g','17748114455868wbwnt',
--      '1774811743853evt67s','17748120474289m1tpc','1774813542230c9hcbr','1776780881274cy1dpj',
--      '1776781022880ar6bse','17769546577377yulir','1777540290031cl4j7x','1777540598423dtpcb5',
--      '1777543294183g5jsf5','1777568769243c7a0vw','17778261628797eho2d','17779806638408l8c5h',
--      '17784144661777a15vb','1778664201277m9ynf','1779971919859ftiz6i','17801736900947yb8zg',
--      '1780322278548q53o3','17803393734061qs4sm','178033988977973prwf','17803401214861qjtb',
--      '1780340311197fcqp6','1780341274487ghi0z2','17803819368342jy8ye','17803822683843x6b1',
--      '178038263594162or5q','17803830813273builm','17803922808997zzxdx','1780425675629dxtd1s',
--      '1780831858884apmf64','1781165834865bhryso');
-- -- expect: UPDATE 34
-- COMMIT;
--
-- STILL QUARANTINED — 1 row, needs a human to open the PDF:
--   17786676480693hcasc  דפוס תכלת
--     COMPANY_DOC_ID 15513 | INVOICE_ID 15355 | AI_DOC_ID 14849 | NAME 'דפוס תכלת -15513'
--   Three different 5-digit numbers, no corroborating pattern anywhere in the corpus.
--   Do not guess. Leave DOC_ID null until someone reads the document.
--
-- ============================================================================
-- ADJUDICATION EVIDENCE — why 34 of 35 resolve to AI_DOC_ID
--
-- These were settled from the CORPUS, not from opening PDFs. That is deliberately
-- stronger evidence than a single document: it shows the same supplier's other
-- invoices, ingested by the same pipeline, stored correctly.
--
-- E2a — 'S<digits>' vs AI 'SI<digits>', 19 rows, 8 suppliers. AI IS RIGHT.
--   The suppliers' own documents use an 'SI' (sales-invoice) prefix, proven by their
--   NON-disputed rows where all three sources agree:
--       גולן פלסטיק   SI26004202 / SI26004202 / SI26004202   <- correct
--       גולן פלסטיק   SI26001548 / SI26001548 / SI26001548   <- correct
--       גולן פלסטיק   S26004185  / S26004185  / SI26004185   <- the 'I' dropped
--       גולן פלסטיק   26002498   / 26002498   / SI26002498   <- whole prefix dropped
--   Prefix-retention rates confirm it is the local extraction that is lossy, not the AI:
--       מילסטון     45 of 93 COMPANY_DOC_ID start 'SI', AI says 46
--       נוברנד פלס  35 of 96 start 'SI', AI says 46      (11 rows lost the prefix)
--       צינומטל      7 start 'SI', AI says 14            (7 rows lost it)
--   Same supplier, same document series, some rows right and some wrong => extraction
--   defect, not eight coincidences.
--
-- E2b — '32/00570x' vs AI 'J2/00570x', 4 rows, קרמיק דיפו. AI IS RIGHT, and the
--   original '3-vs-J OCR' framing was only half right. This supplier's ids carry a
--   letter+digit series prefix that VARIES by batch — G3/, H2/, G2/, J2/ all appear:
--       002701 / 002701 / G3/002701
--       004358 / 004358 / H2/004358
--       004716 / 004716 / G2/004716
--       005710 / 005710 / J2/005710     <- immediate numeric neighbours of the disputed
--       005712 / 005712 / J2/005712        rows, all read J2 by the AI
--       005715 / 005715 / J2/005715
--       32/005716 / 32/005716 / J2/005716  <- the same '32' misread, on a 5th row
--   The four disputed ids (005707/005708/005709/005711) sit inside the 005710-005716
--   J2 run. '32' is a misread of 'J2'. Decisive.
--
-- E3 — 3 singletons, adjudicated individually:
--   17735646311186svn69  ארקו  41300 / 413.00 / AI 100953  -> TAKE AI.
--     '413.00' is amount-shaped and '41300' is the same string with the dot stripped,
--     so BOTH columns descend from one misread of an amount as a document id. The AI
--     is the only independent reading. (Row's real DOC_TOTAL_AMOUNT is 55263, so
--     413.00 is not even the total — it is a stray figure off the page.)
--     Confidence: medium. Worth a spot-check, but no column value is defensible.
--   1774623286132fpkm8g  גוטמן ברזילי  570117No / 570117_No / AI 12/570117  -> TAKE AI.
--     Both columns end in 'No' — the OCR swallowed the literal label 'No.' (number)
--     into the value. The real id is 570117, and the AI's '12/' series prefix matches
--     the NN/NNNNNN format this corpus shows for the same supplier family
--     (12/573214, 12/161125 appear on other rows). Confidence: good.
--   17786676480693hcasc  דפוס תכלת  15513 / 15355 / AI 14849  -> QUARANTINE (above).
-- ============================================================================
--
-- Step 4 of 4 — reconcile INV_ID_FOR_SHIP (305 populated) with LINKED_INVOICE_ID.
-- These encode the SAME shipment<->invoice relationship from opposite sides; do not
-- drop either until the owner confirms which direction is authoritative. Report first:
-- select count(*) from public.incoming_documents
--  where coalesce("INV_ID_FOR_SHIP",'') <> '' and coalesce("LINKED_INVOICE_ID",'') <> ''
--    and "INV_ID_FOR_SHIP" is distinct from "LINKED_INVOICE_ID";
--
-- DO NOT DROP COMPANY_DOC_ID or INVOICE_ID in the same change. The drop is a
-- separate, later step, after every writer is repointed and DOC_ID has been
-- observed tracking correctly through a full processing cycle.

-- NOTE 1: 2.4 is retained only as EVIDENCE FOR WHY THE DIGITS-ONLY TEST WAS REJECTED.
--   It is not part of the rule set. Its 8 hits were adjudicated individually against
--   AI_DOC_ID and it was wrong on 3 of them. One of its hits is worth recording because
--   it was flagged as a suspected false positive and turned out NOT to be one:
--     ID 17798994459594ndrt3  COMPANY_DOC_ID 'PO26000591'  INVOICE_ID 'FD19.26000591'
--   Those two share the digit suffix 26000591 but the 'PO' vs 'FD19' prefixes suggest
--   a purchase order and an invoice. AI_DOC_ID reads 'FD19.26000591', agreeing with
--   INVOICE_ID, so 'PO26000591' is a purchase-order reference that wrongly landed in
--   COMPANY_DOC_ID. Rule C resolves it correctly with no hand intervention.
--
-- NOTE 2: 2.8 below reads "LINKED_INVOICE_ID", which only exists once schema.sql has
--   been re-applied to the target database. Running this file against a DB that has
--   not had the new schema applied yet will raise
--   `ERROR: column "LINKED_INVOICE_ID" does not exist` HERE and only here — that is
--   expected, harmless, and means exactly what it says.
\echo '--- 2.8 POST-CHECK (run AFTER 2.7): every row with a source id has a DOC_ID ---'
\echo '        after all 3 write steps, missing_doc_id must be exactly 1'
\echo '        (17786676480693hcasc, the single un-adjudicable row)'
select count(*) filter (where coalesce("DOC_ID",'') = ''
                          and (coalesce("COMPANY_DOC_ID",'') <> ''
                            or coalesce("INVOICE_ID",'') <> ''))        as missing_doc_id,
       count(*) filter (where "TYPE" = 'SHIPMENT'
                          and coalesce("LINKED_INVOICE_ID",'') = ''
                          and coalesce("INVOICE_ID",'') <> '')          as shipments_missing_link
from public.incoming_documents;


-- ============================================================================
-- SECTION 3 — TOTAL_AMOUNT consolidation (DOC_TOTAL_AMOUNT -> TOTAL_AMOUNT).
--
-- Much safer than Section 2: the two columns are almost perfectly DISJOINT.
--   DOC_TOTAL_AMOUNT populated : 3,760   (written by the GDoc/Shipment lane)
--   TOTAL_AMOUNT     populated :   152   (written by the BS lane, which already
--                                         uses the bare target name today)
--   both populated             :    10   -> identical 2, DIFFERENT 8
-- Only 8 rows need a tie-break. Target name is TOTAL_AMOUNT (owner's ruling, and
-- the BS lane is already on it).
-- ============================================================================

\echo '--- 3.1 PREFLIGHT: the 8 rows where the two amounts disagree ---'
select "ID", "TYPE", "STATUS", "DOC_TOTAL_AMOUNT", "TOTAL_AMOUNT", "SOURCE_TYPE"
from public.incoming_documents
where coalesce("DOC_TOTAL_AMOUNT",'') <> ''
  and coalesce("TOTAL_AMOUNT",'')     <> ''
  and "DOC_TOTAL_AMOUNT" is distinct from "TOTAL_AMOUNT";

-- ---- 3.2 THE WRITE. Requires owner approval. -------------------------------
-- Fills TOTAL_AMOUNT only where it is EMPTY, so the BS lane's existing values
-- (and the 8 disagreements) are never overwritten — those 8 stay as-is and are
-- resolved by hand or left to the BS value, whichever the owner prefers.
--
-- BEGIN;
-- update public.incoming_documents
--    set "TOTAL_AMOUNT" = "DOC_TOTAL_AMOUNT"
--  where coalesce("TOTAL_AMOUNT",'')     =  ''
--    and coalesce("DOC_TOTAL_AMOUNT",'') <> '';
-- -- expect: UPDATE 3750   (3760 minus the 10 already holding a TOTAL_AMOUNT)
-- COMMIT;


-- ============================================================================
-- SECTION 4 — FROM_OFFICE -> FROM_WAREHOUSE backfill.
--
-- Pure copy; no semantic decision. "office" was always the wrong word: these
-- documents come from the WAREHOUSE where goods are physically received.
--
-- SPELLING: the owner wrote "FROM_WHEARHOUSE". The correct English spelling
-- FROM_WAREHOUSE is used throughout, and it is ALREADY the spelling committed in
-- schema.sql and live in the database, so this is consistent with existing
-- convention rather than a fresh choice. Flagging it explicitly for confirmation.
--
--   FROM_OFFICE       populated: 5,697  (values: 'false' 3856 / 'true' 1841 / null 621)
--   FROM_OFFICE_CHECK populated: 5,719
--
-- *** DANGER — the string "FROM_OFFICE" has a SECOND, UNRELATED meaning. ***
-- It is also a STATUS enum value (UI category "attention", Hebrew label 'מהמשרד')
-- in three code sites. Those must NOT be renamed by this effort:
--   apps/indox/app/incoming_documents/api/__init__.py   (_DASH_STATUS_GROUP)
--   apps/indox/app/webapp/src/pages/DashboardPage.tsx
--   digital-office/sim/apps/indox/src/pages/DashboardPage.tsx
-- This SQL touches only the COLUMN, so it is unaffected — but any sed-style
-- rename of the code layer will corrupt those three unless they are excluded.
-- ============================================================================

-- ---- 4.1 THE WRITE. Requires owner approval. -------------------------------
-- BEGIN;
-- update public.incoming_documents
--    set "FROM_WAREHOUSE"       = "FROM_OFFICE",
--        "FROM_WAREHOUSE_CHECK" = "FROM_OFFICE_CHECK"
--  where "FROM_OFFICE" is not null or "FROM_OFFICE_CHECK" is not null;
-- -- expect: UPDATE ~5719
-- COMMIT;

\echo '--- 4.2 POST-CHECK (run AFTER 4.1): must report 0 mismatches ---'
select count(*) as mismatched_rows
from public.incoming_documents
where "FROM_WAREHOUSE"       is distinct from "FROM_OFFICE"
   or "FROM_WAREHOUSE_CHECK" is distinct from "FROM_OFFICE_CHECK";


-- ============================================================================
-- SECTION 5 — POST-BACKFILL DRIFT WATCH.
--
-- Run this on a schedule during the dual-write window. Because NO writer has
-- been repointed yet, these numbers WILL drift apart again after each backfill.
-- That is expected. The window is only closed when the counts stay equal across
-- a full processing cycle WITHOUT re-running the backfill — that is the signal
-- that the writers have actually been migrated.
-- ============================================================================
\echo '--- 5.1 dual-write drift ---'
select
  count(*) filter (where "FROM_WAREHOUSE" is distinct from "FROM_OFFICE")             as from_warehouse_drift,
  count(*) filter (where coalesce("DOC_ID",'') = '' and coalesce("COMPANY_DOC_ID",'') <> '') as doc_id_missing,
  count(*) filter (where coalesce("TOTAL_AMOUNT",'') = ''
                     and coalesce("DOC_TOTAL_AMOUNT",'') <> '')                        as total_amount_missing
from public.incoming_documents;


-- ============================================================================
-- SECTION 6 — HASH: the rows with NO duplicate protection at all.
--
-- WHY THIS MATTERS FOR EVERYTHING ABOVE. indoxIdentity01 (the single identity
-- owner) demotes SHORT_DOC_ID to a display label and makes content HASH the thing
-- that decides "is this a true duplicate". That design is correct — but it only
-- works on rows that HAVE a HASH. `uq_incdoc_hash` is a PARTIAL unique index that
-- deliberately excludes null / empty / 'unknown', so every row without one gets
-- ZERO duplicate protection and is invisible to the constraint.
--
-- MEASURED 2026-08-06: 576 of 6,318 rows (9.1%) are unprotected.
--   (An earlier count of 495 was taken at 6,207 rows — the gap is GROWING, so this
--    is an active leak, not a fixed pool of legacy rows.)
--   Zero rows carry the literal string 'unknown'; the gap is entirely null/empty.
--
-- *** ALREADY BITING: 13 natural-key groups covering 228 rows have MORE THAN ONE ***
-- *** unprotected row sharing the same (SOURCE_TYPE, SOURCE_ID). Those are exactly ***
-- *** the duplicates the index cannot see. 101 of the 576 are already STATUS=DOUBLE. ***
--
-- THE GAP IS THREE DIFFERENT PROBLEMS, NOT ONE. Do not write a single backfill:
--
--   6a. 183 rows, SOURCE_TYPE='GOOGLE_DRIVE_FILE' — *** ROOT CAUSE FOUND 2026-08-06.
--       NOT legacy decay. These rows are hash-less BY CONSTRUCTION, and the leak is live.
--
--       HASH coverage is 100% on every healthy ingestion path and 0% here:
--           GOOGLE_DRIVE_FOLDER  3165 / 3165      GMAIL      2337 / 2337
--           WHATSAPP               43 /   43      MAIL_ATTACHMENT   9 /  9
--           GOOGLE_DRIVE_FILE       0 /  183  <-- every single one
--       A 0-of-183 split against 100% everywhere else is a writer defect, not attrition.
--
--       The writer is the `find_link` action's "Build: Call 'Incoming Document Batch
--       Update' - LINK FOUND" node (indoxV2ActionsGDoc01 / Ship01). It sets
--       SOURCE_TYPE='GOOGLE_DRIVE_FILE', overwrites SOURCE_ID with the Drive file id,
--       and writes  HASH = {{ $json.md5Checksum }}  and  SIZE = {{ $json?.size || null }}.
--       The node is CORRECT; its INPUT is incomplete —
--
--           apps/drive/adapters/google.py:27
--           FIELDS = "id,name,parents,size,mimeType,createdTime,webViewLink,trashed,
--                     owners(displayName,emailAddress)"
--
--       `md5Checksum` IS ABSENT from that projection, and FIELDS is what `_list()` sends
--       as `fields=files(...)` for every `op_list` — the call behind driveApi01, behind
--       indoxV2SearchFile01 / indoxV2SearchWarehouse01, behind `find_link`. So
--       `$json.md5Checksum` is STRUCTURALLY always undefined there and HASH is blanked
--       every time. Confirmed by prediction-then-test: SIZE is empty on the same 183
--       rows while NAME and LINK are present on all 183.
--       (The healthy sync path gets its md5 from the UPLOAD response instead —
--        op_upload uses fields='*', which its own docstring notes syncV3Deliver
--        hard-requires — which is why that path is unaffected.)
--
--       *** THE FIX IS ONE LINE: add `md5Checksum` to FIELDS in google.py:27. ***
--       That is in apps/drive, outside this refactor's lane and shared by every drive
--       caller, so it is REPORTED here rather than applied. Do that first — otherwise
--       any backfill is immediately re-diluted by the next document that hits find_link.
--
--       WORSE THAN A MISSING COLUMN: `find_link` REPLACES the row's natural key
--       (SOURCE_TYPE and SOURCE_ID both overwritten) at the same moment it blanks HASH,
--       so the row loses its duplicate protection exactly as its identity changes. 4 of
--       6 sampled rows are already STATUS='DOUBLE'.
--
--       *** SUPERSEDED 2026-08-06 — 6a IS NOW OWNED BY scripts/ops/indox-rehash-missing.py. ***
--       Read that file, not this paragraph. Three corrections to what is written above:
--
--       (i)  The root cause above (FIELDS / apps/drive) is WRONG and was retracted. The
--            real cause is the n8n GoogleDrive node: with `options.fields` unset, its own
--            `prepareQueryString(undefined)` returns the literal 'id, name', so it asked
--            Drive for `files(id, name)` — no md5Checksum, no size. That is why exactly
--            SIZE and HASH are empty while NAME and SOURCE_ID are populated.
--       (ii) HISTORICAL, not a live leak: 0 new GOOGLE_DRIVE_FILE rows since the
--            2026-08-05 restore, and 'LINK FOUND' appears in ACTION_LOG on 0 rows.
--       (iii)My "every Drive fetch 404s" blocker was MY OWN CALLER BUG, not the
--            environment: I passed fileIdMode "link", but extract_file_id
--            (apps/drive/adapters/opsupport.py:29-38) parses a URL only for mode "url"
--            and returns the raw string for anything else — so Google received a whole
--            URL as a file id. Same host, same file, mode "url": 669,521 bytes. Drive was
--            always reachable.
--
--       SCOPE CORRECTION — only 70 of the 183 are safely fillable. 113 would collide with
--       a HASH another row already holds, and 61 of those are currently counted as
--       genuine COMPLETED documents. A blanket `SET HASH = API_TOOLS_ID` fails on
--       uq_incdoc_hash for every one of the 113 — correctly. That is the constraint doing
--       its job, not an obstacle to route around.
--
--       *** NEVER SUBSTITUTE ONE HASH FOR THE OTHER. *** Drive md5 and apitools
--       `file_hash` are NOT interchangeable: 725 of 3,092 GOOGLE_DRIVE_FOLDER rows
--       disagree, with HASH matching the current Drive bytes and API_TOOLS_ID not.
--       Drive md5 is primary; apitools' hash is a fallback only. Overwriting a good
--       Drive md5 with an apitools hash silently corrupts content identity on rows that
--       are currently correct.
--
--   6b. NOT APPLICABLE — 225 rows, SOURCE_TYPE='BALANCE_SHEET' (184) or 'INVOICE' (41).
--       These are the per-line rows the BS lane SPAWNS from BS_EXTRACTED_LINES
--       (indoxV2ActionsBS01's link_documents action). They have NO FILE OF THEIR OWN —
--       0 of the 184 have a LINK or an API_TOOLS_ID. A content md5 is meaningless for
--       them and will never exist. They must NOT be counted as a backfill gap.
--       They need a DIFFERENT identity: deterministic on (parent BS document, line
--       index), which is precisely what the new bs_extracted_lines child table
--       (schema.sql) is for. Either give them a synthetic HASH derived from that pair,
--       or exempt them explicitly — but decide, because today they are silently
--       pooled with the recoverable rows and inflate the gap by 39%.
--
--   6c. UNRECOVERABLE LEGACY — 168 rows, SOURCE_TYPE null. Only 37 have a LINK.
--       Pre-CONNECTION-era rows. Quarantine and review; do not guess a hash.
--
-- PREREQUISITE FOR THE BOARD-ITEM JOIN: make HASH mandatory AT DELIVERY. Drive's
-- md5Checksum is already read by SyncProcGDoc0001/SyncProcBS000001 and delivery
-- already throws when it is absent — so the CURRENT path is sound and 6a/6c are
-- historical. The live leak to close is 6b, which is not a delivery failure at all
-- but a class of row that delivery never sees.
-- ============================================================================

\echo '--- 6.1 the gap, split by the three problems above ---'
select case
         when "SOURCE_TYPE" = 'GOOGLE_DRIVE_FILE'            then '6a recoverable (re-fetch md5)'
         when "SOURCE_TYPE" in ('BALANCE_SHEET','INVOICE')   then '6b BS-spawned line (no file exists)'
         else                                                     '6c legacy, SOURCE_TYPE null'
       end as bucket,
       count(*) as rows,
       count(*) filter (where coalesce("LINK",'') <> '')         as has_link,
       count(*) filter (where coalesce("API_TOOLS_ID",'') <> '') as has_apitools_id,
       count(*) filter (where "STATUS" = 'DOUBLE')               as already_double
from public.incoming_documents
where "HASH" is null or "HASH" = '' or lower("HASH") = 'unknown'
group by 1 order by 2 desc;

\echo '--- 6.2 THE 6a WORKLIST — feed these to the re-hash pass ---'
select "ID", "LINK", "API_TOOLS_ID", "STATUS", "SOURCE_ID"
from public.incoming_documents
where ("HASH" is null or "HASH" = '' or lower("HASH") = 'unknown')
  and "SOURCE_TYPE" = 'GOOGLE_DRIVE_FILE'
  and coalesce("LINK",'') <> ''
order by "ID";

-- *** CORRECTION 2026-08-06 — 6.3 BELOW IS KEYED ON THE WRONG COLUMN. ***
-- An earlier pass of this file reported "13 natural-key groups covering 228 rows have
-- more than one unprotected row sharing (SOURCE_TYPE, SOURCE_ID)" and called them
-- duplicates the index cannot see. **Retract that.** The ground-truth lane has since
-- proven SOURCE_ID IS NOT A DOCUMENT ID: it holds the FOLDER id for Drive rows and the
-- SENDER ADDRESS for Gmail rows — 583 distinct values across 6,150 rows. So rows
-- "sharing a natural key" mostly just share a folder or a sender, and 6.3's groups are
-- an artefact of the wrong key, not evidence of duplication.
--
-- The real content/identity keys are:
--     HASH        = Drive md5Checksum  (98.8% hit rate — the actual content key)
--     LINK        = Drive file id
--     SOURCE_LINK = Gmail message hex
--
-- This also bears on the identity consolidation: indoxIdentity01 defines
--     natural_key = (SOURCE_TYPE, SOURCE_ID)
-- and hands `candidates` to it on that basis. On this data that key is not selective,
-- so DOUBLE/MATCH/DUPLICATE adjudication is running on a column that identifies a
-- folder rather than a document. **Add this to the Phase-4 prerequisites already
-- recorded in scripts/refactor/single-identity-lint.py's docstring: the seed is one
-- defect, the natural key is a second, independent one.**
--
-- 6.3 is kept below ONLY as the evidence for this retraction — read its output as
-- "rows sharing a folder/sender", never as "duplicate documents".
\echo '--- 6.3 [MISKEYED — see correction above] rows sharing (SOURCE_TYPE, SOURCE_ID) ---'
select "SOURCE_TYPE", "SOURCE_ID", count(*) as rows,
       left(string_agg("ID", ', ' order by "ID"), 120) as sample_ids
from public.incoming_documents
where ("HASH" is null or "HASH" = '' or lower("HASH") = 'unknown')
  and coalesce("SOURCE_ID",'') <> ''
group by 1,2 having count(*) > 1
order by 3 desc;

-- ---- 6.4 THE WRITE (6b) — *** DRAFTED, THEN DISPROVED BY ITS OWN PREFLIGHT. ***
--
-- The obvious synthetic identity for a BS-spawned line is a hash of
--   (SOURCE_ID, COMPANY_DOC_ID, BS_LINE_DATE, BS_LINE_AMOUNT)
-- and that is what this section originally proposed. Running 6.5 against live data
-- BEFORE writing anything shows it is NOT UNIQUE: **7 colliding groups**. Two lines
-- on the same balance sheet with the same date and the same amount are common and
-- legitimate (two identical charges in one period), and no combination of columns
-- that exists on incoming_documents today separates them — the distinguishing fact
-- is the line's ORDINAL POSITION within the parent document, which this table has
-- never stored.
--
-- Writing the hash anyway would make uq_incdoc_hash reject the 2nd row of each of
-- those 7 groups — silently losing real balance-sheet lines. So:
--
--   *** RECOMMENDATION: do NOT synthesise a HASH for 6b now. EXEMPT these 225 rows ***
--   *** explicitly instead, and revisit only after they migrate to the new          ***
--   *** bs_extracted_lines child table, whose ("document_id", "line_index") pair is ***
--   *** exactly the missing ordinal and makes a unique synthetic key trivial.       ***
--
-- The exemption is documentation, not DDL: uq_incdoc_hash already ignores null HASH,
-- so leaving these rows alone IS the exemption. What must change is the reporting —
-- 6.1's bucketing is the thing that stops them being miscounted as a backfill gap.
-- Concretely: the real recoverable gap is 183 rows (6a), not 576.

\echo '--- 6.5 THE PROOF that 6.4 must not run: synthetic-hash collisions (nonzero = do not write) ---'
select count(*) as colliding_pairs from (
  select md5(coalesce("SOURCE_ID",'') || ':' || coalesce("COMPANY_DOC_ID",'') || ':' ||
             coalesce("BS_LINE_DATE",'') || ':' || coalesce("BS_LINE_AMOUNT",'')) as h
  from public.incoming_documents
  where ("HASH" is null or "HASH" = '')
    and "SOURCE_TYPE" in ('BALANCE_SHEET','INVOICE')
    and coalesce("LINK",'') = ''
  group by 1 having count(*) > 1
) x;
