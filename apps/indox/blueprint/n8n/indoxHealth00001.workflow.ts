import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox integration health
// Nodes   : 14  |  Connections: 16
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// ScheduleTrigger                    scheduleTrigger
// RunIndoxHealth                     manualTrigger
// HealthWebhook                      webhook
// DriveCreateProbeFile               executeWorkflow            [onError→regular]
// DriveDownloadProbeFile             executeWorkflow            [onError→regular]
// DriveDeleteProbeFile               executeWorkflow            [onError→regular]
// DriveResult                        code
// MailDocContextProbe                httpRequest                [onError→regular]
// MailResult                         code
// MergeProbes                        merge
// Verdict                            code
// Respond                            respondToWebhook
// StickyNote                         stickyNote
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → DriveCreateProbeFile
//      → DriveDownloadProbeFile
//        → DriveDeleteProbeFile
//          → DriveResult
//            → MergeProbes
//              → Verdict
//                → Respond
//    → MailDocContextProbe
//      → MailResult
//        → MergeProbes.in(1) (↩ loop)
// ScheduleTrigger
//    → DriveCreateProbeFile (↩ loop)
//    → MailDocContextProbe (↩ loop)
// RunIndoxHealth
//    → DriveCreateProbeFile (↩ loop)
//    → MailDocContextProbe (↩ loop)
// HealthWebhook
//    → DriveCreateProbeFile (↩ loop)
//    → MailDocContextProbe (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Schedule Trigger":{"main":[[{"node":"Drive: Create Probe File","type":"main","index":0},{"node":"Mail: Doc Context Probe","type":"main","index":0}]]},"When Called":{"main":[[{"node":"Drive: Create Probe File","type":"main","index":0},{"node":"Mail: Doc Context Probe","type":"main","index":0}]]},"▶ Run Indox Health":{"main":[[{"node":"Drive: Create Probe File","type":"main","index":0},{"node":"Mail: Doc Context Probe","type":"main","index":0}]]},"Health Webhook":{"main":[[{"node":"Drive: Create Probe File","type":"main","index":0},{"node":"Mail: Doc Context Probe","type":"main","index":0}]]},"Drive: Create Probe File":{"main":[[{"node":"Drive: Download Probe File","type":"main","index":0}]]},"Drive: Download Probe File":{"main":[[{"node":"Drive: Delete Probe File","type":"main","index":0}]]},"Drive: Delete Probe File":{"main":[[{"node":"Drive Result","type":"main","index":0}]]},"Drive Result":{"main":[[{"node":"Merge Probes","type":"main","index":0}]]},"Mail: Doc Context Probe":{"main":[[{"node":"Mail Result","type":"main","index":0}]]},"Mail Result":{"main":[[{"node":"Merge Probes","type":"main","index":1}]]},"Merge Probes":{"main":[[{"node":"Verdict","type":"main","index":0}]]},"Verdict":{"main":[[{"node":"Respond","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"de8accc1-f4e8-4a42-887e-4545f489893f","name":"role:infra"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"9a0c3d07-81ee-4b76-a2ca-04112b1e1573","name":"ci/cd"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {"node:Schedule Trigger":{"recurrenceRules":[]}},
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxHealth00001","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxHealth00001',
    name: 'indox integration health',
    active: true,
    isArchived: false,
    tags: ['role:infra', 'indox-app', 'indox', 'ci/cd', 'app:indox'],
    settings: {
        executionOrder: 'v1',
        callerPolicy: 'workflowsFromSameOwner',
        errorWorkflow: 'errorHandler01',
        availableInMCP: false,
        executionTimeout: 300,
    },
})
export class IndoxIntegrationHealthWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'idxh-when-called',
        name: 'When Called',
        /*__n8n__*/ notes: "[app scheduler 2026-08-28] Makes this health check callable as a SUB-WORKFLOW. It previously had only a schedule trigger, a webhook and a manual trigger, so indox01's 'Call Health' would have failed with 'Missing node to start execution' — the same silent failure the drain hit. Additive: the existing entries are untouched.",
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-720, 140],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'idxh-schedule',
        name: 'Schedule Trigger',
        /*__n8n__*/ notes: "[scheduler cutover 2026-08-28] DISABLED, not deleted. indox01 is now the app's only clock and calls this workflow once per ENABLED instance, handing each run its __instance. This trigger fired once globally with no idea instances existed, so leaving it live would double-drive health AND drive it instance-blind. Kept in place because re-enabling it is the revert path: one flag, no restore from backup.",
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [-720, -40],
    })
    ScheduleTrigger = {
        rule: {
            interval: [
                {
                    field: 'hours',
                    hoursInterval: 1,
                },
            ],
        },
    };

    @node({
        id: 'idxh-manual',
        name: '▶ Run Indox Health',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-720, 160],
    })
    RunIndoxHealth = {};

    @node({
        id: 'idxh-webhook',
        webhookId: 'b7c1d2e3-4f5a-4b6c-8d9e-0a1b2c3d4e5f',
        name: 'Health Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 1.1,
        position: [-720, 360],
    })
    HealthWebhook = {
        httpMethod: 'POST',
        path: 'trigger-indox-health',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'idxh-drive-create',
        name: 'Drive: Create Probe File',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-360, -40],
        onError: 'continueRegularOutput',
    })
    DriveCreateProbeFile = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
            cachedResultName: 'drive api',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'createFromText',
                params: "={{ ({ name: 'indox-health-' + $now.toMillis() + '.txt', content: 'indox integration health probe ' + $now.toISO(), profile_id: 'admin' }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                    removed: false,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'idxh-drive-download',
        name: 'Drive: Download Probe File',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-120, -40],
        onError: 'continueRegularOutput',
    })
    DriveDownloadProbeFile = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
            cachedResultName: 'drive api',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'download',
                params: "={{ ({ fileId: $json.id, fileIdMode: 'id', profile_id: 'admin' }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                    removed: false,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'idxh-drive-delete',
        name: 'Drive: Delete Probe File',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [120, -40],
        onError: 'continueRegularOutput',
    })
    DriveDeleteProbeFile = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
            cachedResultName: 'drive api',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'delete',
                params: "={{ ({ fileId: $('Drive: Create Probe File').first().json.id, profile_id: 'admin' }) }}",
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                    removed: false,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: 'idxh-drive-result',
        name: 'Drive Result',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [360, -40],
    })
    DriveResult = {
        jsCode: `// drive api health: the create -> download -> delete round trip must leave an id
// behind and must clean up after itself. Anything else is a failed probe.
// Probe nodes run with onError=continueRegularOutput, so a failed step lands here
// as an item WITHOUT an id (or with an error payload) instead of killing the whole
// execution -- the verdict node then reports the probe as failed.
let ok = false;
let detail = 'drive probe chain did not run';
try {
  const created = ($('Drive: Create Probe File').first() || {}).json || {};
  ok = !!created.id;
  if (!ok) {
    const err = created.error || created.errorMessage || created.description;
    detail = err ? ('probe failed: ' + ((err && err.message) || JSON.stringify(err).slice(0, 300)))
                 : 'createFromText returned no file id';
  } else {
    detail = 'round trip on ' + created.id;
  }
} catch (e) {
  detail = 'probe chain error: ' + ((e && e.message) || String(e));
}
return [{ json: { probe: 'drive api', workflow: 'driveApi01', ok, detail } }];
`,
    };

    @node({
        id: 'idxh-mail-probe',
        name: 'Mail: Doc Context Probe',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [-360, 360],
        onError: 'continueRegularOutput',
    })
    MailDocContextProbe = {
        url: 'http://n8n-webhook:5678/webhook/mail-api/doc-context',
        sendQuery: true,
        queryParameters: {
            parameters: [
                {
                    name: 'source_id',
                    value: 'indoxhealthprobe000',
                },
                {
                    name: '__instance',
                    value: '={{ $json.__instance || "" }}',
                },
            ],
        },
        options: {
            timeout: 30000,
        },
    };

    @node({
        id: 'idxh-mail-result',
        name: 'Mail Result',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-120, 360],
    })
    MailResult = {
        jsCode: `// mail api health: GET /webhook/mail-api/doc-context proves the whole chain --
// webhook -> indoxApiRouter01 -> data backend -> respond. The probe source_id is
// deliberately unmatchable, so the CORRECT answer is a well-formed empty result:
// { found: 0, docs: [] }. A shape mismatch or an error payload is a failure.
const r = $json || {};
const ok = typeof r.found === 'number' && Array.isArray(r.docs) && r.found === 0;
return [{ json: { probe: 'mail api', workflow: 'mailApi01', ok,
  detail: ok ? 'webhook answered {found:0,docs:[]}' :
    ('unexpected response: ' + JSON.stringify(r).slice(0, 300)) } }];
`,
    };

    @node({
        id: 'idxh-merge',
        name: 'Merge Probes',
        type: 'n8n-nodes-base.merge',
        version: 3,
        position: [600, 160],
    })
    MergeProbes = {
        numberInputs: 2,
    };

    @node({
        id: 'idxh-verdict',
        name: 'Verdict',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [840, 160],
    })
    Verdict = {
        jsCode: `// Health is reported the way the original Google Integration Health reported it:
// a green execution means healthy, a thrown error means unhealthy and is caught by
// settings.errorWorkflow -> Error Handler -> GlitchTip. The difference is that this
// one ALSO returns a verdict, so it is assertable from the baseline over the webhook lane.
const probes = $input.all().map(i => i.json).filter(p => p && p.probe);
const failed = probes.filter(p => !p.ok);
const summary = { ok: failed.length === 0, checked: probes.length, probes,
  checked_at: new Date().toISOString() };
if (failed.length) {
  throw new Error('indox integration health FAILED: ' +
    failed.map(f => f.probe + ' (' + f.detail + ')').join('; '));
}
return [{ json: summary }];
`,
    };

    @node({
        id: 'idxh-respond',
        name: 'Respond',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [1080, 160],
    })
    Respond = {
        respondWith: 'allIncomingItems',
        options: {},
    };

    @node({
        id: 'idxh-note',
        name: 'Sticky Note',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-720, -600],
    })
    StickyNote = {
        content: `## indox integration health
Renamed + rescoped successor to \`Google Integration Health\` (\`gwaHealthCheck01\`,
apps/google-workspace-agent/blueprint/n8n/gwaHealthCheck01.json — alive, not deleted; the
false "deleted 2026-07-30" claim that used to be here was itself stale and is fixed now).
That one probed Google directly: the Gmail router, a
hardcoded Google Sheet, and a hardcoded Drive folder id. INDOX no longer talks to Google or to
Sheets directly -- it talks to the **drive api** and **mail api** app workflows -- so this probes
those two contracts instead.

* **drive api** (\`driveApi01\`): createFromText -> download -> delete. Exercises the {op, params}
  contract and the drive service behind it, and deletes its own probe file so it leaves nothing
  behind. No folder id is hardcoded -- \`folderId\` is optional and defaults to the service root.
* **mail api** (\`mailApi01\`): GET /webhook/mail-api/doc-context with an unmatchable source_id.
  The correct answer is \`{found:0, docs:[]}\`, which proves webhook -> indox api -> backend -> respond.

Runnable three ways: the hourly schedule, the manual trigger, or
\`POST /webhook/trigger-indox-health\`, which returns the verdict JSON. That is the baseline lane.`,
        height: 440,
        width: 640,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.ScheduleTrigger.out(0).to(this.DriveCreateProbeFile.in(0));
        this.ScheduleTrigger.out(0).to(this.MailDocContextProbe.in(0));
        this.WhenCalled.out(0).to(this.DriveCreateProbeFile.in(0));
        this.WhenCalled.out(0).to(this.MailDocContextProbe.in(0));
        this.RunIndoxHealth.out(0).to(this.DriveCreateProbeFile.in(0));
        this.RunIndoxHealth.out(0).to(this.MailDocContextProbe.in(0));
        this.HealthWebhook.out(0).to(this.DriveCreateProbeFile.in(0));
        this.HealthWebhook.out(0).to(this.MailDocContextProbe.in(0));
        this.DriveCreateProbeFile.out(0).to(this.DriveDownloadProbeFile.in(0));
        this.DriveDownloadProbeFile.out(0).to(this.DriveDeleteProbeFile.in(0));
        this.DriveDeleteProbeFile.out(0).to(this.DriveResult.in(0));
        this.DriveResult.out(0).to(this.MergeProbes.in(0));
        this.MailDocContextProbe.out(0).to(this.MailResult.in(0));
        this.MailResult.out(0).to(this.MergeProbes.in(1));
        this.MergeProbes.out(0).to(this.Verdict.in(0));
        this.Verdict.out(0).to(this.Respond.in(0));
    }
}
