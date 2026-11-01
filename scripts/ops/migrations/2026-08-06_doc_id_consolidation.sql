-- 2026-08-06 — DOC_ID consolidation, owner-approved, executable migration.
--
-- Extracted verbatim from scripts/ops/indox-column-consolidation.sql SECTION 2 §2.7, which is a
-- reference/analysis document with every write commented out. This file is the runnable form.
--
-- Owner decision (recorded): COMPANY_DOC_ID and INVOICE_ID consolidate into DOC_ID = the document's
-- OWN id; a SHIPMENT's linked invoice moves to LINKED_INVOICE_ID rather than being discarded. That
-- ruling came after measurement showed the two columns disagree on 211 of 212 SHIPMENT rows (they
-- hold DIFFERENT documents there) while agreeing on 90.7% of INVOICE rows (same id, two
-- normalisations). A blanket merge would have destroyed the invoice link on every shipment.
--
-- Backup taken before this ran:
--   data/_registry_backup/incoming_documents.pre-docid.sql   (9.4 MB, 6540 lines)
--
-- Expected: step 1 ~212 · step 2 ~5,600 · step 3 exactly 34 · post-check missing_doc_id = 1
-- The single unresolved row (17786676480693hcasc) keeps DOC_ID NULL by design: three unrelated
-- 5-digit numbers, unsettleable from data. It stays visible rather than being guessed.

\set ON_ERROR_STOP on

-- Step 1 of 3 — SHIPMENT rows: own id -> DOC_ID, linked invoice -> LINKED_INVOICE_ID.
BEGIN;
update public.incoming_documents
   set "DOC_ID"            = nullif("COMPANY_DOC_ID",''),
       "LINKED_INVOICE_ID" = nullif("INVOICE_ID",'')
 where "TYPE" = 'SHIPMENT'
   and coalesce("DOC_ID",'') = '';
COMMIT;

-- Step 2 of 3 — every other TYPE, rules A-D. Category E is deliberately NOT matched here, so those
-- rows keep DOC_ID NULL and stay visible to the post-check.
--   rule C: AI agrees with INVOICE_ID and not COMPANY_DOC_ID -> INVOICE_ID
--   rules A/B/D: prefer COMPANY_DOC_ID, else INVOICE_ID
-- NOTE 2026-08-06: the reference version used `from lateral (...) r` to name the three normalised
-- forms once. Postgres rejects that in UPDATE ... FROM — a LATERAL subquery cannot reference the
-- update target ("invalid reference to FROM-clause entry for table d"). Rewritten with the
-- normalisation inlined. Same rules, same predicate, verified identical in behaviour.
BEGIN;
update public.incoming_documents d
   set "DOC_ID" = case
         when upper(regexp_replace(coalesce(d."AI_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g')) <> ''
          and upper(regexp_replace(coalesce(d."AI_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'))
            = upper(regexp_replace(coalesce(d."INVOICE_ID",''), '[^a-zA-Z0-9]', '', 'g'))
          and upper(regexp_replace(coalesce(d."AI_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'))
           <> upper(regexp_replace(coalesce(d."COMPANY_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'))
         then d."INVOICE_ID"                                          -- rule C
         else coalesce(nullif(d."COMPANY_DOC_ID",''),
                       nullif(d."INVOICE_ID",''))                      -- rules A, B, D
       end
 where coalesce(d."DOC_ID",'') = ''
   and coalesce(d."TYPE",'') is distinct from 'SHIPMENT'
   and (coalesce(d."COMPANY_DOC_ID",'') <> '' or coalesce(d."INVOICE_ID",'') <> '')
   -- exclude category E: AI present and matching neither column
   and not (upper(regexp_replace(coalesce(d."AI_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g')) <> ''
        and upper(regexp_replace(coalesce(d."AI_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'))
         <> upper(regexp_replace(coalesce(d."COMPANY_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'))
        and upper(regexp_replace(coalesce(d."AI_DOC_ID",''), '[^a-zA-Z0-9]', '', 'g'))
         <> upper(regexp_replace(coalesce(d."INVOICE_ID",''), '[^a-zA-Z0-9]', '', 'g')));
COMMIT;

-- Step 3 of 3 — category E, adjudicated 2026-08-06 against the corpus itself. 34 of 35 resolve to
-- AI_DOC_ID on independent evidence (the same supplier's other invoices stored correctly, e.g.
-- SI26004202 alongside S26004185 with the I dropped; J2/005710-J2/005716 bracketing four disputed
-- 32/00570x). The 35th is quarantined.
BEGIN;
update public.incoming_documents
   set "DOC_ID" = nullif("AI_DOC_ID",'')
 where coalesce("DOC_ID",'') = ''
   and coalesce("AI_DOC_ID",'') <> ''
   and "ID" in (
     '17735646311186svn69','17739763446248fpo03','1774623286132fpkm8g','17748114455868wbwnt',
     '1774811743853evt67s','17748120474289m1tpc','1774813542230c9hcbr','1776780881274cy1dpj',
     '1776781022880ar6bse','17769546577377yulir','1777540290031cl4j7x','1777540598423dtpcb5',
     '1777543294183g5jsf5','1777568769243c7a0vw','17778261628797eho2d','17779806638408l8c5h',
     '17784144661777a15vb','1778664201277m9ynf','1779971919859ftiz6i','17801736900947yb8zg',
     '1780322278548q53o3','17803393734061qs4sm','178033988977973prwf','17803401214861qjtb',
     '1780340311197fcqp6','1780341274487ghi0z2','17803819368342jy8ye','17803822683843x6b1',
     '178038263594162or5q','17803830813273builm','17803922808997zzxdx','1780425675629dxtd1s',
     '1780831858884apmf64','1781165834865bhryso');
COMMIT;

-- Post-check — missing_doc_id must be exactly 1 (the quarantined row).
select count(*) filter (where coalesce("DOC_ID",'') <> '')            as doc_id_populated,
       count(*) filter (where coalesce("LINKED_INVOICE_ID",'') <> '') as linked_invoice_populated,
       count(*) filter (where coalesce("DOC_ID",'') = ''
                          and (coalesce("COMPANY_DOC_ID",'') <> ''
                            or coalesce("INVOICE_ID",'') <> ''))      as missing_doc_id
  from public.incoming_documents;
