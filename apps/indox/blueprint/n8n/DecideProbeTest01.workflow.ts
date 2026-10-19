import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : DecideProbeTest01 — what would decide say (TEST ONLY, read-only)
// Nodes   : 8  |  Connections: 7
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Hook                               webhook                    [creds]
// PickIds                            postgres                   [creds]
// EnrichDoubleLines                  postgres                   [creds] [alwaysOutput] [executeOnce]
// GetActionHistory                   postgres                   [creds] [alwaysOutput] [executeOnce]
// AttachActionHistory                code
// CallDecide                         executeWorkflow            [onError→regular]
// Tally                              code
// Respond                            respondToWebhook
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Hook
//    → PickIds
//      → EnrichDoubleLines
//        → GetActionHistory
//          → AttachActionHistory
//            → CallDecide
//              → Tally
//                → Respond
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Hook":{"main":[[{"node":"Pick IDs","type":"main","index":0}]]},"Pick IDs":{"main":[[{"node":"Enrich Double Lines","type":"main","index":0}]]},"Enrich Double Lines":{"main":[[{"node":"Get Action History","type":"main","index":0}]]},"Get Action History":{"main":[[{"node":"Attach Action History","type":"main","index":0}]]},"Attach Action History":{"main":[[{"node":"Call Decide","type":"main","index":0}]]},"Call Decide":{"main":[[{"node":"Tally","type":"main","index":0}]]},"Tally":{"main":[[{"node":"Respond","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-26T08:57:58.592Z","createdAt":"2026-08-26T08:57:58.592Z","role":"workflow:owner","workflowId":"DecideProbeTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'DecideProbeTest01',
    name: 'DecideProbeTest01 — what would decide say (TEST ONLY, read-only)',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class Decideprobetest01WhatWouldDecideSayTestOnlyReadOnlyWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'dp-hook',
        webhookId: 'f0110dc5-11ee-4ec0-9a1b-fde0000000f1',
        name: 'Hook',
        /*__n8n__*/ notes: "Asks the REAL decide what it would do, instead of mirroring its gates in SQL. The three feed nodes below are lifted verbatim from indoxV2Driver01, so decide receives exactly the payload production gives it -- the enriched row, the computed signatures and the dispatch history. Read-only: nothing is dispatched and nothing is written.",
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [0, 0],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    Hook = {
        httpMethod: 'POST',
        path: 'decide-probe-test',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'dp-pick',
        name: 'Pick IDs',
        /*__n8n__*/ notes: "Body: {status:[...], limit:N} or {ids:[...]}. Emits ONE item carrying the pipe-joined id list, which is the shape both feed queries expect.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [224, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    PickIds = {
        operation: 'executeQuery',
        query: `-- [phase-4 2026-08-31] The probe now reads the TEST tenant (indox_test), not the live
-- IN_PROGRESS cohort: what-would-decide-say questions about production go through the live
-- tooling, not this suite.
SELECT "ID" FROM indox_test.incoming_documents
WHERE coalesce("STATUS",'') = ANY(string_to_array($2, '|'))
ORDER BY "updated_at" DESC
LIMIT $1::int;`,
        options: {
            queryReplacement: "={{ $json.body.limit || 200 }},{{ ($json.body.status || []).join('|') }}",
        },
    };

    @node({
        id: 'dp-enrich',
        name: 'Enrich Double Lines',
        /*__n8n__*/ notes: "[renamed 2026-08-20, owner order] Was 'Enrich Doubles'. A DOUBLE LINE is a data-quality fact about the table -- two rows are the same document -- and the answer is a MERGE. That is this node. It is NOT a DOUBLE ACTION EXECUTION (the same action dispatched twice with no ACTION_RESTART between), which is a state-machine health fault owned by 'Dup Guard: Double Action' and must error loudly. Both used to be called 'doubles'. --- [SQL doubles 2026-08-18, owner design] ONE pass over the whole set this driver is holding, BEFORE decide sees anything. Adds IS_DOUBLE / IS_MAIN_DOUBLE / LINES_TO_MERGE, so decide keeps its one-shot view of duplicates while being fed in 3k slices. Survivor = LAST created (created_at DESC, ID DESC); MERGED rows are excluded, which is what makes a merged loser disappear from the next sweep. Also carries __merge_enabled (settings key indoxDoubleMergeOn) so the merge itself stays blocked until it is trusted. IDs are pipe-joined because n8n splits the Query Parameters field on commas. executeOnce: the node must run ONCE for the batch, not once per row.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [448, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        executeOnce: true,
    })
    EnrichDoubleLines = {
        operation: 'executeQuery',
        query: `WITH input AS (SELECT unnest(string_to_array($1, '|')) AS "ID"
), toggle AS (
  SELECT COALESCE((SELECT lower(value) = 'true' FROM indox_test.settings
                   WHERE key = 'indoxDoubleMergeOn' LIMIT 1), false) AS merge_on,
  -- [source feedback 2026-08-21] Same shape and same reason as merge_on: the action moves a
  -- client's Drive files and tags their mail, so it stays blocked until it is trusted. A missing
  -- settings row COALESCEs to false, so the gate can never dark-start.
         COALESCE((SELECT lower(value) = 'true' FROM indox_test.settings
                   WHERE key = 'indoxSourceFeedbackOn' LIMIT 1), false) AS feedback_on,
  -- [priority gate 2026-08-21] THE SETTING HAD NO WAY TO REACH THE GATE THAT READS IT.
  -- indoxV2ActionsGDoc01/Ship01 decide with:
  --     _priorityActive = __CFG().activePrioritySync === true
  -- but __CFG() reads $('Companies') or an injected _cfg, and NEITHER router has a Companies
  -- node and nothing injects _cfg -- so __CFG() is {} on the decide path and _priorityActive was
  -- ALWAYS false. Measured 2026-08-21: action_priority_sync has 0 dispatches all-time, and the
  -- 4,749 rows carrying PRIORITY_SYNC_COMPLETED were written by the v1 processors, not by this
  -- action. Flipping activePrioritySync would have sent the client nothing, silently.
  -- Carried on the row like __merge_enabled and __source_feedback_enabled, for the same reason.
         COALESCE((SELECT lower(value) = 'true' FROM indox_test.settings
                   WHERE key = 'activePrioritySync' LIMIT 1), false) AS priority_on,
  -- [local priority endpoint 2026-08-22] Sends the payload to priorityLocalApi01 instead of the
  -- client's ERP, so action_priority_sync can be switched on and exercised against real documents
  -- with nothing reaching the client. Carried on the row for the same reason as the three above:
  -- the routers have no way to read settings on the decide path.
  -- NOTE THE INVERTED DEFAULT. The other gates COALESCE to false because false is their safe
  -- state. Here the safe state is TRUE -- a missing settings row must mean "keep it local", never
  -- "post to the client". Losing this row should cost a test run, not a duplicated ERP.
         COALESCE((SELECT lower(value) = 'true' FROM indox_test.settings
                   WHERE key = 'indox.actions.priority_sync.local' LIMIT 1), true) AS priority_local
), bad_docid AS (
  /* A DOC_ID USED BY THREE OR MORE COMPANIES IS NOT A DOCUMENT ID.
     [2026-08-23] This rule already existed -- in 'Adjudicate Merge', which skips any group whose
     doc-id is shared across 3+ companies rather than merge documents that only look alike. The
     DETECTOR did not know about it, and that asymmetry is a group with no terminal state: the
     driver raises it, the adjudicator refuses it, nothing is written, and it is raised again on
     the next sweep. Five mains reached 146 action_merge_doubles dispatches this way.
     Every one of the last 10 duplicate groups on the table was this and only this. The worst
     offender, DOC_ID 515561520, is a company registration number appearing under FIFTEEN
     companies across 68 rows; another, 02-6333155, is a phone number under 5. They are not
     duplicates -- they are different documents whose id was mis-extracted.
     Table-wide: 49 such doc-ids, 258 rows.
     Quarantining at the KEY, not after grouping, is what gives them a terminal state: they simply
     stop being duplicates. A row still gets its hash or comp key, so a genuine duplicate hiding
     behind a bad doc-id is still caught by the tiers below -- this narrows the biz tier only.
     Threshold and predicate are copied from the adjudicator so the two cannot disagree again. */
  SELECT btrim("DOC_ID") AS did
  FROM indox_test.incoming_documents
  WHERE coalesce(btrim("DOC_ID"), '') <> ''
    AND length(regexp_replace(btrim("DOC_ID"), '[^a-zA-Z0-9]', '', 'g')) >= 3
  GROUP BY btrim("DOC_ID")
  HAVING count(DISTINCT btrim("COMPANY_ID")) >= 3
), live AS (
  SELECT d.* FROM indox_test.incoming_documents d JOIN input i USING ("ID")
  WHERE d."STATUS" IS DISTINCT FROM 'MERGED'
), keyed AS (
  SELECT l.*, COALESCE(
    CASE WHEN l."COMPANY_ID" IS NOT NULL AND l."COMPANY_ID" <> '' AND lower(l."COMPANY_ID") <> 'unknown'
          AND l."DOC_ID" IS NOT NULL AND l."DOC_ID" <> ''
          AND lower(btrim(l."DOC_ID")) NOT IN ('unknown','action_required','null','none')
          AND length(regexp_replace(btrim(l."DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
          AND regexp_replace(btrim(l."DOC_ID"),'[^a-zA-Z0-9]','','g') !~ '^0+$'
          AND btrim(l."COMPANY_ID") <> btrim(l."DOC_ID")
          AND btrim(l."DOC_ID") NOT IN (SELECT did FROM bad_docid)
         THEN 'biz' || chr(1) || btrim(l."COMPANY_ID") || chr(1) || btrim(l."DOC_ID") END,
    CASE WHEN l."HASH" IS NOT NULL AND l."HASH" <> '' AND lower(l."HASH") <> 'unknown'
          AND (l."LINKED_BS" IS NULL OR l."LINKED_BS" = '' OR lower(l."LINKED_BS") = 'unknown')
         THEN 'hash' || chr(1) || l."HASH" END,
    CASE WHEN l."COMPANY_ID" IS NOT NULL AND l."COMPANY_ID" <> ''
          AND l."SHORT_DOC_ID" IS NOT NULL AND l."SHORT_DOC_ID" <> ''
          AND btrim(l."SHORT_DOC_ID") !~ '^0+$'
         THEN 'comp' || chr(1) || l."COMPANY_ID" || chr(1) || l."SHORT_DOC_ID" END
  ) AS dup_key FROM live l
), keys AS (
  SELECT DISTINCT dup_key FROM keyed WHERE dup_key IS NOT NULL
), universe AS (
  /* DETECTION IS TABLE-WIDE, ACTION STAYS ON THE PIPED LINES [owner order 2026-08-19].
     Every CTE below used to derive from 'live', i.e. the driver's own id list, so a document
     could only be found double against another document IN THE SAME BATCH. 'universe' widens the
     comparison to every still-open row sharing one of the input's keys, so grp_n and rn are
     table-wide facts and "newest is main" holds globally. The final SELECT still JOINs 'input',
     so only the lines this driver piped in are returned and acted on. LINES_TO_MERGE may name
     rows outside the batch: that is information for the merge action, not a licence to touch
     them.

     [detector simplified 2026-08-23, owner order] Two changes, both about keeping this a pure
     DETECTOR. (1) dup_key was spelled out TWICE -- once in the SELECT, once in the WHERE -- so
     the same twenty-line COALESCE had to be edited in two places to stay correct. It is now
     computed once in a derived table and filtered by name. (2) The universe excludes MERGED, and
     ONLY MERGED. Terminal status is the stop condition -- self-enforcing, and it cannot go stale
     the way the merge_sig fingerprint it replaces did (that stamp broke the moment a member's
     HASH arrived after stamping, which is how 74 dispatches landed on one document).

     DOUBLE IS NOT EXCLUDED, AND MUST NOT BE. An earlier draft of this comment said it was, from
     the design where DOUBLE meant "reviewed, genuinely different, kept apart". The owner removed
     keep-apart on 2026-08-23: there is one outcome now, and a conflict is RECORDED in DUP_CAUSE
     and merged anyway. DOUBLE is therefore a transient marker on a non-main that is waiting for
     its main to merge it, not a resolution. Dropping it from the universe would take every
     non-main out of its own group, the main would see grp_n = 1, and NOTHING would ever merge.
     The code has always been right here; only this comment was wrong. */
  SELECT u.* FROM (
    SELECT d.*, COALESCE(
      CASE WHEN d."COMPANY_ID" IS NOT NULL AND d."COMPANY_ID" <> '' AND lower(d."COMPANY_ID") <> 'unknown'
            AND d."DOC_ID" IS NOT NULL AND d."DOC_ID" <> ''
            AND lower(btrim(d."DOC_ID")) NOT IN ('unknown','action_required','null','none')
            AND length(regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g')) >= 3
            AND regexp_replace(btrim(d."DOC_ID"),'[^a-zA-Z0-9]','','g') !~ '^0+$'
            AND btrim(d."COMPANY_ID") <> btrim(d."DOC_ID")
            AND btrim(d."DOC_ID") NOT IN (SELECT did FROM bad_docid)
           THEN 'biz' || chr(1) || btrim(d."COMPANY_ID") || chr(1) || btrim(d."DOC_ID") END,
      CASE WHEN d."HASH" IS NOT NULL AND d."HASH" <> '' AND lower(d."HASH") <> 'unknown'
            AND (d."LINKED_BS" IS NULL OR d."LINKED_BS" = '' OR lower(d."LINKED_BS") = 'unknown')
           THEN 'hash' || chr(1) || d."HASH" END,
      CASE WHEN d."COMPANY_ID" IS NOT NULL AND d."COMPANY_ID" <> ''
            AND d."SHORT_DOC_ID" IS NOT NULL AND d."SHORT_DOC_ID" <> ''
            AND btrim(d."SHORT_DOC_ID") !~ '^0+$'
           THEN 'comp' || chr(1) || d."COMPANY_ID" || chr(1) || d."SHORT_DOC_ID" END
    ) AS dup_key
    FROM indox_test.incoming_documents d
    WHERE d."STATUS" IS DISTINCT FROM 'MERGED'
  ) u
  WHERE u.dup_key IN (SELECT dup_key FROM keys)
), grp AS (
  SELECT *, count(*) OVER (PARTITION BY dup_key) AS grp_n,
            row_number() OVER (PARTITION BY dup_key ORDER BY created_at DESC, "ID" DESC) AS rn
  FROM universe WHERE dup_key IS NOT NULL
), dbl AS (
  -- PURE DETECTION. A group is live when more than one member is still unmerged.
  --
  -- There is no marker, no fingerprint and no settled-flag, because none is needed: the merge
  -- writes STATUS='MERGED' on the losers, MERGED is excluded from the universe above, so the
  -- next sweep sees grp_n = 1 and the main is simply not double any more. The stop condition IS
  -- the terminal status, and it cannot go stale.
  -- (Replaces DOUBLE_LINE_CONTEXT.merge_sig, which fingerprinted ID:HASH per member and broke
  -- the moment a HASH arrived after stamping -- 74 action_merge_doubles dispatches on one
  -- document, 2026-08-23 -- and the DUP_CAUSE gate that replaced it, which could not be
  -- satisfied for a group split across driver batches.)
  SELECT * FROM grp WHERE grp_n > 1
), losers AS (
  SELECT dup_key, jsonb_agg(to_jsonb(d) - 'dup_key' - 'grp_n' - 'rn' ORDER BY d."ID") AS lines
  FROM dbl d WHERE d.rn > 1 GROUP BY dup_key
)
, feed AS (
  -- [source feedback 2026-08-21] THE LOWEST-INDEX SOURCE THAT STILL OWES FEEDBACK, per document.
  --
  -- Computed HERE, in the one SQL pass that already runs per batch, and never in decide. Two
  -- reasons, both measured: SOURCE_LIST is now the FATTEST COLUMN ON THE TABLE (26 MB total,
  -- avg 692 B, 1.37 MB per 2,000-row decide slice), and the last time a fat column was parsed
  -- per row in the decide path it was ACTION_LOG, which is exactly what the 2026-08-17 slimming
  -- removed. Decide gets two scalars instead: an index and an identity.
  --
  -- ONE PER DOCUMENT PER PASS, not all of them. Feedback action names are per-source
  -- (source_feedback_0, _1, ...) so the double-action guard can tell them apart, which means
  -- they take DIFFERENT doc_action locks — n8n.process_lock.doc_action.<ID>::<ACTION>. Emitting
  -- two at once would let two executions upsert the same row concurrently, and the loser's
  -- SOURCE_LIST write would be clobbered; that source then re-decides, finds its own name
  -- already in ACTION_HISTORY with no restart between, and is parked as DOUBLE ACTION BLOCKED
  -- forever. A document with three sources simply takes three sweeps. Only 1,025 of 39,160 rows
  -- have more than one source, and the drain runs continuously.
  SELECT DISTINCT ON (b."ID") b."ID",
         (e.ord - 1)::int AS idx,
         -- The identity the action re-verifies before acting. The index is a dispatch label;
         -- this is what proves the element under it is still the same source.
         COALESCE(e.el->>'source_kind','') || '|' ||
         COALESCE(e.el->>'file_id', e.el->>'message_id', '') AS fkey
    FROM indox_test.incoming_documents b
    JOIN input i3 ON i3."ID" = b."ID",
         LATERAL jsonb_array_elements(b."SOURCE_LIST") WITH ORDINALITY e(el, ord)
   WHERE jsonb_typeof(b."SOURCE_LIST") = 'array'
     AND e.el->>'required_feedback_type' IS NOT NULL
     AND COALESCE((e.el->>'sync_feedback_completed')::boolean, false) = false
   ORDER BY b."ID", e.ord
)
SELECT b.*,
       (x."ID" IS NOT NULL)                AS "IS_DOUBLE",
       COALESCE(x.rn = 1, false)           AS "IS_MAIN_DOUBLE",
       CASE WHEN x.rn = 1 THEN l.lines END AS "LINES_TO_MERGE",
       (SELECT merge_on FROM toggle)             AS "__merge_enabled",
       (SELECT feedback_on FROM toggle)          AS "__source_feedback_enabled",
       (SELECT priority_on FROM toggle)          AS "__priority_sync_enabled",
       (SELECT priority_local FROM toggle)       AS "__priority_local",
       fd.idx                                    AS "__feedback_idx",
       fd.fkey                                   AS "__feedback_key",
       -- [phase 5 2026-08-22] What the Priority payload for this row WOULD hash to right now.
       -- decide compares it against the stored "PRIORITY_SYNC_SIGNATURE" (what was last sent):
       -- equal => the client's record is already correct, stay silent; different => the line
       -- changed, re-send it. Computed here rather than in decide for the same reason
       -- __feedback_idx is -- decide is a pure function over one row -- and, more importantly,
       -- so that the formula has exactly ONE definition (the function), shared by this SELECT,
       -- the writeback and the verifier. A JS copy would drift, and drift here means either
       -- duplicate records in the client's ERP or a correction that never reaches them.
       public.indox_priority_signature(b.*)      AS "__priority_sig",
       -- [selection 2026-08-25] What the two selectors WOULD be deciding from right now. decide
       -- compares each against the hash stored when the selection last ran: equal => the decision
       -- still stands, different => a version changed underneath it (an aging report linked and
       -- wrote BS_LINE_*, a restart re-extracted, an operator corrected a field) and the selection
       -- is re-dispatched. Cheap by construction -- re-deciding reads no file and calls no model.
       -- Same one-definition rule as the priority signature above: the formula lives in the SQL
       -- function, and SelectBase01/SelectType01 reproduce it exactly when they write.
       public.indox_base_selection_hash(b.*)     AS "__base_selection_hash",
       public.indox_selection_hash(b.*)          AS "__selection_hash",
       -- [line-hash 2026-08-26] parity with indoxV2Driver01 :: 'Enrich Double Lines': the whole
       -- line as one value, the thing 'Dup Guard: Double Action' compares against each
       -- ACTION_HISTORY entry's 'h'. The probe is only truthful if it selects what the driver does.
       public.indox_line_hash(b.*)               AS "__line_hash"
FROM indox_test.incoming_documents b
JOIN input i2 ON i2."ID" = b."ID"
LEFT JOIN dbl x ON x."ID" = b."ID"
LEFT JOIN losers l ON l.dup_key = x.dup_key AND x.rn = 1
LEFT JOIN feed fd ON fd."ID" = b."ID"
ORDER BY b."ID"`,
        options: {
            queryReplacement: "={{ $input.all().map(i => i.json.ID).join('|') }}",
        },
    };

    @node({
        id: 'dp-hist',
        name: 'Get Action History',
        /*__n8n__*/ notes: "[action history 2026-08-20, owner order] The newest 16 dispatches per document, from indox_test.indox_action_execution_log, as ACTION_HISTORY, each carrying the LINE_HASH the router stamped at dispatch time. This is what replaces reading the ACTION_LOG string: 'Dup Guard: Double Action' and decide's _log both key on it. DELIBERATELY ITS OWN NODE, not folded into 'Enrich Double Lines' -- that node answers 'is this row a duplicate DOCUMENT' (data quality, answered by a merge); this one answers 'what has this document already been DISPATCHED' (state-machine health). Same reason the two were renamed apart. Cost measured 2026-08-20: 33 ms for 2,000 documents (PK index, avg 8.4 rows/doc, p95 17, max 344). IDs are pipe-joined because n8n splits Query Parameters on commas. executeOnce: once for the batch, not once per row.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [672, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        executeOnce: true,
    })
    GetActionHistory = {
        operation: 'executeQuery',
        query: `WITH input AS (SELECT unnest(string_to_array($1, '|')) AS "ID")
SELECT i."ID", COALESCE(h.hist, '[]'::jsonb) AS "ACTION_HISTORY"
FROM input i
LEFT JOIN LATERAL (
  SELECT jsonb_agg(jsonb_build_object(
           'a', e."ACTION", 's', e."STARTED_AT", 'e', e."ENDED_AT", 'h', e."LINE_HASH")
           ORDER BY e."STARTED_AT" DESC) AS hist
  FROM (SELECT x."ACTION", x."STARTED_AT", x."ENDED_AT", x."LINE_HASH"
        FROM indox_test.indox_action_execution_log x
        WHERE x."ID" = i."ID"
        ORDER BY x."STARTED_AT" DESC
        LIMIT 16) e
) h ON true`,
        options: {
            queryReplacement: "={{ $input.all().map(i => i.json.ID).join('|') }}",
        },
    };

    @node({
        id: 'dp-attach',
        name: 'Attach Action History',
        /*__n8n__*/ notes: "[action history 2026-08-20] Puts ACTION_HISTORY back onto the enriched rows. A postgres node REPLACES its input items, so 'Get Action History' cannot both read the log and carry 'Enrich Double Lines' computed columns (IS_DOUBLE / IS_MAIN_DOUBLE / LINES_TO_MERGE / __merge_enabled) through -- those exist only in that node's SQL output. The alternative is shipping all 2,000 full rows to the DB and back to re-attach one key, which costs far more than the 33 ms join. ORDER IS LOAD-BEARING: the history must be attached AFTER 'Enrich Double Lines', because that node re-selects b.* from incoming_documents and would drop anything attached before it. A document with no dispatches gets [], never undefined, so every consumer can read .length without a guard.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [896, 0],
    })
    AttachActionHistory = {
        jsCode: `// Map ID -> ACTION_HISTORY from the SQL node, then re-emit the enriched rows.
const hist = new Map();
for (const it of $input.all()) {
  const j = it.json || {};
  if (j.ID == null) continue;                     // alwaysOutputData placeholder on a 0-row result
  hist.set(String(j.ID), Array.isArray(j.ACTION_HISTORY) ? j.ACTION_HISTORY : []);
}
const rows = $('Enrich Double Lines').all();
return rows.map(it => {
  // [phase-4 2026-08-31] The rows are the TEST tenant's, and decide must be told so: production
  // parity too -- indoxV2Driver01 stamps __instance on every row it feeds decide, and
  // indoxV2Decide01's extraction_queries read throws without it.
  const j = { ...it.json, ACTION_HISTORY: hist.get(String(it.json.ID)) || [], __instance: 'test' };
  // [source feedback 2026-08-21] SOURCE_LIST NEVER ENTERS THE DECIDE PAYLOAD.
  // Measured today it is the FATTEST COLUMN ON THE TABLE -- 26 MB total, avg 692 B/row,
  // 1.37 MB per 2,000-row slice -- and it is pure ballast here: 'Enrich Double Lines' has
  // already reduced it to the two scalars decide actually needs (__feedback_idx and
  // __feedback_key). This is the same trade the 2026-08-17 slimming made for ACTION_LOG, and
  // it matters for the same reason: the worker aborts at Node's 2,600 MB V8 ceiling long
  // before the 4 GB container limit, so a fat column on a hot path shows up as OOM, not as
  // slowness. The ACTION lane re-reads SOURCE_LIST for its own group (<=150 documents) --
  // which is also fresher than a copy carried since decide.
  delete j.SOURCE_LIST;
  return { json: j };
});
`,
    };

    @node({
        id: 'dp-call',
        name: 'Call Decide',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [1120, 0],
        onError: 'continueRegularOutput',
    })
    CallDecide = {
        workflowId: {
            __rl: true,
            value: 'indoxV2Decide01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'dp-tally',
        name: 'Tally',
        /*__n8n__*/ notes: "decide's OWN verdicts, counted. This is the authoritative answer to 'what would the machine do with these documents' -- a SQL mirror of the gates is a guess about it.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1344, 0],
    })
    Tally = {
        jsCode: `const rows = $input.all().map(i => i.json || {});
const byAction = {}, samples = {};
for (const r of rows) {
  const a = String(r.ACTION || '(none)');
  byAction[a] = (byAction[a] || 0) + 1;
  if (!samples[a]) samples[a] = [];
  if (samples[a].length < 3) samples[a].push({ ID: r.ID, STATUS: r.STATUS, TYPE: r.TYPE });
}
const sent = Object.entries(byAction)
  .filter(([a]) => a === 'action_priority_sync' || a === 'restart_priority_sync')
  .reduce((n, [, c]) => n + c, 0);
// 'Call Decide' continues on error, so its failure arrives here as an ordinary item — and a probe
// that does not notice it reports verdicts for a decision nobody made. Read it and count it.
const failed = rows.filter(r => r.error || r.errorMessage).map(r => String(r.error || r.errorMessage).slice(0, 200));
return [{ json: {
  asked: rows.length,
  failed: failed.length,
  failures: failed,
  WOULD_SEND_TO_PRIORITY: sent,
  verdicts: Object.fromEntries(Object.entries(byAction).sort((x, y) => y[1] - x[1])),
  samples,
}}];
`,
    };

    @node({
        id: 'dp-respond',
        name: 'Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1568, 0],
    })
    Respond = {
        respondWith: 'text',
        responseBody: '={{ JSON.stringify($json) }}',
        options: {
            responseHeaders: {
                entries: [
                    {
                        name: 'content-type',
                        value: 'application/json; charset=utf-8',
                    },
                ],
            },
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Hook.out(0).to(this.PickIds.in(0));
        this.PickIds.out(0).to(this.EnrichDoubleLines.in(0));
        this.EnrichDoubleLines.out(0).to(this.GetActionHistory.in(0));
        this.GetActionHistory.out(0).to(this.AttachActionHistory.in(0));
        this.AttachActionHistory.out(0).to(this.CallDecide.in(0));
        this.CallDecide.out(0).to(this.Tally.in(0));
        this.Tally.out(0).to(this.Respond.in(0));
    }
}
