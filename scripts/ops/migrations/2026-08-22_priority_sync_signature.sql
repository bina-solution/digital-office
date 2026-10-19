-- PRIORITY_SYNC_SIGNATURE — re-send a line to Priority only when the line actually changed.
--
-- WHY THIS EXISTS
-- Priority is keyed by business content (IDSUP/DOCNAME/DATEDOC), not by our row id, so the same
-- document posted twice becomes two records in the client's ERP. The v2 gate is one-shot:
--     if (_priorityActive && !doc.PRIORITY_SYNC_COMPLETED) return 'action_priority_sync';
-- so today a line is sent once and never again, even after its content is corrected. The owner's
-- requirement is the middle path: "no duplications (only on line change, then we send to priority
-- the line again)". That needs a fingerprint of what was last sent.
--
-- THE ONE RULE THIS FILE ENFORCES: there is exactly ONE definition of the signature — the
-- function below. The driver SELECT calls it to compute "what the payload would be NOW", the
-- action writes back the value it actually sent, and decide compares the two. A second copy of
-- this formula in JS would drift from this one, and drift here means either a silent flood of
-- duplicate ERP records or a correction that never reaches the client.
--
-- WHAT IT HASHES: the MAPPED payload, not the raw columns. 'Map Request' transforms before
-- sending (DATEDOC truncates to 8 chars, TOTPRICE is parseFloat) so two different raw values can
-- produce a byte-identical record in Priority. Hashing raw columns would re-send documents whose
-- ERP record did not change — noise for the client, and duplicate-looking traffic.
--
-- WHAT IT DELIBERATELY EXCLUDES: N8N_EXEID. It is `$execution.id`, different on every run.
-- Including it would make every signature differ from the stored one, so every document would
-- re-send on every sweep, forever — the precise failure this feature exists to prevent.
--
-- The JS expressions mirrored here are indoxV2ActionsShip01 'Map Request' (and its identical twin
-- in indoxV2ActionsGDoc01). Equivalence is not assumed: scripts/ops/verify_priority_signature.mjs
-- runs both implementations over real rows and fails on any mismatch.

alter table public.incoming_documents
  add column if not exists "PRIORITY_SYNC_SIGNATURE" TEXT;

comment on column public.incoming_documents."PRIORITY_SYNC_SIGNATURE" is
  'md5 of the mapped Priority payload as last successfully POSTed. NULL = never sent under the '
  'signature regime. Differs from indox_priority_signature(row) => the line changed => re-send.';

create or replace function public.indox_priority_signature(d public.incoming_documents)
returns text
language sql
immutable
as $fn$
  -- Canonical form: the mapped values joined by the ASCII unit separator (chr 31), a
  -- byte that cannot occur in any of these fields. jsonb_build_array was the obvious
  -- choice and was WRONG: Postgres renders jsonb::text with a space after every comma
  -- while JSON.stringify is compact, so SQL and JS hashed different bytes from
  -- identical values -- 0/559 rows agreed. concat_ws is reproducible on both sides.
  -- INVARIANT, and concat_ws makes it load-bearing: concat_ws SKIPS null arguments, so a NULL
  -- element would shift every later field one position left and let two different documents
  -- collapse onto one signature -- a missed re-send, the silent half of the failure mode.
  -- EVERY element below is therefore total: each `case` arm returns a literal or btrim() of a
  -- value it has already established is not null, and each numeric is wrapped in coalesce.
  -- Adding an element that can return NULL silently breaks the whole column -- coalesce it.
  select md5(concat_ws(chr(31),

    -- IDSUP  <= String($json.SELECTED_COMPANY_ID).trim()
    -- String(null) is the literal 'null' in JS, which is NOT the same payload as an empty
    -- string -- the lane really does POST the four characters n-u-l-l. Mirror that, so a row
    -- whose company id is cleared to '' is a genuine change and re-sends.
    case when d."SELECTED_COMPANY_ID" is null then 'null' else btrim(d."SELECTED_COMPANY_ID") end,

    -- DATEDOC <= S && S.length >= 10 ? S.substring(0,6) + S.slice(-2) : (S || "").trim()
    -- JS substring(0,6) == substr(x,1,6); JS slice(-2) == right(x,2).
    case
      when d."SELECTED_DOC_DATE" is null or d."SELECTED_DOC_DATE" = '' then ''
      when length(d."SELECTED_DOC_DATE") >= 10
        then substr(d."SELECTED_DOC_DATE", 1, 6) || right(d."SELECTED_DOC_DATE", 2)
      else btrim(d."SELECTED_DOC_DATE")
    end,

    -- DOCNAME <= String($json.AI_DOC_ID).trim()
    case when d."AI_DOC_ID" is null then 'null' else btrim(d."AI_DOC_ID") end,

    -- DOCSHORT <= String($json.SELECTED_DOC_ID).trim()
    case when d."SELECTED_DOC_ID" is null then 'null' else btrim(d."SELECTED_DOC_ID") end,

    -- TOTPRICE <= parseFloat($json.SELECTED_DOC_AMOUNT) || 0   (a NUMBER, not a string)
    -- parseFloat takes the longest leading numeric prefix and yields NaN otherwise; NaN||0 and
    -- 0||0 both give 0. The regex is that prefix rule; anything unparseable falls to 0.
    coalesce(
      (substring(btrim(coalesce(d."SELECTED_DOC_AMOUNT", ''))
                 from '^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'))::double precision,
      0),

    -- DOC_INV <= String($json.SELECTED_DOC_SHIPMENT_ID || "")      -- note: no .trim() in the JS
    coalesce(d."SELECTED_DOC_SHIPMENT_ID", ''),

    -- PORDNAME <= String($json.SELECTED_DOC_ORDER_ID || "").trim()
    btrim(coalesce(d."SELECTED_DOC_ORDER_ID", '')),

    -- LINKDOC <= String($json.LINK).trim()
    case when d."LINK" is null then 'null' else btrim(d."LINK") end,

    -- TYPEDOC <= String($json.TYPE).trim()
    case when d."TYPE" is null then 'null' else btrim(d."TYPE") end,

    -- SOURCE <= String($json.SOURCE_TYPE).trim()
    case when d."SOURCE_TYPE" is null then 'null' else btrim(d."SOURCE_TYPE") end,

    -- FROMWAREHOUSE <= $json.FROM_OFFICE == true ? 'Y' : ""
    -- LOOSE equality against a TEXT column. JS coerces both sides to Number, so this is 'Y' only
    -- when the text is numerically 1 — never for the literal 'true' the column actually holds
    -- (Number('true') is NaN). Mirrored faithfully rather than corrected: this function must hash
    -- what the lane SENDS, not what it ought to send. The mapping defect is tracked separately;
    -- when it is fixed, these signatures change and the affected lines re-send, which is exactly
    -- the behaviour this column is for.
    -- [2026-08-23] UPDATED TO THE FIXED MAPPING. The arm below used to mirror a DEFECT on
    -- purpose (see the note above): the node compared FROM_OFFICE loosely against true, JS
    -- coerced both sides to Number, and Number('true') is NaN -- so a column that literally holds
    -- 'true' never produced 'Y'. That note said, in as many words, that when the mapping was
    -- fixed these signatures would change and the affected lines would re-send, and that this is
    -- exactly what the column is for.
    --
    -- The mapping WAS fixed in both 'Map Request' nodes (Ship and GDoc, verified live:
    -- String(...).trim().toLowerCase() === 'true' ? 'Y' : ""), and this copy was not updated with
    -- it. The fingerprint therefore disagreed with the payload on 409 of 520 sampled rows -- not
    -- a wrong hash, but a hash of the wrong thing, which is the one failure this function exists
    -- to prevent.
    case when lower(btrim(coalesce(d."FROM_OFFICE", ''))) = 'true' then 'Y' else '' end,

    -- PROPORTZ_CERTAINTY <= String(parseInt($json.SELECTION_CERTAINTY) || 0)   (a STRING)
    (coalesce((substring(btrim(coalesce(d."SELECTION_CERTAINTY", '')) from '^[+-]?[0-9]+'))::bigint,
              0))::text,

    -- N8N_EXEID is deliberately absent — see the header.

    -- INCOMING_DOC_ID <= $json.ID || ""
    coalesce(d."ID", '')

  ))
$fn$;

comment on function public.indox_priority_signature(public.incoming_documents) is
  'Fingerprint of the Priority payload for a row, per indoxV2Actions{Ship,GDoc}01 "Map Request". '
  'Excludes N8N_EXEID (per-run). Sole definition of the signature — do not reimplement in JS.';
