import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox-v2 Drain (pool: P lanes x B documents)
// Nodes   : 26  |  Connections: 28
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// DrainWebhook                       webhook                    [creds]
// RespondHandle                      respondToWebhook           [onError→regular]
// Tick2m                             scheduleTrigger
// WhenCalled                         executeWorkflowTrigger
// ReadSettings                       postgres                   [onError→regular] [creds] [alwaysOutput]
// NormalizeRequest                   code
// IfGateOpen                         if
// GateClosed                         noOp
// SoloCheck                          postgres                   [onError→regular] [creds] [alwaysOutput]
// IfSolo                             if
// ReapStaleDispatches                postgres                   [onError→regular] [creds] [alwaysOutput]
// SelectIds                          postgres                   [creds] [alwaysOutput]
// InitPool                           code
// Scheduler                          code
// IfDone                             if
// ExpandFire                         code
// IfFire                             if
// SkipFire                           noOp
// FireLanes                          httpRequest                [onError→regular] [creds] [alwaysOutput]
// RecordInflight                     code
// TickWait                           postgres                   [creds]
// PollStatus                         postgres                   [creds] [alwaysOutput]
// PollProgress                       postgres                   [creds] [alwaysOutput]
// Reconcile                          code
// Summarize                          code
// DrainDone                          noOp
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// DrainWebhook
//    → RespondHandle
//    → ReadSettings
//      → NormalizeRequest
//        → IfGateOpen
//          → SoloCheck
//            → IfSolo
//              → ReapStaleDispatches
//                → SelectIds
//                  → InitPool
//                    → Scheduler
//                      → IfDone
//                        → Summarize
//                          → DrainDone
//                       .out(1) → ExpandFire
//                          → IfFire
//                            → SkipFire
//                              → RecordInflight
//                                → TickWait
//                                  → PollStatus
//                                    → PollProgress
//                                      → Reconcile
//                                        → Scheduler (↩ loop)
//                           .out(1) → FireLanes
//                              → RecordInflight (↩ loop)
//             .out(1) → GateClosed
//         .out(1) → GateClosed (↩ loop)
// Tick2m
//    → ReadSettings (↩ loop)
// WhenCalled
//    → ReadSettings (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Drain Webhook":{"main":[[{"node":"Respond Handle","type":"main","index":0},{"node":"Read Settings","type":"main","index":0}]]},"Tick (2m)":{"main":[[{"node":"Read Settings","type":"main","index":0}]]},"When Called":{"main":[[{"node":"Read Settings","type":"main","index":0}]]},"Read Settings":{"main":[[{"node":"Normalize Request","type":"main","index":0}]]},"Normalize Request":{"main":[[{"node":"If Gate Open?","type":"main","index":0}]]},"If Gate Open?":{"main":[[{"node":"Solo Check","type":"main","index":0}],[{"node":"Gate Closed","type":"main","index":0}]]},"Select IDs":{"main":[[{"node":"Init Pool","type":"main","index":0}]]},"Init Pool":{"main":[[{"node":"Scheduler","type":"main","index":0}]]},"Scheduler":{"main":[[{"node":"If Done?","type":"main","index":0}]]},"If Done?":{"main":[[{"node":"Summarize","type":"main","index":0}],[{"node":"Expand Fire","type":"main","index":0}]]},"Expand Fire":{"main":[[{"node":"If Fire?","type":"main","index":0}]]},"If Fire?":{"main":[[{"node":"Skip Fire","type":"main","index":0}],[{"node":"Fire Lanes","type":"main","index":0}]]},"Fire Lanes":{"main":[[{"node":"Record Inflight","type":"main","index":0}]]},"Skip Fire":{"main":[[{"node":"Record Inflight","type":"main","index":0}]]},"Record Inflight":{"main":[[{"node":"Tick Wait","type":"main","index":0}]]},"Tick Wait":{"main":[[{"node":"Poll Status","type":"main","index":0}]]},"Poll Status":{"main":[[{"node":"Poll Progress","type":"main","index":0}]]},"Reconcile":{"main":[[{"node":"Scheduler","type":"main","index":0}]]},"Summarize":{"main":[[{"node":"Drain Done","type":"main","index":0}]]},"Poll Progress":{"main":[[{"node":"Reconcile","type":"main","index":0}]]},"Reap Stale Dispatches":{"main":[[{"node":"Select IDs","type":"main","index":0}]]},"Solo Check":{"main":[[{"node":"If Solo?","type":"main","index":0}]]},"If Solo?":{"main":[[{"node":"Reap Stale Dispatches","type":"main","index":0}],[{"node":"Gate Closed","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {"node:Every 5 min":{"recurrenceRules":[]},"global":{"lastFullSweepMs":1786873852538},"node:Lane 1 Schedule (nightly one-shot)":{"recurrenceRules":[]},"node:Lane 5 Tick (2m)":{"recurrenceRules":[]},"node:Tick (2m)":{"recurrenceRules":[]},"node:Nightly (one-shot)":{"recurrenceRules":[]}},
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-11T15:40:21.326Z","createdAt":"2026-08-11T15:40:21.326Z","role":"workflow:owner","workflowId":"indoxV2BaseDrain01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2BaseDrain01',
    name: 'indox-v2 Drain (pool: P lanes x B documents)',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: {
        executionOrder: 'v1',
        callerPolicy: 'workflowsFromSameOwner',
        errorWorkflow: 'errorHandler01',
        executionTimeout: 36000,
        availableInMCP: false,
        binaryMode: 'separate',
    },
})
export class IndoxV2DrainPoolPLanesXBDocumentsWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'lane2-webhook-000000000000c0de',
        webhookId: 'lane2-webhook-fixed-0000000c0de1',
        name: 'Drain Webhook',
        /*__n8n__*/ notes: "THE drain API. POST /webhook/indox-drain with {mode, ids?, status?, parallel?, batch?, dry?}. mode = all | ids | status | changed. Deliberately NOT behind the indoxDrainOn master gate -- a direct call here is operator intent (that is also what makes dry runs possible without opening the gate). Answers IMMEDIATELY with the drain execution id: a Wait node further down puts this execution into 'waiting' and releases the HTTP connection, so a synchronous summary is impossible by construction.",
        type: 'n8n-nodes-base.webhook',
        version: 2.1,
        position: [-1200, 0],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
    })
    DrainWebhook = {
        httpMethod: 'POST',
        path: 'indox-drain',
        authentication: 'basicAuth',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'drain-respond-handle-00000c0de',
        name: 'Respond Handle',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [-980, -160],
        onError: 'continueRegularOutput',
    })
    RespondHandle = {
        respondWith: 'json',
        responseBody: '={{ { "accepted": true, "drain_execution": $execution.id } }}',
        options: {},
    };

    @node({
        id: 'b1000000-0000-4000-8000-000000000001',
        name: 'Tick (2m)',
        /*__n8n__*/ notes: "[scheduler cutover 2026-08-28] DISABLED, not deleted. indox01 is now the app's only clock and calls this drain once per ENABLED instance, handing each run its __instance. This trigger fired once globally and instance-blind, so leaving it live would both double-drive the drain and re-introduce the un-scoped pass the whole migration exists to remove. Everything below about WHAT a fire does still holds -- Normalize Request still decides incremental vs full from the same settings -- only the clock moved. Re-enabling this node is the revert path: one flag, no restore from backup. THE only schedule trigger, cadence-driven by SETTINGS (2026-08-24, owner order). Fires every 2 minutes; Normalize Request decides what each fire IS: normally the incremental pass (mode=changed) paced by indox.statemachine.drain.tick_minutes, and when the db-epoch-minute falls in the first window of an indox.statemachine.drain.full_minutes block (default 120 = every 2h) the fire runs the FULL-TABLE pass (mode=all) instead, with the same parallel/batch settings as any other drain. Both keys are editable in the console settings UI. The old Nightly trigger (02:00, parallel=1) is gone. n8n still skips a fire while the previous one is running, so a long full pass pauses the ticks -- intended.",
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [-1200, 200],
    })
    Tick2m = {
        rule: {
            interval: [
                {
                    field: 'minutes',
                    minutesInterval: 2,
                },
            ],
        },
    };

    @node({
        id: 'drain-when-called-0000c0de',
        name: 'When Called',
        /*__n8n__*/ notes: "[app scheduler 2026-08-28] Makes this drain callable as a SUB-WORKFLOW, which it was not: its only entries were the schedule trigger and the operator webhook, so indox01's 'Call Drain' failed with 'Missing node to start execution' — silently, because that node swallowed the error and the scheduler then recorded work it had never dispatched. Additive: the existing Tick and Drain Webhook are untouched and behave exactly as before. The caller passes __instance, which rides through to the driver and on to indoxApi01; a call with no __instance behaves like today's single-instance run.",
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-1200, 380],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'drain-read-settings-0000c0de',
        name: 'Read Settings',
        /*__n8n__*/ notes: "ONE query for the master gate and all three pool settings. Every value COALESCEs to a safe default so a missing settings row can never dark-stop a lane. [multi-instance 2026-08-28] The query is an EXPRESSION because the schema is per-instance and an identifier cannot be a bound parameter. It reads __instance off the passthrough item -- this node runs BEFORE 'Normalize Request', so the caller's item is the only place the instance is known. No __instance (the schedule triggers) resolves to public, which is exactly today's behaviour; the fallback disappears at the cutover, not before. The name is validated against ^[a-z][a-z0-9_]*$ and throws otherwise -- a instance id reaching SQL unvalidated is an injection site. NOTE the two senses of 'instance': the settings COLUMN instance='incoming-documents-main' is the component name and is NOT the instance; the instance is the schema. Both cadences (tick_minutes paces the incremental pass, full_minutes the full-table pass) stay settings-driven and console-editable. db_now MUST stay the DB clock, not the host's: this host runs ~3h ahead of the database, so a host timestamp would either skip every ledger row or match all of them.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-980, 200],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    ReadSettings = {
        operation: 'executeQuery',
        query: `={{ (function () {
    var t = String($json.__instance || ($json.body && ($json.body.__instance || $json.body.instance)) || '');
    if (!/^[a-z][a-z0-9_]*$/.test(t)) { throw new Error('indoxV2BaseDrain01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); }
    var S = 'indox_' + t;
    var g = function (key, dflt) {
        return "coalesce((SELECT value FROM " + S + ".settings" +
               " WHERE key = '" + key + "'), '" + dflt + "')";
    };
    return "SELECT " +
        g('indoxDrainOn', 'true')                             + " AS drain_on, " +
        g('indoxOn', 'true')                                  + " AS indox_on, " +
        g('indox.statemachine.drain.parallel', '4')           + " AS parallel, " +
        g('indox.statemachine.driver.batch', '2000')          + " AS batch, " +
        g('indox.statemachine.driver.max', '2000')            + " AS lane_max, " +
        g('indox.statemachine.drain.tick_minutes', '2')       + " AS tick_minutes, " +
        g('indox.statemachine.drain.full_minutes', '120')     + " AS full_minutes, " +
        "floor(extract(epoch from now())/60)::bigint AS epoch_min, " +
        "now()::text AS db_now";
})() }}`,
        options: {},
    };

    @node({
        id: 'drain-normalize-00000000c0de',
        name: 'Normalize Request',
        /*__n8n__*/ notes: "Resolves source, mode, parameters and the gate in one place. Webhook calls bypass indoxDrainOn (operator intent); the two schedule triggers do not. Request values override settings so an operator can pin parallel/batch per call without touching the settings table.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-760, 200],
    })
    NormalizeRequest = {
        jsCode: `const cfg = ($input.first() && $input.first().json) || {};
let body = {};
let source = 'tick';
try { if ($('Drain Webhook').isExecuted) { body = $('Drain Webhook').first().json.body || {}; source = 'webhook'; } } catch (e) {}
// [multi-instance 2026-08-28] Which instance this pass is acting for. It arrives from whichever
// entry fired: the app scheduler passes __instance through 'When Called', an operator may put it
// in the webhook body, and the legacy Tick passes nothing at all. Empty means "not told" and is
// carried as '' rather than guessed — everything downstream then behaves exactly as it did before
// multi-instance existed, reading the public compatibility views.
let __instance = '';
try { if ($('When Called').isExecuted) { __instance = String(($('When Called').first().json || {}).__instance || ''); } } catch (e) {}
if (!__instance) { __instance = String(body.__instance || body.instance || ''); }
// [setting-driven cadence 2026-08-24, owner order] ONE schedule trigger; the SETTINGS decide.
// tick_minutes paces the incremental (mode=changed) pass; full_minutes paces the FULL-TABLE
// (mode=all) pass, which runs with the SAME parallel/batch settings as every other drain -- the
// old Nightly trigger and its parallel=1 override are gone. Dueness is stateless: the trigger
// fires every 2 minutes, and a fire whose db-epoch-minute falls in the first window of a
// full_minutes block runs as the full pass instead.
const tickMin = (function (v, d) { const n = Number(v); return (n > 0) ? Math.floor(n) : d; })(cfg.tick_minutes, 2);
const fullMin = (function (v, d) { const n = Number(v); return (n > 0) ? Math.floor(n) : d; })(cfg.full_minutes, 120);
// THE FULL SWEEP IS DECIDED BY THE SCHEDULER, NOT BY A WINDOW HERE (2026-08-28).
//
// It used to promote itself: a fire whose db-epoch-minute fell in the first max(tickMin,2)
// minutes of a full_minutes block ran as the full pass. That was sound while this workflow owned
// its own Tick (2m). The scheduler cutover DISABLED that trigger and handed dispatch to indox01,
// whose spacing is ~4 minutes -- so a 2-minute window was tested against 4-minute fires and got
// straddled. Measured, hacohen, 3 hours: 46 ticks and ONE full sweep; the 08:00 one was skipped
// outright (07:58:15 -> 118, no fire inside the window, 08:02:15 -> 2, and the test is < 2).
// That matters because mode=all is the only pass that revisits a HEALTHY document quiet for
// longer than changedMinutes. (Stalled IN_PROGRESS and ACTION_RESTART rows stopped depending on
// it 2026-08-31: the changed pass rescues those itself -- see the whereSql below.)
//
// indox01 now dispatches 'drain_full' as its own job on state-based dueness
// (app_schedule_state.last_run_at, per instance), which cannot be missed by timing drift. The
// window is gone rather than kept alongside it: two mechanisms deciding the same thing is how
// this drifted out of true in the first place.
// full_minutes now lives as the 'drain_full.every' job cadence and is still the owner's dial.
// A webhook caller can still ask for mode=all explicitly; that path is untouched.
const jobName = (function () {
  try { if ($('When Called').isExecuted) { return String(($('When Called').first().json || {}).job || ''); } } catch (e) {}
  return '';
})();
if (source === 'tick' && jobName === 'drain_full') source = 'full';

const num = function (v, d) { const n = Number(v); return (n > 0) ? Math.floor(n) : d; };
// indoxOn is THE master (owner 2026-09-02): off = no scheduled drain AND no sync, whatever the
// lane switches say; a missing row reads as on. The webhook still bypasses both (operator intent).
const indoxOn = String(cfg.indox_on == null ? 'true' : cfg.indox_on).toLowerCase() === 'true';
const drainOn = indoxOn && String(cfg.drain_on).toLowerCase() === 'true';

let mode = String(body.mode || '').toLowerCase();
if (!mode) mode = (source === 'tick') ? 'changed' : 'all';

let ids = [];
if (body.ids) {
  try {
    const p = typeof body.ids === 'string' ? JSON.parse(body.ids) : body.ids;
    if (Array.isArray(p)) ids = p.map(String).filter(Boolean);
  } catch (e) { ids = []; }
}
if (mode === 'ids' && !ids.length) mode = 'none';

let statuses = [];
if (body.status) {
  const p = Array.isArray(body.status) ? body.status : String(body.status).split(',');
  statuses = p.map(function (x) { return String(x).trim(); }).filter(Boolean);
}
if (mode === 'status' && !statuses.length) mode = 'none';

// [2026-08-24, owner order] The full pass uses the SAME parallel setting as everything else.
const parallel = num(body.parallel, num(cfg.parallel, 4));
const batch    = num(body.batch, num(cfg.batch, 2000));
const laneMax  = num(cfg.lane_max, 2000);
const dry      = (body.dry === true || String(body.dry).toLowerCase() === 'true');

// The webhook is operator intent and is deliberately outside the master gate.
const gateOpen = (source === 'webhook') ? true : drainOn;

const changedMin = num(body.changedMinutes, 15);

// n8n's Query Parameters field takes ONE expression and does NOT split it into $1..$n, so a
// four-parameter query fails with "there is no parameter $4". Instead: exactly ONE parameter
// (a PIPE-joined list -- never comma, n8n splits on commas), plus a WHERE fragment chosen from
// a FIXED set below. The only value interpolated into SQL is changedMin, already floored to an
// integer by num(), so this cannot carry user text into the statement.
const PIPE = String.fromCharCode(124);
let whereSql = 'false';
let listPipe = '';
if (mode === 'all') {
  whereSql = 'true';
} else if (mode === 'ids') {
  whereSql = '"ID" = ANY(string_to_array($1, ' + "'" + PIPE + "'" + '))';
  listPipe = ids.join(PIPE);
} else if (mode === 'status') {
  whereSql = '"STATUS" = ANY(string_to_array($1, ' + "'" + PIPE + "'" + '))';
  listPipe = statuses.join(PIPE);
} else if (mode === 'changed') {
  // [strand rescue 2026-08-31] The changed window alone leaks two classes of live work, both
  // measured on hacohen: 173 IN_PROGRESS rows untouched for 6-72 h (their drivers died with the
  // worker -- OOM, restart, the 2026-08-21 timeout class) and 2 ACTION_RESTART rows sitting
  // THREE DAYS after the user clicked restart. Both are eligible, neither is ever re-selected:
  // their updated_at fell out of the window, and the full pass is 120-minute-cadenced and
  // fragile on a big tenant. The old 30s poll owned this law ("stalled IN_PROGRESS re-picked");
  // it did not survive the drain cutover. Restored HERE because whereSql has exactly one owner.
  //   - IN_PROGRESS bound is 70 minutes, not the old 45: a lane legitimately blocks on its
  //     router POST up to the router's own executionTimeout (3600 s), and the reaper closes the
  //     action-log row at 65 min -- past 70 the dispatch provably has no live owner (same
  //     doctrine as 'Poll Progress'). The per-doc lock makes an early re-pick a skip, not a
  //     double-drive, but 70 keeps the re-pick out of the lock's way entirely.
  //   - ACTION_RESTART is operator intent and is picked on every pass, however old the touch.
  var DQ = String.fromCharCode(34); // literal " -- same no-escape idiom as PIPE above
  whereSql = "(updated_at > now() - interval '" + changedMin + " minutes'"
    + " OR (" + DQ + "STATUS" + DQ + " = 'IN_PROGRESS' AND updated_at < now() - interval '70 minutes')"
    + " OR " + DQ + "STATUS" + DQ + " = 'ACTION_RESTART')";
}

return [{ json: {
  source: source, mode: mode, gateOpen: gateOpen, drainOn: drainOn, dry: dry,
  // Carried so every node downstream — Solo Check first — knows which instance this pass serves.
  __instance: __instance,
  parallel: parallel, batch: batch, laneMax: laneMax,
  changedMin: changedMin, whereSql: whereSql, dbNow: cfg.db_now,
  // NEVER empty. An empty Query Parameters expression makes n8n supply ZERO parameters, and
  // the statement then fails with "there is no parameter $1" -- which only shows up for the
  // modes that do not use a list (all / changed). '-' matches no ID and no STATUS.
  listPipe: (listPipe || '-'),
  idsCount: ids.length, statusCount: statuses.length,
} }];`,
    };

    @node({
        id: 'drain-if-gate-00000000c0de',
        name: 'If Gate Open?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-540, 200],
    })
    IfGateOpen = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'drain-cond-gate',
                    leftValue: "={{ ($json.gateOpen && $json.mode !== 'none') ? 'go' : 'stop' }}",
                    rightValue: 'go',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        looseTypeValidation: true,
        options: {},
    };

    @node({
        id: 'drain-gate-closed-0000c0de',
        name: 'Gate Closed',
        /*__n8n__*/ notes: "indoxDrainOn is false (schedule entries only), or the request named a mode with nothing to select.",
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-320, 380],
    })
    GateClosed = {};

    @node({
        id: 'drain-solo-check-000000000c0de',
        name: 'Solo Check',
        /*__n8n__*/ notes: "[solo 2026-08-24] SCHEDULED FIRES SELF-SKIP WHILE ANY DRAIN IS ALIVE. n8n's schedule-concurrency skip only counts status='running' -- a drain parked in its Tick Wait is 'waiting' (offloaded), so it does NOT block the next tick, and shells stacked one per 2 minutes while a long chain ran: 28 deep on 2026-08-23 (each resume leaning on the wait-tracker, feeding the main-heap OOM), 8 deep again on 2026-08-24 before this node. Counts every OTHER alive BaseDrain execution; 'If Solo?' sends a scheduled fire to Gate Closed when any exist. Webhook fires bypass -- an operator call is deliberate, and the supervisor does its own alive-check before firing.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-680, 200],
        credentials: { postgres: { id: 'tJ195ajNq1kQveRG', name: 'N8N DB [env-managed]' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SoloCheck = {
        operation: 'executeQuery',
        query: `-- [multi-instance 2026-08-28] SAME-INSTANCE ONLY.
--
-- This used to count EVERY other alive BaseDrain. Under the app scheduler that is wrong: with two
-- instances, two concurrent drains is the NORMAL state, and the first one alive would have made the
-- second self-skip forever — one client silently starving another, which is the exact failure the
-- whole multi-instance design exists to prevent.
--
-- The instance is not a column on execution_entity; it rides inside the execution payload. So the
-- match is on execution_data. That is affordable precisely because the candidate set is tiny: it
-- is already filtered to alive drains, of which there are single digits.
--
-- $2 empty = "not told which instance" (the legacy Tick, or an operator webhook without one). Then
-- the old semantics apply and ANY alive drain blocks — the conservative answer for a caller that
-- cannot say who it is acting for.
SELECT count(*)::int AS alive
FROM execution_entity e
LEFT JOIN execution_data d ON d."executionId" = e.id
WHERE e."workflowId" = 'indoxV2BaseDrain01'
  AND e.status IN ('running','waiting','new')
  AND e.id <> $1::int
  AND ( $2 = ''
        OR d.data LIKE '%"__instance":"' || $2 || '"%' )`,
        options: {
            queryReplacement: '={{ $execution.id }},{{ $json.__instance || "" }}',
        },
    };

    @node({
        id: 'drain-if-solo-0000000000c0de',
        name: 'If Solo?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-500, 200],
    })
    IfSolo = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'solo-cond-1',
                    leftValue:
                        "={{ $('Normalize Request').first().json.source === 'webhook' || Number($json.alive || 0) === 0 }}",
                    rightValue: true,
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
        id: 'drain-reap-stale-00000c0de',
        name: 'Reap Stale Dispatches',
        /*__n8n__*/ notes: "[newest-first 2026-08-25, owner order] ORDER BY created_at DESC. This selection had NO ordering at all, so Postgres returned rows in physical order and a document that had just arrived queued behind whatever the heap happened to hold — with ~24,000 rows that is an arbitrary wait. 'Init Pool' slices this list in order (ids.slice(i, i+B)) and the scheduler dispatches batch 0 first, so the SELECT's order IS the dispatch priority. Newest-first starves nothing: the 'all' pass takes the WHOLE selection, so ordering changes WHEN a document is processed, never WHETHER it is.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-320, 60],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    ReapStaleDispatches = {
        operation: 'executeQuery',
        query: `=UPDATE {{ (() => { const i = String($('Normalize Request').first().json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2BaseDrain01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.indox_action_execution_log
SET "ENDED_AT" = now()
WHERE "ENDED_AT" IS NULL
  AND "STARTED_AT" < now() - interval '65 minutes'
RETURNING "ID", "ACTION"`,
        options: {},
    };

    @node({
        id: 'drain-select-ids-0000000c0de',
        name: 'Select IDs',
        /*__n8n__*/ notes: "THE only id source, replacing three nodes (Lane 1+3 Pick All IDs / Lane 6 Pick IDs By Status / Lane 5 Poll Changed). Unfiltered by design for mode=all: decide is the filter and a no_action verdict costs nothing. alwaysOutputData so an empty selection still reaches Init Pool, which then terminates the pool cleanly instead of stalling the chain.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-320, 200],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    SelectIds = {
        operation: 'executeQuery',
        query: `=SELECT "ID" FROM {{ (() => { const i = String($('Normalize Request').first().json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2BaseDrain01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.incoming_documents
WHERE "ID" <> '__bootstrap__'
  AND coalesce($1, '') IS NOT NULL
  AND ({{ $('Normalize Request').first().json.whereSql }})
ORDER BY created_at DESC`,
        options: {
            queryReplacement: "={{ $('Normalize Request').first().json.listPipe }}",
        },
    };

    @node({
        id: 'drain-init-pool-00000000c0de',
        name: 'Init Pool',
        /*__n8n__*/ notes: "Slices the selection into B-document batches. B is the memory lever: one driver execution never receives more than this, so its retained runData is bounded (~55 MB serialized at B=2000 versus 266 MB at 9,790).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-100, 200],
    })
    InitPool = {
        jsCode: `const cfg = $('Normalize Request').first().json;
const ids = $input.all()
  .map(function (i) { return (i.json && i.json.ID) ? String(i.json.ID) : null; })
  .filter(Boolean);

const B = cfg.batch;
const queue = [];
let g = 0;
for (let i = 0; i < ids.length; i += B) {
  g++;
  queue.push({ g: g, ids: ids.slice(i, i + B), n: Math.min(B, ids.length - i) });
}

// A scoped drain (ids / status) must not adopt documents outside its selection when it polls
// the ledger. mode=all needs no scope -- it already covers the table.
const scope = (cfg.mode === 'all' || ids.length > 20000) ? null : ids.slice();

return [{ json: { state: {
  P: cfg.parallel, B: B, laneMax: cfg.laneMax, dry: cfg.dry,
  mode: cfg.mode, source: cfg.source,
  selected: ids.length, queue: queue, gSeq: g, totalBatches: queue.length,
  // Work discovered from the ledger, waiting to be cut into a batch of B.
  pending: [], scope: scope,
  // ENDED_AT high-water mark, seeded from the DB clock (never the host clock).
  watermark: String(cfg.dbNow),
  inflight: [], done: [], samples: [], maxConcurrent: 0,
  globalRunning: 0, polled: false, discovered: 0, lastDiscovered: 0, idleTicks: 0,
  ticks: 0, t0: Date.now(),
} } }];`,
    };

    @node({
        id: 'drain-scheduler-000000000c0de',
        name: 'Scheduler',
        /*__n8n__*/ notes: "The pool. Entered first from Init Pool, then once per tick from Reconcile. Takes at most (P - inflight) batches off the queue, so in-flight lanes can never exceed P, and refills the moment ANY lane finishes rather than at a wave boundary (proven: drainPoolTest01 exec 3456703, uneven durations, overlappingStarts=8). The tick ceiling is a runaway backstop, not a normal exit.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [120, 200],
    })
    Scheduler = {
        jsCode: `const s = $input.first().json.state;

// Cut full batches out of whatever the ledger discovered.
while (s.pending.length >= s.B) {
  s.gSeq++;
  const ids = s.pending.splice(0, s.B);
  s.queue.push({ g: s.gSeq, ids: ids, n: ids.length });
}

// ADMISSION CONTROL IS GLOBAL, not per-drain: slots are measured against every running driver
// execution on the instance, whoever started it -- this drain, a second drain, the 2-minute
// tick, an operator. That is what makes P a real ceiling instead of a per-caller convention.
// s.globalRunning already includes this drain's own lanes.
//
// ...EXCEPT ON THE FIRST PASS, WHICH WAS BLIND. globalRunning is only ever assigned in the
// Reconcile path, from Poll Status, and Poll Status hangs off Tick Wait. The Scheduler is
// entered from Init Pool BEFORE any of that has run, so on entry globalRunning is still its
// initial 0 and this line read "P - 0" -- a full P admitted without seeing anyone else's lanes.
// Harmless with one drain. With indoxDrainOn on, a drain starts every 2 minutes and parks in
// 'waiting' for up to 70 minutes, so the drains ACCUMULATE and every one of them fires a blind
// first batch: 13 alive at 18:42 on 2026-08-22, P=4, and 8 drivers running against a ceiling
// of 4. The global gate was right; it just did not cover tick 1.
// Admit nothing until a poll has actually happened. Costs one Tick Wait (3s) of startup
// latency, once per drain, and makes P a ceiling from the first batch instead of the second.
let slots = s.polled ? Math.max(0, s.P - (s.globalRunning || 0)) : 0;

// Flush a PARTIAL batch only once the ledger has gone quiet for a tick, so trickling work does
// not shatter into tiny lanes and throw away the driver's batch efficiency.
if (slots > 0 && !s.queue.length && s.pending.length && s.lastDiscovered === 0) {
  s.gSeq++;
  const ids = s.pending.splice(0, s.pending.length);
  s.queue.push({ g: s.gSeq, ids: ids, n: ids.length });
}

const fire = [];
while (fire.length < slots && s.queue.length) fire.push(s.queue.shift());
s.ticks = (s.ticks || 0) + 1;

const busy = s.queue.length + s.pending.length + s.inflight.length + fire.length;
if (busy === 0 && s.lastDiscovered === 0) s.idleTicks = (s.idleTicks || 0) + 1;
else s.idleTicks = 0;

// Three consecutive quiet ticks: nothing queued, nothing in flight, and the ledger produced no
// newly-finished action. Anything still running would have written an ENDED_AT by then.
const runaway = s.ticks > 20000;
return [{ json: { state: s, fire: fire, done: (s.idleTicks >= 3 || runaway), runaway: runaway } }];`,
    };

    @node({
        id: 'drain-if-done-00000000c0de',
        name: 'If Done?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [340, 200],
    })
    IfDone = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'drain-cond-done',
                    leftValue: "={{ $json.done ? 'yes' : 'no' }}",
                    rightValue: 'yes',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        looseTypeValidation: true,
        options: {},
    };

    @node({
        id: 'drain-expand-fire-0000000c0de',
        name: 'Expand Fire',
        /*__n8n__*/ notes: "One item per batch to fire. Emits a single SKIP sentinel when the pool is full, because a node handed zero items does not execute and the loop would break.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [560, 320],
    })
    ExpandFire = {
        jsCode: `const j = $input.first().json;
const s = j.state;
const fire = j.fire || [];
if (!fire.length) return [{ json: { SKIP: true } }];

// [multi-instance 2026-08-28] THE INSTANCE DIES HERE IF IT IS NOT PUT ON THE PAYLOAD.
// 'Fire Lanes' calls the driver over HTTP, so nothing is inherited: only the fields this node
// emits reach it. The drain knows its instance (indox01 hands one per enabled instance, and
// 'Normalize Request' captures it) and the driver resolves its schema from $json.__instance —
// but between them sat this object, which listed six fields and not that one. Measured before
// the fix: 32 webhook-entered driver runs in three hours, ZERO carrying an instance. Every one
// of them fell back to 'public', which is correct only while the compatibility views exist and
// becomes a hard failure the moment they are dropped.
// Read from the named node rather than from j: this node's input is the Scheduler's state, which
// never carried the instance.
const inst = (function () {
  try { return String(($('Normalize Request').first().json || {}).__instance || ''); }
  catch (e) { return ''; }
})();

return fire.map(function (b) {
  return { json: {
    SKIP: false, G: b.g, N: b.n,
    IDS_JSON: JSON.stringify(b.ids),
    MAX: s.laneMax, DRY: s.dry,
    __instance: inst,
  } };
});`,
    };

    @node({
        id: 'drain-if-fire-000000000c0de',
        name: 'If Fire?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [780, 320],
    })
    IfFire = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'drain-cond-fire',
                    leftValue: "={{ $json.SKIP ? 'skip' : 'fire' }}",
                    rightValue: 'skip',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        looseTypeValidation: true,
        options: {},
    };

    @node({
        id: 'drain-skip-fire-00000000c0de',
        name: 'Skip Fire',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [1000, 200],
    })
    SkipFire = {};

    @node({
        id: 'drain-fire-lanes-0000000c0de',
        name: 'Fire Lanes',
        /*__n8n__*/ notes: "Fires each batch at the driver webhook. These POSTs return in MILLISECONDS because the driver ACKs before it works ('Respond to Webhook' hangs directly off its 'Webhook'), so firing does not need to be concurrent -- the concurrency is the driver executions themselves. Each response carries that driver's $execution.id, which is what 'Poll Status' then watches. onError continues so one refused lane cannot kill the drain.",
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [1000, 440],
        credentials: { httpBasicAuth: { id: 'azPhHBvOWaf9IsEA', name: 'Incoming Documents [env-managed]' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    FireLanes = {
        method: 'POST',
        url: 'http://n8n-webhook:5678/webhook/incoming-documents-017',
        authentication: 'genericCredentialType',
        genericAuthType: 'httpBasicAuth',
        sendBody: true,
        bodyParameters: {
            parameters: [
                {
                    name: 'IDS',
                    value: '={{ $json.IDS_JSON }}',
                },
                {
                    name: '__instance',
                    value: '={{ $("Normalize Request").first().json.__instance || "" }}',
                },
                {
                    name: 'MAX',
                    value: '={{ $json.MAX }}',
                },
                {
                    name: 'DRY',
                    value: '={{ $json.DRY }}',
                },
                {
                    name: 'TRIGGER_TYPE',
                    value: '={{ "drain_" + $(\'Normalize Request\').first().json.mode + "_g" + $json.G }}',
                },
                {
                    name: 'DRAINER_TYPE',
                    value: '={{ "drainer_" + $(\'Normalize Request\').first().json.mode }}',
                },
                {
                    name: 'DRAINER_ID',
                    value: '={{ "drain:" + $execution.id }}',
                },
                {
                    name: 'DRAINER_CHAIN',
                    value: '={{ "drain:" + $execution.id }}',
                },
                {
                    name: 'ORIGIN_EXECUTION',
                    value: '={{ $execution.id }}',
                },
                {
                    name: 'PARENT_EXECUTION',
                    value: '={{ $execution.id }}',
                },
            ],
        },
        options: {
            timeout: 30000,
        },
    };

    @node({
        id: 'drain-record-inflight-000c0de',
        name: 'Record Inflight',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1220, 320],
    })
    RecordInflight = {
        jsCode: `const sched = $('Scheduler').first().json;
const s = sched.state;
const fired = sched.fire || [];
let k = 0;
for (const it of $input.all()) {
  const j = it.json || {};
  if (j.SKIP) continue;
  const exec = (j.execution !== undefined && j.execution !== null) ? String(j.execution) : null;
  const b = fired[k] || {};
  if (exec) s.inflight.push({ exec: exec, g: b.g || 0, n: b.n || 0, firedTick: s.ticks });
  else if (b.g) s.done.push({ exec: null, g: b.g, n: b.n || 0, status: 'fire_failed', firedTick: s.ticks, doneTick: s.ticks });
  k++;
}
if (s.inflight.length > s.maxConcurrent) s.maxConcurrent = s.inflight.length;
return [{ json: { state: s } }];`,
    };

    @node({
        id: 'drain-tick-wait-000000000c0de',
        webhookId: 'de2b9c57-6e55-4f83-9f44-b3669be88c3d',
        name: 'Tick Wait',
        /*__n8n__*/ notes: "[2026-08-23] WAS A WAIT NODE, AND THE POOL LEAKED A LANE EVERY TICK BECAUSE OF IT. A Wait parks the execution in 'waiting' and hands the resume to n8n. In queue mode that resume is not reliable here: measured on this box, resumes worked for about three minutes after an n8n main restart and then stopped entirely -- execution 1951 sat at status=waiting with waitTill 43 minutes in the past and its execution_data intact, while workers were healthy and consuming other jobs. Over three hours: 37 crashed, 22 waiting, 4 success. Every stranded execution holds a lane, so once the pool is exhausted nothing drains at all and indoxV2Driver01 had run twice, ever. Nothing errors while this happens, which is why it read as an extraction problem for three sessions. Full evidence: issues/drain-waits-never-resume.md. pg_sleep keeps the tick IN-PROCESS, so there is no resume to lose. It costs one DB connection for 3s per tick instead of a worker slot, which is the same trade the pipeline suite already makes with its own postgres-as-sleep nodes. The offload this replaces was deliberate and is a real loss -- a parked execution held no memory between ticks -- but a pool that stops draining is worse than one that costs a connection.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1440, 320],
        credentials: { postgres: { id: 'tJ195ajNq1kQveRG', name: 'N8N DB [env-managed]' } },
    })
    TickWait = {
        operation: 'executeQuery',
        query: 'select pg_sleep(3)',
        options: {},
    };

    @node({
        id: 'drain-poll-status-000000c0de',
        name: 'Poll Status',
        /*__n8n__*/ notes: "The completion oracle is the n8n DB itself -- the same source the retired 'Lane 4 Check Capacity' used. Ids are PIPE-joined because n8n splits Query Parameters on commas. alwaysOutputData so an empty in-flight set still yields an item and the loop survives. THE AGE BOUND MUST EXCEED THE ROUTER'S OWN executionTimeout (3600 s). It was 15 minutes, copied from 'Lane 4 Check Capacity' where that value correctly means 'stale phantom row' -- but here a lane legitimately blocks on its router POST for far longer, and any lane older than the bound silently vanishes from the admission count, so the pool grants its slot again. Measured live 2026-08-21 during the first wet full-table drain: lanes 3459799/3459800 started 16:47:14, concurrency reached 5 at ~14 min and 6-7 once they passed 17 min, against P=4. 70 minutes sits just above the 65-minute reaper horizon, so a row is either still a live owner or already reaped.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1660, 320],
        credentials: { postgres: { id: 'tJ195ajNq1kQveRG', name: 'N8N DB [env-managed]' } },
        alwaysOutputData: true,
    })
    PollStatus = {
        operation: 'executeQuery',
        query: `SELECT id::text AS id, status FROM execution_entity WHERE id = ANY(string_to_array($1, '|')::bigint[])
UNION ALL
SELECT '__global__', count(*)::text FROM execution_entity
WHERE "workflowId" = 'indoxV2Driver01'
  AND status IN ('running', 'new')
  AND coalesce("startedAt", "createdAt") > now() - interval '70 minutes'`,
        options: {
            queryReplacement:
                "={{ ($('Record Inflight').first().json.state.inflight || []).map(x => x.exec).join('|') || '0' }}",
        },
    };

    @node({
        id: 'drain-poll-progress-0000c0de',
        name: 'Poll Progress',
        /*__n8n__*/ notes: "THE PROGRESS SIGNAL. A document is ready for its next action when its previous action ENDED -- not when it started. Keying on STARTED_AT would re-decide a document while its action is still running, and the redis doc_action lock would simply skip it (lock-skip is by design), silently losing the hop. A no_action verdict writes NO ledger row at all, which is exactly why an empty result means 'nothing left to do' rather than 'nothing happened'. Watermark comparison uses the DB clock on both sides; this host runs ~3 h ahead of the database. The one-hour floor keeps the scan bounded -- there is no index on ENDED_AT alone (idx_indox_ael_id_started is (ID, STARTED_AT)), so that is a follow-up if the drain ever runs long enough for it to matter.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [1880, 320],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    PollProgress = {
        operation: 'executeQuery',
        query: `=SELECT DISTINCT ON ("ID") "ID", "ENDED_AT"::text AS ended
FROM {{ (() => { const i = String($('Normalize Request').first().json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2BaseDrain01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.indox_action_execution_log
WHERE "ENDED_AT" > ($1)::timestamptz
  AND "ENDED_AT" > now() - interval '1 hour'
ORDER BY "ID", "ENDED_AT" DESC`,
        options: {
            queryReplacement: "={{ $('Record Inflight').first().json.state.watermark }}",
        },
    };

    @node({
        id: 'drain-reconcile-0000000000c0de',
        name: 'Reconcile',
        /*__n8n__*/ notes: "Moves lanes that reached a terminal status out of inflight, freeing a slot for the next Scheduler pass. A lane whose execution row has vanished entirely (pruned) is also released, otherwise the pool would wedge on a ghost.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2100, 320],
    })
    Reconcile = {
        jsCode: `const s = $('Record Inflight').first().json.state;

// --- lane completion + GLOBAL running count (Poll Status) ---
let globalRunning = 0;
const st = new Map();
for (const it of $('Poll Status').all()) {
  const r = it.json || {};
  if (r.id === '__global__') globalRunning = Number(r.status) || 0;
  else if (r.id) st.set(String(r.id), String(r.status));
}
s.globalRunning = globalRunning;
// Tick 1 of a drain has no poll behind it, so the Scheduler must not admit on the initial
// zero. This is the flag that says the number above is real.
s.polled = true;

const TERMINAL = ['success', 'error', 'crashed', 'canceled'];
const still = [];
for (const f of s.inflight) {
  const v = st.get(f.exec);
  if (v && TERMINAL.indexOf(v) >= 0) {
    s.done.push({ exec: f.exec, g: f.g, n: f.n, status: v, firedTick: f.firedTick, doneTick: s.ticks });
  } else if (!v && st.size > 0) {
    s.done.push({ exec: f.exec, g: f.g, n: f.n, status: 'vanished', firedTick: f.firedTick, doneTick: s.ticks });
  } else {
    still.push(f);
  }
}
s.inflight = still;

// --- newly finished actions (Poll Progress) become the next round of work ---
const scope = s.scope ? new Set(s.scope) : null;
const busyIds = new Set();
s.queue.forEach(function (b) { b.ids.forEach(function (i) { busyIds.add(i); }); });
s.pending.forEach(function (i) { busyIds.add(i); });

let found = 0;
let hw = s.watermark;
for (const it of $input.all()) {
  const r = it.json || {};
  if (!r.ID) continue;
  if (r.ended && String(r.ended) > String(hw)) hw = String(r.ended);
  const id = String(r.ID);
  if (scope && !scope.has(id)) continue;   // a scoped drain never adopts outside documents
  if (busyIds.has(id)) continue;           // already queued or pending
  s.pending.push(id);
  busyIds.add(id);
  found++;
}
s.watermark = hw;
s.lastDiscovered = found;
s.discovered = (s.discovered || 0) + found;

s.samples.push({ tick: s.ticks, inflight: s.inflight.length, done: s.done.length,
                 queued: s.queue.length, pending: s.pending.length,
                 global: globalRunning, found: found });
return [{ json: { state: s } }];`,
    };

    @node({
        id: 'drain-summarize-00000000c0de',
        name: 'Summarize',
        /*__n8n__*/ notes: "Read this off the drain execution -- the webhook could not carry it, because Wait released the HTTP connection long before the drain finished.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [560, 40],
    })
    Summarize = {
        jsCode: `const s = $input.first().json.state;
const rec = s.done.slice().sort(function (a, b) { return a.g - b.g; });
const bad = rec.filter(function (d) { return d.status !== 'success'; });
const fireTicks = [];
rec.forEach(function (r) { if (fireTicks.indexOf(r.firedTick) < 0) fireTicks.push(r.firedTick); });
return [{ json: {
  RESULT: (bad.length === 0 && s.queue.length === 0 && s.inflight.length === 0) ? 'OK' : 'ATTENTION',
  mode: s.mode, source: s.source, dry: s.dry,
  parallel_P: s.P, batch_B: s.B,
  documentsSelected: s.selected,
  batchesTotal: s.totalBatches, batchesCompleted: rec.length,
  documentsDispatched: rec.reduce(function (a, b) { return a + (b.n || 0); }, 0),
  maxConcurrentObserved: s.maxConcurrent, neverExceededP: s.maxConcurrent <= s.P,
  distinctFireTicks: fireTicks.length,
  documentsDiscovered: s.discovered,
  globalRunningAtEnd: s.globalRunning,
  ticks: s.ticks, elapsedSec: Math.round((Date.now() - s.t0) / 1000),
  nonSuccess: bad.length,
  nonSuccessDetail: bad.slice(0, 20).map(function (d) { return 'g' + d.g + ':' + d.status + ':' + d.exec; }).join(','),
  concurrencyTrace: s.samples.map(function (x) { return x.inflight; }).join(','),
  queuedTrace: s.samples.map(function (x) { return x.queued; }).join(','),
  pendingTrace: s.samples.map(function (x) { return x.pending; }).join(','),
  globalTrace: s.samples.map(function (x) { return x.global; }).join(','),
  discoveryTrace: s.samples.map(function (x) { return x.found; }).join(','),
  laneExecutions: rec.map(function (d) { return d.exec; }).join(','),
} }];`,
    };

    @node({
        id: 'drain-done-000000000000c0de',
        name: 'Drain Done',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [780, 40],
    })
    DrainDone = {};

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.DrainWebhook.out(0).to(this.RespondHandle.in(0));
        this.DrainWebhook.out(0).to(this.ReadSettings.in(0));
        this.Tick2m.out(0).to(this.ReadSettings.in(0));
        this.WhenCalled.out(0).to(this.ReadSettings.in(0));
        this.ReadSettings.out(0).to(this.NormalizeRequest.in(0));
        this.NormalizeRequest.out(0).to(this.IfGateOpen.in(0));
        this.IfGateOpen.out(0).to(this.SoloCheck.in(0));
        this.IfGateOpen.out(1).to(this.GateClosed.in(0));
        this.SelectIds.out(0).to(this.InitPool.in(0));
        this.InitPool.out(0).to(this.Scheduler.in(0));
        this.Scheduler.out(0).to(this.IfDone.in(0));
        this.IfDone.out(0).to(this.Summarize.in(0));
        this.IfDone.out(1).to(this.ExpandFire.in(0));
        this.ExpandFire.out(0).to(this.IfFire.in(0));
        this.IfFire.out(0).to(this.SkipFire.in(0));
        this.IfFire.out(1).to(this.FireLanes.in(0));
        this.FireLanes.out(0).to(this.RecordInflight.in(0));
        this.SkipFire.out(0).to(this.RecordInflight.in(0));
        this.RecordInflight.out(0).to(this.TickWait.in(0));
        this.TickWait.out(0).to(this.PollStatus.in(0));
        this.PollStatus.out(0).to(this.PollProgress.in(0));
        this.Reconcile.out(0).to(this.Scheduler.in(0));
        this.Summarize.out(0).to(this.DrainDone.in(0));
        this.PollProgress.out(0).to(this.Reconcile.in(0));
        this.ReapStaleDispatches.out(0).to(this.SelectIds.in(0));
        this.SoloCheck.out(0).to(this.IfSolo.in(0));
        this.IfSolo.out(0).to(this.ReapStaleDispatches.in(0));
        this.IfSolo.out(1).to(this.GateClosed.in(0));
    }
}
