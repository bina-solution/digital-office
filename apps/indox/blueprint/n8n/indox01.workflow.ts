import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : INDOX app scheduler (all automation, all instances)
// Nodes   : 9  |  Connections: 8
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Tick                               scheduleTrigger
// LoadPlan                           postgres                   [creds] [alwaysOutput]
// DecideDue                          code
// RouteJob                           switch
// CallDrain                          executeWorkflow            [onError→regular]
// CallSync                           executeWorkflow            [onError→regular]
// CallReaper                         executeWorkflow            [onError→regular]
// CallHealth                         executeWorkflow            [onError→regular]
// MarkDispatched                     postgres                   [onError→regular] [creds] [alwaysOutput]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Tick
//    → LoadPlan
//      → DecideDue
//        → MarkDispatched
//          → RouteJob
//            → CallDrain
//           .out(1) → CallSync
//           .out(2) → CallReaper
//           .out(3) → CallHealth
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Tick":{"main":[[{"node":"Load Plan","type":"main","index":0}]]},"Load Plan":{"main":[[{"node":"Decide Due","type":"main","index":0}]]},"Decide Due":{"main":[[{"node":"Mark Dispatched","type":"main","index":0}]]},"Mark Dispatched":{"main":[[{"node":"Route Job","type":"main","index":0}]]},"Route Job":{"main":[[{"node":"Call Drain","type":"main","index":0}],[{"node":"Call Sync","type":"main","index":0}],[{"node":"Call Reaper","type":"main","index":0}],[{"node":"Call Health","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {"node:Tick":{"recurrenceRules":[]}},
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-27T22:17:55.176Z","createdAt":"2026-08-27T22:17:55.176Z","role":"workflow:owner","workflowId":"indox01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indox01',
    name: 'INDOX app scheduler (all automation, all instances)',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    // executionTimeout IS THE WALL OF EVERY JOB THIS TICK DISPATCHES (measured live 2026-09-02): n8n
    // hands the parent's deadline down to a sub-execution even when it is not waited for, so with
    // 300 here a sync pass whose mailbox searches ran long (50–125 s each on the client's account)
    // was cancelled at 5 min mid-search and Main crashed on the cancelled call — Main's own 900 never
    // applied. The tick itself ends in seconds; each job carries its own limit (Main 900, Run 300).
    settings: { binaryMode: 'separate', errorWorkflow: 'errorHandler01', executionOrder: 'v1', executionTimeout: 1800 },
})
export class IndoxAppSchedulerAllAutomationAllInstancesWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'ix01-tick',
        name: 'Tick',
        /*__n8n__*/ notes: "The app's ONLY clock, fixed at 2 minutes. Deliberately NOT settings-driven: a schedule trigger's interval is registered in main's memory when the workflow activates, so a value read from settings would not take effect until reactivation and would silently disagree with what the setting says. Cadence per job IS settings-driven — that decision happens in 'Decide Due', where a change applies on the very next tick. 2m is the floor: no job can run more often than this.",
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [0, 112],
    })
    Tick = {
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
        id: 'ix01-plan',
        name: 'Load Plan',
        /*__n8n__*/ notes: "The decision inputs that live in Supabase: the master switch, every indox.auto.* cadence, the enabled instances, and when each (instance, job) last ran. One round trip so they cannot disagree with each other. Nothing about executions is read here or anywhere in this workflow: this scheduler knows about TIME, not about runs.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [224, 112],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    LoadPlan = {
        operation: 'executeQuery',
        query: `WITH auto AS (
  -- Every scheduler setting in one prefix read, so adding a job's cadence needs no SQL change.
  -- [global settings 2026-08-28] public.app_settings, NOT public.settings. This scheduler is the
  -- single entry point for EVERY instance, so its switches are global by definition. public.settings
  -- is a compatibility view onto ONE instance (indox_hacohen), so reading indox.auto.* from there
  -- meant hacohen's rows silently gated the whole estate — and it breaks outright when that view is
  -- dropped at the cutover. app_settings sits beside the other two global tables this same query
  -- already reads, public.indox_instances and public.app_schedule_state; none is instance data.
  SELECT key, value FROM public.app_settings WHERE app = 'indox' AND key LIKE 'indox.auto.%'
), inst AS (
  -- [test isolation 2026-08-31] purpose='test' tenants are the SUITES' property: they mint their
  -- own docs, drive their own decide/execute loops, and assert on the exact rows they wrote.
  -- With the live scheduler also enumerating them, every indox.auto.* job raced the running
  -- suite on indox_test (measured: driver dispatches + BaseDocEx01 + reap on dbf_* docs within
  -- seconds of suite exec 3736039, while the suite's own LC loop was still executing). The
  -- scheduler is the one owner of "which tenants run automatically", so the exclusion lives here.
  SELECT id FROM public.indox_instances WHERE enabled AND coalesce(purpose,'') <> 'test'
), state AS (
  SELECT instance, job, last_run_at FROM public.app_schedule_state WHERE app='indox'
)
SELECT jsonb_build_object(
  'now',       now(),
  'auto',      COALESCE((SELECT jsonb_object_agg(key, value) FROM auto), '{}'::jsonb),
  'instances', COALESCE((SELECT jsonb_agg(id) FROM inst), '[]'::jsonb),
  'state',     COALESCE((SELECT jsonb_agg(jsonb_build_object(
                   'instance',instance,'job',job,'last_run_at',last_run_at)) FROM state), '[]'::jsonb)
)::text AS plan`,
        options: {},
    };

    @node({
        id: 'ix01-decide',
        name: 'Decide Due',
        /*__n8n__*/ notes: "The scheduler proper. For each job x enabled instance: is automation on, is this job on, has its cadence elapsed since last_run_at? That is all it asks. It deliberately does NOT look at whether the target is already running — overlap is the WORKER's business and every one of them already has its own guard (the drain's Solo Check, the sync's locks). A scheduler that also tracked executions would duplicate that logic in a second place and get it subtly different. Emits one item per due pair. A pair with no state row is DUE — that is how a newly added instance or job starts without anyone seeding it. Emits nothing when nothing is due, which ends the run quietly.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [448, 112],
    })
    DecideDue = {
        jsCode: `// Prefer the named node, fall back to this node's input. The fallback is what makes this node
// runnable on its own with 'bbox n8n execute', so the scheduling logic can be tested without
// calling anything. In the real chain the named nodes always exist. If a rewire ever removed one,
// plan stays {} and the scheduler decides NOTHING rather than guessing.
function pick(nodeName, field) {
  try { const v = ($(nodeName).first().json || {})[field]; if (v) return v; } catch (e) {}
  try { const v = ($input.first().json || {})[field]; if (v) return v; } catch (e) {}
  return '{}';
}
let plan = {};
try { plan = JSON.parse(pick('Load Plan', 'plan')); } catch (e) {}

const auto = plan.auto || {};
const on = function (k, dflt) {
  const v = auto['indox.auto.' + k];
  if (v === undefined || v === null || v === '') return dflt;
  return String(v).toLowerCase() === 'true';
};
const every = function (k, dflt) {
  const v = Number(auto['indox.auto.' + k]);
  return v > 0 ? v : dflt;
};

// THE JOBS. Literal here, matching the four Call nodes one-for-one — the workflow IS the
// catalogue. A job list in settings would let someone add a job that no node can run.
const JOBS = [
  { job: 'drain',         workflow: 'indoxV2BaseDrain01', every: every('drain.every', 2) },
  // THE FULL-TABLE SWEEP IS A JOB NOW (2026-08-28), not a modulo window inside the drain.
  //
  // The drain used to promote itself to a full pass when its db-epoch-minute landed in the first
  // 2 minutes of a 120-minute block. That was sound while the drain owned a 2-minute schedule
  // trigger; the scheduler cutover disabled that trigger and made dispatch ~4 minutes apart, so
  // the 2-minute window got straddled and roughly every other sweep was silently skipped --
  // measured: 46 ticks, ONE sweep, in 3 hours, with the 08:00 sweep missed outright.
  // Dueness here is STATE-BASED (app_schedule_state.last_run_at, per instance) and so cannot be
  // missed by timing drift, which is the whole reason every other job already lives in this list.
  { job: 'drain_full',    workflow: 'indoxV2BaseDrain01', every: every('drain_full.every', 120) },
  { job: 'sync',          workflow: 'syncV3Main0001',     every: every('sync.every', 15) },
  // syncLedgerApi01 is an OP router, not a single-purpose worker: without an op its Op Switch
  // matches nothing and the call is a silent no-op. That is exactly what happened between the
  // scheduler cutover and 2026-08-28 -- claims sat unreaped because this dispatch arrived opless.
  // The op below is emitted here for intent, but Mark Dispatched's RETURNING list drops it (see
  // the note on that node), so the JOB NAME is what actually reaches the worker. syncLedgerApi01's
  // Op Router maps ledger_reaper -> REAP. Renaming this job without changing that map breaks it.
  { job: 'ledger_reaper', workflow: 'syncLedgerApi01',    every: every('ledger_reaper.every', 5), op: 'REAP' },
  { job: 'health',        workflow: 'indoxHealth00001',   every: every('health.every', 10) },
];

const now = plan.now ? new Date(plan.now) : new Date();
const instances = Array.isArray(plan.instances) ? plan.instances : [];

// MASTER SWITCH, checked here rather than in SQL so the tick still runs and still says why it did
// nothing. A scheduler that goes silent when disabled cannot be told apart from one that died.
if (!on('on', false))  { console.log('[indox01] automation off'); return []; }
if (!instances.length) { console.log('[indox01] no enabled instances'); return []; }

const last = {};
for (const s of (plan.state || [])) {
  last[String(s.instance) + '|' + String(s.job)] = s.last_run_at ? new Date(s.last_run_at) : null;
}

const out = [], held = [];
for (const inst of instances) {
  for (const j of JOBS) {
    const key = String(inst) + '|' + String(j.job);
    const tag = j.job + '@' + inst;
    if (!on(j.job + '.on', true)) { held.push(tag + ':off'); continue; }

    const prev = last[key];
    const dueAt = prev ? new Date(prev.getTime() + j.every * 60000) : new Date(0);
    if (dueAt > now) { held.push(tag + ':not-due'); continue; }

    out.push({ json: {
      app: 'indox', job: j.job, workflow: j.workflow, instance: inst,
      // The instance IDENTITY the worker receives. Never the schema — indoxApi01 is the one place
      // that maps identity to storage.
      __instance: inst,
      // op is set only for workers that route on it; omitted entirely for the rest so their
      // payload shape is unchanged.
      ...(j.op ? { op: j.op } : {}),
      every: j.every, last_run_at: prev ? prev.toISOString() : null,
    } });
  }
}

console.log('[indox01] due=' + out.length + ' held=' + held.length +
            (held.length ? ' (' + held.join(', ') + ')' : ''));
return out;`,
    };

    @node({
        id: 'ix01-route',
        name: 'Route Job',
        /*__n8n__*/ notes: "Sends each due item to its own Call node. A Switch rather than one dynamic Execute Workflow so every automation INDOX runs is visible on the canvas and in n8n's dependency view. A job with no matching output is dropped by design — adding a job to Decide Due without adding its Call node should do nothing rather than silently reuse another target.",
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [896, 80],
    })
    RouteJob = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: 'r-drain',
                                operator: {
                                    type: 'string',
                                    operation: 'startsWith',
                                },
                                leftValue: '={{ $json.job }}',
                                rightValue: 'drain',
                            },
                        ],
                    },
                    renameOutput: true,
                    outputKey: 'drain',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: 'r-sync',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                                leftValue: '={{ $json.job }}',
                                rightValue: 'sync',
                            },
                        ],
                    },
                    renameOutput: true,
                    outputKey: 'sync',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: 'r-reap',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                                leftValue: '={{ $json.job }}',
                                rightValue: 'ledger_reaper',
                            },
                        ],
                    },
                    renameOutput: true,
                    outputKey: 'ledger_reaper',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        combinator: 'and',
                        conditions: [
                            {
                                id: 'r-health',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                                leftValue: '={{ $json.job }}',
                                rightValue: 'health',
                            },
                        ],
                    },
                    renameOutput: true,
                    outputKey: 'health',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'ix01-call-drain',
        name: 'Call Drain',
        /*__n8n__*/ notes: "mode:'each' is LOAD-BEARING. n8n's Execute Workflow defaults to mode:'once', which sends EVERY input item to ONE sub-execution — measured live: Decide Due emitted 2 items, Route Job passed 2, and Call Drain produced a SINGLE drain run holding both instances. That is precisely the interleaved-instance shape this scheduler exists to avoid, and it degrades silently because the run still succeeds. With 'each' the node runs the target once per item, so two instances get two independent executions. --- waitForSubWorkflow FALSE on every Call node: the drain and sync run for minutes and this scheduler must return long before its next 2-minute tick. Concurrency is bounded by the target's own admission control — the driver's global P ceiling, which counts every running driver and so cannot be exceeded no matter how many drains are alive.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1120, -176],
        onError: 'continueRegularOutput',
    })
    CallDrain = {
        workflowId: {
            __rl: true,
            mode: 'id',
            value: 'indoxV2BaseDrain01',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
            value: {},
            matchingColumns: [],
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: false,
        },
    };

    @node({
        id: 'ix01-call-sync',
        name: 'Call Sync',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1120, 16],
        onError: 'continueRegularOutput',
    })
    CallSync = {
        workflowId: {
            __rl: true,
            mode: 'id',
            value: 'syncV3Main0001',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: false,
        },
    };

    @node({
        id: 'ix01-call-reaper',
        name: 'Call Reaper',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1120, 208],
        onError: 'continueRegularOutput',
    })
    CallReaper = {
        workflowId: {
            __rl: true,
            mode: 'id',
            value: 'syncLedgerApi01',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: false,
        },
    };

    @node({
        id: 'ix01-call-health',
        name: 'Call Health',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1120, 400],
        onError: 'continueRegularOutput',
    })
    CallHealth = {
        workflowId: {
            __rl: true,
            mode: 'id',
            value: 'indoxHealth00001',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: false,
        },
    };

    @node({
        id: 'ix01-mark',
        name: 'Mark Dispatched',
        /*__n8n__*/ notes: "Stamps last_run_at BEFORE the call, deliberately. Two reasons. (1) The cadence measures how often work is STARTED, so a long run must not become due again the instant it ends. (2) It was originally placed AFTER the four Call nodes and read $(\"Decide Due\").item — which failed live with 'ExpressionError: Multiple matches found' the first time two items flowed through, because paired-item lineage cannot be resolved once several branches converge. Reading $json from its own input has no such ambiguity.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [672, 112],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    MarkDispatched = {
        operation: 'executeQuery',
        query: `INSERT INTO public.app_schedule_state (app, instance, job, last_run_at, last_exec, last_note)
VALUES ('indox', $1, $2, now(), $3, 'dispatched')
ON CONFLICT (app, instance, job) DO UPDATE
   SET last_run_at = excluded.last_run_at,
       last_exec   = excluded.last_exec,
       last_note   = excluded.last_note
-- RETURNING carries what the rest of the chain needs, because a postgres node REPLACES the item
-- with its result: Route Job switches on job, and each Call passes __instance to its worker.
-- THIS LIST IS A FIELD FILTER. Anything Decide Due sets that is not named here is silently gone
-- by the time a Call node runs. That is how "op" was lost: Decide Due emitted op='REAP', this
-- node dropped it, and syncLedgerApi01's Op Switch matched nothing -- the reaper ran as a
-- no-op while every execution still reported success.
-- DO NOT add a 4th bind parameter here to carry it. Tried 2026-08-28: adding $4 fed by
-- '{{ $json.op || "" }}' made this node return ZERO items for every job, so Route Job received
-- nothing and the whole scheduler stopped dispatching (drain included) until it was reverted.
-- Fields that only one worker needs are mapped from "job" on the worker side instead.
RETURNING job, instance, instance AS "__instance", last_run_at`,
        options: {
            queryReplacement: '={{ $json.instance }},{{ $json.job }},{{ $execution.id }}',
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Tick.out(0).to(this.LoadPlan.in(0));
        this.LoadPlan.out(0).to(this.DecideDue.in(0));
        this.DecideDue.out(0).to(this.MarkDispatched.in(0));
        this.MarkDispatched.out(0).to(this.RouteJob.in(0));
        this.RouteJob.out(0).to(this.CallDrain.in(0));
        this.RouteJob.out(1).to(this.CallSync.in(0));
        this.RouteJob.out(2).to(this.CallReaper.in(0));
        this.RouteJob.out(3).to(this.CallHealth.in(0));
    }
}
