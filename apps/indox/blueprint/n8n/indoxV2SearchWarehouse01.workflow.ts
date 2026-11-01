import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Search File In Warehouse Scans
// Nodes   : 11  |  Connections: 12
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// SearchFilesAndFolders              executeWorkflow            [alwaysOutput] [retry]
// Start                              executeWorkflowTrigger
// IfFoundFile1                       if
// EditFields                         set
// EditFields1                        set
// EditFields2                        set
// End                                noOp
// IfInputOk                          if
// LoopOverItems                      splitInBatches
// WhReqSettings                      code
// GetWarehouseSetting                executeWorkflow            [onError→regular] [alwaysOutput]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Start
//    → IfInputOk
//      → WhReqSettings
//        → GetWarehouseSetting
//          → SearchFilesAndFolders
//            → IfFoundFile1
//              → EditFields2
//                → End
//             .out(1) → EditFields1
//                → End (↩ loop)
//     .out(1) → EditFields
//        → End (↩ loop)
// LoopOverItems
//   .out(1) → IfInputOk (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Start":{"main":[[{"node":"If Input OK","type":"main","index":0}]]},"Search files and folders":{"main":[[{"node":"If Found File1","type":"main","index":0}]]},"If Found File1":{"main":[[{"node":"Edit Fields2","type":"main","index":0}],[{"node":"Edit Fields1","type":"main","index":0}]]},"Edit Fields2":{"main":[[{"node":"End","type":"main","index":0}]]},"Edit Fields1":{"main":[[{"node":"End","type":"main","index":0}]]},"Edit Fields":{"main":[[{"node":"End","type":"main","index":0}]]},"If Input OK":{"main":[[{"node":"WH Req (settings)","type":"main","index":0}],[{"node":"Edit Fields","type":"main","index":0}]]},"Loop Over Items":{"main":[[],[{"node":"If Input OK","type":"main","index":0}]]},"End":{"main":[[]]},"WH Req (settings)":{"main":[[{"node":"Get Warehouse Setting","type":"main","index":0}]]},"Get Warehouse Setting":{"main":[[{"node":"Resolve Drive","type":"main","index":0}]]},"Resolve Drive":{"main":[[{"node":"If Drive Identity?","type":"main","index":0}]]},"If Drive Identity?":{"main":[[{"node":"Search files and folders","type":"main","index":0}],[{"node":"Edit Fields1","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"1e9bb7a7-e850-4407-8c88-f8950e4c00f0","name":"scanners"},{"updatedAt":"2026-07-30T23:41:29.646Z","createdAt":"2026-07-30T23:41:29.646Z","id":"9c337cfe-7feb-4f3d-ab26-3de6439357ce","name":"sm-refactore-v2.1"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"e93d27c0-bb72-4989-94be-da28cf92d0ac","name":"drive"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"f5d175fb-c738-4607-8ef0-bf03c48e8a0b","name":"role:extractor"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"22f1e71e-91bf-48db-811f-8d3bc4e55a3e","name":"sm-refactor-v2.1"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-31T00:59:54.840Z","createdAt":"2026-07-31T00:59:54.840Z","role":"workflow:owner","workflowId":"indoxV2SearchWarehouse01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2SearchWarehouse01',
    name: 'Search File In Warehouse Scans',
    active: true,
    isArchived: false,
    tags: [
        'indox',
        'scanners',
        'sm-refactore-v2.1',
        'app:indox',
        'drive',
        'indox-app',
        'role:extractor',
        'sm-refactor-v2.1',
    ],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class SearchFileInWarehouseScansWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: '4855653b-ccad-4385-88c9-0e7710a2a853',
        name: 'Search files and folders',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [48, 928],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    SearchFilesAndFolders = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'list',
                params: '={{ ({ folderId: String($json.folderId || ""), limit: 1, whatToSearch: "files", connection_id: String($json.connection_id || ""), profile_id: String($json.profile_id || "") }) }}',
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'op',
                    displayName: 'op',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'params',
                    displayName: 'params',
                    required: false,
                    display: true,
                    type: 'object',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
        options: {},
    };

    @node({
        id: '05ee4e42-7b2b-4a66-8287-1bae961536cf',
        name: 'Start',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-736, 1072],
    })
    Start = {
        workflowInputs: {
            values: [
                {
                    name: 'ID',
                    type: 'any',
                },
                {
                    name: 'COMPANY_NAME',
                    type: 'any',
                },
                {
                    name: 'SHORT_DOC_ID',
                    type: 'any',
                },
                {
                    name: 'WAREHOUSE_FOLDER',
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
        id: '9ec94d2a-a923-4a8b-91eb-a3fe17259518',
        name: 'If Found File1',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [240, 928],
    })
    IfFoundFile1 = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 2,
            },
            conditions: [
                {
                    id: 'bb6d03b8-6b51-4982-bc9c-191d2f44b382',
                    leftValue: '={{ $json?.id }}',
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
        options: {},
    };

    @node({
        id: '541efc98-454c-462f-b9b1-a5a8b4a6f25c',
        name: 'Edit Fields',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [48, 1088],
    })
    EditFields = {
        assignments: {
            assignments: [
                {
                    id: '229b766d-0842-4527-b323-eb70e3841a27',
                    name: 'ID',
                    value: "={{ $('Start').first().json.ID }}",
                    type: 'string',
                },
                {
                    id: 'ac25bf0a-b3ee-4934-aa43-7fb38129c726',
                    name: 'error',
                    value: 'missing company name / doc id ',
                    type: 'string',
                },
                {
                    id: '5f60ca26-02f6-40c4-93a3-d2f9c6151832',
                    name: 'ok',
                    value: false,
                    type: 'boolean',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };

    @node({
        id: 'cc043ed1-47c4-422c-8876-27d31b5e33d0',
        name: 'Edit Fields1',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [480, 944],
    })
    EditFields1 = {
        assignments: {
            assignments: [
                {
                    id: '3137c985-1363-42bc-98a7-4c0afbec2b6a',
                    name: 'ID',
                    value: "={{ $('Start').first().json.ID }}",
                    type: 'string',
                },
                {
                    id: 'ac25bf0a-b3ee-4934-aa43-7fb38129c726',
                    name: 'error',
                    value: 'file not found',
                    type: 'string',
                },
                {
                    id: '2915607e-ece6-4fe3-ac87-349d7cbbbd87',
                    name: 'ok',
                    value: false,
                    type: 'boolean',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };

    @node({
        id: '7c73c61c-bfb1-4c55-a5e9-360810653b56',
        name: 'Edit Fields2',
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [496, 784],
    })
    EditFields2 = {
        assignments: {
            assignments: [
                {
                    id: '95c2b121-5f15-4d9d-a53c-e501135f4f13',
                    name: 'ID',
                    value: "={{ $('Start').first().json.ID }}",
                    type: 'string',
                },
                {
                    id: '2915607e-ece6-4fe3-ac87-349d7cbbbd87',
                    name: 'ok',
                    value: true,
                    type: 'boolean',
                },
            ],
        },
        includeOtherFields: true,
        options: {},
    };

    @node({
        id: '0dab0d7d-ebae-4349-8508-639c4a6bb915',
        name: 'End',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [816, 1088],
    })
    End = {};

    @node({
        id: '7b4930de-ea93-40d7-a00f-d1eecaf4600a',
        name: 'If Input OK',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-208, 1072],
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
            ],
            combinator: 'and',
        },
        looseTypeValidation: true,
        options: {},
    };

    @node({
        id: '2e852df5-a6f4-4a59-8b26-d0794c362158',
        name: 'Loop Over Items',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [-512, 1072],
    })
    LoopOverItems = {
        options: {},
    };

    @node({
        id: '9a1c0d2e-7b64-4f18-9c30-5ad0e2f11b01',
        name: 'WH Req (settings)',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-208, 704],
    })
    WhReqSettings = {
        jsCode: `// Instance-neutral resolution of the warehouse-scans folder.
// Was a hardcoded folder id inline in 'Search files and folders' — one client's
// 'סרוקות הצליח'. Shipped in the blueprint, it made every deployment built from
// this repo search THAT client's Drive whenever a caller omitted WAREHOUSE_FOLDER.
// Same TABLE_GET shape indoxV2ActionsGDoc01/indoxV2ActionsShip01 already use for
// this very setting — one mechanism, not a second one.
//
// INSTANCE: the instance this row belongs to (phase 6.5). The chokepoint THROWS
// without it. 'incoming-documents-main' is the platform default (the DDL default
// on public.settings.instance), not a instance identifier.
const INSTANCE='incoming-documents-main';
// [tenant carry 2026-08-31] __instance is the SCHEMA the chokepoint must serve (cutover
// throw without it -- 21 live errors/hour measured); the 'instance' field above is the row-scope
// VALUE inside that schema. Read at the boundary, never mid-chain.
var __inst=''; try{ __inst=String(($('Start').first().json||{}).__instance||''); }catch(e){}
// [2026-09-02] WHICH DRIVE holds the warehouse scans is tenant configuration too (the search
// node carried one client's connection id): the same read now also fetches the explicit knob
// 'DriveSearchConnection' and the registry (fallback = the first enabled drive pipe's connection).
return [{ json: { INLINE_ACTION: 'TABLE_GET', table: 'settings', instance: INSTANCE, __instance: __inst,
  filters: [ { key: 'WarehouseScansSourceFolder' }, { key: 'DriveSearchConnection' }, { key: 'sync_registry' } ] } }];`,
    };

    @node({
        id: '9a1c0d2e-7b64-4f18-9c30-5ad0e2f11b02',
        name: 'Get Warehouse Setting',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-32, 704],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    GetWarehouseSetting = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'sw-resolve-drive',
        name: 'Resolve Drive',
        /*__n8n__*/ notes: "[2026-09-02] ONE place resolves WHERE to search: the warehouse folder (the caller's WAREHOUSE_FOLDER, else the WarehouseScansSourceFolder setting) and WHICH Drive — the DriveSearchConnection knob (a catalog connection id, or 'profile:<id>' for the local engine), else the first enabled drive pipe's own identity from the registry. No identity or no folder = no drive call at all (the If after this node routes to 'file not found'): a tenant with no Drive configured must not produce an error execution per document.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-32, 848],
    })
    ResolveDrive = {
        jsCode: `const rows = $input.all().map(i => (i && i.json) || {});
const val = k => { const r = rows.find(x => x && x.key === k); return r ? (r.value != null ? r.value : r.VALUE) : null; };
const passed = (() => { try { const v = $('Start').first().json.WAREHOUSE_FOLDER; return (v && String(v).trim()) ? String(v).trim() : ''; } catch (e) { return ''; } })();
const raw = String(val('WarehouseScansSourceFolder') || '');
const m = raw.match(/folders\\/([A-Za-z0-9_-]+)/);
const folderId = passed || (m ? m[1] : ((raw && !raw.includes('/')) ? raw.trim() : ''));
let conn = String(val('DriveSearchConnection') || '').trim(), prof = '';
if (conn.startsWith('profile:')) { prof = conn.slice(8).trim(); conn = ''; }
if (!conn && !prof) {
  try {
    const reg = JSON.parse(String(val('sync_registry') || '[]'));
    const d = (Array.isArray(reg) ? reg : []).find(e => e && e.source === 'drive' && String(e.enabled == null ? 'true' : e.enabled) !== 'false' && (e.connection || e.connection_id || e.profile_id));
    if (d) { conn = String(d.connection || d.connection_id || ''); prof = conn ? '' : String(d.profile_id || ''); }
  } catch (e) {}
}
// 'Get Warehouse Setting' continues on error, so a failed settings read arrived here as rows with
// no key/value and looked exactly like "this warehouse declares nothing" — which then routes to
// 'file not found'. Read the failure and carry it, so an unreadable setting is not a verdict.
const failed = rows.filter(r => r && (r.error || r.errorMessage))
  .map(r => String(r.error || r.errorMessage).slice(0, 200));
return [{ json: { folderId, connection_id: conn, profile_id: prof,
  has_identity: !!(conn || prof) && !!folderId,
  settings_failed: failed.length, settings_failures: failed } }];`,
    };

    @node({
        id: 'sw-if-identity',
        name: 'If Drive Identity?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [-32, 992],
    })
    IfDriveIdentity = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'sw-identity-2026-09-02',
                    leftValue: '={{ $json.has_identity === true }}',
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
        looseTypeValidation: true,
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Start.out(0).to(this.IfInputOk.in(0));
        this.SearchFilesAndFolders.out(0).to(this.IfFoundFile1.in(0));
        this.IfFoundFile1.out(0).to(this.EditFields2.in(0));
        this.IfFoundFile1.out(1).to(this.EditFields1.in(0));
        this.EditFields2.out(0).to(this.End.in(0));
        this.EditFields1.out(0).to(this.End.in(0));
        this.EditFields.out(0).to(this.End.in(0));
        this.IfInputOk.out(0).to(this.WhReqSettings.in(0));
        this.IfInputOk.out(1).to(this.EditFields.in(0));
        this.LoopOverItems.out(1).to(this.IfInputOk.in(0));
        this.WhReqSettings.out(0).to(this.GetWarehouseSetting.in(0));
        this.GetWarehouseSetting.out(0).to(this.ResolveDrive.in(0));
        this.ResolveDrive.out(0).to(this.IfDriveIdentity.in(0));
        this.IfDriveIdentity.out(0).to(this.SearchFilesAndFolders.in(0));
        this.IfDriveIdentity.out(1).to(this.EditFields1.in(0));
    }
}
