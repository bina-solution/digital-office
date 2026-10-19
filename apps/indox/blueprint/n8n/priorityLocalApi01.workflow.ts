import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : priority local api — SHIM_RECEIVE_SUPDOC stand-in
// Nodes   : 4  |  Connections: 3
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// PriorityLocalWebhook               webhook
// NormalisePayload                   code
// InsertRecord                       postgres                   [creds]
// RespondOk                          set
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// PriorityLocalWebhook
//    → NormalisePayload
//      → InsertRecord
//        → RespondOk
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Priority Local Webhook":{"main":[[{"node":"Normalise Payload","type":"main","index":0}]]},"Normalise Payload":{"main":[[{"node":"Insert Record","type":"main","index":0}]]},"Insert Record":{"main":[[{"node":"Respond OK","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-22T18:24:09.534Z","createdAt":"2026-08-22T18:24:09.534Z","role":"workflow:owner","workflowId":"priorityLocalApi01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'priorityLocalApi01',
    name: 'priority local api — SHIM_RECEIVE_SUPDOC stand-in',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class PriorityLocalApiShimReceiveSupdocStandInWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'pla-webhook-01',
        webhookId: 'a7c1f2e4-5b83-4d9a-9e21-6f3c8b0d1a55',
        name: 'Priority Local Webhook',
        /*__n8n__*/ notes: "authentication is NONE on purpose. The caller is our own Post Priority Table node, which carries ONE credential — the real Priority production basic auth, for msh.macomp.vip. Requiring auth here would either fail every local call or force that production secret to be a valid local credential too. The endpoint only accepts what our action lane posts, over the internal docker network. responseMode=lastNode so the caller gets the insert result and a failure to write is a failed POST, exactly as a rejected record would be.",
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [0, 0],
    })
    PriorityLocalWebhook = {
        httpMethod: 'POST',
        path: 'indox-priority-local',
        responseMode: 'lastNode',
        options: {},
    };

    @node({
        id: 'pla-normalise-01',
        name: 'Normalise Payload',
        /*__n8n__*/ notes: "Map Request posts ONE object per call ($json.toJsonString()), but accept an array too so a future batched sender is not a silent no-op. TOTPRICE is coerced with Number() to match the node's declared 'number' type; everything else is stored as the string the endpoint received. The untouched body goes to raw, so a field added to Map Request is still captured even before this table grows a column for it.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    NormalisePayload = {
        jsCode: `const F = ['IDSUP','DATEDOC','DOCNAME','DOCSHORT','TOTPRICE','DOC_INV','PORDNAME',
             'LINKDOC','TYPEDOC','SOURCE','FROMWAREHOUSE','PROPORTZ_CERTAINTY',
             'N8N_EXEID','INCOMING_DOC_ID'];

const out = [];
for (const item of $input.all()) {
  const b = (item.json && item.json.body !== undefined) ? item.json.body : item.json;
  const records = Array.isArray(b) ? b : [b];
  for (const rec of records) {
    const r = rec || {};
    const o = { raw: JSON.stringify(r) };
    // [cutover 2026-08-31] The F list below is a silent field filter: anything not named here
    // ceases to exist, and 'Insert Record' resolves its schema from __instance — so carry it.
    o.__instance = (r.__instance === null || r.__instance === undefined) ? '' : String(r.__instance);
    for (const f of F) {
      if (f === 'TOTPRICE') {
        const n = Number(r[f]);
        o[f] = Number.isFinite(n) ? n : 0;
      } else {
        o[f] = (r[f] === null || r[f] === undefined) ? '' : String(r[f]);
      }
    }
    out.push({ json: o });
  }
}
if (!out.length) throw new Error('priority local api: empty body — nothing to record');
return out;
`,
    };

    @node({
        id: 'pla-insert-01',
        name: 'Insert Record',
        /*__n8n__*/ notes: "INSERT, never upsert — see the workflow map. Two POSTs of one document must produce two rows here, because they produce two records in the client's ERP. Parameterised via $1..$15 rather than string-built SQL so a quote in DOCNAME or a Hebrew LINKDOC cannot break the statement.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [440, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    InsertRecord = {
        operation: 'executeQuery',
        query: `=-- [multi-instance 2026-08-28] This is the ERP STAND-IN, so its rows are per-instance like any
-- other: hacohen's simulated Priority uploads must not land in levi's table. The instance rides
-- the webhook payload (the caller is indoxV2ActionsInv01, which carries it on the row); absent,
-- it resolves to public exactly as before.
insert into {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('priorityLocalApi01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.indox_priority_local
  ("IDSUP","DATEDOC","DOCNAME","DOCSHORT","TOTPRICE","DOC_INV","PORDNAME","LINKDOC",
   "TYPEDOC","SOURCE","FROMWAREHOUSE","PROPORTZ_CERTAINTY","N8N_EXEID","INCOMING_DOC_ID",raw)
values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb)
returning id, "IDSUP", "DOCNAME", "DATEDOC", "INCOMING_DOC_ID";`,
        options: {
            queryReplacement:
                '={{ [$json.IDSUP, $json.DATEDOC, $json.DOCNAME, $json.DOCSHORT, $json.TOTPRICE, $json.DOC_INV, $json.PORDNAME, $json.LINKDOC, $json.TYPEDOC, $json.SOURCE, $json.FROMWAREHOUSE, $json.PROPORTZ_CERTAINTY, $json.N8N_EXEID, $json.INCOMING_DOC_ID, $json.raw] }}',
        },
    };

    @node({
        id: 'pla-respond-01',
        name: 'Respond OK',
        /*__n8n__*/ notes: "Shape mirrors a successful SHIM_RECEIVE_SUPDOC call closely enough that the action lane's success path is exercised for real: a 200 with a body. The lane keys success off the HTTP status, so the body content is informational.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [660, 0],
    })
    RespondOk = {
        assignments: {
            assignments: [
                {
                    id: 'pla-r1',
                    name: 'ok',
                    value: '={{ true }}',
                    type: 'boolean',
                },
                {
                    id: 'pla-r2',
                    name: 'local',
                    value: '={{ true }}',
                    type: 'boolean',
                },
                {
                    id: 'pla-r3',
                    name: 'recorded_id',
                    value: '={{ $json.id }}',
                    type: 'string',
                },
                {
                    id: 'pla-r4',
                    name: 'INCOMING_DOC_ID',
                    value: '={{ $json.INCOMING_DOC_ID }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.PriorityLocalWebhook.out(0).to(this.NormalisePayload.in(0));
        this.NormalisePayload.out(0).to(this.InsertRecord.in(0));
        this.InsertRecord.out(0).to(this.RespondOk.in(0));
    }
}
