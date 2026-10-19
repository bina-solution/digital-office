import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : MAIL app scheduler (all automation, all connections)
// Nodes   : 4  |  Connections: 3
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Tick                               scheduleTrigger
// LoadSettings                       httpRequest
// EnumerateConnections               code
// CallLabelEngine                    executeWorkflow            [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Tick
//    → LoadSettings
//      → EnumerateConnections
//        → CallLabelEngine
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Tick":{"main":[[{"node":"Load Settings","type":"main","index":0}]]},"Load Settings":{"main":[[{"node":"Enumerate Connections","type":"main","index":0}]]},"Enumerate Connections":{"main":[[{"node":"Call Label Engine","type":"main","index":0},{"node":"Stamp Outline","type":"main","index":0}]]},"Call Label Engine":{"main":[[]]}},
    /*__n8n__*/ tags: [{"name":"app:mail"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-28T01:16:53.218Z","createdAt":"2026-08-28T01:16:53.218Z","role":"workflow:owner","workflowId":"mail01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'mail01',
    name: 'MAIL app scheduler (all automation, all connections)',
    active: true,
    isArchived: false,
    tags: ['app:mail', 'mail-app'],
    // executionTimeout is inherited by every engine run this tick dispatches (n8n hands the root
    // deadline down even to un-waited children; measured on the laptop 2026-09-03: all 42 engine
    // errors in three days were cancellations 300–360 s after a tick, the engine's own 840 never
    // applied). ≥ the engine's 840, < the 15-min tick; the tick itself returns in seconds.
    settings: { executionOrder: 'v1', executionTimeout: 900, binaryMode: 'separate' },
})
export class MailAppSchedulerAllAutomationAllConnectionsWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'mail01-tick',
        name: 'Tick',
        /*__n8n__*/ notes: "15 minutes, matching the cadence mailLabelEngine01's own Schedule Trigger used before the fan-out moved here. A tick is cheap: it lists connections and dispatches, then returns - the labelling itself happens in the per-connection sub-executions, which is why waitForSubWorkflow is false on the Call node.",
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [-688, 0],
    })
    Tick = {
        rule: {
            interval: [
                {
                    field: 'minutes',
                    minutesInterval: 15,
                },
            ],
        },
    };

    @node({
        id: 'mail01-settings',
        name: 'Load Settings',
        /*__n8n__*/ notes: "The organizer settings carry the label map. Only PROCESSED is needed here - see 'Enumerate Connections' for why the query excludes that label and nothing else.",
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [-480, 0],
    })
    LoadSettings = {
        url: 'http://mailapi:8970/organizer/settings',
        options: {
            timeout: 15000,
        },
    };

    @node({
        id: 'mail01-enum',
        name: 'Enumerate Connections',
        /*__n8n__*/ notes: "THE REGISTRY IS r.connections. Never r.active - that is a UI pointer, mutable global state, and treating it as a registry is the defect this workflow was built to remove. One item out per connection; 'Call Label Engine' turns each into its own sub-execution.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-288, 0],
    })
    EnumerateConnections = {
        jsCode: `// Every mailbox in the registry gets a run. No selection, no fallback, no pointer.
const r = await this.helpers.httpRequest({ method: 'GET',
  url: 'http://mailapi:8970/connections', json: true, timeout: 15000 });
const list = ((r && r.connections) ? r.connections : []).filter(c => c && c.id);
// Refusing on an empty registry is right; refusing because ONE pointer was unset never was.
if (!list.length) throw new Error('mail01: mailapi returned no usable connections.'
  + ' Refusing to dispatch: a mail op must name its mailbox.');

// [one marker 2026-08-27, owner order] EXCLUDE ONLY THE COMPLETION LABEL.
// The query used to also exclude every TO_SYNC / IN_PROGRESS label. That is wrong twice over.
// Semantically: PROCESSED is what the label engine stamps when it FINISHES, so it is the one
// label that means "already handled". TO_SYNC / IN_PROGRESS describe where a mail sits in the
// SYNC pipeline and say nothing about whether the labeller has run - excluding them hides mail
// the engine has never looked at.
// Operationally: every excluded name must EXIST in the mailbox being searched, because mailapi
// refuses a query naming an unknown label rather than answering total:0. Measured on the 00:45
// tick - 2 of 6 connections died with "unknown label(s) in query" while the 4 mailboxes that
// happened to own those labels succeeded on the byte-identical query (execs 3686671, 3686678
// vs 3686673, 3686675, 3686676). Excluding one label that the engine itself creates removes
// both problems at once.
// [guard 2026-09-03] a rules edit that deletes or renames PROCESSED must not take every mailbox's
// tick down with a TypeError: refuse loudly, with the reason, before any search is built.
const G = ($('Load Settings').first().json || {}).gmail || {};
const L = G.labels || {};
const processed_label = (L.PROCESSED && L.PROCESSED.name) ? String(L.PROCESSED.name) : '';
if (!processed_label) throw new Error('mail01: the organizer settings carry no PROCESSED label'
  + ' — the completion marker is what keeps a handled mail out of the next search; restore the row.');
const query = '-in:scheduled -label:' + processed_label.replace(/ /g, '-');

// [reachable mailboxes only, one run per mailbox — measured 2026-09-02 11:15 on hacohen-prod]
// The registry held 10 connections: the client's Gmail, TWO entries for person2@example.com
// (an env-configured one and an app-password one) and SEVEN local-mailserver test mailboxes whose
// IMAP login fails on that host. Every tick dispatched all ten: the seven dead ones each ended in
// the engine's bootstrap lane creating the PROCESSED label through a mailbox it cannot log into
// (10 error executions per tick), and the one real developer mailbox was labelled twice. The
// probe route answers per connection with {ok, account_hint, reason}; a mailbox that fails it is
// skipped WITH its reason in the outline, and a second connection into the same account is
// skipped too (one IMAP connection per mailbox is the owner's rule at the mailbox level).
const seen = new Map(); const skipped = [];
for (const c of list) {
  let p = null;
  try {
    p = await this.helpers.httpRequest({ method: 'GET', json: true, timeout: 30000,
      url: 'http://mailapi:8970/connections/' + encodeURIComponent(c.id) + '/probe' });
  } catch (e) { p = { ok: false, reason: String((e && e.message) || e).slice(0, 120) }; }
  if (!p || p.ok !== true) { skipped.push(c.id + ': ' + String((p && p.reason) || 'probe failed').slice(0, 90)); continue; }
  const box = String(p.account_hint || c.id).trim().toLowerCase();
  if (seen.has(box)) { skipped.push(c.id + ': same mailbox as ' + seen.get(box)); continue; }
  seen.set(box, c.id);
}
if (!seen.size) throw new Error('mail01: no reachable mailbox — ' + skipped.join(' | ').slice(0, 400));

// processed_label travels so a sub-run can CREATE it in a mailbox that does not have it yet.
// It is passed explicitly rather than parsed back out of the query: the query hyphenates
// spaces, and this label already contains a hyphen, so reversing that would corrupt the name.
// limit 50 (was 10, owner 2026-09-03): a two-day outage left a backlog that 10 per tick drained at
// ~960/day; 50 keeps a tick under the engine's 840 s budget (measured ~10 s per thread) and
// drains five times faster. Still bounded: one add + one remove call per message.
return [...seen.values()].map(id => ({ json: { connection_id: id, query, limit: 50, processed_label, _skipped: skipped } }));
`,
    };

    @node({
        id: 'mail01-call',
        name: 'Call Label Engine',
        /*__n8n__*/ notes: "Every parameter here is load-bearing, and each was copied from indox01's Call nodes rather than chosen. mode:'each' - Execute Workflow DEFAULTS to 'once', which sends EVERY item to ONE sub-execution; that would put all 6 mailboxes in a single run and still report success, which is the silent-collapse this fan-out exists to prevent. waitForSubWorkflow:false - the tick must return long before the next one rather than serialize on the slowest mailbox. onError:continueRegularOutput - an error in one mailbox must not silence the other five; on the 00:45 tick two connections failed and the other four completed because of exactly this. workflowInputs passthrough carries {connection_id, query, limit, processed_label}, which is what mailLabelEngine01's Sub Trigger declares. IF A SOLO/BUSY/LOCK CHECK IS EVER ADDED it MUST key on (workflow, connection), never workflow alone - keyed on the workflow, the first connection's run makes the other five skip, and that looks like a fan-out that mostly works.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-80, 0],
        onError: 'continueRegularOutput',
    })
    CallLabelEngine = {
        workflowId: {
            __rl: true,
            mode: 'id',
            value: 'mailLabelEngine01',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
            value: {},
            matchingColumns: [],
            schema: [
                {
                    id: 'query',
                    displayName: 'query',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'limit',
                    displayName: 'limit',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'number',
                    removed: false,
                },
                {
                    id: 'connection_id',
                    displayName: 'connection_id',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
                {
                    id: 'processed_label',
                    displayName: 'processed_label',
                    required: false,
                    defaultMatch: false,
                    display: true,
                    canBeUsedToMatch: true,
                    type: 'string',
                    removed: false,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: true,
        },
        mode: 'each',
        options: {
            waitForSubWorkflow: false,
        },
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @node({
        id: 'mail01-stamp-outline',
        name: 'Stamp Outline',
        /*__n8n__*/ notes: "Highlight data for the concurrency board (execution_metadata key `outline`). The count is the whole point of this scheduler: it fans out over EVERY mail connection, and a regression to one connection is invisible on the board without it — which is exactly the defect this workflow was created to fix.",
        type: 'n8n-nodes-base.executionData',
        version: 1,
        position: [-68, 208],
    })
    StampOutline = {
        dataToSave: {
            values: [
                { key: 'outline', value: "={{ 'label_engine_x' + $input.all().length + '_conns' + ((($input.first().json._skipped) || []).length ? '_skipped' + $input.first().json._skipped.length : '') }}" },
                { key: 'exection_type', value: 'mail_scheduler' },
                { key: 'connections', value: '={{ $input.all().length }}' },
                { key: 'connection_ids', value: "={{ $input.all().map(i => i.json.connection_id).join(',') }}" },
                { key: 'skipped', value: "={{ (($input.first().json._skipped) || []).join(' | ') }}" },
            ],
        },
    };

    @links()
    defineRouting() {
        this.Tick.out(0).to(this.LoadSettings.in(0));
        this.LoadSettings.out(0).to(this.EnumerateConnections.in(0));
        this.EnumerateConnections.out(0).to(this.CallLabelEngine.in(0));
        this.EnumerateConnections.out(0).to(this.StampOutline.in(0));
    }
}
