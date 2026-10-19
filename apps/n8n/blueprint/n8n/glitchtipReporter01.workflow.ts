import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : GlitchTip Error Reporter
// Nodes   : 5  |  Connections: 4
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// ErrorTrigger                       errorTrigger
// CodeInJavascript                   code
// HttpRequest                        httpRequest                [onError→out(1)] [retry]
// WhenExecutedByAnotherWorkflow      executeWorkflowTrigger
// SinkUnreachableSuppressed          code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// ErrorTrigger
//    → CodeInJavascript
//      → HttpRequest
//       .out(1) → SinkUnreachableSuppressed
// WhenExecutedByAnotherWorkflow
//    → CodeInJavascript (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Error Trigger":{"main":[[{"node":"Code in JavaScript","type":"main","index":0}]]},"Code in JavaScript":{"main":[[{"node":"HTTP Request","type":"main","index":0}]]},"HTTP Request":{"main":[[],[{"node":"Sink Unreachable (suppressed)","type":"main","index":0}]]},"When Executed by Another Workflow":{"main":[[{"node":"Code in JavaScript","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:44:12.933Z","createdAt":"2026-07-30T23:44:12.933Z","id":"12d9b7a3-e589-4bf5-aaa1-26a013cd0175","name":"shared"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"536fb995-3c38-4ed4-9683-ae8d07edb41e","name":"n8n-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"de8accc1-f4e8-4a42-887e-4545f489893f","name":"role:infra"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"7e527add-9b38-577f-82e2-2d04f0c4d9db","name":"app:n8n"}],
    /*__n8n__*/ versionMetadata: {"name":"Version 4ae0fac8","description":""},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T01:00:42.729Z","createdAt":"2026-07-31T01:00:42.729Z","role":"workflow:owner","workflowId":"glitchtipReporter01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'glitchtipReporter01',
    name: 'GlitchTip Error Reporter',
    active: true,
    isArchived: false,
    tags: ['shared', 'n8n-app', 'role:infra', 'app:n8n'],
    settings: { executionOrder: 'v1' },
})
export class GlitchtipErrorReporterWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '808ad6aa-ec44-448a-a93a-60d0408811a5',
        name: 'Error Trigger',
        type: 'n8n-nodes-base.errorTrigger',
        version: 1,
        position: [0, 0],
    })
    ErrorTrigger = {};

    @node({
        id: '25fd464e-263d-4c20-b7da-fba45f7ae2fe',
        name: 'Code in JavaScript',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [208, 0],
    })
    CodeInJavascript = {
        jsCode: `// Build a Sentry-compatible event from the Error Trigger payload.
// Goal: a DESCRIPTIVE title so התראות shows WHICH workflow failed and WHY.
// n8n's Error Trigger emits TWO shapes: runtime node errors under
// \`execution.error\`, and activation/trigger errors under \`trigger.error\`.
// Read both so the message is never lost to "Unknown workflow error".
const d = $input.first().json || {};
const wf = d.workflow || {};
const ex = d.execution || {};
const trg = d.trigger || {};
const err = ex.error || trg.error || {};

const wfName = wf.name || 'workflow';
const nodeName = (err.node && err.node.name) || ex.lastNodeExecuted || '';
const msg = err.message
  || err.description
  || (err.cause && err.cause.message)
  || (err.errorResponse && err.errorResponse.message)
  || (typeof err === 'string' ? err : '')
  || 'workflow execution failed';
const errType = err.name || err.type || 'WorkflowError';
const nodePart = nodeName ? \` · \${nodeName}\` : '';

// Skip n8n ACTIVATION-time errors (mode=internal / WorkflowActivationError): these fire on
// every restart for triggerless or leftover workflows — config noise, not runtime failures.
// They'd bury the actionable errors (a failed extraction, a real node error) in התראות.
if (errType === 'WorkflowActivationError' || (trg.mode === 'internal' && /has no node to start|problem activating/i.test(msg))) {
  return [];
}

// GEN:REPORT_GATE:BEGIN — regenerated by gate_glitchtip_reporter() in apps/n8n/hooks/push.
// Never hand-edit: the hook rewrites this block from ERROR_REPORT_GLITCHTIP + N8N_SENTRY_DSN on
// every push, exactly as gate_telegram_notifier() does for errorHandler01's Telegram branch.
const REPORTING_ENABLED = true;
const DISABLED_REASON = "";
// GEN:REPORT_GATE:END

// A disabled sink must produce a VISIBLE skip, never a bare success. "Returns success while doing
// nothing" is the dominant defect class in this platform, so the skip carries the reason AND the
// error it would have reported — an operator can tell it apart from a real send at a glance.
if (!REPORTING_ENABLED) {
  return [{ json: {
    __report_skipped: true,
    reason: DISABLED_REASON || 'error reporting disabled',
    would_have_reported: { workflow: wfName, node: nodeName || null, message: msg, type: errType },
    timestamp: new Date().toISOString(),
  }}];
}

const sentryEvent = {
  event_id: require('crypto').randomBytes(16).toString('hex'),
  timestamp: new Date().toISOString(),
  platform: 'node',
  level: 'error',
  logger: 'n8n.workflow',
  server_name: 'n8n-workflow-engine',
  environment: 'production',
  release: 'n8n-workflows@1.0.0',
  transaction: wfName,
  exception: { values: [{
    // TITLE in GlitchTip/התראות: "<workflow> · <node>: <message>"
    type: \`\${wfName}\${nodePart}\`,
    value: \`\${msg}\` + (errType && errType !== 'WorkflowError' ? \` (\${errType})\` : ''),
    stacktrace: { frames: [{ filename: wfName, function: nodeName || 'unknown', lineno: 1, in_app: true }]}
  }]},
  tags: {
    workflow_id: String(wf.id || 'unknown'),
    workflow_name: wfName,
    node_name: nodeName || 'unknown',
    node_type: (err.node && err.node.type) || 'unknown',
    execution_id: String(ex.id || 'unknown'),
    execution_mode: ex.mode || trg.mode || 'unknown'
  },
  extra: {
    workflow: { id: wf.id, name: wfName, active: wf.active },
    execution: { id: ex.id, mode: ex.mode || trg.mode, retryOf: ex.retryOf, startedAt: ex.startedAt, url: ex.url },
    error: { message: msg, type: errType, stack: err.stack, node: err.node, context: err.context }
  },
  fingerprint: [ wfName, nodeName || 'unknown', errType ]
};

return [{ json: sentryEvent }];`,
    };

    @node({
        id: '49843eab-2a26-425a-be69-f519862a2250',
        name: 'HTTP Request',
        /*__n8n__*/ notes: "RCA 2026-08-05: URL project id must match the project that owns sentry_key ba06c13f8350cf7e77b6d6246278f2d2. .generated/glitchtip.projects.yml provisions projects alphabetically; 'n8n' is the 11th of 13 -> project id 11 on a freshly-provisioned GlitchTip DB (verified live: projects_projectkey.project_id=11 for this key). The old hardcoded '/api/1/store/' pointed at project 1 (any-concurrency), so GlitchTip correctly rejected every event all day with 401 'Invalid DSN' -- the reporter was never actually reaching GlitchTip. If the app roster ever changes alphabetical order before 'n8n', this id needs updating again; consider resolving it dynamically instead of hardcoding.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.httpRequest',
        version: 4.3,
        position: [416, 0],
        onError: 'continueErrorOutput',
        retryOnFail: true,
        waitBetweenTries: 3000,
    })
    HttpRequest = {
        method: 'POST',
        url: 'http://glitchtip:8000/api/11/store/',
        sendHeaders: true,
        headerParameters: {
            parameters: [
                {
                    name: 'Content-Type',
                    value: 'application/json',
                },
                {
                    name: 'X-Sentry-Auth',
                    value: 'Sentry sentry_version=7, sentry_client=n8n-workflow/1.0, sentry_key=ba06c13f8350cf7e77b6d6246278f2d2',
                },
            ],
        },
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ $json }}',
        options: {},
    };

    @node({
        id: '48a7544a-324b-44aa-99cb-d81f7eb7561b',
        name: 'When Executed by Another Workflow',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, -176],
    })
    WhenExecutedByAnotherWorkflow = {
        inputSource: 'passthrough',
    };

    @node({
        id: '9f3c1d70-5b21-4e08-9a44-2c6d7e1f0b93',
        name: 'Sink Unreachable (suppressed)',
        /*__n8n__*/ notes: "Error branch of HTTP Request. Keeps the reporter structurally incapable of producing an error execution, whatever the sink does — see RCA 2026-08-06 (reporter/handler cycle).",
        /*__n8n__*/ notesInFlow: true,
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [624, 0],
    })
    SinkUnreachableSuppressed = {
        jsCode: `// The GlitchTip sink rejected the event or was unreachable.
// This is DELIBERATELY a green outcome. RCA 2026-08-06: the LIVE workflow_entity row for
// glitchtipReporter01 carried settings.errorWorkflow = 'errorHandler01', and errorHandler01's
// "Call 'GlitchTip Error Reporter'" node calls this workflow — so a failed report re-entered the
// handler, which called the reporter again, which failed again. Measured 2026-08-06 01:10-01:45Z:
// ~1,205 reporter errors against ~1,481 handler runs in one hour, a near-1:1 self-sustaining cycle
// that buried every real fault. An error-reporting path must never be able to emit an error.
// Record the failure here, legibly, and exit green.
const err = ($input.first().json || {}).error || {};
return [{ json: {
  __report_skipped: true,
  __sink_unreachable: true,
  reason: 'glitchtip sink unreachable or rejected the event',
  sink_error: err.message || err.description || String(err.reason || '').slice(0, 300) || 'unknown',
  http_code: err.httpCode || err.statusCode || null,
  timestamp: new Date().toISOString(),
}}];`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.ErrorTrigger.out(0).to(this.CodeInJavascript.in(0));
        this.CodeInJavascript.out(0).to(this.HttpRequest.in(0));
        this.HttpRequest.out(1).to(this.SinkUnreachableSuppressed.in(0));
        this.WhenExecutedByAnotherWorkflow.out(0).to(this.CodeInJavascript.in(0));
    }
}
