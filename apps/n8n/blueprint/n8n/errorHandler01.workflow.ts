import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Error Handler
// Nodes   : 16  |  Connections: 15
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// ErrorTrigger                       errorTrigger
// Telegram                           telegram                   [creds]
// GetLockMap                         redis                      [creds]
// IfHasLock                          if
// RecordErrorNoBackoffNoStatus       postgres                   [onError→regular] [creds]
// EhUnlockDoc                        executeWorkflow
// EhDelMap                           redis                      [creds]
// ClassifyError                      code
// IsCrashDebris                      if
// RecordCrashNoCascade               postgres                   [onError→regular] [creds]
// BuildSentryEvent                   code
// SendToGlitchtip                    httpRequest                [onError→out(1)] [retry]
// SinkUnreachableSuppressed          code
// EhScanActionKeys                   redis                      [onError→regular] [creds] [alwaysOutput]
// EhMapLockKeys                      code
// EhUnlockDocAction                  executeWorkflow            [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// ErrorTrigger
//    → ClassifyError
//      → IsCrashDebris
//        → RecordCrashNoCascade
//       .out(1) → BuildSentryEvent
//          → SendToGlitchtip
//           .out(1) → SinkUnreachableSuppressed
//       .out(1) → Telegram
//    → GetLockMap
//      → IfHasLock
//        → RecordErrorNoBackoffNoStatus
//          → EhUnlockDoc
//            → EhDelMap
//    → EhScanActionKeys
//      → EhMapLockKeys
//        → EhUnlockDocAction
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Error Trigger":{"main":[[{"node":"Classify Error","type":"main","index":0},{"node":"Get Lock Map","type":"main","index":0},{"node":"EH Scan Action Keys","type":"main","index":0}]]},"Get Lock Map":{"main":[[{"node":"If Has Lock","type":"main","index":0}]]},"If Has Lock":{"main":[[{"node":"Record ERROR (no backoff, no status)","type":"main","index":0}],[]]},"EH Unlock Doc":{"main":[[{"node":"EH Del Map","type":"main","index":0}]]},"Classify Error":{"main":[[{"node":"Is Crash Debris?","type":"main","index":0}]]},"Is Crash Debris?":{"main":[[{"node":"Record Crash (no cascade)","type":"main","index":0}],[{"node":"Build Sentry Event","type":"main","index":0},{"node":"Telegram","type":"main","index":0}]]},"Build Sentry Event":{"main":[[{"node":"Send To GlitchTip","type":"main","index":0}]]},"Send To GlitchTip":{"main":[[],[{"node":"Sink Unreachable (suppressed)","type":"main","index":0}]]},"EH Scan Action Keys":{"main":[[{"node":"EH Map Lock Keys","type":"main","index":0}]]},"EH Map Lock Keys":{"main":[[{"node":"EH Unlock Doc Action","type":"main","index":0}]]},"Record ERROR (no backoff, no status)":{"main":[[{"node":"EH Unlock Doc","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:44:12.933Z","createdAt":"2026-07-30T23:44:12.933Z","id":"12d9b7a3-e589-4bf5-aaa1-26a013cd0175","name":"shared"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"536fb995-3c38-4ed4-9683-ae8d07edb41e","name":"n8n-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"de8accc1-f4e8-4a42-887e-4545f489893f","name":"role:infra"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"7e527add-9b38-577f-82e2-2d04f0c4d9db","name":"app:n8n"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {"Error Trigger":[{"json":{"execution":{"id":"2203101","url":"http://n8n:5678/workflow/Qq2sY8nWb4Dz0KcL/executions/2203101","error":{"cause":{"ID":"={{ $('Google Sheets Trigger').item.json.ID }}","STATUS":"COMPLETED"},"level":"warning","tags":{},"timestamp":1761937352515,"context":{"runIndex":0,"itemIndex":0,"messageTemplate":"An expression references this node, but the node is unexecuted. Consider re-wiring your nodes or checking for execution first, i.e. {{ $if( $(\"{{nodeName}}\").isExecuted, <action_if_executed>, \"\") }}","descriptionKey":"pairedItemNoConnection","type":"no_execution_data","nodeCause":"Google Sheets Trigger","parameter":"workflowInputs.value"},"functionality":"pairedItem","name":"ExpressionError","message":"Node 'Google Sheets Trigger' hasn't been executed","stack":"ExpressionError: Node 'Google Sheets Trigger' hasn't been executed\n    at createExpressionError (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/n8n-workflow@file+packages+workflow/node_modules/n8n-workflow/src/workflow-data-proxy.ts:790:11)\n    at ensureNodeExecutionData (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/n8n-workflow@file+packages+workflow/node_modules/n8n-workflow/src/workflow-data-proxy.ts:1093:13)\n    at Object.get (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/n8n-workflow@file+packages+workflow/node_modules/n8n-workflow/src/workflow-data-proxy.ts:1153:9)\n    at Proxy.eval (eval at getFunction (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/@n8n+tournament@1.0.6/node_modules/@n8n/tournament/src/FunctionEvaluator.ts:13:16), <anonymous>:6:68)\n    at FunctionEvaluator.evaluate (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/@n8n+tournament@1.0.6/node_modules/@n8n/tournament/src/FunctionEvaluator.ts:20:13)\n    at Tournament.execute (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/@n8n+tournament@1.0.6/node_modules/@n8n/tournament/src/index.ts:45:25)\n    at evaluateExpression (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/n8n-workflow@file+packages+workflow/node_modules/n8n-workflow/src/expression-evaluator-proxy.ts:20:9)\n    at Expression.renderExpression (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/n8n-workflow@file+packages+workflow/node_modules/n8n-workflow/src/expression.ts:330:29)\n    at Expression.resolveSimpleParameterValue (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/n8n-workflow@file+packages+workflow/node_modules/n8n-workflow/src/expression.ts:311:28)\n    at resolveParameterValue (/usr/local/lib/node_modules/n8n/node_modules/.pnpm/n8n-workflow@file+packages+workflow/node_modules/n8n-workflow/src/expression.ts:501:16)"},"lastNodeExecuted":"Call 'Incoming Document Batch Update' - STATUS COMPLETED (BS)","mode":"trigger"},"workflow":{"id":"Qq2sY8nWb4Dz0KcL","name":"Incoming Documents 0.1.2 - Test"}}}]},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T01:00:42.729Z","createdAt":"2026-07-31T01:00:42.729Z","role":"workflow:owner","workflowId":"errorHandler01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'errorHandler01',
    name: 'Error Handler',
    active: true,
    isArchived: false,
    tags: ['shared', 'n8n-app', 'role:infra', 'app:n8n'],
    settings: { executionOrder: 'v1' },
})
export class ErrorHandlerWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'c232a177-ca37-48b9-bf66-f810d337692f',
        name: 'Error Trigger',
        type: 'n8n-nodes-base.errorTrigger',
        version: 1,
        position: [608, 496],
    })
    ErrorTrigger = {};

    @node({
        id: '2085488b-aeac-4021-a8de-47cb3dd93b9a',
        webhookId: '6a726a93-eebc-4966-a976-c3fbef2d510d',
        name: 'Telegram',
        /*__n8n__*/ notes: "Alert delivery. NO continueOnFail: a rejected alert is a FAILURE and must show as one when it runs for real. GATED (optional, default OFF): committed `disabled:true` is the safe default because no real TELEGRAM_BOT_TOKEN has ever existed for this credential (.env's is the literal placeholder \"your-telegram-bot-token-here\", synced into EmuwriU7cnK5nZTM on every restart) -- every error handled by this workflow used to ALSO fail here (\"Not Found\"), which made the whole errorHandler01 execution show as error/crashed even though the GlitchTip report and the lock/dead-letter branches had completed. `apps/n8n/hooks/push` (gate_telegram_notifier) flips `disabled` at push time based on .env: enabled only when ERROR_NOTIFY_TELEGRAM=true AND TELEGRAM_BOT_TOKEN is set to something other than the placeholder. Runs last (v1 canvas order) so failing here (when genuinely enabled) cannot suppress the doc unlock or the GlitchTip report.",
        /*__n8n__*/ notesInFlow: false,
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.telegram',
        version: 1.2,
        position: [768, 700],
        credentials: { telegramApi: { id: 'EmuwriU7cnK5nZTM', name: 'N8N TG LOGGER [env-managed]' } },
    })
    Telegram = {
        chatId: '=-1002488442473',
        text: `=Workflow: <pre>{{ JSON.stringify($('Error Trigger').item.json.workflow, null, 2).slice(0, 150).replace(/</g, '&lt;').replace(/>/g, '&gt;') }}</pre>

Execution: <pre>{{ JSON.stringify($('Error Trigger').item.json.execution, null, 2).slice(0, 3500).replace(/</g, '&lt;').replace(/>/g, '&gt;') }}</pre>



`,
        additionalFields: {
            appendAttribution: false,
            parse_mode: 'HTML',
        },
    };

    @node({
        id: 'eh-getmap',
        name: 'Get Lock Map',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [0, 440],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    GetLockMap = {
        operation: 'get',
        propertyName: '_lockdoc',
        key: '=n8n.exec.{{ $json.execution.id }}.docmap',
        options: {},
    };

    @node({
        id: 'eh-ifhas',
        name: 'If Has Lock',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [210, 440],
    })
    IfHasLock = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'eh-has',
                    leftValue: '={{ $json._lockdoc }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
    };

    @node({
        id: 'eh-backoff',
        name: 'Record ERROR (no backoff, no status)',
        /*__n8n__*/ notes: "onError=continueRegularOutput is INTENTIONAL: EH Unlock Doc downstream must run even if this write fails, else the doc stays locked for the 10min TTL. The underlying error is still reported via the GlitchTip branch.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [420, 440],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
    })
    RecordErrorNoBackoffNoStatus = {
        operation: 'executeQuery',
        query: `=/* CLEANUP #9, 2026-08-14. This is n8n's GLOBAL error handler: it fires on ANY execution
   failure, including infrastructure ones it cannot distinguish from a bad document. It must
   therefore NOT author state. It used to author a retry counter, STATUS='MAX_ITERATIONS' at 5,
   and an exponential park; a single n8n restart then moved MAX_ITERATIONS 367 -> 379.
   The iteration guard still exists where it belongs -- 'Global :: Record Base Doc Failure'
   owns it, on a real action outcome. Re-running a failed document is ACTION_RESTART, and only
   that. This handler writes ERROR and nothing else.

   [multi-instance 2026-08-28] The table reference was UNQUALIFIED, resolving through search_path to
   public. The instance is taken from the SAME item this already reads the document id from: the doc
   and the schema it lives in have to agree, and reading them from two places is how they diverge.
   Absent, it resolves to public exactly as before. Note this handler fires on ANY execution failure,
   including ones with no document context at all — that is why it stays fail-soft rather than
   throwing on a missing instance.

   [tenancy cutover 2026-08-31] The soft public fallback is REMOVED, but this handler runs for EVERY
   workflow's failures and must never throw — a throwing error handler eats the original error. So
   it GATES instead: a valid __instance routes the UPDATE to indox_<instance>.incoming_documents;
   anything else writes a legible skip row to public.app_logs (a SHARED table) and touches no tenant
   table. The docmap writers currently store the bare doc id, so until one supplies __instance
   alongside it this branch records skips — the safe half of the old behaviour, minus the public
   write. */
{{ (() => { const q = (s) => String(s).replace(/'/g, "''"); const lock = $('Get Lock Map').first().json || {}; const et = $('Error Trigger').first().json || {}; const i = String(lock.__instance || ''); const doc = q(lock._lockdoc || ''); const exec = q((et.execution || {}).id || ''); const ex = (et.execution || {}); const msg = q(String(((ex.error || {}).message) || (ex.lastNodeExecuted ? 'failed at ' + ex.lastNodeExecuted : '') || '').slice(0, 300)); if (/^[a-z][a-z0-9_]*$/.test(i)) { return "UPDATE indox_" + i + ".incoming_documents SET \\"ERROR\\" = LEFT('action failed @exec " + exec + (msg ? ": " + msg : "") + "', 500) WHERE \\"ID\\" = '" + doc + "' AND \\"STATUS\\" NOT IN ('COMPLETED','OLD','EXTRACTION_FAILED','GARBAGE','DOUBLE','MERGED');"; } return "INSERT INTO public.app_logs (stream, payload) VALUES ('n8n.error_handler.skipped_doc_error', jsonb_build_object('reason', 'no valid __instance — tenant incoming_documents write skipped (2026-08-31 cutover)', 'doc_id', '" + doc + "', 'execution_id', '" + exec + "', 'workflow_id', '" + q((et.workflow || {}).id || '') + "'));"; })() }}`,
        options: {},
    };

    @node({
        id: 'eh-unlock',
        name: 'EH Unlock Doc',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [640, 440],
    })
    EhUnlockDoc = {
        workflowId: {
            __rl: true,
            value: 'processLock01',
            mode: 'list',
            cachedResultName: 'process_lock',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                PROCESS: 'doc_action',
                KEY: "={{ $('Get Lock Map').first().json._lockdoc }}",
                ACTION: 'unlock',
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'PROCESS',
                    displayName: 'PROCESS',
                    type: 'string',
                    display: true,
                    required: false,
                    canBeUsedToMatch: true,
                    removed: false,
                },
                {
                    id: 'KEY',
                    displayName: 'KEY',
                    type: 'string',
                    display: true,
                    required: false,
                    canBeUsedToMatch: true,
                    removed: false,
                },
                {
                    id: 'ACTION',
                    displayName: 'ACTION',
                    type: 'string',
                    display: true,
                    required: false,
                    canBeUsedToMatch: true,
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        mode: 'each',
        options: {},
    };

    @node({
        id: 'eh-delmap',
        name: 'EH Del Map',
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [840, 440],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
    })
    EhDelMap = {
        operation: 'delete',
        key: "=n8n.exec.{{ $('Error Trigger').first().json.execution.id }}.docmap",
    };

    @node({
        id: 'b1a7c2e0-11aa-4c31-9d70-2f5a6c0e11a1',
        name: 'Classify Error',
        /*__n8n__*/ notes: "Crash-signature split. See jsCode: records shutdown debris without cascading, keeps genuine OOM visible for the census.",
        /*__n8n__*/ notesInFlow: true,
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [760, 200],
    })
    ClassifyError = {
        jsCode: `// TASK 1 (2026-08-06) — tell SHUTDOWN DEBRIS apart from a real failure, before anything cascades.
//
// n8n marks every in-flight execution \`crashed\` when the process goes down, and fires the wired
// errorWorkflow ONCE PER CRASHED EXECUTION. So a single \`bbox n8n push\` manufactured ~200 Error
// Handler runs and ~200 GlitchTip runs: measured 195 of 245 invocations in one 30-minute window
// were \`WorkflowCrashedError\`, spread across three unrelated workflows with near-identical counts
// (Sync v3 Deliver 114 / Sync Processor - drive-gdoc 114 / Process Document 108). One operational
// event became hundreds of executions — that is the amplifier the owner is looking at on the board.
//
// THIS DOES NOT DROP THE CLASS. A genuine host OOM is the same signature (the monitor lane has
// kernel evidence of four CONSTRAINT_NONE kills of apitools in 18 minutes), so discarding it would
// hide real resource exhaustion. The split of duty is deliberate:
//   * HERE, per execution: record it compactly and do not cascade. A single execution cannot see
//     the pattern that distinguishes debris from a real kill, so it does not try to guess.
//   * IN THE CENSUS, across executions: scripts/ops/error-pulse.sh (CENSUS_HOURS=..) already does
//     the discrimination properly, via mass-stop instants — many executions across SEVERAL
//     DIFFERENT workflows stopping in the same second, which nothing but a teardown produces.
//     Measured chance baseline 0.10%; debris scores 96-100%, real defects score at chance.
// Recording without amplifying is enough on its own, and it keeps the evidence the census needs.
const d = $input.first().json || {};
const wf = d.workflow || {};
const ex = d.execution || {};
const trg = d.trigger || {};
const err = ex.error || trg.error || {};
const msg = String(err.message || err.description || '');
const kind = String(err.name || err.type || '');

const isCrash = kind === 'WorkflowCrashedError'
  || /possible out-of-memory issue/i.test(msg)
  || /workflow did not finish/i.test(msg);

return [{ json: {
  __is_crash: isCrash,
  crash_payload: {
    workflow_id: wf.id || null,
    workflow_name: wf.name || null,
    execution_id: ex.id || null,
    execution_mode: ex.mode || trg.mode || null,
    stopped_at: new Date().toISOString(),
    error_kind: kind || null,
    message: msg.slice(0, 500),
    // Deliberately NOT classified here. The census decides debris-vs-real from the
    // cross-workflow mass-stop pattern; a single execution has no view of it.
    classification: 'deferred-to-census',
  },
  // everything the reporter branch needs, untouched
  ...d,
}}];`,
    };

    @node({
        id: 'b1a7c2e0-11aa-4c31-9d70-2f5a6c0e11a2',
        name: 'Is Crash Debris?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [960, 200],
    })
    IsCrashDebris = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'c0a1f2d3-0001-4a11-9b22-33e4f5a6b7c8',
                    leftValue: '={{ $json.__is_crash }}',
                    rightValue: '',
                    operator: {
                        type: 'boolean',
                        operation: 'true',
                        singleValue: true,
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'b1a7c2e0-11aa-4c31-9d70-2f5a6c0e11a3',
        name: 'Record Crash (no cascade)',
        /*__n8n__*/ notes: "Terminal on purpose: the crash is RECORDED (public.app_logs, stream n8n.crash) and goes no further. Parameterised ($1), never string-interpolated — the message is attacker-adjacent text. onError=continueRegularOutput so a logging failure can never itself raise and re-enter this handler.",
        /*__n8n__*/ notesInFlow: true,
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1180, 120],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
    })
    RecordCrashNoCascade = {
        operation: 'executeQuery',
        query: `INSERT INTO public.app_logs (stream, payload)
VALUES ('n8n.crash', $1::jsonb);`,
        options: {
            queryReplacement: '={{ JSON.stringify($json.crash_payload) }}',
        },
    };

    @node({
        id: 'b1a7c2e0-11aa-4c31-9d70-2f5a6c0e11a4',
        name: 'Build Sentry Event',
        /*__n8n__*/ notes: "Merged from glitchtipReporter01 (2026-08-06, owner: one error-handling workflow). Carries the GEN:REPORT_GATE block that apps/n8n/hooks/push rewrites from ERROR_REPORT_GLITCHTIP — the hook now finds this node by that MARKER, not by name.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1180, 280],
    })
    BuildSentryEvent = {
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
const REPORTING_ENABLED = false;
const DISABLED_REASON = "ERROR_REPORT_GLITCHTIP=false (must be exactly 'true')";
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
        id: 'b1a7c2e0-11aa-4c31-9d70-2f5a6c0e11a5',
        name: 'Send To GlitchTip',
        /*__n8n__*/ notes: "RCA 2026-08-05: URL project id must match the project that owns sentry_key ba06c13f8350cf7e77b6d6246278f2d2. .generated/glitchtip.projects.yml provisions projects alphabetically; 'n8n' is the 11th of 13 -> project id 11 on a freshly-provisioned GlitchTip DB (verified live: projects_projectkey.project_id=11 for this key). The old hardcoded '/api/1/store/' pointed at project 1 (any-concurrency), so GlitchTip correctly rejected every event all day with 401 'Invalid DSN' -- the reporter was never actually reaching GlitchTip. If the app roster ever changes alphabetical order before 'n8n', this id needs updating again; consider resolving it dynamically instead of hardcoding.",
        /*__n8n__*/ notesInFlow: false,
        type: 'n8n-nodes-base.httpRequest',
        version: 4.3,
        position: [1400, 280],
        onError: 'continueErrorOutput',
        retryOnFail: true,
        waitBetweenTries: 3000,
    })
    SendToGlitchtip = {
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
        id: 'b1a7c2e0-11aa-4c31-9d70-2f5a6c0e11a6',
        name: 'Sink Unreachable (suppressed)',
        /*__n8n__*/ notes: "Error branch of HTTP Request. Keeps the reporter structurally incapable of producing an error execution, whatever the sink does — see RCA 2026-08-06 (reporter/handler cycle).",
        /*__n8n__*/ notesInFlow: true,
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1620, 360],
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

    @node({
        id: 'eh-scan-action-keys',
        name: 'EH Scan Action Keys',
        /*__n8n__*/ notes: "Recover which <ID>::<ACTION> pairs the FAILED execution was holding. indoxV2ActionRouter01/\"Redis Start\" writes incoming_docs_actions:<ID>:<ACTION>:<execId> BEFORE the action runs, so the marker exists for every line that got as far as being dispatched. Scoped by execution id, so this never touches another run's locks.",
        type: 'n8n-nodes-base.redis',
        version: 1,
        position: [400, 620],
        credentials: { redis: { id: 'BoJE1odVZ6MBcpax', name: 'Redis Local Account [env-managed]' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    EhScanActionKeys = {
        operation: 'keys',
        keyPattern: '=incoming_docs_actions:*:{{ $json.execution.id }}',
        getValues: false,
    };

    @node({
        id: 'eh-map-lock-keys',
        name: 'EH Map Lock Keys',
        /*__n8n__*/ notes: "Rebuilds the exact key shape the acquire used: String(ID) + \"::\" + String(ACTION).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [620, 620],
    })
    EhMapLockKeys = {
        jsCode: `// Turn incoming_docs_actions:<ID>:<ACTION>:<execId> back into the composite lock key.
// THIS NODE MUST NEVER THROW. It runs inside the error handler; an exception here would
// bury the original error and skip the release that this whole branch exists to perform.
const out = [];
try {
  for (const item of $input.all()) {
    const keys = (item && item.json && item.json.keys) || [];
    for (const k of keys) {
      try {
        const p = String(k).split(':');
        // [0]=incoming_docs_actions [1]=ID [2]=ACTION [3]=execId
        if (p.length < 4) continue;
        const id = p[1], action = p[2];
        if (!id || !action) continue;
        out.push({ json: { KEY: String(id) + '::' + String(action), ID: id, ACTION: action } });
      } catch (e) { /* one malformed key must not lose the rest */ }
    }
  }
} catch (e) { return []; }
return out;`,
    };

    @node({
        id: 'eh-unlock-doc-action',
        name: 'EH Unlock Doc Action',
        /*__n8n__*/ notes: "FAILURE-side release of the doc_action mutex. The success side lives in indoxV2ActionRouter01; releasing only on success is the same leak in slow motion, because the failure path is what accumulates. The pre-existing \"EH Unlock Doc\" beside this one releases PROCESS=doc_step keyed on the bare document id, which no longer matches anything the driver acquires — it is kept because \"EH Del Map\" is chained behind it, not because it still frees a lock.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [840, 620],
        onError: 'continueRegularOutput',
    })
    EhUnlockDocAction = {
        workflowId: {
            __rl: true,
            value: 'processLock01',
            mode: 'list',
            cachedResultUrl: '/workflow/processLock01',
            cachedResultName: 'process_lock',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                PROCESS: 'doc_action',
                KEY: '={{ $json.KEY }}',
                ACTION: 'unlock',
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'PROCESS',
                    displayName: 'PROCESS',
                    type: 'string',
                    display: true,
                    required: false,
                    canBeUsedToMatch: true,
                    removed: false,
                },
                {
                    id: 'KEY',
                    displayName: 'KEY',
                    type: 'string',
                    display: true,
                    required: false,
                    canBeUsedToMatch: true,
                    removed: false,
                },
                {
                    id: 'ACTION',
                    displayName: 'ACTION',
                    type: 'string',
                    display: true,
                    required: false,
                    canBeUsedToMatch: true,
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        mode: 'each',
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.ErrorTrigger.out(0).to(this.ClassifyError.in(0));
        this.ErrorTrigger.out(0).to(this.GetLockMap.in(0));
        this.ErrorTrigger.out(0).to(this.EhScanActionKeys.in(0));
        this.GetLockMap.out(0).to(this.IfHasLock.in(0));
        this.IfHasLock.out(0).to(this.RecordErrorNoBackoffNoStatus.in(0));
        this.EhUnlockDoc.out(0).to(this.EhDelMap.in(0));
        this.ClassifyError.out(0).to(this.IsCrashDebris.in(0));
        this.IsCrashDebris.out(0).to(this.RecordCrashNoCascade.in(0));
        this.IsCrashDebris.out(1).to(this.BuildSentryEvent.in(0));
        this.IsCrashDebris.out(1).to(this.Telegram.in(0));
        this.BuildSentryEvent.out(0).to(this.SendToGlitchtip.in(0));
        this.SendToGlitchtip.out(1).to(this.SinkUnreachableSuppressed.in(0));
        this.EhScanActionKeys.out(0).to(this.EhMapLockKeys.in(0));
        this.EhMapLockKeys.out(0).to(this.EhUnlockDocAction.in(0));
        this.RecordErrorNoBackoffNoStatus.out(0).to(this.EhUnlockDoc.in(0));
    }
}
