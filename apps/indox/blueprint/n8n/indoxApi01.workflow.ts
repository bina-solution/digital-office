import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : indox api
// Nodes   : 40  |  Connections: 38
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// ApiActionSwitch                    switch
// StripControl                       code
// LoadMatchIndex                     postgres                   [creds] [alwaysOutput] [executeOnce] [retry]
// ResolveIds                         code
// BuildBulkUpsertSql                 code
// PgBulkUpsert                       postgres                   [creds] [retry]
// RestoreUpsertedDocs                code
// BuildGetAllSql                     code
// PgGetAll                           postgres                   [creds] [alwaysOutput] [retry]
// PageGetAll                         code
// BuildGetSql                        code
// PgGet                              postgres                   [creds] [alwaysOutput] [retry]
// PgDelete                           postgres                   [creds] [retry]
// BuildTableGet                      code
// PgTableGet                         postgres                   [creds] [retry]
// BuildTableUpsert                   code
// PgTableUpsert                      postgres                   [creds] [retry]
// Keepalive                          scheduleTrigger
// KeepaliveNoop                      noOp
// GetChangedDocs                     postgres                   [creds] [retry]
// StickyNoteTrigger                  stickyNote
// BuildDeliver                       code
// PgDeliverInsert                    postgres                   [creds] [alwaysOutput] [retry]
// DeliverFetchReq                    code
// PgDeliverFetch                     postgres                   [creds] [retry]
// BuildMatchIndexSql                 code
// GuardGetSize                       code
// BuildMergeRead                     code
// PgMergeRead                        postgres                   [creds] [alwaysOutput]
// BuildMergeWrite                    code
// PgMergeWrite                       postgres                   [creds]
// MergeEmitIds                       code
// MergeUnlockDoc                     executeWorkflow            [onError→regular]
// MergeResult                        code
// ApiEmitIds                         code
// ApiUnlockDoc                       executeWorkflow            [onError→regular]
// IfManagement                       if
// CallSyncApi                        executeWorkflow
// UpsertAdapter                      code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → IfManagement
//      → CallSyncApi
//     .out(1) → ApiActionSwitch
//        → StripControl
//          → UpsertAdapter
//            → BuildMatchIndexSql
//              → LoadMatchIndex
//                → ResolveIds
//                  → BuildBulkUpsertSql
//                    → PgBulkUpsert
//                      → RestoreUpsertedDocs
//                        → ApiEmitIds
//                          → ApiUnlockDoc
//       .out(1) → BuildGetAllSql
//          → PgGetAll
//            → PageGetAll
//              → GuardGetSize
//       .out(2) → BuildGetSql
//          → PgGet
//            → GuardGetSize (↩ loop)
//       .out(3) → PgDelete
//       .out(4) → BuildTableGet
//          → PgTableGet
//       .out(5) → BuildTableUpsert
//          → PgTableUpsert
//       .out(6) → BuildDeliver
//          → PgDeliverInsert
//            → DeliverFetchReq
//              → PgDeliverFetch
//       .out(7) → BuildMergeRead
//          → PgMergeRead
//            → BuildMergeWrite
//              → PgMergeWrite
//                → MergeEmitIds
//                  → MergeUnlockDoc
//                    → MergeResult
//       .out(8) → GetChangedDocs
// Keepalive
//    → KeepaliveNoop
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"If Management","type":"main","index":0}]]},"API Action Switch":{"main":[[{"node":"Strip Control","type":"main","index":0}],[{"node":"Build Get All SQL","type":"main","index":0}],[{"node":"Build Get SQL","type":"main","index":0}],[{"node":"PG Delete","type":"main","index":0}],[{"node":"Build Table Get","type":"main","index":0}],[{"node":"Build Table Upsert","type":"main","index":0}],[{"node":"Build Deliver","type":"main","index":0}],[{"node":"Build Merge Read","type":"main","index":0}],[{"node":"Get Changed Docs","type":"main","index":0}]]},"Strip Control":{"main":[[{"node":"UPSERT Adapter","type":"main","index":0}]]},"Load Match Index":{"main":[[{"node":"Resolve IDs","type":"main","index":0}]]},"Resolve IDs":{"main":[[{"node":"Build Bulk Upsert SQL","type":"main","index":0}]]},"Build Get SQL":{"main":[[{"node":"PG Get","type":"main","index":0}]]},"Build Table Get":{"main":[[{"node":"PG Table Get","type":"main","index":0}]]},"Build Table Upsert":{"main":[[{"node":"PG Table Upsert","type":"main","index":0}]]},"Keepalive":{"main":[[{"node":"Keepalive NoOp","type":"main","index":0}]]},"Build Deliver":{"main":[[{"node":"PG Deliver Insert","type":"main","index":0}]]},"PG Deliver Insert":{"main":[[{"node":"Deliver Fetch Req","type":"main","index":0}]]},"Deliver Fetch Req":{"main":[[{"node":"PG Deliver Fetch","type":"main","index":0}]]},"Build Match Index SQL":{"main":[[{"node":"Load Match Index","type":"main","index":0}]]},"PG Get":{"main":[[{"node":"Guard Get Size","type":"main","index":0}]]},"PG Get All":{"main":[[{"node":"Page Get All","type":"main","index":0}]]},"Build Merge Read":{"main":[[{"node":"PG Merge Read","type":"main","index":0}]]},"PG Merge Read":{"main":[[{"node":"Build Merge Write","type":"main","index":0}]]},"Build Merge Write":{"main":[[{"node":"PG Merge Write","type":"main","index":0}]]},"PG Merge Write":{"main":[[{"node":"Merge Emit IDs","type":"main","index":0}]]},"API Emit IDs":{"main":[[{"node":"API Unlock Doc","type":"main","index":0}]]},"If Management":{"main":[[{"node":"Call Sync Api","type":"main","index":0}],[{"node":"API Action Switch","type":"main","index":0}]]},"UPSERT Adapter":{"main":[[{"node":"Build Match Index SQL","type":"main","index":0}]]},"Build Bulk Upsert SQL":{"main":[[{"node":"PG Bulk Upsert","type":"main","index":0}]]},"PG Bulk Upsert":{"main":[[{"node":"Restore Upserted Docs","type":"main","index":0}]]},"Restore Upserted Docs":{"main":[[{"node":"API Emit IDs","type":"main","index":0}]]},"Build Get All SQL":{"main":[[{"node":"PG Get All","type":"main","index":0}]]},"Page Get All":{"main":[[{"node":"Guard Get Size","type":"main","index":0}]]},"Merge Emit IDs":{"main":[[{"node":"Merge Unlock Doc","type":"main","index":0}]]},"Merge Unlock Doc":{"main":[[{"node":"Merge Result","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {"node:Keepalive":{"recurrenceRules":[0]}},
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-12T19:30:21.402Z","createdAt":"2026-08-12T19:30:21.402Z","role":"workflow:owner","workflowId":"indoxApi01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxApi01',
    name: 'indox api',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1', binaryMode: 'separate' },
})
export class IndoxApiWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'trg',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-1680, -16],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'sw',
        name: 'API Action Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [-1200, 800],
    })
    ApiActionSwitch = {
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
                        conditions: [
                            {
                                id: 'UPSERT',
                                leftValue: "={{ $json.INLINE_ACTION || 'UPSERT' }}",
                                rightValue: 'UPSERT',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'UPSERT',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'GET_ALL',
                                leftValue: "={{ $json.INLINE_ACTION || 'UPSERT' }}",
                                rightValue: 'GET_ALL',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'GET_ALL',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'GET',
                                leftValue: "={{ $json.INLINE_ACTION || 'UPSERT' }}",
                                rightValue: 'GET',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'GET',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'DELETE',
                                leftValue: "={{ $json.INLINE_ACTION || 'UPSERT' }}",
                                rightValue: 'DELETE',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'DELETE',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'TABLE_GET',
                                leftValue: "={{ $json.INLINE_ACTION || 'UPSERT' }}",
                                rightValue: 'TABLE_GET',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'TABLE_GET',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'TABLE_UPSERT',
                                leftValue: "={{ $json.INLINE_ACTION || 'UPSERT' }}",
                                rightValue: 'TABLE_UPSERT',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'TABLE_UPSERT',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'DELIVER',
                                leftValue: "={{ $json.INLINE_ACTION || 'UPSERT' }}",
                                rightValue: 'DELIVER',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'DELIVER',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'MERGE',
                                leftValue: "={{ $json.INLINE_ACTION || 'UPSERT' }}",
                                rightValue: 'MERGE',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'MERGE',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            leftValue: '',
                            typeValidation: 'strict',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'GET_CHANGED',
                                leftValue: "={{ $json.INLINE_ACTION || 'UPSERT' }}",
                                rightValue: 'GET_CHANGED',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'GET_CHANGED',
                },
            ],
        },
        options: {},
    };

    @node({
        id: 'strip',
        name: 'Strip Control',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-880, 128],
    })
    StripControl = {
        jsCode: 'return items.map(i=>{const j={...i.json};delete j.INLINE_ACTION;return {json:j};});',
    };

    @node({
        id: 'idx',
        name: 'Load Match Index',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-112, 128],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        executeOnce: true,
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    LoadMatchIndex = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryReplacement: '={{ $json.params }}',
        },
    };

    @node({
        id: 'res',
        name: 'Resolve IDs',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [144, 128],
    })
    ResolveIds = {
        jsCode: `// [unlock coverage 2026-08-13] READ EVERY ITEM. Reading from the UPSERT Adapter starved the
// unlock: the adapter deliberately DROPS items (no ID/SOURCE_TYPE/HASH, null-stripped), and every
// dropped item is a document whose doc_action lock is never released — locks went 998 -> ~2,900,
// BLOCKED BY LOCK dominated the ACTION_LOG, and completions fell to ~45/hr.
// [fold 2026-08-12] READ FROM THE ADAPTER, NOT AROUND IT. This node used to rebuild its items
// from $('Strip Control'), which sits UPSTREAM of the UPSERT Adapter inserted during the Batch
// Upsert fold. That discarded every canonicalisation the adapter had just applied, and carried the
// control flag \`unlock\` (plus LOCAL_STATUS / AI_STATUS provenance) through to PG Upsert, whose
// autoMapInputData then tried to write them as columns: "Column 'unlock' does not exist".
const incoming = $('Strip Control').all().map(i=>i.json);
const index = $input.all().map(i=>i.json);
const bad = v => v===undefined||v===null||v===''||v==='unknown'||v==='ACTION_REQUIRED';
const SEP='';
// [C3 2026-08-21] THE DOC-ID QUARANTINE IS GONE WITH THE THING IT GUARDED.
// It existed for one purpose: to stop a weak business key from silently folding two rows together
// -- excluding 'none', all-zeros, values under 3 alphanumerics, a value equal to the row's own
// COMPANY_ID, and quarantining any doc number seen under more than one company. Every one of those
// rules was a patch on the same underlying mistake: letting the WRITER act on INFERRED identity.
// The writer no longer matches on business keys at all (see logicalMatch below), so there is
// nothing left to quarantine here. The judgement itself is not lost -- it belongs to the merge
// action, which is where a doc number shared across companies becomes a quarantined group with a
// stated reason instead of a silent non-match.
// ARTIFACT-identity indexes so we UPDATE an existing row instead of inserting a duplicate.
// Two keys, both CERTAIN: the same bytes (HASH) and the same handle at the same source
// (SOURCE_TYPE, SOURCE_ID). The claim this note used to carry -- "the ONLY way to get a real
// DOUBLE is a manual insert" -- was true only while the writer also folded on business keys, and
// it was true by hiding them rather than by preventing them. Duplicates are now VISIBLE and the
// merge action adjudicates them.
// [multi-artifact sources 2026-08-25] ONE SOURCE HANDLE CAN CARRY SEVERAL ARTIFACTS.
// (SOURCE_TYPE, SOURCE_ID) is a Drive FILE, but for mail SOURCE_ID is the MESSAGE id and a
// message can hold several documents. Keyed on the handle alone, the first attachment claimed
// the key and every sibling logicalMatch'd onto it, so a two-attachment mail could only ever
// become one row. Measured on gmail-bs 1a039e97bc1d04e1: Run Mail Processor returned 2, both
// files were uploaded, Resolve IDs folded 2 -> 1.
// So the handle index is now keyed by (SOURCE_TYPE, SOURCE_ID, NAME) and the handle-only index
// is KEPT alongside it, used only for rows that carry no NAME — those cannot be told apart, and
// folding them is still the safest answer, exactly as before.
const srcNameKey = r => String(r.SOURCE_TYPE)+SEP+String(r.SOURCE_ID)+SEP+String(r.NAME);
const srcKey     = r => String(r.SOURCE_TYPE)+SEP+String(r.SOURCE_ID);
const bySrc={}, bySrcName={}, byHash={}; const existingIds=new Set();
for(const r of index){
  if(!bad(r.ID)) existingIds.add(String(r.ID));
  if(!bad(r.SOURCE_TYPE)&&!bad(r.SOURCE_ID)){
    const k=srcKey(r); if(bySrc[k]===undefined)bySrc[k]=r.ID;
    if(!bad(r.NAME)){const kn=srcNameKey(r); if(bySrcName[kn]===undefined)bySrcName[kn]=r.ID;}
  }
  if(!bad(r.HASH)&&byHash[String(r.HASH)]===undefined) byHash[String(r.HASH)]=r.ID;
}
const gen=()=>'doc_'+Date.now().toString(36)+Math.random().toString(36).slice(2,8);
// [C3 2026-08-21] THE WRITER ANSWERS "IS THIS THE SAME ARTIFACT?" -- NOT "IS THIS THE SAME
// DOCUMENT?". Those are different questions with different evidence, and this function used to
// answer both.
//
// It probed (COMPANY_ID, DOC_ID) and (COMPANY_ID, SHORT_DOC_ID) first. Those are BUSINESS keys --
// INFERRED identity, extracted by a model from a scanned page. When they matched, this code
// silently FOLDED the incoming row into the matched one and every non-empty incoming field
// overwrote it: LINK, SOURCE_ID, HASH, the lot. No audit row, no reversibility, no veto, no
// quarantine, and nothing anywhere recording that a fold had happened. A wrong extraction on one
// page therefore rewrote a different document's handles, and the only trace was that the other
// document stopped pointing at its own file.
//
// Identity that is INFERRED belongs to the merge action, which exists precisely to adjudicate it:
// it has the conflict veto, the doc-id quarantine, merge_audit, MERGED_INTO and a reversal path.
// Identity that is CERTAIN -- the same bytes (HASH), or the same handle at the same source
// (SOURCE_TYPE, SOURCE_ID) -- is a fact, and that is what a writer may act on alone.
//
// CONSEQUENCE, STATED PLAINLY: rows that used to be folded here now become separate rows, so the
// duplicate COUNT goes up. That is the point. A visible duplicate is adjudicable; a silent fold is
// not, and 13.6% of them were wrong.
function logicalMatch(row){
  if(!bad(row.HASH)&&byHash[String(row.HASH)]!==undefined)return byHash[String(row.HASH)];
  if(!bad(row.SOURCE_TYPE)&&!bad(row.SOURCE_ID)){
    // Same handle AND same name = this artifact again (a re-delivery) -> fold, as before.
    // Same handle, different name = a SIBLING artifact from the same message -> its own row.
    if(!bad(row.NAME)){const kn=srcNameKey(row); return bySrcName[kn]!==undefined?bySrcName[kn]:null;}
    const k=srcKey(row); if(bySrc[k]!==undefined)return bySrc[k];
  }
  return null;
}
const out=[]; const outIndexById={};
function register(id,row){
  existingIds.add(String(id));
  if(!bad(row.SOURCE_TYPE)&&!bad(row.SOURCE_ID)){
    const k=srcKey(row); if(bySrc[k]===undefined)bySrc[k]=id;
    if(!bad(row.NAME)){const kn=srcNameKey(row); if(bySrcName[kn]===undefined)bySrcName[kn]=id;}
  }
  if(!bad(row.HASH)&&byHash[String(row.HASH)]===undefined) byHash[String(row.HASH)]=id;
}
for(const row of incoming){
  let id=null;
  if(!bad(row.ID) && existingIds.has(String(row.ID))){
    id=row.ID;                                 // genuine update of a row that already exists
  } else {
    id=logicalMatch(row);                       // existing logical twin (DB or earlier in THIS batch)
    if(bad(id) && !bad(row.ID)) id=row.ID;      // truly first sighting: keep caller's id
  }
  const wasGenerated = bad(id);
  if(bad(id)) id=gen();
  // __instance is the schema selector, not a column; dropping it here keeps it out of updateKeys.
  // [clearable columns 2026-09-03] an explicit null on ERROR / REQUIRED_ACTION is a WRITE (clear),
  // not an omission: ACTION_RESTART's { ERROR: null } used to be stripped here, so a stale error
  // text survived every restart and a parked document could never explain itself twice.
  const CLEARABLE=new Set(['ERROR','REQUIRED_ACTION']);
  const clean={}; for(const [k,v] of Object.entries(row)){ if(k==='__instance') continue; if(v===null&&CLEARABLE.has(k)){ clean[k]=null; continue; } if(v!==null&&v!==undefined&&v!=='') clean[k]=v; }
  // Guard against garbage rows: never CREATE a bare row from an empty item. A brand-new (generated-id)
  // row must carry real content; an update (resolved/provided id) must change at least one field.
  const SUBSTANTIVE=['NAME','HASH','SOURCE_ID','SOURCE_LINK','LINK','TYPE','AI_TYPE','COMPANY_ID','DOC_ID','SHORT_DOC_ID','BS_EXTRACTED_LINES','SUBJECT','FROM','DOC_DATE','TOTAL_AMOUNT'];
  const hasReal = SUBSTANTIVE.some(f=>!bad(clean[f]));
  const updateKeys = Object.keys(clean).filter(k=>k!=='ID');
  const sid=String(id);
  const alreadyEmitted = outIndexById[sid]!==undefined;
  if(wasGenerated){ if(!hasReal) continue; }                 // skip minting an empty new row
  else { if(updateKeys.length===0 && !alreadyEmitted) continue; }  // skip pointless empty update
  clean.ID=id; clean.TIMESTAMP=new Date().toISOString();
  // [provenance 2026-08-21] A BRAND-NEW ROW ALWAYS GETS A self ELEMENT, WHATEVER CREATED IT.
  //
  // the three deliveries (syncDeliver{Drive,Gmail,Link}01) build one, but they are not the only create path:
  // balance-sheet ledger lines, the v1 gmail downloaders and 'Build: Create New Shipment Row'
  // all mint rows through here. Measured 2026-08-21, hours after the backfill: 15 BALANCE_SHEET
  // and 3 GMAIL rows had already arrived with no SOURCE_LIST at all. A row with no provenance is
  // invisible to source feedback and carries nothing for a merge to inherit -- so the guarantee
  // belongs at the single write owner, not at each caller.
  //
  // Only on CREATE (wasGenerated), and only when the caller supplied none, so a lane that builds a
  // richer element always wins and an UPDATE never re-stamps one.
  if (wasGenerated && !Array.isArray(clean.SOURCE_LIST)) {
    const _st = String(clean.SOURCE_TYPE || '').toUpperCase();
    const _kind = (_st === 'GOOGLE_DRIVE_FOLDER' || _st === 'GOOGLE_DRIVE_FILE' || _st === 'WHATSAPP') ? 'drive'
                : (_st.indexOf('GMAIL') >= 0 || _st === 'MAIL_ATTACHMENT') ? 'mail' : 'other';
    const _link = String(clean.LINK || '');
    // Backslashes are DOUBLED because this whole node body is a .ts template literal: a single
    // \\ is eaten there, so /drive.google.com// reaches n8n as /drive.google.com/ -- which
    // terminates the regex at the first unescaped slash and makes the node a syntax error. That
    // is exactly what I shipped at 17:52 today; it broke 4 of 9 indoxApi01 runs before it was
    // caught. Every other regex in this file is written the same way for the same reason.
    const _m = _link.match(/drive\\.google\\.com\\/(?:file\\/d\\/|open\\?id=|uc\\?id=)([A-Za-z0-9_-]{20,})/);
    const _sid = String(clean.SOURCE_ID || '');
    const _isMailbox = _sid.indexOf('@') >= 0;
    clean.SOURCE_LIST = [{
      origin: 'self', doc_row_id: id, first_seen: clean.TIMESTAMP, dup_cause: null,
      source_kind: _kind,
      sync_registry_name: clean.SYNC_NAME || null,
      source_folder_id: (String(clean.SOURCE_LINK || '').match(/\\/folders\\/([A-Za-z0-9_-]+)/) || [])[1] || null,
      file_id: _kind === 'drive' ? ((_m && _m[1]) || (_sid || null)) : ((_m && _m[1]) || null),
      message_id: (_kind === 'mail' && _sid && !_isMailbox) ? _sid : null,
      mailbox: _isMailbox ? _sid : null,
      link: clean.LINK || null, hash: clean.HASH || null,
      link_connection: clean.LINK_CONNECTION || null,
      sync_connection: clean.SYNC_CONNECTION || null,
      // Feedback is NEVER switched on here. This layer knows the row, not the pipe's policy --
      // that lives in sync_registry and reaches an element through the delivery lanes. A row
      // created by some other path stays feedback-off until something that knows says otherwise.
      required_feedback_type: null, feedback_on_success: false, feedback_on_failure: false,
      sync_feedback_completed: false, sync_feedback_outcome: null, sync_feedback_dest: null,
      sync_feedback_error: 'created outside a sync delivery lane, so no pipe policy is known',
      sync_feedback_at: null,
    }];
  }
  if(alreadyEmitted){
    // INTRA-BATCH DEDUP: same logical doc seen earlier in THIS batch -> merge, never duplicate.
    Object.assign(out[outIndexById[sid]].json, clean);
  } else {
    outIndexById[sid]=out.length;
    out.push({json:clean});
    register(id, clean);   // so later identical rows in this same batch resolve to this id
  }
}
var $__out = out;
// [tenant-carry 2026-08-31] THE BATCH'S TENANT SURVIVES THIS NODE. \`clean\` drops __instance so it
// never lands in updateKeys, but 'Build Bulk Upsert SQL' resolves its SCHEMA from the FIRST ITEM
// it receives -- which is this node's output. Dropping the field here left that resolver blind and
// every UPSERT died on the cutover throw (measured: exec 3735797, 21 items in with __instance,
// 0 out with it). One API call is one instance's batch (the resolver's own contract), so the
// tenant is read once from the incoming rows and re-stamped on every emitted item; the SQL
// builder's SKIP set already keeps it out of the column list.
var __TENANT = (function () { for (var i = 0; i < incoming.length; i++) { var v = incoming[i] && incoming[i].__instance; if (v !== undefined && v !== null && v !== '') return v; } return undefined; })();
// [control-keys 2026-08-13] CONTROL KEYS STRIPPED AT THE WRITE BOUNDARY.
// \`unlock\` is a flag the state-machine builders stamp so indox api knows to release the doc_action
// lock; LOCAL_STATUS / AI_STATUS are extractor provenance. None of them are columns on
// incoming_documents, and PG Upsert uses autoMapInputData, so leaving them on the item fails with
// "Column 'unlock' does not exist in selected table". Stripped HERE — after the ids used for the
// unlock have already been collected — so removing them cannot reduce unlock coverage.
return ($__out).map(function (it) {
  var j = Object.assign({}, it.json);
  delete j.unlock; delete j.LOCAL_STATUS; delete j.AI_STATUS; delete j.INLINE_ACTION;
  // [error-key 2026-08-13] n8n attaches its own runtime error object as a lowercase \`error\` key
  // whenever an upstream node continues-on-fail. The column is uppercase "ERROR", so lowercase
  // \`error\` matches nothing and autoMapInputData rejects the whole batch:
  //   NodeOperationError: Column 'error' does not exist in selected table
  // Measured 2026-08-13 00:30-00:40Z: 23 indox api failures in one window, surfaced when the
  // sync retry queue began feeding previously-unreachable mail items into the downloaders.
  // Stripped, not mapped -- this is a nested runtime object, while the real "ERROR" diagnostic
  // string is written explicitly elsewhere (6,143 rows carry one) and must not be clobbered.
  delete j.error; delete j.errorResponse;
  // [column-shape 2026-08-13] ONLY REAL COLUMN NAMES SURVIVE THE WRITE BOUNDARY.
  // PG Upsert uses autoMapInputData, so every key becomes a column and one stray key rejects the
  // WHOLE batch. Three bursts tonight, three different keys: unlock (~23:00), error/errorResponse
  // (00:41), output_filename (02:29-02:32, 110 errors). A deny-list cannot close this.
  // Verified against the live schema: 108 columns, 103 all-UPPERCASE, 5 all-lowercase, 0 mixed-case.
  // So a real column is /^[A-Z0-9_]+$/ or one of the five; everything else is runtime junk
  // regardless of casing (this is what catches camelCase like errorResponse, which a
  // lowercase-only rule missed — my own pre-ship test rejected that first version).
  // [doc_date_norm removed from the allowlist 2026-08-26, owner order] It is a DERIVED column:
  // trigger trg_incdoc_doc_date_norm recomputes it from DOC_DATE on every insert and update, and
  // a direct write to it is discarded (demonstrated live -- set it to '2020-01-01' and the row
  // comes back holding the DOC_DATE-derived value). Carrying it across the write boundary bought
  // nothing and cost plenty: a timestamptz read back through n8n serialises as
  // "2026-05-10T00:00:00.000Z", and 2,036 rows ended up with that string in DOC_DATE itself,
  // which Map Request then truncated to "2026-00Z" and posted to the ERP. Selection owns
  // DOC_DATE and its format; the database derives the rest.
  // [2026-08-28] 'סימון כרטסת עדכנית' dropped: a Sheets-era marker, 0 non-null of 25,982 rows.
  var __COL_OK = { created_at:1, updated_at:1, priority_sync:1 };
  for (var __k in j) {
    if (!Object.prototype.hasOwnProperty.call(j, __k)) continue;
    if (__COL_OK[__k]) continue;
    if (!/^[A-Z0-9_]+$/.test(__k)) delete j[__k];
  }
  // [tenant-carry 2026-08-31] Stamped AFTER the column filter -- __instance fails the
  // uppercase test and would be deleted by the loop above. It is not a column: 'Build Bulk
  // Upsert SQL' reads it for the SCHEMA and its SKIP set keeps it out of the column list.
  if (__TENANT !== undefined) j.__instance = __TENANT;
  return { json: j };
});`,
    };

    @node({
        id: 'api-bulk-upsert-build-01',
        name: 'Build Bulk Upsert SQL',
        /*__n8n__*/ notes: "[bulk upsert 2026-08-17, owner order] The API call was always batched (one call per action group) but the old 'PG Upsert' node (operation:upsert) wrote ONE STATEMENT PER ITEM — measured 0.77s/row, 996s for a 1,300-row OLD group, the whole cycle's dominant wall. This node groups the batch by field-shape (each action's Build emits one shape, so 1-3 shapes per call) and emits ONE INSERT..ON CONFLICT DO UPDATE statement per shape via jsonb_array_elements — same match-on-ID semantics, one round-trip instead of 1,300. Casts come from the live information_schema map (non-text columns only); updated_at is owned by trg_incdoc_touch and is never written. [content-twin guard 2026-08-17] A NEW ID carrying a HASH that already belongs to another doc used to abort the whole statement on uq_incdoc_hash (pre-existed in the old per-row node too: execs 3365596/3367253/3367904 died the same way at 10:51-12:02, batch only widened the blast). Now: in-batch twins dedupe in JS, table-level twins skip via NOT EXISTS mirroring the partial-index predicate — the DO NOTHING semantics schema.sql P0a documents. Same-ID-twice merges last-wins (one INSERT may not touch a row twice).",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [400, 128],
    })
    BuildBulkUpsertSql = {
        jsCode: `// Group items by their exact key-set; one bulk statement per shape.
// EVERY non-text column MUST be listed. The payload arrives as jsonb and each value is read with
// ->> , which yields TEXT; without a cast Postgres refuses with "column is of type X but
// expression is of type text ... You will need to rewrite or cast the expression" and the whole
// batch fails. Adding a typed column to the table therefore means adding it HERE too -- I missed
// exactly that on 2026-08-21 when BS_LINK_ROUND (integer) and BS_LINK_DOCUMENTS_AT (timestamptz)
// went in for the continuous-relink work, and every BS link upsert failed until it was added.
const CAST = { ITERATION_COUNT: 'integer', RETRY_COUNT: 'integer', MERGED_AT: 'timestamptz',
  NEXT_RETRY_AT: 'timestamptz', created_at: 'timestamptz',
  MERGE_BATCH_ID: 'uuid', SOURCE_LIST: 'jsonb', priority_sync: 'boolean',
  BS_LINK_DOCUMENTS_AT: 'timestamptz' };
// doc_date_norm is NOT here, and must not be: it is derived by trigger from DOC_DATE, a direct
// write to it is discarded anyway, and letting it cross the boundary is what put ISO timestamps
// into DOC_DATE. It is also filtered out of the payload upstream, in 'Resolve IDs'.
// __instance is a CONTROL field, not a column: it selects the SCHEMA a few lines below and
// incoming_documents has no such column, so an upsert that emitted it would fail outright.
const SKIP = new Set(['updated_at', 'doc_date_norm', '__instance']);
// Same ID twice in one batch: merged last-wins (one INSERT may not touch a row twice).
// Content-twin detection (owner: keep the machinery, the SQL CONSTRAINT is what was removed):
// a second NEW ID carrying an already-seen real HASH in one batch is the same file bytes and
// is dropped first-wins. EXISTING docs always write (updates are never hash-vetoed).
const REALHASH = h => h != null && h !== '' && String(h).toLowerCase() !== 'unknown';
// [schema-per-instance 2026-08-27] The instance's documents live in its own schema; the driver
// stamps "__instance" on every row it emits. 'public' remains the migration fallback (compatibility
// views over the live instance) and disappears with them. Identifier, so pattern-checked rather
// than bound. Read from the first item: one API call is always one instance's batch.
const SCHEMA = (() => { const f = ($input.all()[0] || {}).json || {};
  const s = String(f.__instance || '');
  if (!s) throw new Error('indoxApi01: request carries no __instance. The public fallback was removed 2026-08-28 (cutover step 2); every caller must name its instance. public never meant no tenant, it meant whichever tenant public resolves to.');
  if (!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: ' + s);
  return 'indox_' + s; })();
const byId = new Map();
for (const item of $input.all()) {
  const j = item.json || {};
  if (j.ID == null || j.ID === '') continue;
  const prev = byId.get(j.ID);
  byId.set(j.ID, prev ? Object.assign({}, prev, j) : j);
}
const seenHash = new Map();
let twinsDropped = 0;
const rowsIn = [];
for (const j of byId.values()) {
  if (REALHASH(j.HASH)) {
    const lo = String(j.HASH).toLowerCase();
    const owner = seenHash.get(lo);
    if (owner && owner !== j.ID) { twinsDropped++; continue; }
    seenHash.set(lo, j.ID);
  }
  rowsIn.push(j);
}
const shapes = new Map();
for (const j of rowsIn) {
  const keys = Object.keys(j).filter(k => !SKIP.has(k)).sort();
  const sig = keys.join('\\u0001');
  if (!shapes.has(sig)) shapes.set(sig, { keys, rows: [] });
  const row = {};
  for (const k of keys) row[k] = j[k] === undefined ? null : j[k];
  shapes.get(sig).rows.push(row);
}
const out = [];
for (const { keys, rows } of shapes.values()) {
  const cols = keys.map(k => '"' + k.replace(/"/g, '') + '"');
  const sel = keys.map(k => {
    const c = CAST[k];
    const expr = "(v.j->>'" + k.replace(/'/g, '') + "')";
    return c ? expr + '::' + c : expr;
  });
  // [SOURCE_LIST append-only 2026-08-21] Every other column is last-writer-wins, which is right:
  // one action owns one fact and the state machine serialises them. SOURCE_LIST is the exception
  // -- it is a COLLECTION that two different actions add to. The merge action appends the loser's
  // sources to the winner; the source_feedback action patches one element's completion fields.
  // They take DIFFERENT doc_action locks (the key is <ID>::<ACTION>), so they can run at the same
  // moment on one document, and with EXCLUDED semantics whichever landed second erased the other.
  // Losing the merge's append means a source vanishes and that file can never be filed again;
  // losing feedback's patch means the element reverts, is re-decided, finds its own per-source
  // action name already in ACTION_HISTORY with no restart between, and is parked as DOUBLE ACTION
  // BLOCKED forever. So the merge is the DATABASE's job, at the one write point, rather than each
  // caller's: public.indox_merge_source_list patches by source identity, appends what is new, and
  // KEEPS what the incoming array does not mention. Order is preserved because decide dispatches
  // source_feedback_<i> BY INDEX. See scripts/ops/migrations/2026-08-21_source_list_append_only.sql.
  const updates = keys.filter(k => k !== 'ID')
    .map(k => {
      const q = '"' + k.replace(/"/g, '') + '"';
      return k === 'SOURCE_LIST'
        ? q + ' = public.indox_merge_source_list(' + SCHEMA + '.incoming_documents.' + q + ', EXCLUDED.' + q + ')'
        : q + ' = EXCLUDED.' + q;
    });
  const sql =
    'INSERT INTO ' + SCHEMA + '.incoming_documents (' + cols.join(', ') + ')\\n' +
    'SELECT ' + sel.join(', ') + '\\n' +
    "FROM jsonb_array_elements(replace($1, chr(1), ',')::jsonb) AS v(j)\\n" +
    (updates.length
      ? 'ON CONFLICT ("ID") DO UPDATE SET ' + updates.join(', ')
      : 'ON CONFLICT ("ID") DO NOTHING');
  out.push({ json: { sql, payload: JSON.stringify(rows).replaceAll(',', String.fromCharCode(1)), n: rows.length, twinsDropped } });
}
return out.length ? out : [{ json: { sql: 'SELECT 1', payload: '[]', n: 0 } }];
`,
    };

    @node({
        id: 'api-bulk-upsert-exec-01',
        name: 'PG Bulk Upsert',
        /*__n8n__*/ notes: "One statement per field-shape (1-3 per call). $1 carries the rows as JSON with commas as chr(1) — the postgres node splits queryReplacement on commas; restored inside the SQL, same trick as the router's bracket INSERT.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [656, 128],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    PgBulkUpsert = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryBatching: 'independently',
            queryReplacement: '={{ $json.payload }}',
        },
    };

    @node({
        id: 'api-bulk-upsert-restore-01',
        name: 'Restore Upserted Docs',
        /*__n8n__*/ notes: "The bulk node's output is statement stubs; downstream (API Emit IDs -> API Unlock Doc) needs the per-doc items exactly as the old per-item PG Upsert emitted them. Restore from Resolve IDs.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [912, 128],
    })
    RestoreUpsertedDocs = {
        jsCode: "return $('Resolve IDs').all();",
    };

    @node({
        id: 'bgetall',
        name: 'Build Get All SQL',
        /*__n8n__*/ notes: "GET_ALL used to be a hardcoded whole-table SELECT on 'PG Get All'. It still is when the caller asks for nothing: the legacy query is reproduced exactly (ORDER BY ID, LIMIT 100001, bootstrap row excluded), so every existing GET_ALL caller is unaffected. What this node adds is OPTIONAL paging - keyset (after/cursor, preferred) or offset (page/offset) - so a caller can walk the table 1k at a time instead of materialising all of it in one worker.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-1056, 304],
    })
    BuildGetAllSql = {
        mode: 'runOnceForEachItem',
        jsCode: `// GET_ALL - the whole-table read, now OPTIONALLY paginated.
//
// NO PAGING FIELDS => the legacy query, identical in effect: every row except the bootstrap
// sentinel, ORDER BY "ID", LIMIT 100001 (CAP+1, so 'Guard Get Size' can still tell "exactly at
// the cap" from "overflowed"). Existing callers send no paging fields and see no change at all -
// not in the rows, not in the item count, not in the shape.
//
// Optional request fields:
//   limit | pageSize   rows per page, 1..100000. PRESENCE OF THIS TURNS PAGING ON.
//   after | cursor     KEYSET cursor - the last "ID" you were given. Returns the rows AFTER it.
//                      PREFERRED: cost is O(limit) however deep you page, and a page is defined
//                      by data rather than by position.
//   page  | pageIndex  0-BASED offset page; offset = page * limit. Requires limit.
//   offset             explicit row offset; wins over page. Requires limit.
//   order              'asc' (default) or 'desc', on "ID".
//   withTotal          true -> every row of the page carries the WHOLE-TABLE row count (bootstrap
//                      row excluded), which 'Page Get All' lifts into the page envelope as total
//                      and strips back off the rows. Deliberately independent of the cursor and
//                      of the offset, so it is the same number on every page and a caller can
//                      divide it by limit to get a page count. It costs one extra aggregate scan
//                      per page, hence opt-in.
//                      (A window count(*) over() would be WRONG here: under a keyset cursor the
//                      filtered set is only the rows AFTER the cursor, so it shrinks page by page
//                      and reports 999 on the last page of a 39,000-row table.)
//
// after/cursor and page/offset are MUTUALLY EXCLUSIVE. A caller that sends both does not know
// which one it means, and quietly honouring one of them is exactly how a pager skips rows.
//
// WHY KEYSET IS THE ADVICE - CORRECTNESS: this corpus grows continuously (~355 rows/hr when the
// caps were last raised). Under OFFSET, every insert below the offset shifts the window and a row
// slides across a page boundary - returned twice, or never. Keyset on the primary key cannot do
// that. Its own honest trade: rows inserted with an "ID" BELOW the cursor mid-sweep are not seen
// by THIS sweep (the next one picks them up); rows above it are.
//
// WHY KEYSET IS THE ADVICE - COST, measured on this table at 38,999 rows (EXPLAIN ANALYZE):
//   keyset  ("ID" > cursor, limit 1001)   Index Scan using incoming_documents_pkey  ->   1.0 ms
//   offset  (limit 1001 offset 37000)     Parallel Seq Scan + external merge Sort
//                                         spilling 19-25 MB to DISK per worker      -> 389.0 ms
// The offset plan pays that on EVERY page, because OFFSET still has to produce and discard the
// rows it skips. "ID" is the primary key (unique btree), which is what makes the keyset plan an
// index scan and what makes a page boundary unambiguous - a non-unique sort key would let rows
// sharing a value straddle the boundary and be dropped.
const j = $json;

// The unpaginated ceiling. CAP+1 is selected on purpose - see 'Guard Get Size'.
const HARD_CAP = 100000;

const num = (v, what) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  if (!Number.isInteger(n)) throw new Error('GET_ALL: ' + what + ' must be a whole number, got ' + JSON.stringify(v));
  return n;
};

const limit  = num(j.limit !== undefined ? j.limit : j.pageSize, 'limit');
const page   = num(j.page  !== undefined ? j.page  : j.pageIndex, 'page');
const offRaw = num(j.offset, 'offset');
const curRaw = j.after !== undefined ? j.after : j.cursor;
const after  = (curRaw === null || curRaw === undefined || curRaw === '') ? null : String(curRaw);
const desc   = String(j.order || 'asc').toLowerCase() === 'desc';
const withTotal = j.withTotal === true || j.withTotal === 'true';

if (limit !== null && (limit < 1 || limit > HARD_CAP)) {
  throw new Error('GET_ALL: limit must be between 1 and ' + HARD_CAP + ', got ' + limit);
}
if (page !== null && page < 0) throw new Error('GET_ALL: page is 0-based and cannot be negative, got ' + page);
if (offRaw !== null && offRaw < 0) throw new Error('GET_ALL: offset cannot be negative, got ' + offRaw);
if ((page !== null || offRaw !== null) && limit === null) {
  throw new Error('GET_ALL: page/offset need an explicit limit - without one the "page" is the whole table.');
}
if (after !== null && (page !== null || offRaw !== null)) {
  throw new Error('GET_ALL: after/cursor and page/offset are mutually exclusive. Choose keyset (after) or offset (page/offset).');
}

const offset = offRaw !== null ? offRaw : (page !== null ? page * limit : null);
const paginated = limit !== null || after !== null;

// The bootstrap exclusion goes through a bound parameter rather than a SQL literal, so this
// builder never hand-quotes anything into the statement.
const params = ['__bootstrap__'];
let where = '"ID" <> $1';
if (after !== null) {
  params.push(after);
  where += ' and "ID" ' + (desc ? '<' : '>') + ' $' + params.length;
}

// Over-fetch exactly one row. That extra row is the ONLY honest evidence that another page
// exists: "I received exactly limit rows" cannot distinguish a full last page from a truncated
// one, and a pager that guesses drops the tail of the table.
const take = (limit === null ? HARD_CAP : limit) + 1;
// [schema-per-instance 2026-08-27] 'public' is the migration fallback (compat views over the live
// instance), not a default instance; it goes when the views do. Identifier, so pattern-checked.
const SCHEMA = (() => { let f = {}; try { f = $json || {}; } catch (e) {}
  if (!f.__instance) { try { f = ($input.all()[0] || {}).json || {}; } catch (e) {} }
  const s = String(f.__instance || '');
  if (!s) throw new Error('indoxApi01: request carries no __instance. The public fallback was removed 2026-08-28 (cutover step 2); every caller must name its instance. public never meant no tenant, it meant whichever tenant public resolves to.');
  if (!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: ' + s);
  return 'indox_' + s; })();
const sel  = withTotal
  ? 'select *, (select count(*) from ' + SCHEMA + '.incoming_documents where "ID" <> $1) as "_total"'
  : 'select *';
const sql  = sel + ' from ' + SCHEMA + '.incoming_documents where ' + where +
             ' order by "ID" ' + (desc ? 'desc' : 'asc') +
             ' limit ' + take + (offset ? ' offset ' + offset : '');

return { json: { sql, params, _page: { paginated, limit, offset, page, after, order: desc ? 'desc' : 'asc', withTotal } } };
`,
    };

    @node({
        id: 'pgall',
        name: 'PG Get All',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-880, 304],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    PgGetAll = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryReplacement: '={{ $json.params }}',
        },
    };

    @node({
        id: 'pgallpage',
        name: 'Page Get All',
        /*__n8n__*/ notes: "Trims the over-fetched sentinel row and appends the page envelope. A NO-OP for an unpaginated GET_ALL - it returns its input untouched - which is what keeps every pre-existing caller (zzDecideSweep01, the action lanes, any manual GET_ALL) byte-identical. Only a caller that asked for a page gets the extra trailing envelope item. CAVEAT: paging is defined for a SINGLE request item. 'Build Get All SQL' runs once per input item (that is how the legacy behaviour of N items => N whole-table reads is preserved), so if a caller sends several paginated items at once the rows of all of them arrive together and the envelope describes only the first.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-624, 304],
    })
    PageGetAll = {
        jsCode: `// Page trimming + the page envelope.
//
// LEGACY IS UNTOUCHED: if 'Build Get All SQL' did not paginate, this returns $input.all() as-is -
// no trailing item, no key added or removed, same count. Existing GET_ALL callers cannot tell
// this node exists.
//
// A PAGINATED call gets its rows plus ONE extra trailing item, the page envelope:
//   { _indoxApi:'GET_ALL_PAGE', mode:'keyset'|'offset', order, limit, count, hasMore,
//     after, offset, page, nextCursor, nextOffset, nextPage, total }
// Loop by feeding nextCursor back as after (or nextOffset back as offset) until hasMore is false.
// hasMore is DERIVED from the over-fetched row, never guessed from the count. total is the
// whole-table count (same on every page, cursor-independent), null unless withTotal was
// requested and null on a page that returned no rows.
const cfg = (() => { try { return ($('Build Get All SQL').first().json || {})._page || {}; } catch (e) { return {}; } })();
const items = $input.all();
if (!cfg.paginated) return items;

// alwaysOutputData upstream hands us one empty placeholder item on a legitimate 0-row page.
const rows = items.filter(i => i && i.json && Object.keys(i.json).length);
const limit = (cfg.limit === null || cfg.limit === undefined) ? rows.length : cfg.limit;
const hasMore = rows.length > limit;
const kept = hasMore ? rows.slice(0, limit) : rows;

// withTotal rides along on every row; lift it into the envelope and take it back off the rows, so
// a paged row is shape-identical to an unpaged one.
let total = null;
for (const r of kept) {
  if (r.json._total !== undefined) {
    if (total === null) total = Number(r.json._total);
    delete r.json._total;
  }
}

const isOffset = cfg.offset !== null && cfg.offset !== undefined;
const lastId = kept.length ? String(kept[kept.length - 1].json.ID) : null;
return kept.concat([{ json: {
  _indoxApi: 'GET_ALL_PAGE',
  mode: isOffset ? 'offset' : 'keyset',
  order: cfg.order || 'asc',
  limit: cfg.limit === undefined ? null : cfg.limit,
  count: kept.length,
  hasMore,
  after: cfg.after === undefined ? null : cfg.after,
  offset: isOffset ? cfg.offset : null,
  page: cfg.page === undefined ? null : cfg.page,
  nextCursor: hasMore ? lastId : null,
  nextOffset: (isOffset && hasMore) ? cfg.offset + kept.length : null,
  nextPage: (isOffset && hasMore && cfg.page !== null && cfg.page !== undefined) ? cfg.page + 1 : null,
  total,
} }]);
`,
    };

    @node({
        id: 'bget',
        name: 'Build Get SQL',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-880, 480],
    })
    BuildGetSql = {
        mode: 'runOnceForEachItem',
        jsCode: `// GET — bounded, parameterized lookup. Accepts, in precedence order:
//   j.ids     'a,b,c'                 -> "ID" = any(...)
//   j.filters [{COL:val},...]         -> OR of AND-groups (BATCH lookup; added 2026-07-17)
//   j.filter  {COL: val|{op,value}}   -> single AND-group
//   j.ID      scalar                  -> "ID" = $1
//
// WHY j.filters exists: callers used to ask GET_ALL and match in JS. That shipped every row of
// incoming_documents into the worker (45,839 rows / 37MB raw -> hundreds of MB of JS objects, copied
// again at each executeWorkflow boundary) and reliably blew the 1536MB worker heap. j.filters pushes
// the caller's N lookups down into ONE bounded query.
//
// Only whitelisted columns become SQL predicates. A caller key that is not whitelisted is simply not
// pushed down — the caller's own matcher re-applies the FULL query to the rows we return, so a
// partially-pushed-down group is always a SUPERSET of the true match set. Same answer, bounded input.
const j = $json;
const COLS = new Set(['ID','TYPE','STATUS','NAME','LINK','HASH','COMPANY_ID','COMPANY_NAME',
  'DOC_ID','SHORT_DOC_ID','SOURCE_TYPE','SOURCE_ID','SOURCE_LINK','REQUIRED_ACTION',
  'SYNC_NAME','AI_TYPE','INVOICE_ID','PURCHASE_ID','SHIPMENT_DOC_ID','API_TOOLS_ID']);
const CAP = 100000;                     // matches 'Guard Get Size'. Was 5000 while the guard
// was raised 5000 -> 20000 (2026-08-05) -> 100000 (2026-08-11); this one was left behind on the
// assumption that the narrow GET is 'scoped to one caller batch'. The driver broke that: it asks
// for its ENTIRE lane allocation in one GET (39,029/4 = 9,757 ids at scale 4), so the query was
// silently clamped to CAP+1 = 5001 rows and half of every lane was never fetched, never decided,
// never acted on. Measured 2026-08-19 on all four lanes of the full-table cycle.
const q = c => '"' + String(c).replace(/"/g, '""') + '"';
const bad = v => v === null || v === undefined || v === '';
const params = [];
let where = '1=1';

// [no silent truncation 2026-08-19] The query below selects CAP+1 rows so overflow is detectable,
// but the only node that checked was 'Guard Get Size' -- against its OWN, different constant. A narrow
// GET returning CAP+1 could therefore never trip a 100000 guard, and the caller got a silent sample.
// Refuse here instead, where both the cap and the request size are known. Raising CAP without this
// only moves the cliff and keeps it quiet.
// [schema-per-instance 2026-08-27] see the note on Build Get All SQL — 'public' is the migration
// fallback, not a default instance, and it goes when the compatibility views do.
// GET IS BATCH-SHAPED, so the instance can legitimately arrive PER ROW rather than at the top
// level: indoxV2Driver01 sends filters:[{ID:...,__instance:'hacohen'},...]. Reading only the top
// level made a fully-migrated, correctly tenant-aware caller fail closed -- the same class of
// mistake as conflating "instance" with "__instance" earlier today: right rule, wrong field.
// Lift it from the rows when they AGREE. Rows that disagree are a genuinely unsafe request (one
// SQL statement, one schema) and still refuse.
let __inst = String((j || {}).__instance || '');
if (!__inst && Array.isArray(j.filters)) {
  const vals = [];
  for (const r of j.filters) {
    const v = String(((r || {}).__instance) || '');
    if (v && vals.indexOf(v) < 0) vals.push(v);
  }
  if (vals.length === 1) { __inst = vals[0]; }
  else if (vals.length > 1) {
    throw new Error('indoxApi01 GET: filters name MORE THAN ONE instance (' + vals.join(', ') +
      '). One statement reads one schema, so this cannot be served -- split the batch per instance.');
  }
}
const SCHEMA = (() => { const s = __inst;
  if (!s) throw new Error('indoxApi01: request carries no __instance, at the top level or on any filter row. The public fallback was removed 2026-08-28 (cutover step 2); every caller must name its instance. public never meant no tenant, it meant whichever tenant public resolves to.');
  if (!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: ' + s);
  return 'indox_' + s; })();
const __requested = j.ids ? String(j.ids).split(',').filter(Boolean).length
                  : (Array.isArray(j.filters) ? j.filters.length : 0);
if (__requested > CAP) {
  throw new Error('GET: ' + __requested + ' lookups exceeds CAP ' + CAP +
    '. Refusing to silently truncate - the caller must chunk its request.');
}

if (j.ids) {
  params.push(j.ids);
  where = q('ID') + ' = any(string_to_array($' + params.length + ", ','))";
} else if (Array.isArray(j.filters) && j.filters.length) {
  const groups = [], seen = new Set();
  for (const g of j.filters) {
    if (!g || typeof g !== 'object') continue;
    // Resolve the (column, value) pairs FIRST so the dedupe signature is about the DATA, not about
    // which $n the params happened to land on. (Signing the rendered '$n' text meant every group was
    // unique and the dedupe silently never fired.)
    const pairs = [];
    for (const [k, v] of Object.entries(g)) {
      if (bad(v) || !COLS.has(k)) continue;
      pairs.push([k, String(v)]);
    }
    // A group with nothing to push down would select the whole table — the exact thing that OOM'd us.
    // Refuse it loudly; a caller that genuinely means "everything" must say GET_ALL.
    if (!pairs.length) {
      throw new Error('GET: filter group has no filterable column: ' + JSON.stringify(g) +
                      '. Use GET_ALL if the whole table is really intended.');
    }
    pairs.sort((a, b) => a[0] < b[0] ? -1 : 1);
    const sig = JSON.stringify(pairs);
    if (seen.has(sig)) continue;                       // identical group -> one predicate is enough
    seen.add(sig);
    const parts = pairs.map(([k, v]) => { params.push(v); return q(k) + '::text = $' + params.length; });
    groups.push('(' + parts.join(' AND ') + ')');
  }
  if (!groups.length) return { json: { sql: 'select * from ' + SCHEMA + '.incoming_documents where false', params: [] } };
  where = groups.join(' OR ');
} else if (j.filter && typeof j.filter === 'object' && Object.keys(j.filter).length) {
  const parts = [];
  for (const [k, v] of Object.entries(j.filter)) {
    if (v && typeof v === 'object' && v.op) {
      const val = v.value;
      if (v.op === 'in') { params.push(Array.isArray(val) ? val.join(',') : val); parts.push(q(k) + ' = any(string_to_array($' + params.length + ", ','))"); }
      else if (v.op === 'contains') { params.push(val); parts.push(q(k) + ' ILIKE $' + params.length); }
      else { const m = { eq: '=', neq: '<>', gt: '>', gte: '>=', lt: '<', lte: '<=', like: 'like', ilike: 'ilike' }[v.op] || '='; params.push(val); parts.push(q(k) + ' ' + m + ' $' + params.length); }
    } else { params.push(v); parts.push(q(k) + ' = $' + params.length); }
  }
  where = parts.join(' AND ');
} else if (j.ID) {
  params.push(j.ID);
  where = q('ID') + ' = $' + params.length;
}

// CAP+1 so 'Guard Get Size' can tell "exactly at the cap" from "overflowed" and fail loudly rather
// than silently truncating.
// [null-strip 2026-08-20, owner order] Rows come back as ONE json column ('_row') with
// null-valued keys removed, instead of a 112-column tabular result. Measured on 10k real
// rows: 45 MB -> 36 MB (-20%), because the average row carries 50.5 NULLs of 112 columns
// and every one of them costs '"COLUMN_NAME":null' on the wire and again at every
// executeWorkflow hop. Nulls are free in Postgres (null bitmap) and cost only once
// serialised. 'Guard Get Size' unwraps _row back to the flat shape callers expect.
//
// THE ONE SEMANTIC CHANGE, stated plainly: stripping removes the KEY, so a null column
// arrives as UNDEFINED rather than as null. Every consumer that reads a value is unaffected
// (j.FOO is falsy either way, and the callers guard with bad()/COALESCE), but a consumer
// that tests for the KEY is not. Exactly one existed -- indoxV2Driver01 :: 'If NOT UNDEFINED
// NAME' ({{ $json.NAME === undefined }}) -- and it failed 7 rows of one 2,000-row batch on
// 2026-08-20 because 194 documents legitimately carry NAME null. That node is DISABLED as of
// this change (owner order), which is what makes this safe. Before adding any new key-presence
// test on a row column, remember it will be reading a stripped payload.
//
// json_ (not jsonb_): jsonb re-sorts keys, json keeps column order, so the payload reads the
// same as before. Cost measured at 670ms for 10k rows -- the DB was never the bottleneck.
const sql = 'select json_strip_nulls(row_to_json(incoming_documents)) as _row from ' + SCHEMA + '.incoming_documents where (' + where + ") and \\"ID\\" <> '__bootstrap__' limit " + (CAP + 1);
return { json: { sql, params, _cap: CAP } };
`,
    };

    @node({
        id: 'pgget',
        name: 'PG Get',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-624, 480],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    PgGet = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryReplacement: '={{ $json.params }}',
        },
    };

    @node({
        id: 'pgdel',
        name: 'PG Delete',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-880, 656],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    PgDelete = {
        operation: 'executeQuery',
        query: '={{ (() => { const i = String($json.__instance || ""); if (!i) { throw new Error("indoxApi01: request carries no __instance. The public fallback was removed 2026-08-28 (cutover step 2); every caller must name its instance. public never meant no tenant, it meant whichever tenant public resolves to."); } if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error("bad __instance: " + i); } return "delete from indox_" + i + ".incoming_documents where \\"ID\\" = any(string_to_array($1, \',\')) returning \\"ID\\""; })() }}',
        options: {
            queryReplacement: '={{ $json.ids || $json.ID }}',
        },
    };

    @node({
        id: 'btg',
        name: 'Build Table Get',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-880, 832],
    })
    BuildTableGet = {
        mode: 'runOnceForEachItem',
        jsCode: `// The read chokepoint for INDOX's config tables — and, since phase 6, the place tenancy is enforced.
//
// \`settings\`, \`companies\` and \`tag_rules\` carry an \`instance\` discriminator. The one failure mode of
// that design is a FORGOTTEN predicate: the query still succeeds, it just quietly returns another
// client's configuration. Nothing at the call site looks wrong. So the gate throws rather than
// defaulting — a gate that defaults is a gate that hides the bug it exists to catch.
//
// \`instance:'*'\` is the deliberate exception, for the one caller that legitimately reads ACROSS
// instances: the scanner, which must see every instance's registry in order to fan out to them. It
// is spelled explicitly so that reading everything is a decision in the caller, never an accident.
//
// ai_extraction_cache and trusted_suppliers are NOT instance-scoped, on purpose: they are keyed by
// content hash, and the same supplier PDF arriving at two clients should be OCR'd once.
const ALLOW={ai_extraction_cache:1,tag_rules:1,settings:1,companies:1,trusted_suppliers:1};
const INSTANCE={settings:1,companies:1,tag_rules:1};
const j=$json; const t=String(j.table||''); if(!ALLOW[t]) throw new Error('table not allowed: '+t);
const inst=(j.instance===undefined||j.instance===null)?'':String(j.instance);
if(INSTANCE[t] && !inst) throw new Error('read of public.'+t+" needs an \`instance\` (or instance:'*' to read across all of them) — without one this returns another instance's config");
// [schema-per-instance 2026-08-27] The instance's data lives in its own schema. A caller that
// knows which instance it is acting for passes \`__instance\` (the instance id, e.g. 'hacohen' —
// NOT the schema); anything that does not yet falls back
// to \`public\`, where compatibility VIEWS point at the live instance. That fallback is scaffolding
// for the migration, not a default instance — it disappears with the views in the same change that
// makes every caller pass \`__instance\`, and after that an absent instance must be an error.
// Identifier, not a parameter: it cannot be bound, so it is pattern-checked instead of quoted.
// [shared tables 2026-08-28, owner decision] ai_extraction_cache is SHARED, keyed by content hash
// so one supplier PDF is OCR'd once across clients — it lives in public and is never
// schema-qualified. This is the table the comment above already described as non-instance; the
// schema cutover had wrongly moved it into the instance.
const SHARED={ai_extraction_cache:1};
// BATCH LIFT (2026-08-28). The instance can legitimately arrive PER ROW on a batch-shaped
// request, not only at the top level. Reading only the top level is what made Build Get SQL
// reject a fully migrated, correctly tenant-aware caller: right rule, wrong field. Accept rows
// that AGREE; refuse rows that disagree, because one statement touches one schema and picking
// one silently is the failure this whole cutover exists to remove.
let __inst=String(j.__instance||'');
if(!__inst){
  const __rows=[].concat(Array.isArray(j.rows)?j.rows:[], Array.isArray(j.filters)?j.filters:[]);
  const __v=[];
  for(const r of __rows){ const v=String((r||{}).__instance||''); if(v && __v.indexOf(v)<0) __v.push(v); }
  if(__v.length===1){ __inst=__v[0]; }
  else if(__v.length>1){ throw new Error('indoxApi01: batch names more than one instance ('+__v.join(', ')+'); one statement touches one schema, so split the batch per instance.'); }
}
const SCHEMA=(()=>{ if(SHARED[t]) return 'public';
  const s=__inst;
  if(!s) throw new Error('indoxApi01: request carries no __instance (public fallback removed 2026-08-28, cutover step 2). Note the SHARED[t] check above still returns public for genuinely global tables -- reaching this line means a PER-INSTANCE table was asked for without naming an instance.');
  if(!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: '+s);
  return 'indox_'+s; })();
const params=[]; let where='1=1'; const q=c=>'"'+String(c).replace(/"/g,'""')+'"';
const parts=[];
if(INSTANCE[t] && inst!=='*'){ params.push(inst); parts.push(q('instance')+' = $'+params.length); }
if(j.filter && typeof j.filter==='object'){ for(const [k,v] of Object.entries(j.filter)){ params.push(v); parts.push(q(k)+' = $'+params.length);} }
if(parts.length) where=parts.join(' AND ');
return {json:{sql:'select * from '+SCHEMA+'.'+t+' where '+where, params}};`,
    };

    @node({
        id: 'ptg',
        name: 'PG Table Get',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-624, 832],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    PgTableGet = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryReplacement: '={{ $json.params }}',
        },
    };

    @node({
        id: 'btu',
        name: 'Build Table Upsert',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-880, 1008],
    })
    BuildTableUpsert = {
        mode: 'runOnceForEachItem',
        jsCode: `// The write chokepoint. Same tenancy argument as Build Table Get, one degree more dangerous: a
// write without an \`instance\` does not merely read the wrong client's config, it OVERWRITES it.
// Under the (instance, key) primary key an absent instance falls to the column default, so the row
// lands on the first instance — silently, and with a success response.
//
// The conflict target has to widen with the key, or \`on conflict ("key")\` names a constraint that
// no longer exists and every upsert fails at runtime instead of merging.
const ALLOW={ai_extraction_cache:['cache_key'],tag_rules:['id'],settings:['instance','key'],companies:['instance','מזהה 1'],trusted_suppliers:null};
const INSTANCE={settings:1,companies:1,tag_rules:1};
// __null: the columns this write must actively CLEAR, as opposed to leave alone (2026-08-06).
// Everything else here is "send a column and it is written; omit it and it keeps its old value",
// which has no way to say "set this back to nothing". That gap served STALE DATA AS CURRENT:
// syncV3Main0001's start stamp could not clear \`run_finished_at\` / \`last_result\`, so a row read
// \`run_status='running'\` next to the PREVIOUS pass's finish time and result. It never reached a
// screen only because RunProgress.tsx happens not to render last_result while running — an accident
// of one consumer, not a guarantee, and every new reader of /sync/runs would have inherited it.
// Values already travel as bound parameters ($1..$n), so a cleared column is just a null param;
// this only has to stop the \`!==null\` filter below from dropping the column entirely.
const j={...$json}; const t=String(j.table||''); if(!(t in ALLOW)) throw new Error('table not allowed: '+t);
const clear=Array.isArray(j.__null)?j.__null.map(String):[]; delete j.__null;
// __if_absent: SEED SEMANTICS -- create the row when it does not exist, never re-assert it when it
// does (2026-08-27). Default stays DO UPDATE so every existing caller is unchanged; only a seeder
// opts in. Added after indoxV2TestFixtures01 re-asserted 47 fixture keys over live values and
// flipped indox.actions.priority_sync.local back to 'true', routing a client's documents to the
// local stand-in for 213 documents. An allowlist of keys to PROTECT had already been extended twice
// after incidents and was still incomplete; inverting the default is the fix that cannot fall
// behind. NOTE: with DO NOTHING the \`returning *\` yields no row when one already existed -- a
// caller using this flag must treat "no row back" as "already present", not as failure.
const ifAbsent = j.__if_absent === true || j.__if_absent === 'true'; delete j.__if_absent;
// [schema-per-instance 2026-08-27] See the same note on Build Table Get. \`public\` is the
// migration's compatibility fallback (views over the live instance), NOT a default instance;
// it goes away with the views once every caller passes \`__instance\`, and an absent instance becomes
// an error at that point. Identifier, so pattern-checked rather than bound as a parameter.
// [shared tables 2026-08-28, owner decision] ai_extraction_cache is SHARED across instances, not
// per-instance — it is keyed by content hash, so the same supplier PDF arriving at two clients is
// OCR'd once. It lives in public and must NEVER be schema-qualified; doing so would address a
// table that does not exist in the instance schema. This restores the intent already stated in
// Build Table Get's own comment, which the schema cutover had contradicted.
const SHARED={ai_extraction_cache:1};
// BATCH LIFT (2026-08-28). The instance can legitimately arrive PER ROW on a batch-shaped
// request, not only at the top level. Reading only the top level is what made Build Get SQL
// reject a fully migrated, correctly tenant-aware caller: right rule, wrong field. Accept rows
// that AGREE; refuse rows that disagree, because one statement touches one schema and picking
// one silently is the failure this whole cutover exists to remove.
let __inst=String(j.__instance||'');
if(!__inst){
  const __rows=[].concat(Array.isArray(j.rows)?j.rows:[], Array.isArray(j.filters)?j.filters:[]);
  const __v=[];
  for(const r of __rows){ const v=String((r||{}).__instance||''); if(v && __v.indexOf(v)<0) __v.push(v); }
  if(__v.length===1){ __inst=__v[0]; }
  else if(__v.length>1){ throw new Error('indoxApi01: batch names more than one instance ('+__v.join(', ')+'); one statement touches one schema, so split the batch per instance.'); }
}
const SCHEMA=(()=>{ if(SHARED[t]) return 'public';
  const s=__inst;
  if(!s) throw new Error('indoxApi01: request carries no __instance (public fallback removed 2026-08-28, cutover step 2). Note the SHARED[t] check above still returns public for genuinely global tables -- reaching this line means a PER-INSTANCE table was asked for without naming an instance.');
  if(!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: '+s);
  return 'indox_'+s; })();
delete j.__instance;
if(INSTANCE[t] && !String(j.instance||'')) throw new Error('write to public.'+t+' carries no \`instance\` — it would land on the default instance and overwrite another client\\'s configuration');
const conflict=ALLOW[t]; delete j.table; delete j.INLINE_ACTION;
// A cleared column may not be part of the conflict target: nulling a key component would either
// fail the upsert or match a different row. Loud, because a silent skip here is the same class of
// bug the marker was added to fix.
const badClear=clear.filter(c=>(conflict||[]).indexOf(c)>=0);
if(badClear.length) throw new Error('__null may not clear a conflict-target column: '+badClear.join(', '));
// __instance excluded: schema selector, not a column.
const cols=Object.keys(j).filter(k=>k!=='__instance'&&j[k]!==null&&j[k]!==undefined).concat(clear.filter(c=>!(c in j)));
const q=c=>'"'+String(c).replace(/"/g,'""')+'"';
// \`typeof null === 'object'\`, so the null check has to come FIRST or a cleared column would be
// written as the four-character string "null".
const params=cols.map(c=>{ if(!(c in j)) return null; const v=j[c];
  return (v!==null && typeof v==='object') ? JSON.stringify(v) : v; });
const ph=cols.map((_,i)=>'$'+(i+1));
let sql='insert into '+SCHEMA+'.'+t+' ('+cols.map(q).join(',')+') values ('+ph.join(',')+')';
if(conflict && conflict.length){ const ck=conflict.map(q).join(',');
  if(ifAbsent){ sql+=' on conflict ('+ck+') do nothing'; }
  else { const upd=cols.filter(c=>conflict.indexOf(c)<0).map(c=>q(c)+'=excluded.'+q(c)).join(', ');
    sql+=' on conflict ('+ck+') do update set '+(upd||q(conflict[0])+'=excluded.'+q(conflict[0])); } }
else if(ifAbsent){ throw new Error('__if_absent needs a conflict target; public.'+t+' has none'); }
sql+=' returning *'; return {json:{sql,params}};`,
    };

    @node({
        id: 'ptu',
        name: 'PG Table Upsert',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-624, 1008],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 3000,
    })
    PgTableUpsert = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryReplacement: '={{ $json.params }}',
        },
    };

    @node({
        id: 'kalv',
        name: 'Keepalive',
        /*__n8n__*/ disabled: true,
        type: 'n8n-nodes-base.scheduleTrigger',
        version: 1.2,
        position: [-1680, -288],
    })
    Keepalive = {
        rule: {
            interval: [
                {
                    field: 'hours',
                    hoursInterval: 6,
                },
            ],
        },
    };

    @node({
        id: 'knoop',
        name: 'Keepalive NoOp',
        type: 'n8n-nodes-base.noOp',
        version: 1,
        position: [-1440, -288],
    })
    KeepaliveNoop = {};

    @node({
        id: 'indox-poll-q',
        name: 'Get Changed Docs',
        /*__n8n__*/ notes: "THE BACKOFF GATE (2026-08-07, redrive-loop lane). This node is the ONLY active driver of indoxV2Driver01 (graph-traced: the sole executeWorkflow node in the fleet targeting it, in an active workflow, is this workflow's 'Process Changed Doc'). It therefore decides, alone, whether errorHandler01's 'Backoff + Dead-letter' means anything at all -- and until this clause it read NEITHER \"NEXT_RETRY_AT\" NOR \"RETRY_COUNT\". Two mechanisms in THIS SAME FILE disagreed: 'Terminalize Stalled' already carried `(\"NEXT_RETRY_AT\" is null or \"NEXT_RETRY_AT\" <= now())` and honoured the backoff; the pickup did not, so a scheduled retry was ignored and a dead-lettered document was re-driven anyway. The loop was self-sustaining by construction: trg_incdoc_touch (BEFORE UPDATE) bumps updated_at on EVERY row write, so the dead-letter's own UPDATE put the row back inside `updated_at > now() - interval '150 seconds'` and the next 30s tick picked it up again. Measured live: doc_msi5h17vzra0ds reached RETRY_COUNT=646 and was still in this node's output, eligible via that branch alone; 2 documents produced 242 of 1,707 attributed driver executions (14.2%) in one 6.7h window. NOTE THE ASYMMETRY that makes this clause safe: it can only ever REMOVE rows, never add them, so nothing that is picked up today stops being picked up except while a backoff it already earned is pending -- no wake-up branch was added on purpose, because 169 rows currently carry a stale PAST \"NEXT_RETRY_AT\" (94 of them COMPLETED) and a `NEXT_RETRY_AT <= now()` wake branch would re-drive every one of them every 30s forever, which is the same loop with a new door. `or \"STATUS\" = 'ACTION_RESTART'` keeps the operator Retry button (DocumentDetailPage.tsx: PATCH STATUS -> ACTION_RESTART) working on a dead-lettered document -- one attempt per click, since RETRY_COUNT is already past the threshold and the next failure re-seals it.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [-880, 1536],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 4000,
    })
    GetChangedDocs = {
        operation: 'executeQuery',
        query: `=-- [multi-instance 2026-08-28] Both references below were UNQUALIFIED, so they resolved
-- through search_path to public — invisible to a census that greps for "public.<table>", and they
-- would have broken silently when the compatibility views came down. Schema now resolved from
-- __instance like every other site.
-- [terminal failure set 2026-08-14, cleanup #3b] Seven failure statuses added to the elig
-- exclusion, and \`recov\` trimmed to what may still legitimately be re-driven: DOUBLE (adjudication),
-- ACTION_RESTART (the operator hatch, via s_restart), MISSING_LINK (file discovery still retries --
-- see the drainer's matching note). Everything else is a state-machine verdict and is now terminal
-- in BOTH feeds; re-running one is ACTION_RESTART and nothing else.
-- [terminal-set reconciliation 2026-08-14, cleanup #17] THIS POLL IS THE SECOND FEEDER, AND IT
-- DISAGREED WITH THE DRAINER ABOUT WHAT "TERMINAL" MEANS. indoxV2BaseDrain01 excludes 8 statuses;
-- this node excluded 3. Measured live: PAUSE 34 rows and MAX_ITERATIONS 377 rows were refused by
-- the drainer and still eligible here, so neither verdict actually held.
--   PAUSE          -- operator hold. The 'infinity' note below recommends "a STATUS the pickup
--                     excludes (the PAUSE pattern)" while the pickup did not exclude PAUSE.
--   MAX_ITERATIONS -- the state machine's give-up verdict, re-offered here via \`recov\`, which made
--                     the 5-attempt limit meaningless. ACTION_RESTART still admits the row through
--                     s_restart, so the operator's re-run hatch is unchanged.
-- NOT changed here: s_adj (COMPLETED, pool 21,187) still re-offers finished rows -- low volume in
-- practice (rn*12.0+0.5 against limit 120; measured 8 dispatches / 8 docs / 130 min) but it is the
-- mechanism behind "COMPLETED is not terminal", and it needs its own review, not a blind deletion.
-- [restart lottery 2026-08-12] ACTION_RESTART IS A COMMAND, AND IT WAS BEING RATIONED LIKE A BACKLOG.
--
-- ACTION_RESTART is the operator's "start this document over" — the immediate hatch the
-- decide layer already implements (indoxV2ActionsGDoc01/'Decide GDoc Action' gdocHead returns
-- 'restart_gdoc' the moment it sees the status; the Ship/BS/DOC BASE routers do the same).
-- Nothing downstream was broken. The row simply never arrived.
--
-- WHERE IT WENT. The only two feeders are this poll and indoxV2BaseDrain01, and the drainer
-- lists 'ACTION_RESTART' in the exclusion set of its \`open\` CTE, so this node was the sole
-- path. Here the status is in \`recov\`, which routes it to s_recov: ordered by
-- md5("ID" || epoch/120) — a reshuffle, not a queue — capped at rn <= 120, and then cut again
-- by the global \`limit 120\`.
--
-- MEASURED 2026-08-12 02:0xZ by dry-running THIS query against the live table: s_recov's pool
-- was 1,218 rows and the six documents actually sitting in ACTION_RESTART drew ranks
-- 188 / 475 / 537 / 597 / 606 / 1147. Only ranks <= 120 enter the union at all, and of those
-- roughly 14 survive the global cut, so a given restart had about a 1% chance per poll. At one
-- poll every 5 minutes that is a MEAN WAIT NEAR SEVEN HOURS, and the live evidence matched it
-- exactly: those six rows had been parked 3h, 6h, 7h, 13h, 15h and 2 days 4h, every one of them
-- with ITERATION_COUNT = 0, i.e. never once dispatched since the operator asked.
--
-- s_burst does not save it either. A row's updated_at IS refreshed by the operator's write, but
-- s_burst takes the SIX most recent updates on a pipeline writing thousands of rows an hour, so
-- the restart is out of that window within seconds.
--
-- THE FIX IS A QUEUE, NOT A BIGGER LOTTERY TICKET. s_restart is ordered by updated_at ASC
-- (oldest unanswered command first — deterministic, no md5), and its k of rn - 2000 puts it
-- ahead of every other slice including s_burst, so it is also dispatched FIRST inside the poll's
-- 120 items rather than queued behind them.
--
-- IT CANNOT RUN AWAY WITH THE POLL. rn <= 20 caps it at 20 of the 120 slots, and it only ever
-- claims slots that ACTION_RESTART rows exist to fill (six today, and the status is only ever
-- written by a human). It is self-draining: the restart actions set STATUS='IN_PROGRESS' and
-- clear the completion flags (see 'Build: Call ... - STATUS MISSING_COMPANY_ID' downstream of
-- 'Action: Restart GDOC'), so a row leaves the slice on the same pass that picks it up — there
-- is no re-offer loop. Worst-case latency becomes one poll interval instead of unbounded.
-- [null-status + infinity wall 2026-08-11 P7] TWO POPULATIONS NO SLICE COULD EVER RETURN.
--
-- A. NULL STATUS -- 54 documents, lost to three-valued logic. Eligibility ALREADY admitted
--    them ("STATUS" is null is in the OR-group below, and the exclusion list is written
--    coalesce("STATUS",'') not in (...) so it is null-safe). The DERIVED FLAGS were not:
--        ("STATUS" = 'COMPLETED') as terminal   -> NULL when STATUS IS NULL
--        ("STATUS" in (...))      as recov      -> NULL
--        ("STATUS" = 'DOUBLE' ...) as stamped_double -> NULL
--    Every slice is 'where not terminal and ...', and NOT NULL is NULL, so the row is
--    dropped by the WHERE; s_adj is 'where terminal and not recov', also NULL, also dropped.
--    So NO SLICE COULD RETURN A NULL-STATUS ROW -- admitted by eligibility, then discarded
--    by every consumer of it. VERIFIED on live data 2026-08-11: of the 54,
--    ("STATUS"='COMPLETED') IS NULL for 54/54 and NOT ("STATUS"='COMPLETED') is TRUE for 0/54.
--    Untouched 27 hours; 41 have no ACTION_LOG at all, i.e. never processed since ingest.
--    All 54 have LINK and TYPE, 41 need nothing but base extraction.
--
--    FIX IS coalesce("STATUS",''), WHICH IS THE PATTERN THIS ESTATE ALREADY USES -- the
--    exclusion list on the eligibility line below, and indoxV2TailDrain01's gate, both
--    already write it that way. This brings three stragglers in line with it. For every
--    NON-NULL status the flags are byte-identical ('' <> any status name), so no existing
--    row changes slice, keeps or loses a key. It is purely the NULL case becoming defined.
--    stamped_double is included even though 0 NULL rows carry merge_sig today: it is the
--    same defect one line down, and leaving it is a trap for the next null row.
--
-- B. NEXT_RETRY_AT = 'infinity' -- 65 more, walled by a gate that now has no writer.
--    [free-the-walled P5] above cut ONE hole in this gate, for STATUS='NEEDS_REVIEW', and
--    argued the clause was safe because it "drains a fixed, closed set of rows that no
--    writer can replenish". THAT ARGUMENT IS NOW TRUE FOR EVERY STATUS, not just
--    NEEDS_REVIEW, and it has been re-verified rather than assumed:
--      - PARSED (not grepped) all 90 workflows x {live activeVersionId, draft}: the only
--        real 'infinity' references in the estate are THIS clause reading it, and
--        syncDeliverGmail01/'Split Attachments' using JS Infinity for a byte-size default.
--        No node assigns NEXT_RETRY_AT='infinity' anywhere, active or inactive.
--      - No Postgres function or trigger on incoming_documents mentions it either.
--      - Re-read the full infinity id-set 25 minutes apart across a live pipeline:
--        205 -> 205, ZERO new ids.
--    So 'infinity' is a closed legacy artifact of the pre-P5 dead-letter, and the
--    NEEDS_REVIEW scoping is now the only thing keeping the REST of that same artifact
--    walled. Measured 2026-08-11, the rows it strands: MISSING_COMPANY_ID 41, MISSING_TYPE
--    12, MAX_ITERATIONS 6, API_TOOLS_FAILED 5, EXTRACTION_FAILED 1. Every one of those
--    statuses is already in the recovery set, every one carries RETRY_COUNT >= 5 (they are
--    retry-exhausted, not paced), and all 65 are typed.
--
--    NOT AN UNBOUNDED WIDENING. The live backoff writers set a REAL timestamp
--    (5*3^n minutes) and retire to MAX_ITERATIONS -- see the [de-invent P5] block in
--    indoxV2ActionsGlobal01/'Join COMPANY_NAME' -- so nothing can re-create an infinity
--    row, and this clause empties permanently, exactly as the NEEDS_REVIEW one was
--    designed to. If a future writer ever needs a real park-forever, it should use a
--    STATUS the pickup excludes (the PAUSE pattern), not a sentinel in the pacing column.
--
-- LOAD: none, and this is the same accounting the passes above use. Eligibility widens by
-- 65 rows; the 54 null rows were ALREADY eligible and merely unreachable. Every slice cap
-- (rn <= 120 / rn <= 6) and the overall LIMIT 120 are untouched, so the same 120 dispatches
-- per poll are spread over ~0.6% more candidates. No slice gains or loses a slot.
-- [per-type starvation 2026-08-11] THE BINDING CONSTRAINT WAS A SLICE THAT COULD NOT REACH ITS OWN ROWS.
-- Upload and base are no longer the limit: measured 2026-08-11 06:4xZ, Upload Doc To API TOOLS ran
-- 548/hr and Base Document Extraction 508/hr, both ahead of ~296/hr intake. The three per-type
-- wrappers (InvoiceDocEx01 / ShipmentDocEx01 / BsDocEx01) ran a COMBINED 192/hr against 2,545
-- documents queued for per-type -- a 13-hour drain, and the actual ceiling on COMPLETED (~70/hr).
-- Nothing there is slow: the Gemini extractor behind them does 840/hr at 11.9s, and the wrappers
-- themselves return in 12-15s. They were STARVED OF DISPATCH by this node.
--
-- MEASURED, by dry-running the LIVE query against the live table and bucketing the 120 rows it
-- returns by pipeline stage:
--     await_upload 52 | await_base 20 | await_pertype 20 | await_selection 24 | await_completion 4
-- 20 of 120 slots -- 240/hr offered, 192/hr converted (80%, so the decide gate is NOT the loss) --
-- for the one stage everything else is queueing behind, while 52 slots went to a stage already
-- running 1.9x its own intake.
--
-- ROOT CAUSE, and it is a head-of-line failure of exactly the kind this file has been rewritten
-- four times to remove, reintroduced inside s_recov. 1,658 of the 2,545 per-type-ready documents
-- (65%) carry a recovery STATUS -- 972 NEEDS_REVIEW, 217 MISSING_COMPANY_ID, 102 API_TOOLS_FAILED,
-- 95 MISSING_TYPE -- so \`not recov\` excludes them from s_live/s_stale and s_recov is their ONLY
-- slice. s_recov ordered by \`needs_base desc\` as its PRIMARY key. Its pool is 2,777 rows of which
-- just 34 are needs_base, and its interleave weight (rn*6.0) buys ~16 slots per poll -- so those 34
-- rows sat in front of all 16 slots, every poll, forever. Dry-run of s_recov's top 16: 15
-- await_upload + 1 await_base, ZERO await_pertype. The rn<=120 cap never bound; the weight did.
-- The 34 needs_base rows were being handed ~16 slots/poll -- full coverage every 2.3 polls, for a
-- stage three other slices already serve -- while 1,658 per-type documents got none.
--
-- FIX, three parts, ALL PURE REALLOCATION -- no slice is widened, LIMIT stays 120, the eligibility
-- predicate is BYTE-FOR-BYTE UNCHANGED (only a computed flag is added to elig's select list), so
-- every row eligible before is eligible now and no extra work is dispatched:
--   1. s_recov drops the \`needs_base desc\` key and the needs_base rows, keeping its rn*6.0 share
--      and pure md5 rotation -- its ~16 slots now sweep the 2,743 rows it exists to serve.
--   2. s_recovbase is those 34 needs_base rows, given their own bounded share at rn*24.0 (~3.6
--      slots/poll = full coverage every 10 polls). They are not abandoned, just not privileged.
--   3. s_pertype is the missing slice: every per-type-ready document (uploaded, base done, typed,
--      per-type NOT done, selection NOT done) regardless of STATUS, so it spans BOTH the s_live
--      and the s_recov populations. rn*5.0 + rotation at the 300s poll bucket. Funded by s_new
--      4.0 -> 6.0 and s_old 12.0 -> 14.0, the two slices whose pool is 100% await_upload (6,192
--      of 6,192 rows) -- the stage that was over-served.
--
-- VERIFIED BY DRY-RUN before deploy, same method and same minute as the baseline above:
--     await_upload 32 | await_base 4 | await_pertype 57 | await_selection 21 | await_completion 5
-- per-type 20 -> 57 slots/poll (240 -> 684 offered/hr, ~2.9x). Upload is deliberately left at 32
-- slots (384/hr offered) -- still above the ~296/hr intake, so its backlog keeps draining rather
-- than growing. That headroom is why s_pertype is rn*5.0 and not rn*4.0: rn*4.0 measured 65
-- per-type but pushed upload to 25 slots (300/hr), at/below intake, which would have traded a
-- real regression for a marginal gain.
--
-- s_burst, s_fin, s_finstale, s_live, s_stale and s_adj are untouched, so the cascade and both
-- finisher arms keep their exact behaviour. IF per-type dispatch overshoots what the three
-- wrappers can absorb -- watch bull:jobs:wait -- s_pertype's rn*5.0 is the number to raise, not
-- worker concurrency (pinned at 8, OOM history) and not the poll interval.
-- [P6 2026-08-11] TWO MORE STATUSES THAT NO PICKUP COULD EVER SELECT.
-- The [recovery 2026-08-10] pass above cured exactly this defect for eight statuses and
-- MISSED THESE TWO -- not terminal, not deliberately excluded, simply never named, so they
-- were unreachable BY CONSTRUCTION. Measured 2026-08-11 01:2xZ, with the forward action each
-- row would actually receive computed against the live decide gates:
--   ACTION_REQUIRED  44 rows -- 40 have a live forward action (24 extract_base_doc,
--                     7 figure_company_id, 4 figure_company_offline, 2 base apitools-retry,
--                     3 update_status_missing_company), 4 route on to their type.
--   MISSING_LINK     33 rows -- all linkless, all typed (19 SHIPMENT / 14 INVOICE), none
--                     holding an API_TOOLS_ID. 17 get 'find_link' (Decide GDoc Action line
--                     153: !SEARCH_IN_DRIVE_COMPLETED && SHORT_DOC_ID && COMPANY_NAME), i.e.
--                     a real Drive search that can recover the file. The other 16 have
--                     already been searched and answer 'no_action_link_not_found' -- HONEST
--                     COST, stated rather than hidden: 16 rows of no-op in a 2,216-row slice
--                     (0.7%), too small to earn a fence like \`not stamped_double\`, which
--                     exists for a 168-row case.
--
-- PAUSE (35 rows) IS DELIBERATELY STILL EXCLUDED, and that is not an oversight -- it is the
-- one of the three that must NOT be re-admitted. 'Decide DOC BASE Action' line 164 returns
-- 'no_action_paused' before every forward gate and the router has a dedicated 'No Action:
-- Paused' node, so PAUSE is a designed hold state. The rows confirm it: their ACTION_LOG
-- carries operator markers (manual-drain-20260806, drain_paused_on_oom,
-- drain_parked_for_tranche) and every sampled REQUIRED_ACTION reads "Skipping.. File too big,
-- 10mb max". They were paused BY A HUMAN, on purpose, because they cannot be processed.
-- Re-admitting them would send all 35 straight to extract_base_doc to re-OCR files that
-- exceed the limit -- re-creating the OOM the operator paused them to avoid. An operator
-- un-pauses these, not the pickup.
--
-- LOAD: none. Eligibility widens by 77 rows against an s_recov pool of 2,139 (+3.6%), and the
-- slice's BUDGET is unchanged -- s_recov keeps rn*6.0 and rn <= 120, ~16 of the 120 slots. The
-- same ~16 dispatches per poll are simply spread over 3.6% more candidates, so the pool's
-- full-coverage cycle moves from ~134 to ~139 polls (11.1h -> 11.5h at the live 5-minute
-- trigger). No slice loses a slot and no extra work is dispatched.
-- [fairness 2026-08-10] WHICH 40 DOCUMENTS THE 2-MINUTE POLL PICKS. The width is unchanged --
-- still exactly 40 rows, still the same eligibility predicate, verbatim, in \`elig\` below.
--
-- v1 (01:09 UTC) fixed the first plug: this was \`order by updated_at asc limit 40\`, and
-- updated_at is bumped by every successful step, so the moment a document advanced it was sent
-- to the BACK of a 6,932-row queue behind every never-touched row. A document needs several
-- visits to reach COMPLETED (base -> company/name -> per-type -> selection -> COMPLETED), so
-- once ingestion outran pickup (2026-08-09 ~17:48) no document could ever get its SECOND step.
-- Measured: the 481 rows that had finished base extraction sat at positions 4,659-6,932 while
-- the window advanced ~137 rows/hour. Consequences, all from that one line: COMPLETED/hr -> 0
-- (last stamp 21:15), indoxV2FigureDocType01/indoxV2FigureCompanyId01 -> 0 runs (docBaseDecide
-- only reaches the type/company gates on a visit AFTER base extraction), and every document
-- created today never selected at all -- empty ACTION_LOG, no TYPE, no COMPANY on the owner's
-- dashboard.
--
-- v2 (this version) fixes the SECOND plug, which v1 exposed. The eligibility predicate has a
-- dup-detector arm that admits rows by (COMPANY_ID, DOC_ID) collision regardless of status, and
-- those rows are STATUS='COMPLETED' with the OLDEST updated_at in the whole set (14:33-16:22).
-- Under any oldest-first order they own the front of the queue permanently: 'Decide GDoc Action'
-- answers \`no_action_already_completed\` and writes nothing, so their updated_at never moves and
-- they can never be displaced. Measured at 01:44 UTC: 19 of the top 40 positions -- roughly half
-- the entire pickup budget -- were already-finished documents. Only 42 such rows exist; they are
-- simply perfectly placed. They must still be visited (that is how a double gets adjudicated),
-- but they must not be able to take half the capacity, so they get their own bounded share.
--
-- FOUR SLICES, round-robin by an interleave key, so no class can starve another:
--   s_live : in flight and NOT terminal -- base flag set or any ACTION_LOG history. Finishing a
--            started document is worth more than starting a new one; this is the slice that
--            makes COMPLETED rise.                                         ~1/3 of the budget
--   s_new  : never touched, NEWEST first -- the guarantee that today's arrivals get typed
--            instead of queueing behind more than a day of backlog.        ~1/3
--   s_old  : never touched, oldest first -- the original behaviour, so the backlog still drains
--            in FIFO order and nothing is abandoned.                       ~1/6
--   s_adj  : STATUS='COMPLETED', i.e. admitted only for double adjudication. Bounded.  ~1/6
-- The key is rn*3 / rn*6 + offset, so the slices interleave and a slice with fewer rows than its
-- share yields those slots to the others -- an empty s_live gives the budget back to the
-- untouched slices, i.e. the old behaviour exactly. \`min(k)\` de-duplicates the row that a small
-- untouched pool puts in both s_old and s_new. ORDERING ONLY: every row eligible before is
-- eligible now, and no row is eligible that was not.--
-- [rotation 2026-08-10] TIES ON updated_at WERE STARVING MOST OF THE IN-FLIGHT POOL.
-- updated_at is written per BATCH, not per row: one upsert stamps every row it touched with the
-- same microsecond, and a bulk re-drive stamps hundreds. Measured at 02:05 UTC the live slice held
-- 649 rows across only 28 distinct timestamps, 395 of them sharing 2026-08-09 23:57:27.107392.
-- \`row_number() over (order by updated_at asc)\` puts an ARBITRARY 40 of those 395 in front, and
-- because the plan is stable it is the SAME arbitrary 40 on every poll -- the other 355 are
-- starved for as long as the tie group exists, which is exactly the head-of-line failure this
-- query was rewritten to remove, one level down.
-- The tiebreak below rotates the order WITHIN a tie group once per poll bucket (120s == the poll
-- interval), so every member of a tie group reaches the front within a few minutes instead of
-- never. It is applied ONLY as a tiebreak: updated_at still decides strictly between rows of
-- different ages, so genuine oldest-first fairness is untouched. Deterministic within one poll
-- (now() is fixed for the statement), so a single pickup is internally consistent.
-- [finisher-bias 2026-08-10] THE BUDGET WAS BUYING THE WRONG DOCUMENTS.
-- The slices below were all ordered by updated_at, which measures WHEN a document was last touched
-- and says nothing about HOW CLOSE IT IS TO DONE. Measured at 09:40 UTC, bucketing the 40 rows this
-- query actually returns: 20 needed base extraction (~11 more dispatches each), 14 were mid-chain,
-- 6 were already COMPLETED (adjudication) -- and ZERO were near-finishers. Meanwhile 150 eligible
-- documents had SELECTION_COMPLETED='true' (one dispatch from COMPLETED) and 275 more had
-- PER_TYPE_EXTRACTION_COMPLETED='true' (two away). 425 documents that each needed 1-2 visits were
-- receiving 0 of ~4,800 visits/hour, while the budget went to documents that each needed ~11.
-- That is why COMPLETED sat flat at 6,225 for eight hours: the pipeline was doing enormous work,
-- almost none of it landing on a document that could actually finish.
--
-- s_fin is that missing slice: eligible, non-terminal, terminal-adjacent (SELECTION_COMPLETED set,
-- or per-type extraction done). It takes ~3/11 of the budget, ~11 of the 40 slots, so the
-- near-finisher pool drains in well under an hour instead of never.
--
-- WIDTH IS DELIBERATELY UNCHANGED AT 40. The premise that the host has spare capacity does not
-- survive measurement: 6 cores at load average 21, swap 94% consumed (377 MB free of 6 GiB), and
-- an n8n queue already 1,268 executions deep (1,013 running + 255 new) at a 3.4% error rate.
-- Picking more rows per poll lengthens that queue; it does not raise the completion rate. This
-- change buys no extra work -- it spends the SAME 40 dispatches on documents that can convert.
--
-- Slice ratio of the pickup: s_fin 3 : s_live 3 : s_new 3 : s_old 1 : s_adj 1. The untouched pool
-- keeps s_new + s_old = 4/11, so today's arrivals still get typed and the backlog still drains
-- FIFO -- reduced from 1/2, not starved. Interleave keys are numeric with distinct fractional
-- offsets so no two slices collide on k; a slice holding fewer rows than its share yields those
-- slots to the others, exactly as before. All v1/v2/rotation fairness properties are preserved
-- verbatim: same eligibility predicate, same per-slice rotation tiebreak, same min(k) dedup.
-- [cadence 2026-08-10] POLL INTERVAL 30s -> 2 MINUTES. At 30s each poll caught only ~1-2 genuinely
-- changed rows, and each became its own Process Changed Doc -> indoxV2Driver01 invocation, so every
-- downstream splitInBatches (Loop Over Items5 @100, Lines Batching Loop @20000, Loop Over Items -
-- Extract AI @30) received a single item and paid a full round-trip for it: maximum per-invocation
-- overhead, zero batching benefit, ~24,000 executions/hour drowning 16 execution slots. At 2 minutes
-- the same changed rows accumulate into one dispatch and batch through the routers properly.
-- SUPERSEDED by [one-knob 2026-08-10] below. This used to read: "INVARIANT: the change-window
-- (150s) must stay LONGER than the poll interval (120s) ... 30s of overlap." That coupling is gone
-- -- the window is now 15 minutes, far wider than any poll, so the trigger is the only knob and
-- this file needs no edit when it changes. Do NOT re-introduce a poll-sized window.
-- The rotation tiebreak bucket is 120s. It does not need to equal the poll: its only job is to
-- differ between consecutive pickups while staying fixed within one statement, which any bucket
-- shorter than the poll satisfies. At a 5-minute poll it simply rotates more than once per poll.
-- Deterministic within a single pickup, different on the next one.
--
-- [burst-priority 2026-08-10] THE SWEEPER HAD SWALLOWED THE CASCADE.
-- This node has TWO jobs, and the rewrite collapsed them into one. The trigger sticky note states
-- the design: "every 1 min, pick rows whose updated_at changed in the last 90s (any add/update,
-- NOT status-biased) and run main for each. Converges: a settled doc stops changing -> drops out
-- of the window." That is a BURST: an action writes the row -> the row enters the changed-window
-- -> it is picked again on the next poll -> next action -> repeat until no_action_*. A document
-- walks its whole chain in minutes. The status-based sweep is only the BACKSTOP for rows the
-- burst misses.
--
-- Both jobs were being served by one undifferentiated ordering, and the backstop drowned the
-- burst. Measured 09:59 UTC: 7,193 rows eligible, 0 of them changed in the last 150s, 15 in the
-- last 10 minutes -- and a just-changed document ranked ~1,200th within its own slice because
-- s_live/s_fin ordered by updated_at ASC (oldest first), which sorts a document that JUST made
-- progress to the BACK of its slice. So every cascade died after exactly one step, the write rate
-- decayed toward zero (~10 rows/min table-wide), and with no writes there was nothing left to
-- cascade. COMPLETED sat flat at 6,225 for eight hours as a direct consequence.
--
-- s_burst is the restored primary: every non-terminal row that changed inside the 150s window,
-- newest change first, at absolute priority (negative interleave key) and uncapped by the backlog
-- slices. It is self-limiting exactly as the sticky note says -- a settled document stops changing
-- and leaves the window on its own -- and it is cheap: the window holds single digits of rows, so
-- the backstop still receives ~34 of the 40 slots. Width is NOT the lever here; priority is.
-- A wider LIMIT over a diluted set just spreads the same starvation, so LIMIT stays at 40 until
-- the restored burst has been measured.
--
-- s_fin/s_live/s_new now order DESC so recent progress is re-picked immediately rather than last
-- -- the same defect the fairness rewrite cured for the queue as a whole, still present inside the
-- in-flight slices. s_old and the new s_stale keep the ASC arms (untouched backlog, and in-flight
-- rows idle long enough to fall out of the window) so nothing can be permanently abandoned: that
-- is the [fairness 2026-08-10] property, preserved. Eligibility is byte-for-byte unchanged -- every
-- row eligible before is eligible now -- and min(k) still de-duplicates a row appearing in several
-- slices, so a burst row costs exactly one slot.
-- [recovery 2026-08-10] THE PIPELINE COULD NOT REACH ITS OWN RECOVERABLE ROWS.
-- Eligibility admitted only IN_PROGRESS / TO_EXTRACT / null / '' (plus the decaying 150s
-- window and the dup-set). Every other status was unreachable BY CONSTRUCTION -- not
-- terminal, not deliberately excluded, simply never named. Measured 2026-08-10 13:2xZ:
-- 2,516 documents sat in statuses docBaseDecide has live forward paths for, and 2,220 of
-- them (88%) had genuine work queued behind that wall:
--     NEEDS_REVIEW 1,077 (1,069 with real work)   MISSING_COMPANY_ID 526 (323)
--     EXTRACTION_FAILED 330 (330)                 DOUBLE 320 (320)
--     MISSING_TYPE 164 (84)                       ACTION_RESTART 59 (59)
--     API_TOOLS_FAILED 25 (20)                    UNKNOWN_COMPANY 15 (15)
-- 870 of them needed nothing but base extraction. Proven empirically, not inferred: 224
-- NEEDS_REVIEW rows re-read 14.6 minutes later had been touched ZERO times.
--
-- Two consequences compounded it. The reaper PARKS rows to NEEDS_REVIEW, a status pickup
-- treats as terminal -- 44 documents/hour into a one-way sink, 788 corpus-wide, 479 of
-- them carrying no ERROR at all. And ACTION_RESTART was a live contradiction: decide
-- re-opens its gates on \`STATUS === 'ACTION_RESTART'\` and the retry clause special-cases
-- it, but eligibility excluded it, so the "redo this document" signal was unreachable.
--
-- MAX_ITERATIONS is DELIBERATELY still excluded. It is the iteration ceiling; re-admitting
-- it would defeat the guard that took a single pickup from 41 wasted slots to 10.
--
-- CONTAINMENT. Recovered rows are excluded from all six existing slices (\`not recov\`), so
-- every row eligible before keeps its exact key and no live work is displaced -- 2,516 old
-- rows would otherwise dominate the ASC arms (s_old/s_stale) and starve the burst. They get
-- ONE bounded slice, s_recov, at rn*6.0 -> ~6 of 40 slots. s_burst DELIBERATELY still sees
-- them: a recovered row that gets acted on must re-enter the 45s window and cascade its
-- whole chain, exactly as the sticky note describes, instead of taking one step and dying.
-- s_recov orders finishers first (218 of the 320 DOUBLE rows have SELECTION_COMPLETED set
-- and are one dispatch from COMPLETED), then oldest-starved first.
-- [terminal-leak 2026-08-10] A QUARTER OF THE BUDGET WAS SPENT ON TERMINAL ROWS.
-- The terminal exclusion added earlier lives only inside the dup-set SUBQUERY. The main
-- eligibility predicate excluded 'MERGED' and nothing else, so the \`updated_at > now() -
-- 150 seconds\` arm admitted MAX_ITERATIONS / GARBAGE / OLD rows unfiltered -- and that arm
-- is self-sustaining: the row is picked, something writes it, updated_at bumps, it re-enters
-- the window, forever. Measured by dry-running this very query against the live table at
-- 13:3xZ: 10 of the 40 returned rows were MAX_ITERATIONS. 25% of all pickup capacity, on
-- rows docBaseDecide answers no_action_* for (MAX_ITERATIONS line 312, GARBAGE 308, OLD 199).
-- Excluding them frees those 10 slots for documents that can actually convert.
-- The escape hatch is ACTION_RESTART, which the recovery slice above now makes reachable for
-- the first time -- so a row wrongly terminalised can still be revived deliberately.
-- [recov-rotation 2026-08-10] v2 SERVED THE SAME FOUR ROWS FOREVER.
-- Ordering by \`updated_at asc\` inside s_recov pinned its head: a recovered row that
-- cannot progress never writes, so its updated_at never moves, so it wins the next
-- poll too. Measured by capturing the ids the LIVE pickup returned, twice, ten
-- minutes apart: 4 of 5 identical. The 5th differed only because it tied on
-- updated_at with its replacement to the microsecond, which is the one case the md5
-- tiebreak could act on. ~180 dispatches/hour were landing on 4 documents while
-- 2,229 others never got a turn -- head-of-line starvation, the exact defect this
-- file was rewritten twice to remove, reintroduced one level down inside a new slice.
--
-- Recovery is a SEED, not a drain: any recovered row that writes anything enters the
-- 45s window and s_burst cascades the rest of its chain at absolute priority. So the
-- slice needs COVERAGE, not prioritisation. Rotating on md5 per 120s bucket sweeps
-- the whole pool -- 711 needs_base rows at ~6 slots/poll is full coverage in ~4
-- hours, versus never. needs_base stays the leading key because those rows have an
-- unambiguous forward action (extract_base_doc) regardless of their status label.
-- [one-knob 2026-08-10] THE POLL INTERVAL IS NOW THE ONLY KNOB.
-- This query used to carry a change-window sized just above the trigger (150s against a
-- 120s poll, "30s of overlap"), plus a separate 45s burst window. Three constants in two
-- files that had to be edited together, with nothing enforcing the relationship: raise
-- the poll alone and changes land and expire between polls, seen only by the status
-- backstop -- silently, because the backstop still returns rows.
-- The window does not govern how much work is done. The caps do: s_burst rn <= 6, every
-- other slice rn <= 40, and LIMIT 40 overall. So the window is now simply far wider than
-- any sane poll interval. Change the trigger to 1m or 10m and this query needs no edit.
-- s_burst keeps its absolute priority and its cap of 6, ordered newest-change-first, so a
-- wider window changes WHICH six it sees, never how many -- it can only make the cascade
-- more complete, never heavier.
-- [width 2026-08-10] 40 -> 120, BECAUSE THE QUEUE IS NOW EMPTY.
-- Width was held at 40 all day, and that was correct at the time: every earlier proposal
-- to widen was made while bull:jobs:wait sat at 1,300-2,900, i.e. the workers already had
-- more than they could take and a wider pickup would only have lengthened the queue.
-- That is no longer the state. n8n-postgres was pinned at \`cpus: '1'\` and sitting at 102%
-- of that one core -- the real ceiling beneath everything else. Raised to 4 cores,
-- postgres fell to 46%, apitools went 0.03% -> 22%, one worker went idle -> 99%, and
-- bull:jobs:wait drained to ZERO and stayed there across consecutive samples. The
-- pipeline is now dispatch-starved rather than saturated.
-- Compounding it: the poll moved 2m -> 5m without width moving, so dispatch fell from
-- 30 polls/hr x 40 = 1,200 rows/hr to 12 x 40 = 480. 120 restores 1,440/hr and uses the
-- queue as the buffer, which is the intended shape: enqueue a batch, let the workers
-- drain it across the interval.
-- IF bull:jobs:wait starts sitting deep again, THIS is the number to bring back down --
-- not the poll, and not worker concurrency (perf-profiles.yml pins 8 with OOM history).
-- [finisher starvation 2026-08-10] s_fin WAS STARVING ITS OWN TAIL.
-- s_fin orders updated_at DESC so a document that just made progress is re-picked
-- immediately -- that is deliberate and it is what makes the cascade work. But a
-- finisher that is NOT being touched sorts to the back and stays there, because fresh
-- finishers keep arriving ahead of it. Measured at 16:35Z against the live table:
--   667 finishers eligible; ranked newest-first,
--     top 33  (one poll's s_fin share at width 120): 10 ready-to-complete
--     rank 300+                                    : 93 ready-to-complete
--   newest finisher last written 34 minutes ago, oldest 5,786 minutes (4 days) ago.
-- 171 documents needed nothing but the terminal write, and 93 of them sat beyond any
-- plausible per-poll budget. This is the same head-of-line failure this file was
-- rewritten to remove -- reintroduced one level down, inside the slice that exists
-- specifically to finish documents.
--
-- Fix is the pattern already used for the in-flight pool (s_live DESC / s_stale ASC):
-- give finishers an ASC companion. The finisher share is SPLIT, not enlarged -- rn*4
-- becomes rn*8 on each half -- so the combined finisher budget is exactly what s_fin
-- had alone and no other slice loses anything. At width 120 that is ~13 stale
-- finishers per poll, ~156/hour, which clears the 93 within the hour instead of never.
-- [double no-op fence 2026-08-10] THE FINISHER SLICES WERE FEEDING THEMSELVES NO-OPS.
-- Measured: of the 171 documents whose every gate is satisfied and which need nothing but
-- the terminal write, 168 carry \`merge_sig\` in DOUBLE_LINE_CONTEXT -- 94 with STATUS
-- 'DOUBLE' and a further 74 sitting in 'TO_EXTRACT'. decide adjudicates the stamp before
-- any other gate and returns no_action_double, deterministically, forever. So the two
-- slices that exist specifically to FINISH documents were handing their budget, every
-- poll, to rows that cannot be finished. Only 3 of the 171 were genuinely completable.
-- s_recov already excludes them (\`and not stamped_double\`); s_fin and s_finstale did not.
--
-- This is a fence, not a fix. Those 168 documents are fully processed confirmed
-- duplicates and the real defect is that the state machine has NO TERMINAL STATE for
-- "confirmed duplicate, finished" -- so they can never leave. That is an owner decision
-- (MERGED, which is the existing tombstone and already excluded here, versus COMPLETED,
-- which would count the same real-world document twice). Until it lands they stay
-- visible and unmodified -- no row is edited -- they simply stop consuming the finisher
-- budget that documents which CAN finish need.
-- [coverage 2026-08-10] THE PICKUP KEPT RETURNING THE SAME 120 ROWS.
-- Measured by running the LIVE query twice, 70 seconds apart: 109 of 120 rows IDENTICAL,
-- 11 in / 11 out. At 12 polls an hour that is ~132 fresh documents reached per hour
-- against 9,370 workable -- a 71-HOUR cycle before a given document is looked at again.
-- The pipeline was not grinding the same documents (a completed document averages 2.2
-- actions, and each document gets ~1.2 driver passes an hour); it was re-SELECTING the
-- same rows while thousands sat untouched. That is why raising width 40 -> 120 did not
-- help: a wider net cast repeatedly over the same water.
--
-- Cause: every slice ordered by updated_at, and a row that produces no write keeps its
-- updated_at, so it holds its rank permanently. The md5 term was only the THIRD sort key
-- -- a tiebreak -- so it shuffled only rows sharing an identical microsecond. Same
-- head-of-line failure already fixed inside s_recov, still live in the backlog arms.
--
-- Fix: for the two BACKLOG slices only, rotation becomes the PRIMARY key, bucketed at
-- 300s to match the poll, so each poll samples a genuinely different subset. Eligibility
-- is byte-identical, slice shares and caps are untouched -- this cannot add load, it only
-- changes WHICH rows the same budget buys.
--
-- s_burst / s_fin / s_live / s_new DELIBERATELY keep updated_at DESC: they exist so a
-- document that JUST advanced is re-picked immediately and walks its whole chain.
-- Rotating those would break the cascade this file was rewritten to restore.
-- [free-the-walled 2026-08-11 P5] NEEDS_REVIEW WAS IN THE RECOVERY SET AND STILL UNREACHABLE.
-- [recovery 2026-08-10] above added NEEDS_REVIEW to the admitted statuses, but admission is
-- ANDed with the retry gate on the last line of this predicate, and the writers that minted
-- NEEDS_REVIEW stamped NEXT_RETRY_AT='infinity' in the same statement. 'infinity' <= now() is
-- false forever, so those rows were walled off by the very clause meant to pace them: measured
-- 2026-08-11 01:14Z, 260 of 1,191 NEEDS_REVIEW rows, including 146 of the 147 that need nothing
-- but base extraction. The recovery slice could never see them.
--
-- The 'infinity' minting is removed at source in the same change (errorHandler01/'Backoff +
-- Dead-letter', indoxV2ActionsGlobal01/'Record Base Doc Failure', and the three inline
-- __recordStageMiss blocks), so this clause is SELF-LIMITING: it drains a fixed, closed set of
-- rows that no writer can replenish, and empties permanently as the pipeline re-labels them.
-- Scoped to exactly that artifact -- STATUS NEEDS_REVIEW *and* NEXT_RETRY_AT infinity -- so no
-- other status gains an 'infinity' bypass and no live backoff anywhere is shortened. Recovery
-- is proven to work once rows are reachable: of the rows the reaper stamped, 30 reached
-- COMPLETED, 31 API_TOOLS_FAILED, 18 MISSING_COMPANY_ID, 9 MISSING_TYPE.

-- [max-iterations released 2026-08-11] THE PREMISE OF THE EXCLUSION NO LONGER HOLDS.
-- THIS REVERSES A DELIBERATE DECISION DOCUMENTED ABOVE. [recovery 2026-08-10] states
-- "MAX_ITERATIONS is DELIBERATELY still excluded ... re-admitting it would defeat the guard
-- that took a single pickup from 41 wasted slots to 10", and [terminal-leak 2026-08-10]
-- records an arm that admitted MAX_ITERATIONS unfiltered and burned 25% of pickup capacity.
-- BOTH WERE CORRECT AT THE TIME, and neither was ignored -- the premise underneath them was
-- that 'Decide DOC BASE Action' answered no_action_max_iterations UNCONDITIONALLY, so every
-- admitted row was guaranteed waste. Two changes shipped 2026-08-10/11 removed exactly that:
--   P1: the iteration counter now counts DISTINCT (action, timestamp, execution-id) triples
--       instead of raw 13-digit timestamp occurrences. ACTION_LOG re-appending had inflated
--       it 5.5-6.2x (worst case 67x), so 501 documents read as over the 50-cap when only 8
--       genuinely were. The population was mostly mislabelled, not exhausted.
--   P3: the STATUS === 'MAX_ITERATIONS' short-circuit is now conditional on _iter >= _maxIter
--       rather than unconditional, so a parked row can re-evaluate and leave.
-- P3 was INERT while this clause held: measured, only 3 of 354 rows were touched in the half
-- hour after it went live, because pickup never handed them to decide at all. With P1+P3 live,
-- 348 of 356 are under the cap by TRUE count, 289 are finishers and 336 are typed AND companied
-- -- decide now returns real actions for them. The 8 genuinely over the cap still short-circuit
-- and cost only the bounded share below.
--
-- CONTAINMENT IS THE SAME PATTERN [recovery 2026-08-10] used: MAX_ITERATIONS joins the recov
-- flag, so released rows are excluded from all seven other slices and land ONLY in s_recov
-- (rn*6.0, capped) -- a fixed share of an unchanged width, so this cannot add load, it only
-- changes which rows that share buys. It is added to the admitted-status list as well as
-- removed from the exclusion: admission is an AND of the status OR-group with the exclusion
-- list, so dropping it from the exclusion alone would have left it unreachable and this whole
-- change silently inert. The dup-detector subquery keeps its own MAX_ITERATIONS exclusion
-- untouched -- that governs what counts as a duplicate set, which is a different question.
with elig as (
  select "ID", updated_at,
         (coalesce("STATUS",'') = 'COMPLETED') as terminal,
         -- [touched re-sourced 2026-08-21, owner order] Was
         --   BASE_EXTRACTION_COMPLETED = 'true' OR ACTION_LOG <> ''
         -- and it was the LAST state-machine read of ACTION_LOG. touched only ever meant "has
         -- this document been worked on at all"; it splits the slices below into s_new /
         -- s_old (never touched) and s_stale (touched but gone quiet), so getting it wrong does
         -- not lose documents, it mis-prioritises them: every worked-but-never-base-extracted row
         -- would read as brand new and flood s_new, starving the genuinely new ones.
         --
         -- ITERATION_COUNT is a real counter now (+1 per dispatch in indoxV2ActionRouter01 ::
         -- 'Log Action Start'), so "> 0" is the direct statement of the same fact, with no join
         -- and no string. KNOWN AND ACCEPTED: ACTION_RESTART resets the counter to 0, so a
         -- restarted document reads "new" again for one pass -- which is arguably right, since a
         -- restart is a deliberate request to re-walk the pipeline from the top.
         (lower(coalesce("BASE_EXTRACTION_COMPLETED", '')) = 'true'
          or coalesce("ITERATION_COUNT", 0) > 0) as touched,
         (lower(coalesce("SELECTION_COMPLETED", '')) = 'true'
          or lower(coalesce("PER_TYPE_EXTRACTION_COMPLETED", '')) = 'true') as finisher,
         (coalesce("LINK",'') <> '' and coalesce("BASE_EXTRACTION_COMPLETED",'') = '') as needs_base,
         (coalesce("API_TOOLS_ID",'') <> '' and lower(coalesce("BASE_EXTRACTION_COMPLETED",'')) = 'true' and coalesce("TYPE",'') <> '' and lower(coalesce("PER_TYPE_EXTRACTION_COMPLETED",'')) <> 'true' and lower(coalesce("SELECTION_COMPLETED",'')) <> 'true') as pertype_ready,
         (coalesce("STATUS",'') = 'DOUBLE' and coalesce("DOUBLE_LINE_CONTEXT",'') like '%merge_sig%') as stamped_double,
         (coalesce("STATUS",'') = 'ACTION_RESTART') as restart,
         (coalesce("STATUS",'') in ('DOUBLE','ACTION_RESTART','MISSING_LINK')) as recov
  from {{ (() => { const s = String($json.__instance || ''); if (!s) throw new Error('indoxApi01: request carries no __instance. The public fallback was removed 2026-08-28 (cutover step 2); every caller must name its instance. public never meant no tenant, it meant whichever tenant public resolves to.'); if (!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: ' + s); return 'indox_' + s; })() }}.incoming_documents
  where "ID" is not null and "ID" <> '' and "ID" <> '__bootstrap__' and ("STATUS" = 'IN_PROGRESS' or "STATUS" = 'TO_EXTRACT' or "STATUS" is null or "STATUS" = '' or "STATUS" in ('DOUBLE','ACTION_RESTART','MISSING_LINK') or updated_at > now() - interval '15 minutes' or "ID" in (select z."ID" from (select "ID", count(*) over (partition by "COMPANY_ID", trim(nullif("DOC_ID",''))) as _n from {{ (() => { const s = String($json.__instance || ''); if (!s) throw new Error('indoxApi01: request carries no __instance. The public fallback was removed 2026-08-28 (cutover step 2); every caller must name its instance. public never meant no tenant, it meant whichever tenant public resolves to.'); if (!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: ' + s); return 'indox_' + s; })() }}.incoming_documents where coalesce("STATUS",'') not in ('MERGED','MAX_ITERATIONS','GARBAGE','OLD') and coalesce("COMPANY_ID",'') <> '' and coalesce("DOUBLE_LINE_CONTEXT",'') not like '%merge_sig%' and trim(nullif("DOC_ID",'')) is not null and length(regexp_replace(trim(nullif("DOC_ID",'')), '[^a-zA-Z0-9]', '', 'g')) >= 3 and regexp_replace(trim(nullif("DOC_ID",'')), '[^a-zA-Z0-9]', '', 'g') !~ '^0+$' and lower(trim(nullif("DOC_ID",''))) not in ('unknown','action_required','null','none') and trim(nullif("DOC_ID",'')) <> trim("COMPANY_ID")) z where z._n > 1)) and coalesce("STATUS",'') not in ('MERGED','GARBAGE','OLD','PAUSE','MAX_ITERATIONS','MISSING_COMPANY_ID','MISSING_TYPE','UNKNOWN_COMPANY','EXTRACTION_FAILED','API_TOOLS_FAILED','ACTION_REQUIRED','NEEDS_REVIEW')
),
s_restart as (select "ID", row_number() over (order by updated_at asc) rn from elig where not terminal and restart),
s_burst as (select "ID", row_number() over (order by updated_at desc) rn from elig where not terminal and updated_at > now() - interval '15 minutes'),
s_fin  as (select "ID", row_number() over (order by updated_at desc, md5("ID" || (floor(extract(epoch from now()) / 120))::text)) rn from elig where not terminal and finisher and not recov and not stamped_double),
s_finstale as (select "ID", row_number() over (order by updated_at asc, md5("ID" || (floor(extract(epoch from now()) / 120))::text)) rn from elig where not terminal and finisher and not recov and not stamped_double),
s_live as (select "ID", row_number() over (order by updated_at desc, md5("ID" || (floor(extract(epoch from now()) / 120))::text)) rn from elig where not terminal and touched and not finisher and not recov),
s_new  as (select "ID", row_number() over (order by updated_at desc) rn from elig where not terminal and not touched and not finisher and not recov),
s_old  as (select "ID", row_number() over (order by md5("ID" || (floor(extract(epoch from now()) / 300))::text)) rn from elig where not terminal and not touched and not finisher and not recov),
s_stale as (select "ID", row_number() over (order by md5("ID" || (floor(extract(epoch from now()) / 300))::text)) rn from elig where not terminal and touched and not finisher and not recov),
s_recov as (select "ID", row_number() over (order by md5("ID" || (floor(extract(epoch from now()) / 120))::text)) rn from elig where not terminal and recov and not stamped_double and not needs_base),
s_recovbase as (select "ID", row_number() over (order by md5("ID" || (floor(extract(epoch from now()) / 120))::text)) rn from elig where not terminal and recov and not stamped_double and needs_base),
s_pertype as (select "ID", row_number() over (order by md5("ID" || (floor(extract(epoch from now()) / 300))::text)) rn from elig where not terminal and pertype_ready and not stamped_double),
s_adj  as (select "ID", row_number() over (order by updated_at asc, md5("ID" || (floor(extract(epoch from now()) / 120))::text)) rn from elig where terminal and not recov),
u as (
  select "ID", rn * 1.0  - 2000.0 as k from s_restart where rn <= 20
  union all
  select "ID", rn * 1.0  - 1000.0 as k from s_burst where rn <= 6
  union all
  select "ID", rn * 8.0  + 0.00 as k from s_fin      where rn <= 120
  union all
  select "ID", rn * 8.0  + 0.05 as k from s_finstale where rn <= 120
  union all
  select "ID", rn * 4.0  + 0.1 as k from s_live  where rn <= 120
  union all
  select "ID", rn * 6.0  + 0.2 as k from s_new   where rn <= 120
  union all
  select "ID", rn * 14.0 + 0.3 as k from s_old   where rn <= 120
  union all
  select "ID", rn * 12.0 + 0.4 as k from s_stale where rn <= 120
  union all
  select "ID", rn * 12.0 + 0.5 as k from s_adj   where rn <= 120
  union all
  select "ID", rn * 6.0  + 0.6 as k from s_recov where rn <= 120
  union all
  select "ID", rn * 5.0  + 0.15 as k from s_pertype where rn <= 120
  union all
  select "ID", rn * 24.0 + 0.7 as k from s_recovbase where rn <= 120
)
select z."ID" from (select "ID", min(k) as k from u group by "ID") z
order by z.k asc limit 120;
`,
        options: {},
    };

    @node({
        id: 'indox-trg-note',
        name: 'Sticky Note Trigger',
        type: 'n8n-nodes-base.stickyNote',
        version: 1,
        position: [-1680, -528],
    })
    StickyNoteTrigger = {
        color: 4,
        content: `## Change events: API provides, DRAINER initiates (owner order 2026-08-16)
'Get Changed Docs' is now a callable op — INLINE_ACTION='GET_CHANGED' via the Action switch —
returning eligible changed-doc IDs (change window + backoff gate + terminal-set + slice caps,
all unchanged). The 5-min self-tick ('Poll Line Changes') and the direct driver call
('Process Changed Doc') were REMOVED: the drainer is the ONLY initiator of indoxV2Driver01 —
it polls this op each tick, gated on indoxDrainOn, and drives the ids through its Run-By-ID
lane. drain off => nothing re-drives changed docs, by design. (pg_notify still unusable here:
row_to_json > 8KB breaks UPDATEs; LISTEN unreliable.)`,
        height: 250,
        width: 560,
    };

    @node({
        id: 'sv3-build-deliver',
        name: 'Build Deliver',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-880, 1184],
    })
    BuildDeliver = {
        jsCode: `// sync-v3 DELIVER: insert-if-new. Content dedup is NOT enforced here any more (uq_incdoc_hash retired).
// Contract: row MUST carry a valid HASH. Emits insert sql (ON CONFLICT DO NOTHING) +
// a separate fetch sql (fresh snapshot -> safe under concurrent same-hash deliveries).
const out=[];
// [schema-per-instance 2026-08-27] see Build Get All SQL — 'public' is the migration fallback,
// not a default instance, and it goes when the compatibility views do.
const SCHEMA=(()=>{ const s=String((($input.all()[0]||{}).json||{}).__instance||'');
  if(!s) throw new Error('indoxApi01: request carries no __instance (public fallback removed 2026-08-28, cutover step 2). Note the SHARED[t] check above still returns public for genuinely global tables -- reaching this line means a PER-INSTANCE table was asked for without naming an instance.');
  if(!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: '+s);
  return 'indox_'+s; })();
for (const it of $input.all()) {
  const j={...it.json}; delete j.INLINE_ACTION; delete j.__instance;
  const bad=v=>v===undefined||v===null||v===''||String(v).toLowerCase()==='unknown';
  if (bad(j.HASH)) throw new Error('DELIVER requires a valid HASH (content identity)');
  if (bad(j.ID)) j.ID='doc_'+Date.now().toString(36)+Math.random().toString(36).slice(2,8);
  j.TIMESTAMP=new Date().toISOString();
  // [SOURCE_LIST 2026-08-21] The 'self' element names the row it belongs to, and the row's ID is
  // only settled HERE (the line above mints it when the caller sent none), so syncDeliverGmail01
  // cannot fill this in. Every other origin ('merged_loser', 'attached') carries the id of the
  // OTHER row it came from and is left exactly as the caller wrote it.
  if (Array.isArray(j.SOURCE_LIST)) j.SOURCE_LIST=j.SOURCE_LIST.map(e=>
    (e&&typeof e==='object'&&e.origin==='self'&&!e.doc_row_id)?{...e,doc_row_id:j.ID}:e);
  // __instance excluded: schema selector, not a column.
  const cols=Object.keys(j).filter(k=>k!=='__instance'&&j[k]!==null&&j[k]!==undefined);
  const q=c=>'"'+String(c).replace(/"/g,'""')+'"';
  const params=cols.map(c=>(typeof j[c]==='object'?JSON.stringify(j[c]):String(j[c])));
  const ph=cols.map((_,i)=>'$'+(i+1));
  const pred='"HASH" is not null and "HASH" <> \\'\\' and lower("HASH") <> \\'unknown\\'';
  // [uq_incdoc_hash retired 2026-08-19, owner order] Was: on conflict ("HASH") where <pred> do
  // nothing. That is PARTIAL-INDEX INFERENCE and needs a unique index on HASH carrying exactly
  // that predicate. The owner dropped that index deliberately ('no sense of hard blocking it,
  // instead we will merge lines with similar hashes'), so every DELIVER since has failed with
  // 'there is no unique or exclusion constraint matching the ON CONFLICT specification' -- 95
  // occurrences, 10-17/hour, each one a document that was never ingested. Bare DO NOTHING still
  // guards the primary key and needs no index; content twins are now the merge path's business.
  // [C2 2026-08-21] DELIVER RESOLVES ARTIFACT IDENTITY BEFORE IT CREATES.
  //
  // This was the ONLY create path in the system with no identity check at all. It minted a fresh
  // doc_ id and inserted; 'on conflict do nothing' guards the PRIMARY KEY, and a brand-new id never
  // conflicts, so the guard has never once stopped a duplicate. Every re-delivery of a file the
  // table already held became a second row -- and re-delivery is normal, because the scanner
  // re-reads folders (13,968 rows on this table were picked up out of a pipe's own 'synced' folder).
  //
  // The check is deliberately ARTIFACT-only, the same two certain keys 'Resolve IDs' now uses:
  // the same bytes (HASH), or the same handle at the same source (SOURCE_TYPE, SOURCE_ID). It does
  // NOT look at COMPANY_ID/DOC_ID -- at delivery those are not extracted yet, and inferred identity
  // is the merge action's business, never a writer's.
  //
  // WHERE NOT EXISTS, not ON CONFLICT: there is no unique index on HASH to infer (uq_incdoc_hash
  // was dropped deliberately on 2026-08-19 -- 'no sense of hard blocking it, instead we will merge
  // lines with similar hashes'), and re-adding one would resurrect exactly the hard rejection the
  // owner removed. This declines to CREATE a twin while leaving merging free to decide what the
  // twin means. The bare 'on conflict do nothing' stays as the primary-key backstop.
  // [multi-artifact sources 2026-08-25] THE SOURCE HANDLE IS NOT ALWAYS ONE ARTIFACT.
  // (SOURCE_TYPE, SOURCE_ID) identifies a Drive FILE, but for mail SOURCE_ID is the MESSAGE id,
  // and one message can carry several documents. With the handle alone as an identity key the
  // first attachment created a row and every sibling was declined as "already delivered" --
  // measured on gmail-bs message 1a039e97bc1d04e1 (aging report + invoice): Find Balance Doc
  // emitted 2, both uploaded to Drive, ONE row survived, and it was a chimera carrying the
  // invoice's NAME/HASH beside a LINK pointing at the aging report's file. That contradicts the
  // owner's ruling for multi-attachment mail: filter garbage, deliver everything else.
  // NAME joins the handle clause so the clause still means "this same artifact, again":
  // re-delivering an attachment matches (same message, same output filename) and is declined as
  // before, while a genuine sibling has a different filename and is created. Identical bytes are
  // caught by the HASH clause first regardless of name, so content dedup is unaffected.
  const _si = c => { const i = cols.indexOf(c); return i < 0 ? null : '$' + (i + 1); };
  const _h = _si('HASH'), _st = _si('SOURCE_TYPE'), _sid = _si('SOURCE_ID'), _nm = _si('NAME');
  const idParts = [];
  if (_h)             idParts.push('d."HASH" = ' + _h);
  if (_st && _sid)    idParts.push('(d."SOURCE_TYPE" = ' + _st + ' and d."SOURCE_ID" = ' + _sid
                                   + (_nm ? ' and d."NAME" = ' + _nm : '') + ')');
  const guard = idParts.length
    ? ' where not exists (select 1 from ' + SCHEMA + '.incoming_documents d where ' + idParts.join(' or ') + ')'
    : '';
  const sql='insert into '+SCHEMA+'.incoming_documents ('+cols.map(q).join(',')+') select '+ph.join(',')+guard+' on conflict do nothing';
  // The fetch must answer with whichever row now owns this artifact -- the one just inserted, or
  // the pre-existing one the guard deferred to. Hash first, because it is the stronger key.
  // [2026-08-22] THE ABSENT-VALUE SENTINEL WAS A NUL BYTE, and postgres does not accept one in a
  // text parameter at all -- 'select chr(0)' answers 'null character not permitted'. Over the
  // wire that surfaces as the protocol-level 'invalid message format', naming neither the
  // parameter nor the value:
  //     PG Deliver Fetch: invalid message format
  //     Failed query: select "ID","HASH" ... ("SOURCE_TYPE" = $2 and "SOURCE_ID" = $3) ...
  // Any DELIVER without a SOURCE_TYPE or SOURCE_ID hit it, so syncItemApiTest01 -- whose whole
  // point is a MINIMAL delivery -- could never pass. The drive and gmail ingest lanes always send
  // both, which is why this looked confined to one suite instead of to the shared write path.
  //
  // No sentinel is needed. The pair is either usable or absent, and the insert guard a few lines
  // up already says so with if (_st && _sid); the fetch simply never asked. It does now, and
  // drops the clause AND its two parameters together, so the placeholder count always matches
  // what is bound.
  const _hasSrc = String(j.SOURCE_TYPE == null ? '' : j.SOURCE_TYPE) !== ''
               && String(j.SOURCE_ID   == null ? '' : j.SOURCE_ID)   !== '';
  // The fetch must ask the SAME question as the insert guard, or it answers with a sibling
  // instead of this artifact: on a two-attachment mail the old handle-only fetch returned
  // whichever attachment landed first, and the caller then recorded the wrong row id for the
  // file it had just uploaded. NAME travels with the handle here for exactly that reason.
  const _hasName = String(j.NAME == null ? '' : j.NAME) !== '';
  const _srcName = _hasSrc && _hasName;
  const fparams = _srcName
    ? [String(j.HASH), String(j.SOURCE_TYPE), String(j.SOURCE_ID), String(j.NAME)]
    : (_hasSrc ? [String(j.HASH), String(j.SOURCE_TYPE), String(j.SOURCE_ID)] : [String(j.HASH)]);
  out.push({json:{sql,params,
    fetch_sql: _srcName
      ? 'select "ID","HASH" from ' + SCHEMA + '.incoming_documents where "HASH" = $1 or ("SOURCE_TYPE" = $2 and "SOURCE_ID" = $3 and "NAME" = $4) order by ("HASH" = $1) desc, created_at asc limit 1'
      : (_hasSrc
        ? 'select "ID","HASH" from ' + SCHEMA + '.incoming_documents where "HASH" = $1 or ("SOURCE_TYPE" = $2 and "SOURCE_ID" = $3) order by ("HASH" = $1) desc, created_at asc limit 1'
        : 'select "ID","HASH" from ' + SCHEMA + '.incoming_documents where "HASH" = $1 order by created_at asc limit 1'),
    fetch_params:fparams}});
}
return out;`,
    };

    @node({
        id: 'sv3-pg-deliver',
        name: 'PG Deliver Insert',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [-624, 1184],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 1000,
    })
    PgDeliverInsert = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryReplacement: '={{ $json.params }}',
        },
    };

    @node({
        id: 'sv3-deliver-fetch-req',
        name: 'Deliver Fetch Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-368, 1184],
    })
    DeliverFetchReq = {
        jsCode: `// re-emit fetch queries from Build Deliver (PG insert output is empty on DO NOTHING;
// $('...').all() by design -- never .item across postgres nodes)
return $('Build Deliver').all().map(i=>({json:{sql:i.json.fetch_sql,params:i.json.fetch_params}}));`,
    };

    @node({
        id: 'sv3-pg-deliver-fetch',
        name: 'PG Deliver Fetch',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [-112, 1184],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 1000,
    })
    PgDeliverFetch = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryReplacement: '={{ $json.params }}',
        },
    };

    @node({
        id: 'bmisql',
        name: 'Build Match Index SQL',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-368, 128],
    })
    BuildMatchIndexSql = {
        jsCode: `// Build a logical-identity index scoped to THIS batch.
//
// WHY: 'Resolve IDs' only ever probes existingIds / byHash / bySrc with keys taken from the
// incoming rows. So loading only the rows that share one of those keys is EXACTLY equivalent to
// loading the whole table — and it is the difference between 45,839 rows on every single UPSERT and
// a few dozen. The unbounded version (\`select ... from {{ $json.__instance ? 'indox_' + $json.__instance : 'public' }}.incoming_documents\` with no WHERE) was fine at
// 100 rows and fatal at 45,839: it ran on every writeback and blew the 1536MB worker heap.
const rows = $input.all().map(i => i.json);
const bad = v => v === undefined || v === null || v === '' || v === 'unknown' || v === 'ACTION_REQUIRED';
const params = [];
const p = v => { params.push(String(v)); return '$' + params.length; };

const ids = new Set(), hashes = new Set(), pairs = new Map();
for (const r of rows) {
  if (!bad(r.ID)) ids.add(String(r.ID));
  if (!bad(r.HASH)) hashes.add(String(r.HASH));
  // [C3 2026-08-21] (SOURCE_TYPE, SOURCE_ID) replaces the two BUSINESS-key pairs. See the long
  // note on 'Resolve IDs' for why. Those rows are no longer LOADED because they are no longer
  // PROBED -- keeping them would only widen the scan for nothing.
  if (!bad(r.SOURCE_TYPE) && !bad(r.SOURCE_ID))
    pairs.set('SRC' + r.SOURCE_TYPE + '' + r.SOURCE_ID, ['SOURCE_ID', String(r.SOURCE_TYPE), String(r.SOURCE_ID)]);
}

const ors = [];
if (ids.size) ors.push('"ID" in (' + [...ids].map(p).join(',') + ')');
if (hashes.size) ors.push('"HASH" in (' + [...hashes].map(p).join(',') + ')');
for (const [col, lhs, val] of pairs.values())
  ors.push('("' + (col === 'SOURCE_ID' ? 'SOURCE_TYPE' : 'COMPANY_ID') + '" = ' + p(lhs) + ' and "' + col + '" = ' + p(val) + ')');

// No usable key anywhere in the batch -> nothing can match -> don't scan the table for nothing.
const where = ors.length ? ors.join(' OR ') : 'false';
// NAME travels with the handle because (SOURCE_TYPE, SOURCE_ID) is not one artifact for every
// source: a mail message id is shared by all of its attachments. Resolve IDs needs the name to
// tell a sibling attachment apart from a re-delivery of the same one.
// [schema-per-instance 2026-08-27] see Build Get All SQL — 'public' is the migration fallback.
const SCHEMA = (() => { const s = String((($input.all()[0] || {}).json || {}).__instance || '');
  if (!s) throw new Error('indoxApi01: request carries no __instance. The public fallback was removed 2026-08-28 (cutover step 2); every caller must name its instance. public never meant no tenant, it meant whichever tenant public resolves to.');
  if (!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: ' + s);
  return 'indox_' + s; })();
const sql = 'select "ID","HASH","SOURCE_TYPE","SOURCE_ID","NAME" from ' + SCHEMA + '.incoming_documents where ' + where;
return { json: { sql, params } };
`,
    };

    @node({
        id: 'ggsz',
        name: 'Guard Get Size',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-368, 384],
    })
    GuardGetSize = {
        jsCode: `// Fail loudly instead of silently truncating or silently OOM-ing.
//
// Both GET and GET_ALL select CAP+1 rows. Getting CAP+1 back means the caller asked for more of
// incoming_documents than a 1536MB worker can hold as JS objects (the table is 45,839 rows / 37MB raw
// and every executeWorkflow hop copies it). Truncating would quietly return wrong answers, so we
// refuse. A caller that hits this must narrow its query — GET with \`filters\` pushes N lookups into one
// bounded round-trip.
//
// CAP=100000 (5000 -> 20000 on 2026-08-05 -> 100000 on 2026-08-11).
// Owner: the API must NOT be the limiter. Batching is the main driver's job (Lines Batching
// Loop); every other path should carry as many INDOX lines as exist, and up to 100k rows is
// expected to be fine. So this stops being a working cap and becomes a pure sanity backstop.
// PG Get All selects CAP+1, which is what makes this guard reachable AT ALL: it previously
// selected exactly CAP, so the refusal below could never trigger and an oversized table would
// have been silently sampled — the first CAP rows by ID, newest documents invisible, no error.
// Corpus was 17,361 and rising ~355/hr when this was raised (~7h of headroom left at 20000).
// (original note) CAP=20000 (raised from 5000 on 2026-08-05): GET_ALL ('PG Get All') now deliberately reads the WHOLE
// incoming_documents table (ORDER BY "ID", LIMIT 20000) so the dedup sweep sees every row instead of an
// unordered partial sample — see that node's comment. Table was 6,203 rows at the time; 20000 gives
// ~3.2x headroom. This guard is shared with the narrow GET path ('Build Get SQL', its own CAP=5000
// bounds the query it builds to 5001 rows), so raising this threshold also raises where THAT path's
// overflow gets caught — accepted because Build Get SQL only ever runs targeted ID/HASH/company+doc
// lookups scoped to one caller batch (it refuses filter groups with no filterable column), so it has no
// realistic path to exceed 5000 rows; a full-table request there is refused before it reaches this guard.
const CAP = 100000;
// The page envelope 'Page Get All' appends is loop control, not a row. Counting it as one made
// the single request limit=CAP (100000 rows + 1 envelope = 100001 items) trip this guard and
// throw, i.e. the largest legal page was the one page you could not ask for.
const rows = $input.all().filter(i => i.json && Object.keys(i.json).length && i.json._indoxApi !== 'GET_ALL_PAGE');
if (rows.length > CAP) {
  throw new Error('indox api: query returned more than ' + CAP + ' rows of incoming_documents. ' +
    'Refusing to load the table into the worker heap. Narrow the query (GET with \`filters\`) ' +
    'or page GET_ALL (limit + after/cursor), instead of asking for everything.');
}
// alwaysOutputData upstream can hand us a single empty placeholder item on a legitimate 0-row result.
// Pass it through: callers must still receive an item so their matcher runs and reports matchCount 0.
//
// [null-strip 2026-08-20] The narrow GET path ('Build Get SQL') now selects ONE json column,
// json_strip_nulls(row_to_json(...)) AS _row, so each item arrives as { _row: {...} }. Unwrap it
// here, at the single node both GET paths already pass through, so the caller-visible shape is
// unchanged and no downstream workflow needs to know. Conditional on purpose: 'Page Get All'
// (GET_ALL) shares this guard and still delivers flat tabular rows, which fall through untouched.
//
// [cutover 2026-08-31] EVERY ROW ECHOES THE REQUEST'S TENANT. GET results feed decide (which now
// throws without __instance) and re-enter as UPSERT lines — and the database row itself carries
// no tenant column, so the echo must happen exactly once, at the single node both GET paths pass
// through. Never overwrites a value a row somehow already carries.
const __ri = (() => { try { return String(($('When Called').first().json || {}).__instance || ''); } catch (e) { return ''; } })();
return $input.all().map(i => {
  const j = (i.json && i.json._row) ? i.json._row : i.json;
  if (__ri && j && typeof j === 'object' && j.__instance == null) j.__instance = __ri;
  return { json: j };
});
`,
    };

    @node({
        id: 'mg-code-build-merge-read-1',
        name: 'Build Merge Read',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-880, 1360],
    })
    BuildMergeRead = {
        jsCode: `// MERGE — the resolve_double merge writer, entry (final-indox.md CHANGE 3).
// Contract per item: { INLINE_ACTION:'MERGE', winner_id, loser_ids:[...], reason? }.
// One bounded read fetches every implicated row; the write is assembled from the
// FRESH rows, never from what the caller believed. A merge NEVER deletes.
const ops = [];
for (const it of $input.all()) {
  const j = it.json || {};
  if (String(j.INLINE_ACTION || '') !== 'MERGE') continue;
  const w = j.winner_id != null ? String(j.winner_id) : '';
  const ls = (Array.isArray(j.loser_ids) ? j.loser_ids : []).map(String).filter(x => x && x !== w);
  if (!w || !ls.length) continue;
  // [C5 2026-08-21] dup_cause travels with the verdict. It is decided by 'Adjudicate Merge',
  // which is the only place holding the whole group; by the time the write runs the losers are
  // already being absorbed and the evidence for WHY is gone.
  ops.push({ winner: w, losers: ls, reason: String(j.reason || 'resolve_double'),
             dup_cause: j.dup_cause ? String(j.dup_cause) : null });
}
if (!ops.length) throw new Error("MERGE called with no valid {winner_id, loser_ids} item");
const ids = [...new Set(ops.flatMap(o => [o.winner, ...o.losers]))];
if (ids.some(i => i.includes(','))) throw new Error('MERGE: id contains a comma: ' + ids.join(' '));
// [schema-per-instance 2026-08-27] see Build Get All SQL. Carried onto the output so Build Merge
// Write, which reads THIS node's json, writes to the same schema it read from — a merge that read
// one instance and wrote another would absorb a client's documents into someone else's winner.
const INSTANCE = String((($input.all()[0] || {}).json || {}).__instance || '');
const SCHEMA = (() => { if (!INSTANCE) throw new Error('indoxApi01 MERGE: no __instance (public fallback removed 2026-08-28). MERGE absorbs losers into a winner, so an unscoped one could fold documents from one tenant into a winner in another.');
  if (!/^[a-z][a-z0-9_]*$/.test(INSTANCE)) throw new Error('bad __instance: ' + INSTANCE);
  return 'indox_' + INSTANCE; })();
// The INSTANCE (identity), not the schema, is what travels — Build Merge Write derives its own
// schema from it. Passing the schema would put the indox_<id> convention in two places.
return [{ json: { _ops: ops, __instance: INSTANCE,
  sql: 'select * from ' + SCHEMA + '.incoming_documents where "ID" = any(string_to_array($1, \\',\\'))',
  params: [ids.join(',')] } }];`,
    };

    @node({
        id: 'mg-pg-merge-read-00000001',
        name: 'PG Merge Read',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-624, 1360],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    PgMergeRead = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryReplacement: '={{ $json.params }}',
        },
    };

    @node({
        id: 'mg-code-build-merge-write1',
        name: 'Build Merge Write',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-368, 1360],
    })
    BuildMergeWrite = {
        jsCode: `// MERGE — assemble the writes from the FRESH rows.
// Winner: absorbs ONLY fields it is missing (identity/provenance columns are never
// absorbed), gains ALSO_SEEN_AS (JSON array of loser IDs, deduped, append-only).
// Losers: STATUS='MERGED' + MERGED_INTO=winner; every provenance column untouched,
// so sync_ledger.doc_id, the board's (CONNECTION, SOURCE_ID) join and the LINK-based
// Drive match keep resolving. Reversal = clear MERGED_INTO + restore STATUS.
const meta = $('Build Merge Read').first().json;
// [schema-per-instance 2026-08-27] taken from Build Merge Read's output, NOT re-derived: the write
// must land in the same schema the read came from.
const SCHEMA = (() => { const s = String(meta.__instance || '');
  if (!s) throw new Error('indoxApi01: request carries no __instance. The public fallback was removed 2026-08-28 (cutover step 2); every caller must name its instance. public never meant no tenant, it meant whichever tenant public resolves to.');
  if (!/^[a-z][a-z0-9_]*$/.test(s)) throw new Error('bad __instance: ' + s);
  return 'indox_' + s; })();
const rows = $input.all().map(i => i.json).filter(r => r && r.ID);
const byId = {};
for (const r of rows) byId[String(r.ID)] = r;
const NEVER = ['ID','SOURCE_TYPE','SOURCE_ID','SOURCE_LINK','HASH','LINK','CONNECTION', 'LINK_CONNECTION', 'SYNC_CONNECTION','SYNC_NAME',
  'SIZE','STATUS','MERGED_INTO','ALSO_SEEN_AS','TIMESTAMP','RECEIVED_DATE',
  'DOUBLE_LINE_CONTEXT','ERROR','REQUIRED_ACTION','ITERATION_COUNT','NEXT_RETRY_AT','RETRY_COUNT',
  'EMPTY','created_at','updated_at'];
const bad = v => v === undefined || v === null || v === '' || String(v).toLowerCase() === 'unknown';
const out = [];
// [2026-08-20] nowMs went with the ACTION_LOG merge stamps that were its only reader.
const execId = (typeof $execution !== 'undefined' && $execution.id) || '';
const q = c => '"' + String(c).replace(/"/g, '""') + '"';
for (const op of meta._ops) {
  const w = byId[op.winner];
  if (!w) throw new Error('MERGE winner not found: ' + op.winner);
  if (String(w.STATUS || '') === 'MERGED') throw new Error('MERGE winner ' + op.winner + ' is itself MERGED (into ' + (w.MERGED_INTO || '?') + ')');
  const missing = op.losers.filter(id => !byId[id]);
  if (missing.length) throw new Error('MERGE loser(s) not found: ' + missing.join(','));
  const live = op.losers.map(id => byId[id]).filter(l => String(l.STATUS || '') !== 'MERGED');
  const absorb = {};
  for (const l of live) {
    for (const [k, v] of Object.entries(l)) {
      if (NEVER.includes(k) || k.startsWith('_') || bad(v)) continue;
      if (!bad(w[k])) continue;
      if (absorb[k] === undefined) absorb[k] = v;
    }
  }
  let seen = [];
  try { const a = JSON.parse(w.ALSO_SEEN_AS || '[]'); if (Array.isArray(a)) seen = a.map(String); } catch (e) {}
  for (const l of live) if (!seen.includes(String(l.ID))) seen.push(String(l.ID));
  // [2026-08-20] The ACTION_LOG appends on both sides of a merge went with the column. A merge is
  // already recorded structurally and durably: the winner keeps ALSO_SEEN_AS (every absorbed ID),
  // the loser keeps STATUS='MERGED' + MERGED_INTO. Neither side needed a prose line to say so.
  // [C5 2026-08-21] DUP_CAUSE rides onto the WINNER -- the row that survives to be counted.
  // The column answers 'why did this document ever have a twin', which is what turns 4,714
  // undifferentiated groups into a ranked defect list and, afterwards, lets a prevention be
  // shown to have worked.
  const wcols = { ...absorb, ALSO_SEEN_AS: JSON.stringify(seen),
    ...(op.dup_cause ? { DUP_CAUSE: op.dup_cause } : {}) };
  // [priority-skip carry 2026-08-25, owner order] A BLOCK FLAG SURVIVES A MERGE: the surviving
  // main is blocked if ANY member of the group was. The absorb rule above cannot carry it — it
  // copies only into MISSING winner fields, and an explicit false on the winner blocks the copy.
  // Measured live 2026-08-25: 557922's marked loser merged into an unmarked winner, which then
  // synced to Priority. TEXT-boolean normalised like every other boolean on this row.
  if ([w, ...live].some(d => String(d.PRIORITY_SKIP ?? '').trim().toLowerCase() === 'true')) {
    wcols.PRIORITY_SKIP = true;
  }
  {
    const params = []; const sets = [];
    for (const [c, v] of Object.entries(wcols)) {
      params.push(typeof v === 'object' ? JSON.stringify(v) : String(v));
      sets.push(q(c) + ' = $' + params.length);
    }
    params.push(String(w.ID));
    out.push({ json: { sql: 'update ' + SCHEMA + '.incoming_documents set ' + sets.join(', ') + ' where ' + q('ID') + ' = $' + params.length, params } });
  }
  // [C6 2026-08-21] A MERGE MUST BE REVERSIBLE, AND UNTIL NOW IT WAS NOT.
  //
  // The loser recorded only STATUS='MERGED' + MERGED_INTO. Three columns built for exactly this
  // -- STATUS_BEFORE_MERGE, MERGED_AT, MERGE_BATCH_ID -- and the whole merge_audit table (17
  // columns, already holding 3,520 DRY-RUN rows) were never written by the live path. So a merge
  // could be undone only by GUESSING what the loser's STATUS had been, and a bad batch could not
  // be identified at all, let alone rolled back as a unit.
  //
  // Not theoretical: cycle 3's status flip un-merged 665 rows and left MERGED_INTO dangling, and
  // only 209 were restorable -- from merge_audit's dry-run rows, because the live path had
  // written nothing.
  //
  // MERGE_BATCH_ID is derived from the execution id, so every loser absorbed by one execution
  // shares a batch and 'undo that run' becomes a single WHERE clause. COALESCE on
  // STATUS_BEFORE_MERGE keeps the FIRST pre-merge status if a row is ever re-merged.
  for (const l of live) {
    out.push({ json: { sql: 'update ' + SCHEMA + '.incoming_documents set "STATUS" = \\'MERGED\\', "MERGED_INTO" = $1, ' +
        '"STATUS_BEFORE_MERGE" = COALESCE("STATUS_BEFORE_MERGE", $3), "MERGED_AT" = now(), ' +
        '"MERGE_BATCH_ID" = md5(\\'exec:\\' || $4)::uuid where "ID" = $2',
      params: [String(w.ID), String(l.ID), String(l.STATUS || ''), String(execId || 'unknown')] } });
    // The audit row is the undo log. loser_snapshot is the whole row as it stood, so a restore
    // never has to reconstruct anything by inference.
    // The action column is CHECK-constrained to MERGE / ATTACH / REVIEW -- uppercase. tier is the
    // CONFIDENCE band the 3,520 existing dry-run rows already use (A = same bytes, B1 = two rows
    // agree, B2 = attach), NOT the duplicate's cause; conflating the two would have made the
    // live rows unreadable next to the dry-run ones. dup_cause gets its own column.
    const _tier = op.reason === 'same-hash' ? 'A' : (op.reason === 'two-rows-agree' ? 'B1' : 'B1');
    out.push({ json: { sql: 'insert into ' + SCHEMA + '.merge_audit (batch_id, dry_run, merged_at, action, ' +
        'winner_id, loser_id, company_id, doc_key, tier, reason, dup_cause, loser_status_before, ' +
        'loser_snapshot, loser_api_tools_id) values (md5(\\'exec:\\' || $1)::uuid, false, now(), ' +
        '\\'MERGE\\', $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)',
      params: [String(execId || 'unknown'), String(w.ID), String(l.ID),
               String(l.COMPANY_ID || ''), String(l.DOC_ID || ''),
               _tier, String(op.reason || ''), String(op.dup_cause || ''),
               String(l.STATUS || ''), JSON.stringify(l), String(l.API_TOOLS_ID || '')] } });
  }
}
if (!out.length) throw new Error('MERGE resolved to zero writes — every named loser is already MERGED; nothing to do is a caller bug here');
return out;`,
    };

    @node({
        id: 'mg-pg-merge-write-0000001',
        name: 'PG Merge Write',
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [-112, 1360],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
    })
    PgMergeWrite = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {
            queryReplacement: '={{ $json.params }}',
        },
    };

    @node({
        id: 'mg-emit-ids-0001',
        name: 'Merge Emit IDs',
        /*__n8n__*/ notes: "The documents this MERGE touched -- the set whose doc_action locks must now be released. Mirrors 'API Emit IDs' on the upsert path; that node's own note calls the upsert 'the one step every action necessarily ends with', which is true of every action EXCEPT this one. A merge ends here, at PG Merge Write, and nothing on this branch unlocked. Audited 2026-08-23: 977 of 1,203 live doc_action locks were ::action_merge_doubles and 364 of 400 sampled sat on a CLOSED dispatch bracket -- 81% of the lock population held by actions that had already finished, expiring only by TTL (measured up to 4,358s). Reads _ops from 'Build Merge Read' rather than this node's input, the same source 'Merge Result' trusts. Emits winner AND losers: the driver dispatched on the group MAIN and pickWinner may have made it either one, and a doc-scoped unlock on a document holding no lock is a no-op.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [144, 1360],
    })
    MergeEmitIds = {
        jsCode: `const meta = $('Build Merge Read').first().json;
const out = new Set();
for (const o of ((meta && meta._ops) || [])) {
  if (o && o.winner) out.add(String(o.winner));
  for (const l of ((o && o.losers) || [])) if (l) out.add(String(l));
}
// NEVER return an empty array. This node is in the chain that ends at 'Merge Result', which is
// what the caller receives; emitting nothing would stop the branch and the MERGE op would answer
// with no envelope at all. The sentinel unlocks a key that cannot exist, which is a no-op.
if (!out.size) return [{ json: { ID: '__no_merge_ids__' } }];
return [...out].map(ID => ({ json: { ID } }));`,
    };

    @node({
        id: 'mg-unlock-doc-0001',
        name: 'Merge Unlock Doc',
        /*__n8n__*/ notes: "Release the doc_action lock for a completed MERGE. Same contract as 'API Unlock Doc': PROCESS=doc_action, KEY is the BARE doc id, and processLock01's doc-scoped unlock scan-deletes '<ID>::*' so this workflow does not need to know the action name. onError=continue for the same reason too -- a lock-service blip must never fail a merge that already succeeded, and the TTL remains the backstop. This is a separate node rather than a second feeder into 'API Unlock Doc' so the upsert path is left completely untouched.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [368, 1360],
        onError: 'continueRegularOutput',
    })
    MergeUnlockDoc = {
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
                KEY: '={{ $json.ID }}',
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
        options: {},
    };

    @node({
        id: 'mg-code-merge-result-0001',
        name: 'Merge Result',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [592, 1360],
    })
    MergeResult = {
        jsCode: `// MERGE — result envelope for the caller (mirrors the api's success shapes).
const meta = $('Build Merge Read').first().json;
return [{ json: { success: true,
  merged: meta._ops.map(o => ({ winner: o.winner, losers: o.losers, reason: o.reason })) } }];`,
    };

    @node({
        id: 'api-emit-ids',
        name: 'API Emit IDs',
        /*__n8n__*/ notes: "Which documents this upsert touched — the set whose doc_step locks must now be released.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1168, 128],
    })
    ApiEmitIds = {
        jsCode: `// [unlock gate REVERTED 2026-08-13] Unconditional again. The opt-in gate starved the machine:
// locks went 998 -> 2,845 and 663 of ~1,000 recent ACTION_LOG stamps were "BLOCKED BY LOCK", with
// completions falling from ~500/hr to 13/hr. Cause was incomplete caller coverage, not the idea -
// passthrough upsert paths that reach the call through an IF node had no Set builder to carry the
// flag. Re-introduce the gate only once EVERY upsert path provably sets unlock=true.
// VERBATIM from indoxDocBatchUpsert01/'SB Emit IDs', re-homed here so the unlock lives at the
// upsert — the one step every action necessarily ends with.
//
// The multi-source fallback is load-bearing: $('...') returns 0 items when a node reference goes
// stale after a sub-call, which silently skipped the unlock and leaked doc_action locks (INCR-ed,
// never DELETE-d). Keep all three sources.
const out = new Set();
const add = (items) => { for (const i of (items||[])) { try { const id = i && i.json && (i.json.ID != null ? i.json.ID : i.json.id); if (id != null && id !== '') out.add(String(id)); } catch(e){} } };
try { add($('Resolve IDs').all()); } catch(e){}
if (!out.size) { try { add($('Strip Control').all()); } catch(e){} }
if (!out.size) { try { add($input.all()); } catch(e){} }
return [...out].map(ID => ({ json: { ID } }));`,
    };

    @node({
        id: 'api-unlock-doc',
        name: 'API Unlock Doc',
        /*__n8n__*/ notes: "[doc-scoped 2026-08-16] Release the doc_action lock — THE ONLY unlock in the system (owner order; the router's late Unlock Doc Action was removed: it could wrongly release a lock another driver had already taken for the doc's NEXT action). KEY is the BARE doc ID: processLock01's unlock now scan-deletes '<ID>::*' for bare keys, which releases the completing action's '<ID>::<ACTION>' lock without this workflow needing to know the action name. (History: this node passed the bare ID against compound keys for weeks — a silent NO-OP; the doc-scoped unlock in processLock01 is what made it real.) Safe: at upsert time the doc's only doc_action lock is the completing action's own. onError=continue: a lock-service blip must never fail an upsert that already succeeded — TTL is the backstop.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1424, 128],
        onError: 'continueRegularOutput',
    })
    ApiUnlockDoc = {
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
                KEY: '={{ $json.ID }}',
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
        options: {},
    };

    @node({
        id: 'ifmgmt-0000-4000-8000-00000000c0de',
        name: 'If Management',
        type: 'n8n-nodes-base.if',
        version: 2,
        position: [-1440, -16],
    })
    IfManagement = {
        conditions: {
            options: {
                caseSensitive: true,
                leftValue: '',
                typeValidation: 'strict',
                version: 1,
            },
            conditions: [
                {
                    id: 'm1',
                    leftValue: '={{ $json.INLINE_ACTION }}',
                    rightValue: 'RESET',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
                {
                    id: 'm2',
                    leftValue: '={{ $json.INLINE_ACTION }}',
                    rightValue: 'STATUS',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
                {
                    id: 'm3',
                    leftValue: '={{ $json.INLINE_ACTION }}',
                    rightValue: 'INJECT',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
                {
                    id: 'm4',
                    leftValue: '={{ $json.INLINE_ACTION }}',
                    rightValue: 'SCAN',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'or',
        },
        options: {},
    };

    @node({
        id: 'callsync-000-4000-8000-00000000c0de',
        name: 'Call Sync Api',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [-1200, -208],
    })
    CallSyncApi = {
        workflowId: {
            __rl: true,
            value: 'SyncApi0000000001',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'upsadapt-000-4000-8000-00000000c0de',
        name: 'UPSERT Adapter',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-624, 128],
    })
    UpsertAdapter = {
        jsCode: `// [fold 2026-08-12] RE-HOMED FROM indoxDocBatchUpsert01. Two changes vs the original, both
// forced by the new position (inside indox api's UPSERT branch, after 'Strip Control'):
//   * reads $input instead of $input — that was Batch Upsert's
//     trigger and does not exist here, which threw "Referenced node doesn't exist".
//   * no longer stamps INLINE_ACTION='UPSERT' — that verb existed to ROUTE into this workflow; the
//     Action switch has already routed and Strip Control already removed it, so re-adding it would
//     hand PG Upsert (autoMapInputData) a non-existent column.
// The canonicalisation itself is untouched.
// [data quality 2026-08-11] WRITE-TIME CANONICALISATION AT THE ESTATE'S SINGLE WRITER.
//
// WHY HERE. Every write to incoming_documents funnels through this node: 25 executeWorkflow
// callers across 10 workflows (both Gmail downloaders, the driver, all four routers, the
// central Upsert). It is the only place a value rule can be stated ONCE and not be bypassable.
// The alternative -- repeating a normaliser in each Build:* Set node -- is how the estate got
// here: 'Build: ... - Doc Total Amount' and 'Build: ... - Doc Date' (the Query* paths) ALREADY
// normalise, while 'Build Per Type Upsert' / 'Build Base Doc Upsert' (the two-point paths)
// write the extractor's raw string. Two of four writers normalise; the column holds the union.
//
// MEASURED ON LIVE DATA 2026-08-11 (audit): DOC_TOTAL_AMOUNT present on 5,632 COMPLETED, of
// which 1,359 (24%) cannot be cast to numeric -- 1,319 thousands-separated ('1,234.56') and 21
// ambiguous ('9,9,9'). DOC_DATE holds ISO (4,876), dd/mm/yyyy (3,850) and 376 other forms
// including 331 two-digit years, 1 in Eastern-Arabic numerals, and 16 IMPOSSIBLE dates -- some
// of them US month-first ('05/24/2026', '11/26/0081') leaking into a day-first column, plus
// junk years 0027 / 0081 / 0153 / 2045 / 2076 / 9998.
//
// THREE VERDICTS, AND THE THIRD IS THE POINT:
//   ok     -- the value is already well formed. Written through BYTE-IDENTICAL. No consumer
//             sees a change; ISO dates are validated and then deliberately NOT reformatted.
//   fix    -- the value is recoverable by a rule that cannot guess: strip thousands separators,
//             expand a 2-digit year, transliterate Eastern-Arabic digits, or swap a month-first
//             date whose month field is >12 (impossible day-first, so the swap is forced, not
//             inferred).
//   reject -- the value cannot be a number / cannot be a date. THE KEY IS DELETED, so the
//             existing column is left untouched rather than overwritten with garbage. This
//             mirrors the estate's own 'key OMITTED, never set false' discipline in
//             'Select Base Values' and 'Select Per Type Values'.
//
// DELIBERATELY DOES NOT TOUCH THE *_COMPLETED FLAGS. A rejected value arrives in the same item
// as DOC_DATE_COMPLETED / DOC_TOTAL_AMOUNT_COMPLETED = true, and clearing those would re-open
// invoiceDecide's \`!doc.DOC_DATE && !doc.DOC_DATE_COMPLETED\` gate on a source that will keep
// producing the same unusable string -- a livelock. Rejecting the VALUE only is strictly
// subtractive: it removes garbage and can neither add a dispatch nor change any gate's verdict.
//
// SCOPE IS EXACTLY TWO COLUMNS. SHORT_DOC_ID is NOT sanitised here even though the '00000'
// sentinel is a live defect: gdocHead re-dispatches get_short_doc_id whenever SHORT_DOC_ID is
// absent or != the value derived from COMPANY_DOC_ID, so DROPPING the key would livelock every
// document whose COMPANY_DOC_ID has no alphanumerics. That defect belongs in 'Resolve IDs'
// (which must not accept an all-zero SHORT_DOC_ID as an identity key) and in gdocHead.
const __dqAscii = s => String(s).replace(/[\\u0660-\\u0669]/g, d => String(d.charCodeAt(0) - 0x0660));

// AMOUNT. Accepts plain numerics and comma-GROUPED numerics only. A comma that is not a valid
// thousands separator ('9,9,9') is ambiguous between a separator and a decimal mark, so it is
// rejected rather than guessed at. Sign and parenthesised negatives are preserved; zero and
// negative totals are NOT rejected (a credit note is a business fact, not a format defect).
function __dqAmount(raw){
  const orig = String(raw).trim();
  let s = __dqAscii(orig).replace(/[\\s\\u00A0]/g,'').replace(/[\\u20AA\\u20AC\\u00A3$]/g,'');
  let neg = false;
  if (/^\\(.*\\)$/.test(s)) { neg = true; s = s.slice(1,-1); }
  if (/^[-+]/.test(s)) { neg = neg || s.charAt(0) === '-'; s = s.slice(1); }
  let core = null;
  if (/^\\d+(\\.\\d+)?$/.test(s))              core = s;
  else if (/^\\d{1,3}(,\\d{3})+(\\.\\d+)?$/.test(s)) core = s.replace(/,/g,'');
  else return { verdict:'reject' };
  if (!isFinite(Number(core))) return { verdict:'reject' };
  const val = (neg ? '-' : '') + core;
  return val === orig ? { verdict:'ok' } : { verdict:'fix', val:val };
}

// DATE. Two accepted canonical forms, both unambiguous: ISO yyyy-mm-dd (validated, never
// reformatted) and day-first dd/mm/yyyy. A value that matches neither recognised SHAPE is left
// exactly as it arrived -- this filter only removes values it can PROVE are impossible.
function __dqDim(y,m){ return new Date(Date.UTC(y, m, 0)).getUTCDate(); }
function __dqDate(raw){
  const orig = String(raw).trim();
  if (orig === '') return { verdict:'reject' };
  const s = __dqAscii(orig).replace(/\\s+/g,'');
  const YMAX = new Date().getUTCFullYear() + 1;
  const ok = (y,m,d) => y >= 1990 && y <= YMAX && m >= 1 && m <= 12 && d >= 1 && d <= __dqDim(y,m);
  const dmy = (y,m,d) => String(d).padStart(2,'0') + '/' + String(m).padStart(2,'0') + '/' + y;
  let mm;
  // Excel serial -- the same rule 'Selection & Scoring Logic1'/normalizeDate already applies.
  if ((mm = s.match(/^(\\d{5})(\\.\\d+)?$/))) {
    const dt = new Date(Math.round((parseFloat(s) - 25569) * 86400 * 1000));
    if (isNaN(dt.getTime())) return { verdict:'reject' };
    const y = dt.getUTCFullYear(), m = dt.getUTCMonth() + 1, d = dt.getUTCDate();
    return ok(y,m,d) ? { verdict:'fix', val: dmy(y,m,d) } : { verdict:'reject' };
  }
  // ISO, with or without a trailing time. Validate; keep the caller's exact string.
  if ((mm = s.match(/^(\\d{4})-(\\d{2})-(\\d{2})(?:[T ].*)?$/))) {
    return ok(+mm[1], +mm[2], +mm[3]) ? { verdict:'ok' } : { verdict:'reject' };
  }
  // Day-first family: d/m/y, d.m.y, d-m-y, 2- or 4-digit year.
  if ((mm = s.match(/^(\\d{1,2})([\\/.\\-])(\\d{1,2})\\2(\\d{2,4})$/))) {
    let d = +mm[1], m = +mm[3];
    const ys = mm[4];
    if (ys.length === 3) return { verdict:'reject' };
    const y = ys.length === 2 ? 2000 + (+ys) : +ys;
    // MONTH-FIRST CONTAMINATION. m>12 is impossible as a month, and d<=12 makes the swapped
    // reading the only one that yields a real date. Forced, not inferred; when d is also >12
    // no reading works and the value is rejected below.
    if (m > 12 && d <= 12) { const t = d; d = m; m = t; }
    if (!ok(y,m,d)) return { verdict:'reject' };
    const val = dmy(y,m,d);
    return val === orig ? { verdict:'ok' } : { verdict:'fix', val:val };
  }
  return { verdict:'ok' };
}

const __DQ = { DOC_DATE: __dqDate, DOC_TOTAL_AMOUNT: __dqAmount };
const src=$input.all().map(i=>i.json); const out=[];
for(const it of src){ const j={...it}; delete j.__force_backend; delete j._be; delete j.unlock; delete j.LOCAL_STATUS; delete j.AI_STATUS;
  for(const k of Object.keys(j)){ const v=j[k]; if(v===null||v===undefined) delete j[k]; }
  for (const __c of Object.keys(__DQ)) {
    if (j[__c] === undefined) continue;
    const __r = __DQ[__c](j[__c]);
    if (__r.verdict === 'fix') j[__c] = __r.val;
    else if (__r.verdict === 'reject') delete j[__c];
  }
  if(!(j.ID||j.SOURCE_TYPE||j.HASH||j.NAME||j.LINK||j.SOURCE_ID||j.SOURCE_LINK)) continue; /* skip spurious empty registrations (no id + no identifying data) -> prevents NULL docs */
  out.push({json:j}); }
return out;
`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.IfManagement.in(0));
        this.ApiActionSwitch.out(0).to(this.StripControl.in(0));
        this.ApiActionSwitch.out(1).to(this.BuildGetAllSql.in(0));
        this.ApiActionSwitch.out(2).to(this.BuildGetSql.in(0));
        this.ApiActionSwitch.out(3).to(this.PgDelete.in(0));
        this.ApiActionSwitch.out(4).to(this.BuildTableGet.in(0));
        this.ApiActionSwitch.out(5).to(this.BuildTableUpsert.in(0));
        this.ApiActionSwitch.out(6).to(this.BuildDeliver.in(0));
        this.ApiActionSwitch.out(7).to(this.BuildMergeRead.in(0));
        this.ApiActionSwitch.out(8).to(this.GetChangedDocs.in(0));
        this.StripControl.out(0).to(this.UpsertAdapter.in(0));
        this.LoadMatchIndex.out(0).to(this.ResolveIds.in(0));
        this.ResolveIds.out(0).to(this.BuildBulkUpsertSql.in(0));
        this.BuildGetSql.out(0).to(this.PgGet.in(0));
        this.BuildTableGet.out(0).to(this.PgTableGet.in(0));
        this.BuildTableUpsert.out(0).to(this.PgTableUpsert.in(0));
        this.Keepalive.out(0).to(this.KeepaliveNoop.in(0));
        this.BuildDeliver.out(0).to(this.PgDeliverInsert.in(0));
        this.PgDeliverInsert.out(0).to(this.DeliverFetchReq.in(0));
        this.DeliverFetchReq.out(0).to(this.PgDeliverFetch.in(0));
        this.BuildMatchIndexSql.out(0).to(this.LoadMatchIndex.in(0));
        this.PgGet.out(0).to(this.GuardGetSize.in(0));
        this.PgGetAll.out(0).to(this.PageGetAll.in(0));
        this.BuildMergeRead.out(0).to(this.PgMergeRead.in(0));
        this.PgMergeRead.out(0).to(this.BuildMergeWrite.in(0));
        this.BuildMergeWrite.out(0).to(this.PgMergeWrite.in(0));
        this.PgMergeWrite.out(0).to(this.MergeEmitIds.in(0));
        this.ApiEmitIds.out(0).to(this.ApiUnlockDoc.in(0));
        this.IfManagement.out(0).to(this.CallSyncApi.in(0));
        this.IfManagement.out(1).to(this.ApiActionSwitch.in(0));
        this.UpsertAdapter.out(0).to(this.BuildMatchIndexSql.in(0));
        this.BuildBulkUpsertSql.out(0).to(this.PgBulkUpsert.in(0));
        this.PgBulkUpsert.out(0).to(this.RestoreUpsertedDocs.in(0));
        this.RestoreUpsertedDocs.out(0).to(this.ApiEmitIds.in(0));
        this.BuildGetAllSql.out(0).to(this.PgGetAll.in(0));
        this.PageGetAll.out(0).to(this.GuardGetSize.in(0));
        this.MergeEmitIds.out(0).to(this.MergeUnlockDoc.in(0));
        this.MergeUnlockDoc.out(0).to(this.MergeResult.in(0));
    }
}
