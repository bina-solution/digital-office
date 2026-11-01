-- 2026-08-06 — resolve_double backfill, tiers 1–2 (final-indox.md CHANGE 3 + close-out step).
--
-- Merges the existing (COMPANY_ID, DOC_ID) violation groups that qualify for AUTOMATIC
-- adjudication, with exactly the rules the live writer (indoxApiSupabase01 MERGE branch /
-- 'Adjudicate Merge' in indoxV2ActionsGlobal01) applies — one rulebook, two entry points:
--   tier 1: group has <= 1 distinct REAL hash (non-blank, non-'unknown'). Two distinct
--           real hashes cannot coexist under uq_incdoc_hash, so this is the same-hash
--           tier: no contradicting content evidence anywhere in the group.
--   tier 2: exactly 2 rows, > 1 real hash, agreeing on TYPE + DOC_DATE + amount
--           (blank agrees with anything).
--   never:  quarantined doc-ids (seen under >= 3 companies), validity-failing doc-ids
--           (blank/'unknown'/'ACTION_REQUIRED'/all-zero/< 3 alnum/== COMPANY_ID),
--           and every group that fits neither tier — those stay for tier 3 (review
--           queue) / tier 4 (re-extraction), NOT this script.
--
-- A merge NEVER deletes. Losers keep every provenance column (SOURCE_*, HASH, LINK,
-- CONNECTION, SYNC_NAME, SIZE) and get STATUS='MERGED' + MERGED_INTO=<winner ID>; the
-- winner absorbs ONLY fields it is missing (from the most-complete loser) and gains
-- ALSO_SEEN_AS = JSON array of loser IDs. Reversal = restore from the backup table.
--
-- Winner rule (identical to the writer): most *_COMPLETED='true' flags, then
-- STATUS='COMPLETED' first, then earliest created_at, then lowest ID.
--
-- RUN ORDER: after PUSH WINDOW 2 (the live writer must exist first so new arrivals merge
-- instead of re-colliding), sequenced by the coordinator. Requires MERGED_INTO/ALSO_SEEN_AS
-- (schema.sql applied). NOT idempotent by design: step 0's CREATE TABLE fails loudly on a
-- second run instead of double-appending ACTION_LOG lines — rerun only after dropping the
-- bak table deliberately.
--
-- Measured at build time (2026-08-06 ~15:26 UTC, 6,430 rows): 288 violation groups,
-- 323 excess rows; tier 1 = 31 groups / 31 losers; tier 2 = ~159 groups / 159 losers.
-- Counts drift as extraction lanes fill DOC_ID — the script computes its sets at run time;
-- the post-checks print the real numbers.

\set ON_ERROR_STOP on

-- Step 0 of 4 — working sets + backup (backup BEFORE any write; loud-fail on rerun).
BEGIN;

create temp table t_rd_rows on commit drop as
with base as (
  select d.*,
         trim(coalesce(nullif(d."DOC_ID", ''), nullif(d."COMPANY_DOC_ID", ''))) as kdoc_raw
  from public.incoming_documents d
  where d."ID" <> '__bootstrap__'
    and coalesce(d."STATUS", '') <> 'MERGED'
), valid as (
  select b.*, b.kdoc_raw as kdoc
  from base b
  where b.kdoc_raw is not null
    and lower(b.kdoc_raw) not in ('unknown', 'action_required', 'null', 'none')
    and length(regexp_replace(b.kdoc_raw, '[^a-zA-Z0-9]', '', 'g')) >= 3
    and regexp_replace(b.kdoc_raw, '[^a-zA-Z0-9]', '', 'g') !~ '^0+$'
    and coalesce(b."COMPANY_ID", '') <> ''
    and b.kdoc_raw <> trim(b."COMPANY_ID")
), quarantine as (
  select kdoc from valid group by kdoc having count(distinct "COMPANY_ID") >= 3
)
select v.* from valid v where v.kdoc not in (select kdoc from quarantine);

create temp table t_rd_groups on commit drop as
select "COMPANY_ID" as gc, kdoc as gk,
       count(*)                                                  as n,
       count(distinct "HASH") filter (where coalesce("HASH",'') <> ''
                                        and lower("HASH") <> 'unknown') as real_hashes,
       count(distinct nullif(trim(coalesce("TYPE",'')), ''))            as n_type,
       count(distinct nullif(trim(coalesce("DOC_DATE",'')), ''))        as n_date,
       count(distinct nullif(trim(coalesce(nullif("DOC_TOTAL_AMOUNT",''),
                                           "TOTAL_AMOUNT")), ''))       as n_amount
from t_rd_rows
group by 1, 2
having count(*) > 1;

create temp table t_rd_scope on commit drop as
select g.*,
       case when g.real_hashes <= 1 then 1
            when g.n = 2 and g.n_type <= 1 and g.n_date <= 1 and g.n_amount <= 1 then 2
       end as tier
from t_rd_groups g
where g.real_hashes <= 1
   or (g.n = 2 and g.n_type <= 1 and g.n_date <= 1 and g.n_amount <= 1);

-- backup: full rows of every group member this script may touch
create table public.bak_resolve_double_t12_20260806 as
select r.* from t_rd_rows r join t_rd_scope s on r."COMPANY_ID" = s.gc and r.kdoc = s.gk;

select (select count(*) from t_rd_groups)                       as violation_groups_now,
       (select count(*) from t_rd_scope where tier = 1)         as tier1_groups,
       (select count(*) from t_rd_scope where tier = 2)         as tier2_groups,
       (select count(*) from public.bak_resolve_double_t12_20260806) as rows_backed_up;

-- Step 1 of 4 — rank every member; 1 winner per group (writer's exact ordering).
create temp table t_rd_rank on commit drop as
select r."ID", r."COMPANY_ID" as gc, r.kdoc as gk,
       row_number() over (
         partition by r."COMPANY_ID", r.kdoc
         order by
           ( (case when r."BASE_EXTRACTION_COMPLETED"     ilike 'true' then 1 else 0 end)
           + (case when r."PER_TYPE_EXTRACTION_COMPLETED" ilike 'true' then 1 else 0 end)
           + (case when r."FIGURE_COMPANY_COMPLETED"      ilike 'true' then 1 else 0 end)
           + (case when r."FIGURE_TYPE_COMPLETED"         ilike 'true' then 1 else 0 end)
           + (case when r."COMPANY_NAME_COMPLETED"        ilike 'true' then 1 else 0 end)
           + (case when r."DOC_DATE_COMPLETED"            ilike 'true' then 1 else 0 end)
           + (case when r."DOC_TOTAL_AMOUNT_COMPLETED"    ilike 'true' then 1 else 0 end)
           + (case when r."INVOICE_ID_COMPLETED"          ilike 'true' then 1 else 0 end)
           + (case when r."PURCHASE_ID_COMPLETED"         ilike 'true' then 1 else 0 end)
           + (case when r."SHIPMENT_ID_COMPLETED"         ilike 'true' then 1 else 0 end)
           + (case when r."AI_EXTRACTION_COMPLETED"       ilike 'true' then 1 else 0 end)
           + (case when r."SELECTION_COMPLETED"           ilike 'true' then 1 else 0 end)
           + (case when r."API_TOOLS_ID_COMPLETED"        ilike 'true' then 1 else 0 end)) desc,
           (case when r."STATUS" = 'COMPLETED' then 0 else 1 end) asc,
           r.created_at asc nulls last,
           r."ID" asc
       ) as rk
from t_rd_rows r
join t_rd_scope s on r."COMPANY_ID" = s.gc and r.kdoc = s.gk;

create temp table t_rd_pairs on commit drop as
select w."ID" as winner_id, l."ID" as loser_id, w.gc, w.gk, s.tier,
       row_number() over (partition by w.gc, w.gk order by l.rk) as loser_rank
from t_rd_rank w
join t_rd_rank l on l.gc = w.gc and l.gk = w.gk and l.rk > 1
join t_rd_scope s on s.gc = w.gc and s.gk = w.gk
where w.rk = 1;

select tier, count(distinct winner_id) as groups, count(*) as losers from t_rd_pairs group by tier;

-- Step 2 of 4 — winners: absorb missing content fields from the best loser,
-- record ALSO_SEEN_AS, stamp ACTION_LOG. Never touches provenance columns.
update public.incoming_documents w
   set "COMPANY_NAME"      = coalesce(nullif(w."COMPANY_NAME",''),      nullif(b."COMPANY_NAME",'')),
       "TYPE"              = coalesce(nullif(w."TYPE",''),              nullif(b."TYPE",'')),
       "DOC_DATE"          = coalesce(nullif(w."DOC_DATE",''),          nullif(b."DOC_DATE",'')),
       "DOC_TOTAL_AMOUNT"  = coalesce(nullif(w."DOC_TOTAL_AMOUNT",''),  nullif(b."DOC_TOTAL_AMOUNT",'')),
       "TOTAL_AMOUNT"      = coalesce(nullif(w."TOTAL_AMOUNT",''),      nullif(b."TOTAL_AMOUNT",'')),
       "PURCHASE_ID"       = coalesce(nullif(w."PURCHASE_ID",''),       nullif(b."PURCHASE_ID",'')),
       "SHIPMENT_DOC_ID"   = coalesce(nullif(w."SHIPMENT_DOC_ID",''),   nullif(b."SHIPMENT_DOC_ID",'')),
       "INVOICE_ID"        = coalesce(nullif(w."INVOICE_ID",''),        nullif(b."INVOICE_ID",'')),
       "LINKED_INVOICE_ID" = coalesce(nullif(w."LINKED_INVOICE_ID",''), nullif(b."LINKED_INVOICE_ID",'')),
       "DOC_ID"            = coalesce(nullif(w."DOC_ID",''),            nullif(b."DOC_ID",'')),
       "THUMBNAIL"         = coalesce(nullif(w."THUMBNAIL",''),         nullif(b."THUMBNAIL",'')),
       "API_TOOLS_ID"      = coalesce(nullif(w."API_TOOLS_ID",''),      nullif(b."API_TOOLS_ID",'')),
       "BS_EXTRACTED_LINES"= coalesce(nullif(w."BS_EXTRACTED_LINES",''),nullif(b."BS_EXTRACTED_LINES",'')),
       "ALSO_SEEN_AS"      = (
         select coalesce(
           (select jsonb_agg(x)::text from (
              select distinct x from (
                select jsonb_array_elements_text(
                  case when coalesce(w."ALSO_SEEN_AS",'') ~ '^\[' then w."ALSO_SEEN_AS"::jsonb else '[]'::jsonb end) as x
                union
                select p2.loser_id from t_rd_pairs p2 where p2.winner_id = w."ID"
              ) u) t),
           '[]')),
       "ACTION_LOG"        = coalesce(w."ACTION_LOG",'') || ', Merge Winner (backfill-t' || p.tier || ') absorbed '
                             || (select string_agg(p3.loser_id, '+') from t_rd_pairs p3 where p3.winner_id = w."ID")
                             || ', ' || (extract(epoch from now())*1000)::bigint || ', backfill'
  from (select distinct winner_id, gc, gk, tier from t_rd_pairs) p
  join t_rd_rank br on br.gc = p.gc and br.gk = p.gk and br.rk = 2
  join public.incoming_documents b on b."ID" = br."ID"
 where w."ID" = p.winner_id;

-- Step 3 of 4 — losers: tombstone, keep provenance, point at the winner.
update public.incoming_documents l
   set "STATUS"      = 'MERGED',
       "MERGED_INTO" = p.winner_id,
       "ACTION_LOG"  = coalesce(l."ACTION_LOG",'') || ', Merged Into ' || p.winner_id
                       || ' (backfill-t' || p.tier || '), '
                       || (extract(epoch from now())*1000)::bigint || ', backfill'
  from t_rd_pairs p
 where l."ID" = p.loser_id;

COMMIT;

-- Step 4 of 4 — post-checks (read-only; run in the same session or standalone).
--   a. every MERGED row must point somewhere
select count(*) as merged_without_pointer
  from public.incoming_documents
 where "STATUS" = 'MERGED' and coalesce("MERGED_INTO",'') = '';
--   b. no winner may itself be MERGED
select count(*) as merged_winners
  from public.incoming_documents w
 where w."STATUS" = 'MERGED'
   and exists (select 1 from public.incoming_documents l where l."MERGED_INTO" = w."ID");
--   c. remaining live violation groups (tier 3/4 residue — expected ~98 at build time)
select count(*) as remaining_violation_groups
from (
  select "COMPANY_ID", trim(coalesce(nullif("DOC_ID",''), nullif("COMPANY_DOC_ID",''))) as k
  from public.incoming_documents
  where "ID" <> '__bootstrap__' and coalesce("STATUS",'') <> 'MERGED'
    and coalesce("COMPANY_ID",'') <> ''
    and trim(coalesce(nullif("DOC_ID",''), nullif("COMPANY_DOC_ID",''))) is not null
  group by 1, 2 having count(*) > 1) t;
--   d. provenance intact on every loser (spot invariant: SOURCE_ID/HASH unchanged vs backup)
select count(*) as provenance_drift
  from public.incoming_documents d
  join public.bak_resolve_double_t12_20260806 b on b."ID" = d."ID"
 where d."STATUS" = 'MERGED'
   and (coalesce(d."SOURCE_ID",'') <> coalesce(b."SOURCE_ID",'')
     or coalesce(d."HASH",'')      <> coalesce(b."HASH",'')
     or coalesce(d."LINK",'')      <> coalesce(b."LINK",''));
