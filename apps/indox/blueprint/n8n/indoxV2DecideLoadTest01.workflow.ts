import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Decide Load Test
// Nodes   : 8  |  Connections: 8
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenClickingExecuteWorkflow        manualTrigger
// LoadTestWebhook                    webhook                    [creds]
// LoadFullTable                      postgres                   [creds]
// CallDecideOneBatch                 executeWorkflow
// SlimVerdicts                       set
// LoopBatches                        splitInBatches
// InsertRows                         postgres                   [creds]
// LoadTestRespond                    respondToWebhook           [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenClickingExecuteWorkflow
//    → LoadFullTable
//      → CallDecideOneBatch
//        → SlimVerdicts
//          → LoopBatches
//            → LoadTestRespond
//           .out(1) → InsertRows
//              → LoopBatches (↩ loop)
// LoadTestWebhook
//    → LoadFullTable (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When clicking ‘Execute workflow’":{"main":[[{"node":"Load Full Table","type":"main","index":0}]]},"Load Test Webhook":{"main":[[{"node":"Load Full Table","type":"main","index":0}]]},"Load Full Table":{"main":[[{"node":"Call Decide (one batch)","type":"main","index":0}]]},"Call Decide (one batch)":{"main":[[{"node":"Slim Verdicts","type":"main","index":0}]]},"Slim Verdicts":{"main":[[{"node":"Loop Batches","type":"main","index":0}]]},"Loop Batches":{"main":[[{"node":"Load Test Respond","type":"main","index":0}],[{"node":"Insert Rows","type":"main","index":0},{"node":"Loop Batches","type":"main","index":0}]]},"Insert Rows":{"main":[[]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-17T19:37:28.465Z","createdAt":"2026-08-17T19:37:28.465Z","role":"workflow:owner","workflowId":"indoxV2DecideLoadTest01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2DecideLoadTest01',
    name: 'indox-v2 Decide Load Test',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { executionOrder: 'v1', saveDataSuccessExecution: 'none' },
})
export class IndoxV2DecideLoadTestWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'dlt-manual-01',
        name: 'When clicking ‘Execute workflow’',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [0, 0],
    })
    WhenClickingExecuteWorkflow = {};

    @node({
        id: 'dlt-webhook-01',
        name: 'Load Test Webhook',
        /*__n8n__*/ notes: "POST {\"limit\":10000,\"offset\":0}. One BATCH per execution, driven from outside, deliberately: an in-workflow loop node would keep every iteration's runData in the worker heap, which is the exact accumulation this design exists to avoid. Fresh execution per batch = memory actually released between batches.",
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [0, 160],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    LoadTestWebhook = {
        httpMethod: 'POST',
        path: 'indox-decide-load-test',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'dlt-load-01',
        name: 'Load Full Table',
        /*__n8n__*/ notes: "MEASURED 2026-08-18: 38,955 rows, 74MB on disk, avg 1,983 B/row (ACTION_LOG alone is 576 B/row). As JS objects that inflates roughly 35x, and the CALLER needs two copies — the set it sends plus the set decide returns under the full-row contract. That is why 39k in ONE execution killed the caller four times while decide itself succeeded every time (47/67/88s). LIMIT/OFFSET come from the POST body so each execution carries one 10k batch.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [240, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    LoadFullTable = {
        operation: 'executeQuery',
        query: 'SELECT *, \'test\' AS "__instance" FROM indox_test.incoming_documents WHERE "ID" IS NOT NULL AND "ID" <> \'__bootstrap__\' ORDER BY "ID"',
        options: {},
    };

    @node({
        id: 'dlt-call-decide-01',
        name: 'Call Decide (one batch)',
        /*__n8n__*/ notes: "The real production decide (indoxV2Decide01). PROVEN at full scale 2026-08-18: 38,955 rows decided in ONE call three times — Mega Decide node 73.6s / 88s / 67s, 38,955 items in and out. Decide is not the capacity limit; the caller's round trip is.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.3,
        position: [480, 0],
    })
    CallDecideOneBatch = {
        workflowId: {
            __rl: true,
            value: 'indoxV2Decide01',
            mode: 'id',
            cachedResultName: 'indox-v2 Decide',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'dlt-slim-01',
        name: 'Slim Verdicts',
        /*__n8n__*/ notes: "Code nodes execute in the TASK RUNNER, so building the export inside one would serialise every returned row across the runner websocket. A Set node is nodes-base and runs IN-PROCESS, dropping each row to the 8 audit columns before anything crosses a process boundary. Decide is untouched and still returns full rows; this is caller-side projection only.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [700, 0],
    })
    SlimVerdicts = {
        mode: 'manual',
        includeOtherFields: false,
        assignments: {
            assignments: [
                {
                    id: 'sv0',
                    name: 'ID',
                    value: '={{ $json.ID }}',
                    type: 'string',
                },
                {
                    id: 'sv1',
                    name: 'ACTION',
                    value: '={{ $json.ACTION }}',
                    type: 'string',
                },
                {
                    id: 'sv2',
                    name: 'DOC_TYPE',
                    value: '={{ $json.DOC_TYPE }}',
                    type: 'string',
                },
                {
                    id: 'sv3',
                    name: 'IS_OLD',
                    value: '={{ $json.IS_OLD }}',
                    type: 'string',
                },
                {
                    id: 'sv4',
                    name: 'OLD_REASON',
                    value: '={{ $json.OLD_REASON }}',
                    type: 'string',
                },
                {
                    id: 'sv5',
                    name: 'STATUS',
                    value: '={{ $json.STATUS }}',
                    type: 'string',
                },
                {
                    id: 'sv6',
                    name: 'TYPE',
                    value: '={{ $json.TYPE }}',
                    type: 'string',
                },
                {
                    id: 'sv7',
                    name: 'COMPANY_ID',
                    value: '={{ $json.COMPANY_ID }}',
                    type: 'string',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'dlt-loop-01',
        name: 'Loop Batches',
        /*__n8n__*/ notes: "[owner order 2026-08-18] 10k per write — batching belongs to the POST-processing only, never to the decide call itself. Output 0 = done -> respond, output 1 = the 10k slice -> Insert Rows, which loops back here.",
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [900, 0],
    })
    LoopBatches = {
        batchSize: 10000,
        options: {},
    };

    @node({
        id: 'dlt-insert-01',
        name: 'Insert Rows',
        /*__n8n__*/ notes: "Results go to a TABLE, never into an HTTP body: a 39k-row response has to be assembled by the worker and held by main until the client drains it, and main died doing exactly that (2.5 GiB cgroup kill, 2026-08-18 11:55). Postgres is nodes-base => in-process, so the whole post-decide path touches no task runner. CSV comes afterwards from psql \\copy, which gets the quoting right for free.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [920, -144],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    InsertRows = {
        operation: 'insert',
        schema: {
            __rl: true,
            value: 'public',
            mode: 'list',
        },
        table: {
            __rl: true,
            value: 'decide_oneshot_results',
            mode: 'list',
        },
        columns: {
            mappingMode: 'autoMapInputData',
        },
        options: {},
    };

    @node({
        id: 'dlt-respond-01',
        name: 'Load Test Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1140, 0],
        onError: 'continueRegularOutput',
    })
    LoadTestRespond = {
        respondWith: 'text',
        responseBody: '={{ JSON.stringify({ ok: true, note: "see public.decide_oneshot_results" }) }}',
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
        this.WhenClickingExecuteWorkflow.out(0).to(this.LoadFullTable.in(0));
        this.LoadTestWebhook.out(0).to(this.LoadFullTable.in(0));
        this.LoadFullTable.out(0).to(this.CallDecideOneBatch.in(0));
        this.CallDecideOneBatch.out(0).to(this.SlimVerdicts.in(0));
        this.SlimVerdicts.out(0).to(this.LoopBatches.in(0));
        this.LoopBatches.out(0).to(this.LoadTestRespond.in(0));
        this.LoopBatches.out(1).to(this.InsertRows.in(0));
        this.InsertRows.out(0).to(this.LoopBatches.in(0));
    }
}
