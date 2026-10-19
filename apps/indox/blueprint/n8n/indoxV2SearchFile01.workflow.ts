import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Search File
// Nodes   : 6  |  Connections: 7
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Start                              executeWorkflowTrigger
// LoopOverItems                      splitInBatches
// IfInputOk                          if
// SearchFilesAndFolders              httpRequest                [onError→regular] [retry]
// ShapeResult                        code
// ReturnAllResults                   noOp
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Start
//    → LoopOverItems
//      → ReturnAllResults
//     .out(1) → IfInputOk
//        → SearchFilesAndFolders
//          → ShapeResult
//            → LoopOverItems (↩ loop)
//       .out(1) → ShapeResult (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Start":{"main":[[{"node":"Settings Req","type":"main","index":0}]]},"Settings Req":{"main":[[{"node":"Get Settings","type":"main","index":0}]]},"Get Settings":{"main":[[{"node":"Attach Connection","type":"main","index":0}]]},"Attach Connection":{"main":[[{"node":"Loop Over Items","type":"main","index":0}]]},"Search files and folders":{"main":[[{"node":"Shape Result","type":"main","index":0}]]},"If Input OK":{"main":[[{"node":"Search files and folders","type":"main","index":0}],[{"node":"Shape Result","type":"main","index":0}]]},"Shape Result":{"main":[[]]},"Loop Over Items":{"main":[[{"node":"Return All Results","type":"main","index":0}],[{"node":"If Input OK","type":"main","index":0},{"node":"Loop Over Items","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1e9bb7a7-e850-4407-8c88-f8950e4c00f0","name":"scanners"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"e93d27c0-bb72-4989-94be-da28cf92d0ac","name":"drive"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"f5d175fb-c738-4607-8ef0-bf03c48e8a0b","name":"role:extractor"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T00:59:54.840Z","createdAt":"2026-07-31T00:59:54.840Z","role":"workflow:owner","workflowId":"indoxV2SearchFile01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2SearchFile01',
    name: 'Search File',
    active: true,
    isArchived: false,
    tags: [
        'sm-refactore-v2.1',
        'indox',
        'scanners',
        'app:indox',
        'drive',
        'indox-app',
        'role:extractor',
        'sm-refactor-v2.1',
    ],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class SearchFileWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'aa7c9051-8ec6-4a6c-943a-73140eae42c4',
        name: 'Start',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-736, 1072],
    })
    Start = {
        workflowInputs: {
            values: [
                {
                    name: 'COMPANY_NAME',
                    type: 'any',
                },
                {
                    name: 'SHORT_DOC_ID',
                    type: 'any',
                },
                {
                    name: 'ID',
                    type: 'any',
                },
                {
                    name: '__instance',
                    type: 'any',
                },
            ],
        },
    };

    @node({
        id: 'sf-settings-req',
        name: 'Settings Req',
        /*__n8n__*/ notes: "[2026-09-02] WHICH DRIVE TO SEARCH is tenant configuration, never a literal in shipped code (the previous body carried one client's connection id, so every deployment built from this repo searched THAT client's Drive). One TABLE_GET for two keys: `DriveSearchConnection` (an explicit knob) and `sync_registry` (the fallback: the first enabled drive pipe's connection — the Drive the documents themselves come from). __instance is the tenant; the chokepoint throws without it.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-640, 880],
    })
    SettingsReq = {
        jsCode: `var __inst=''; try{ __inst=String(($('Start').first().json||{}).__instance||''); }catch(e){}
return [{ json: { INLINE_ACTION: 'TABLE_GET', table: 'settings', instance: 'incoming-documents-main', __instance: __inst,
  filters: [ { key: 'DriveSearchConnection' }, { key: 'sync_registry' } ] } }];`,
    };

    @node({
        id: 'sf-get-settings',
        name: 'Get Settings',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [-512, 880],
        alwaysOutputData: true,
        onError: 'continueRegularOutput',
    })
    GetSettings = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sf-attach-connection',
        name: 'Attach Connection',
        /*__n8n__*/ notes: "Re-emits the Start items (the executeWorkflow node replaced them with settings rows) with DRIVE_CONNECTION resolved: the explicit knob first, else the first enabled drive pipe's connection from the registry, else '' — and an empty one is REFUSED by the drive service (400 naming what to pass), never silently searched against whatever connection the console happens to be bound to.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-384, 880],
    })
    AttachConnection = {
        jsCode: `const rows = $input.all().map(i => (i && i.json) || {});
const val = k => { const r = rows.find(x => x && x.key === k); return r ? (r.value != null ? r.value : r.VALUE) : null; };
// identity = a catalog connection id (DRIVE_CONNECTION) or a local-engine profile (DRIVE_PROFILE):
// the knob first, else the first enabled drive pipe's own identity — the same two keys the sync
// units carry, so the search runs against the Drive the documents themselves come from.
let conn = String(val('DriveSearchConnection') || '').trim(), prof = '';
if (conn.startsWith('profile:')) { prof = conn.slice(8).trim(); conn = ''; }
if (!conn && !prof) {
  try {
    const reg = JSON.parse(String(val('sync_registry') || '[]'));
    const d = (Array.isArray(reg) ? reg : []).find(e => e && e.source === 'drive' && String(e.enabled == null ? 'true' : e.enabled) !== 'false' && (e.connection || e.connection_id || e.profile_id));
    if (d) { conn = String(d.connection || d.connection_id || ''); prof = conn ? '' : String(d.profile_id || ''); }
  } catch (e) {}
}
return $('Start').all().map(i => ({ json: { ...(i.json || {}), DRIVE_CONNECTION: conn, DRIVE_PROFILE: prof } }));`,
    };

    @node({
        id: '021f28d7-17e2-4a38-a594-64e92d9b38a2',
        name: 'Loop Over Items',
        /*__n8n__*/ notes: "batchSize PINNED to 1 (load-bearing): per-item isolation + per-iteration $('...') refs + driveApi01's Shape list reads only the first response. done → Return All Results = the 1:1-in-order return.",
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-512, 1072],
    })
    LoopOverItems = {
        batchSize: 1,
        options: {},
    };

    @node({
        id: '50a4bd07-63c5-4385-a540-5c9e774dddf2',
        name: 'If Input OK',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-208, 928],
    })
    IfInputOk = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: '7ea7854e-7301-4e26-82dd-48a29c239c89',
                    leftValue: '={{ String($json.COMPANY_NAME) }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
                {
                    id: '4f7cbd6c-1d8a-4bb7-b2f2-17f90b9c995f',
                    leftValue: '={{ String($json.SHORT_DOC_ID) }}',
                    rightValue: '',
                    operator: {
                        type: 'string',
                        operation: 'notEmpty',
                        singleValue: true,
                    },
                },
                {
                    id: 'sf-identity-2026-09-02',
                    leftValue: '={{ String($json.DRIVE_CONNECTION || $json.DRIVE_PROFILE || "") }}',
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
        looseTypeValidation: true,
        options: {},
    };

    @node({
        id: '9396d0b7-5111-49d9-a6a1-88bcc2db3743',
        name: 'Search files and folders',
        /*__n8n__*/ notes: "[direct-call 2026-08-17, owner speed order] One POST to the drive service's /list per doc — the SAME canonical op the driveApi01 wrapper made, minus the ~2s n8n sub-execution spawned per search (measured 4.07s/line via the wrapper; the Drive HTTP itself is ~1.5s). The service still owns the connection and enforces its contract; only this hot path skips the n8n-side facade. Query built inline (service applies it since the 2026-08-13 'GAP CLOSED' fix). A zero-result is an EXPLICIT {files:[]} response — no empty-item swallow is possible. onError continueRegularOutput + retryOnFail: a real failure (after 4 tries) becomes an ok:false item for THIS doc only — the rest of the batch continues.",
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [48, 928],
        onError: 'continueRegularOutput',
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    SearchFilesAndFolders = {
        method: 'POST',
        url: 'http://drive:8975/list',
        sendBody: true,
        specifyBody: 'json',
        jsonBody:
            '={{ JSON.stringify({ folderId: \'\', query: "name contains \'" + String($json.COMPANY_NAME||\'\').replace(/\'/g, "\\\\\'") + "\' and name contains \'" + String($json.SHORT_DOC_ID||\'\').replace(/\'/g, "\\\\\'") + "\'", limit: 5, whatToSearch: "files", connection_id: String($json.DRIVE_CONNECTION || ""), profile_id: String($json.DRIVE_PROFILE || "") }) }}',
        options: {
            timeout: 30000,
        },
    };

    @node({
        id: 'c9e1f2a3-0003-4ccc-8ddd-000000000000',
        name: 'Shape Result',
        /*__n8n__*/ notes: "The whole result contract in one place. Emits EXACTLY ONE item per doc (up to 5 search hits collapse to the best name-match) — this is what keeps the return 1:1 and in order. found:false is a normal answer with a message; ok:false is reserved for real failures (search error / invalid input) and the caller must not settle the doc on it.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [288, 1072],
    })
    ShapeResult = {
        jsCode: `// one input doc per loop iteration -> exactly one output item.
// [direct-call 2026-08-17] input is now the drive service's /list RESPONSE ({files:[...]}) —
// or an {error:...} item when the HTTP call failed after retries, or the raw doc when input
// was invalid. Zero-result = files:[] (explicit — the old empty-item swallow cannot happen).
const src = $('Loop Over Items').first().json;
// connection_id rides on every answer: the caller stamps LINK_CONNECTION from it (the Drive the
// file was FOUND in), never from a literal — one client's connection id used to be hardcoded there.
const base = { ID: String(src.ID || ''), SHORT_DOC_ID: String(src.SHORT_DOC_ID || ''), COMPANY_NAME: String(src.COMPANY_NAME || ''), connection_id: String(src.DRIVE_CONNECTION || '') };
let out;
if (!base.COMPANY_NAME || !base.SHORT_DOC_ID) {
  out = { ...base, ok: false, error: 'missing company name / doc id' };
} else {
  const j = ($input.first() && $input.first().json) || {};
  const hits = Array.isArray(j.files) ? j.files : [];
  const hit = hits.find(f => f && f.id && String(f.name || '').includes(base.SHORT_DOC_ID));
  if (j.error) out = { ...base, ok: false, error: String((j.error && j.error.message) || j.error) };
  else if (hit) out = { ...base, ok: true, found: true, id: hit.id, name: hit.name, size: hit.size ?? null, md5Checksum: hit.md5Checksum ?? null, link: hit.webViewLink || hit.link || null };
  else if (Array.isArray(j.files)) out = { ...base, ok: true, found: false, message: 'file not found' };
  else out = { ...base, ok: false, error: 'unexpected /list response shape: ' + JSON.stringify(j).slice(0, 120) };
}
return [{ json: out }];`,
    };

    @node({
        id: 'c9e1f2a3-0002-4bbb-8ccc-000000000000',
        name: 'Return All Results',
        /*__n8n__*/ notes: "The workflow's RETURN: Loop Over Items' done output = the items fed back per iteration, i.e. one result per input doc, input order. Do not add nodes that filter, reorder, or aggregate between the loop and this node.",
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-288, 1264],
    })
    ReturnAllResults = {};

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Start.out(0).to(this.SettingsReq.in(0));
        this.SettingsReq.out(0).to(this.GetSettings.in(0));
        this.GetSettings.out(0).to(this.AttachConnection.in(0));
        this.AttachConnection.out(0).to(this.LoopOverItems.in(0));
        this.SearchFilesAndFolders.out(0).to(this.ShapeResult.in(0));
        this.IfInputOk.out(0).to(this.SearchFilesAndFolders.in(0));
        this.IfInputOk.out(1).to(this.ShapeResult.in(0));
        this.ShapeResult.out(0).to(this.LoopOverItems.in(0));
        this.LoopOverItems.out(0).to(this.ReturnAllResults.in(0));
        this.LoopOverItems.out(1).to(this.IfInputOk.in(0));
    }
}
