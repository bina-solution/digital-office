-- 2026-08-21 — C10: BS↔document linking becomes CONTINUOUS instead of one-shot-and-latched.
--
-- THE DEFECT
-- ----------
-- `indoxV2ActionsBS01 :: bsDecide` reads:
--     if (!doc.BS_LINK_DOCUMENTS_COMPLETED) return 'link_documents';
-- The action matches the balance sheet's ledger lines against real documents, writes
-- LINKED_BS / BS_LINE_AMOUNT / BS_LINE_DATE / BS_LINE_NOTE onto each matching document row, and
-- latches the flag. It then NEVER RUNS AGAIN for that balance sheet.
--
-- A ledger is almost always ahead of the paperwork: the line exists the moment the accountant
-- books it, the scanned invoice arrives days or weeks later. Every document that arrives after
-- its balance sheet was linked therefore stays unmatched — and the ledger line, which was
-- ingested as its own placeholder row, becomes a second row for the same document.
--
-- Measured 2026-08-21: 6,097 placeholder line rows (BS_LINE_AMOUNT set, no HASH, no LINK) against
-- 26,504 real document rows, and **1,166 business keys hold BOTH a placeholder line and a real
-- document**. That is the single largest duplicate cause in the table.
--
-- THE FIX, AND WHY IT NEEDS A ROUND COUNTER
-- -----------------------------------------
-- Re-firing `link_documents` on the same balance sheet is a SECOND DISPATCH OF THE SAME ACTION
-- with no ACTION_RESTART between, which 'Dup Guard: Double Action' blocks by design — it keys on
-- exact action-name equality and that rule is not up for negotiation. So each re-link round gets
-- its own name (`link_documents_r1`, `_r2`, …), exactly as per-source feedback names each source
-- (`source_feedback_0`, `_1`, …). Every round is then "dispatched once, ever" in the guard's own
-- terms, and the guard needs no change at all.
--
--   BS_LINK_DOCUMENTS_AT     when the last link ran. A round is DUE when a candidate document for
--                            this company appeared after it.
--   BS_LINK_ROUND            how many times linking has run. 0 keeps the historical action name,
--                            so nothing already in ACTION_HISTORY changes meaning.
--
-- Bounded at 9 rounds: a balance sheet that has re-linked ten times is a data fault, not a
-- workload, and unbounded rounds would mint unbounded action names.

\set ON_ERROR_STOP on

ALTER TABLE public.incoming_documents
  ADD COLUMN IF NOT EXISTS "BS_LINK_DOCUMENTS_AT" timestamptz,
  ADD COLUMN IF NOT EXISTS "BS_LINK_ROUND"        integer DEFAULT 0;

-- Existing latched balance sheets have no timestamp, so "has a document appeared since?" cannot
-- be answered for them. Seed it from the row's own updated_at: the last time anything touched the
-- balance sheet is the most defensible lower bound available, and it makes every document that
-- has arrived SINCE then eligible without re-linking the whole history in one burst.
UPDATE public.incoming_documents
   SET "BS_LINK_DOCUMENTS_AT" = COALESCE(updated_at, created_at)
 WHERE lower(COALESCE("BS_LINK_DOCUMENTS_COMPLETED", '')) = 'true'
   AND "BS_LINK_DOCUMENTS_AT" IS NULL;

-- Serves the driver's per-batch "is a relink due?" probe: newest real document per company.
CREATE INDEX IF NOT EXISTS idx_incdoc_company_created_real
    ON public.incoming_documents ("COMPANY_ID", created_at)
 WHERE "STATUS" <> 'MERGED' AND "HASH" IS NOT NULL AND "HASH" <> '';

\echo '--- state after ---'
SELECT count(*) FILTER (WHERE lower(COALESCE("BS_LINK_DOCUMENTS_COMPLETED",'')) = 'true') AS latched,
       count(*) FILTER (WHERE "BS_LINK_DOCUMENTS_AT" IS NOT NULL)                         AS stamped,
       count(*) FILTER (WHERE COALESCE("BS_LINK_ROUND", 0) > 0)                           AS rounds_gt_0
  FROM public.incoming_documents;
