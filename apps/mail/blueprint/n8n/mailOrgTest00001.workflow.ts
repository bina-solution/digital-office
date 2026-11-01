import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : mail-organizer E2E Test
// Nodes   : 37  |  Connections: 40
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RunMailOrganizerTest               manualTrigger
// LaneWebhook                        webhook
// TestConnectionsReq                 code
// TestConnections                    executeWorkflow            [alwaysOutput] [retry]
// Config                             code
// CleanupPrior                       postgres                   [creds] [alwaysOutput]
// LaneSwitch                         switch
// LeSeedReq                          code
// LeSeed                             executeWorkflow            [alwaysOutput] [retry]
// LePreReq                           code
// LePre                              executeWorkflow            [alwaysOutput]
// LeRules                            code                       [alwaysOutput]
// LeEngineReq                        code
// LeEngine                           executeWorkflow            [alwaysOutput]
// LePostReq                          code
// LePost                             executeWorkflow            [alwaysOutput]
// LeUnitReq                          code
// LeUnit                             executeWorkflow            [alwaysOutput]
// LeRun                              executeWorkflow            [alwaysOutput]
// LeW1Watch                          postgres                   [creds] [alwaysOutput] [retry]
// LeW1Guard                          code                       [alwaysOutput]
// LeW1Ready                          if
// LeW1Sleep                          postgres                   [creds] [alwaysOutput]
// LeDocs                             postgres                   [creds] [alwaysOutput]
// AssertLe                           code
// SlSeedReq                          code
// SlSeed                             executeWorkflow            [alwaysOutput] [retry]
// SlEngineReq                        code
// SlEngine                           executeWorkflow            [alwaysOutput]
// SlRules                            code                       [alwaysOutput]
// SlLabelsReq                        code
// SlLabels                           executeWorkflow            [alwaysOutput]
// AssertSl                           code
// Chain1AllOnly                      if
// ChainSummaryAllOnly                if
// TestSummary                        code
// RespondLane                        respondToWebhook           [onError→regular]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RunMailOrganizerTest
//    → TestConnectionsReq
//      → TestConnections
//        → Config
//          → CleanupPrior
//            → LaneSwitch
//              → LeSeedReq
//                → LeSeed
//                  → LePreReq
//                    → LePre
//                      → LeRules
//                        → LeEngineReq
//                          → LeEngine
//                            → LePostReq
//                              → LePost
//                                → LeUnitReq
//                                  → LeUnit
//                                    → LeRun
//                                      → LeW1Watch
//                                        → LeW1Guard
//                                          → LeW1Ready
//                                            → LeDocs
//                                              → AssertLe
//                                                → Chain1AllOnly
//                                                  → SlSeedReq
//                                                    → SlSeed
//                                                      → SlEngineReq
//                                                        → SlEngine
//                                                          → SlRules
//                                                            → SlLabelsReq
//                                                              → SlLabels
//                                                                → AssertSl
//                                                                  → ChainSummaryAllOnly
//                                                                    → TestSummary
//                                                                  → RespondLane
//                                                → RespondLane (↩ loop)
//                                           .out(1) → LeW1Sleep
//                                              → LeW1Watch (↩ loop)
//             .out(1) → SlSeedReq (↩ loop)
//             .out(2) → LeSeedReq (↩ loop)
// LaneWebhook
//    → TestConnectionsReq (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"▶ Run Mail Organizer Test":{"main":[[{"node":"Test Connections Req","type":"main","index":0}]]},"Lane Webhook":{"main":[[{"node":"Test Connections Req","type":"main","index":0}]]},"Test Connections Req":{"main":[[{"node":"Test Connections","type":"main","index":0}]]},"Test Connections":{"main":[[{"node":"Config","type":"main","index":0}]]},"Config":{"main":[[{"node":"Cleanup Prior","type":"main","index":0}]]},"Cleanup Prior":{"main":[[{"node":"Lane Switch","type":"main","index":0}]]},"Lane Switch":{"main":[[{"node":"LE Seed Req","type":"main","index":0}],[{"node":"SL Seed Req","type":"main","index":0}],[{"node":"LE Seed Req","type":"main","index":0}]]},"LE Seed Req":{"main":[[{"node":"LE Seed","type":"main","index":0}]]},"LE Seed":{"main":[[{"node":"LE Pre Req","type":"main","index":0}]]},"LE Pre Req":{"main":[[{"node":"LE Pre","type":"main","index":0}]]},"LE Pre":{"main":[[{"node":"LE Rules","type":"main","index":0}]]},"LE Rules":{"main":[[{"node":"LE Engine Req","type":"main","index":0}]]},"LE Engine Req":{"main":[[{"node":"LE Engine","type":"main","index":0}]]},"LE Engine":{"main":[[{"node":"LE Post Req","type":"main","index":0}]]},"LE Post Req":{"main":[[{"node":"LE Post","type":"main","index":0}]]},"LE Post":{"main":[[{"node":"LE Unit Req","type":"main","index":0}]]},"LE Unit Req":{"main":[[{"node":"LE Unit","type":"main","index":0}]]},"LE Unit":{"main":[[{"node":"LE Run","type":"main","index":0}]]},"LE Run":{"main":[[{"node":"LE W1 Watch","type":"main","index":0}]]},"LE W1 Watch":{"main":[[{"node":"LE W1 Guard","type":"main","index":0}]]},"LE W1 Guard":{"main":[[{"node":"LE W1 Ready?","type":"main","index":0}]]},"LE W1 Ready?":{"main":[[{"node":"LE Docs","type":"main","index":0}],[{"node":"LE W1 Sleep","type":"main","index":0}]]},"LE W1 Sleep":{"main":[[{"node":"LE W1 Watch","type":"main","index":0}]]},"LE Docs":{"main":[[{"node":"Assert LE","type":"main","index":0}]]},"SL Seed Req":{"main":[[{"node":"SL Seed","type":"main","index":0}]]},"SL Seed":{"main":[[{"node":"SL Engine Req","type":"main","index":0}]]},"SL Engine Req":{"main":[[{"node":"SL Engine","type":"main","index":0}]]},"SL Engine":{"main":[[{"node":"SL Rules","type":"main","index":0}]]},"SL Rules":{"main":[[{"node":"SL Labels Req","type":"main","index":0}]]},"SL Labels Req":{"main":[[{"node":"SL Labels","type":"main","index":0}]]},"SL Labels":{"main":[[{"node":"Assert SL","type":"main","index":0}]]},"Assert LE":{"main":[[{"node":"Chain 1 (all only)","type":"main","index":0},{"node":"Respond Lane","type":"main","index":0}]]},"Chain 1 (all only)":{"main":[[{"node":"SL Seed Req","type":"main","index":0}]]},"Assert SL":{"main":[[{"node":"Chain Summary (all only)","type":"main","index":0},{"node":"Respond Lane","type":"main","index":0}]]},"Chain Summary (all only)":{"main":[[{"node":"🏁 Test Summary","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"cf994cba-b6d0-53fa-8729-2b8d0c21b28f","name":"app:mail"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"333960da-8376-4dd1-8b39-c3d4b448ca86","name":"mail-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"mailOrgTest00001","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'mailOrgTest00001',
    name: 'mail-organizer E2E Test',
    active: false,
    isArchived: false,
    tags: ['indox', 'app:mail', 'indox-app', 'mail-app', 'lifecycle:test'],
    settings: { executionOrder: 'v1', executionTimeout: 600, callerPolicy: 'workflowsFromSameOwner' },
})
export class MailOrganizerE2eTestWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'mo-run-run-mail-organizer-test',
        name: '▶ Run Mail Organizer Test',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-820, 300],
    })
    RunMailOrganizerTest = {};

    @node({
        id: 'mo-lane-webhook',
        webhookId: 'mail-organizer-lane-0001',
        name: 'Lane Webhook',
        type: 'n8n-nodes-base.webhook',
        version: 2,
        position: [-820, 460],
    })
    LaneWebhook = {
        httpMethod: 'POST',
        path: 'mail-organizer-e2e-lane',
        responseMode: 'responseNode',
        options: {},
    };

    @node({
        id: 'mo-testconn-req',
        name: 'Test Connections Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-760, 380],
    })
    TestConnectionsReq = {
        jsCode: `// ONE deterministic connections read for the whole suite (phase-4 tenant cutover).
// The mail-profile-enumeration block is gone: the test tenant's identities are SEEDED into
// indox_test.settings under key='test_connections' ({drive_connection_id, mail_connection_id,
// drive_profile_id}) and this is the only place a suite may learn them. __instance:'test'
// selects the indox_test schema; instance:'*' spans that schema's component rows -- the same
// pair syncV3Main0001's Registry Req sends, for the same reason.
return [{json:{INLINE_ACTION:'TABLE_GET', table:'settings', __instance:'test', instance:'*', filter:{key:'test_connections'}}}];`,
    };

    @node({
        id: 'mo-testconn',
        name: 'Test Connections',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [-680, 380],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    TestConnections = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'mo-config',
        name: 'Config',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-600, 380],
    })
    Config = {
        jsCode: `const lane=(()=>{try{return ($('Lane Webhook').first().json.body||{}).lane||'all';}catch(e){return 'all';}})();
// TENANT GATE (phase-4 cutover). This suite seeds mail, deletes rows and asserts documents, so
// it may only ever run against the test tenant -- schema indox_test.
// [pin-is-dead 2026-08-31] The suite MINTS the tenant (G64 R7 pins the literal): REST-run pins
// never reach a manualTrigger's item, so requiring the trigger to carry it meant '' and a throw.
// A lane webhook that names a DIFFERENT tenant is still refused loudly.
const __up=(()=>{
  try{const b=($('Lane Webhook').first().json.body||{}); if(b.__instance) return String(b.__instance);}catch(e){}
  return '';
})();
if(__up && __up!=='test') throw new Error("mailOrgTest00001: lane webhook carries __instance "+JSON.stringify(__up)+" -- this suite runs only against the test tenant (indox_test).");
const __instance='test';
// THE MAILBOX COMES FROM THE TENANT, NOT FROM DISCOVERY (phase-4). The embedded
// mail-profile-enumeration block is deleted: the test tenant's identities live in
// indox_test.settings key='test_connections' and arrive via the one 'Test Connections' node
// upstream. A lane webhook may still hand in a mailbox explicitly (the runner does); everything
// else resolves from the seeded row's mail_connection_id.
const tc=(()=>{try{const r=$('Test Connections').first().json||{}; const v=r.value; if(v===undefined||v===null||v==='') return null; return (typeof v==='string')?JSON.parse(v):v;}catch(e){return null;}})();
if(!tc) throw new Error("mailOrgTest00001: no readable indox_test.settings row key='test_connections' -- seed it ({drive_connection_id, mail_connection_id, drive_profile_id}) before running this suite.");
let connection_id=(()=>{try{return ($('Lane Webhook').first().json.body||{}).connection_id||'';}catch(e){return '';}})();
if(!connection_id) connection_id=String(tc.mail_connection_id||'');
// BELT (kept from the discovery era). A non-local id means the mail engine is bound to a real
// account — refuse it and let the ops fail loudly rather than seed fixture mail into someone's
// live mailbox.
if(connection_id && !connection_id.startsWith('mail_imap_local-')) connection_id='';
// run-unique token: every lane's mail + ledger rows are scoped to THIS execution
return [{json:{lane, __instance, tok:String($execution.id||Date.now()), connection_id}}];`,
    };

    @node({
        id: 'mo-cleanup-prior',
        name: 'Cleanup Prior',
        /*__n8n__*/ notes: "[sync item 2026-09-02] sync_attempt is FOLDED into sync_ledger (attempts/not_before/last_error live on the ledger row; schema.sql, migration 2026-09-02_sync_item.sql) — the delete that named it made this node die with 'relation does not exist' before any lane ran. The ledger delete below already removes this run's attempt state.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [-380, 380],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    CleanupPrior = {
        operation: 'executeQuery',
        query: `=with a as (delete from indox_test.incoming_documents where "SYNC_NAME" like 'mailorg\\_%' returning 1),
 b as (delete from indox_test.sync_ledger where regexp_replace(source,'^[^/]*/','') like 'mailorg\\_%' returning 1),
 d as (delete from indox_test.sync_cursor where regexp_replace(source,'^[^/]*/','') like 'mailorg\\_%' returning 1),
 e as (delete from public.drive_files where folder like 'mailorg\\_%' returning 1)
select (select count(*) from a)::int as docs,(select count(*) from b)::int as ledger`,
        options: {},
    };

    @node({
        id: 'mo-lane-switch',
        name: 'Lane Switch',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [-160, 380],
    })
    LaneSwitch = {
        rules: {
            values: [
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'label-engine',
                                leftValue: "={{ $('Config').first().json.lane }}",
                                rightValue: 'label-engine',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'label-engine',
                },
                {
                    conditions: {
                        options: {
                            caseSensitive: true,
                            typeValidation: 'loose',
                            version: 2,
                        },
                        conditions: [
                            {
                                id: 'system-labels',
                                leftValue: "={{ $('Config').first().json.lane }}",
                                rightValue: 'system-labels',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'system-labels',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
            renameFallbackOutput: 'all',
        },
    };

    @node({
        id: 'mo-le-seed-req',
        name: 'LE Seed Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [80, 200],
    })
    LeSeedReq = {
        jsCode: `// __conn_stamped — every mail op names its mailbox explicitly (mailapi refuses an unnamed op).
const __conn_stamped = (function(){

function enchdr(s){return '=?UTF-8?B?'+Buffer.from(String(s),'utf8').toString('base64')+'?=';}
function buildMime(o){
  const b='bnd_'+Math.random().toString(36).slice(2,12);
  const att=Buffer.from(o.attContent,'utf8').toString('base64').replace(/(.{76})/g,'$1\\r\\n');
  const L=['From: '+o.from,'To: mail-organizer-test@demo.indox','Date: '+new Date().toUTCString(),
    'Subject: '+enchdr(o.subject),'MIME-Version: 1.0',
    'Content-Type: multipart/mixed; boundary="'+b+'"','',
    '--'+b,'Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
    Buffer.from(o.body,'utf8').toString('base64'),'',
    '--'+b,'Content-Type: application/pdf; name="'+o.attName+'"','Content-Transfer-Encoding: base64',
    'Content-Disposition: attachment; filename="'+enchdr(o.attName)+'"','',att,'','--'+b+'--',''];
  return Buffer.from(L.join('\\r\\n'),'utf8').toString('base64');
}
const tok=$('Config').first().json.tok;
// Hebrew subject+body on purpose: rule 8 (PROMOTIONAL) fires on a body with NO Hebrew, and
// PROMOTIONAL blocks DOC_TO_SYNC. A Hebrew business mail with an attachment is the real shape.
return [{json:{op:'append', __instance:'test', params:{
  raw_base64: buildMime({from:'mailorg-test@demo.indox',
    subject:'mailorg_'+tok+' מסמך נכנס לבדיקה',
    body:'מצורף מסמך לבדיקת מנוע התיוג. מספר הרצה '+tok,
    attName:'mailorg_'+tok+'.pdf', attContent:'mail organizer gate attachment '+tok}),
  labels:[], folder:'INBOX', ...($('Config').first().json.connection_id?{connection_id:$('Config').first().json.connection_id}:{})}}}];
})();
const __cid = $('Config').first().json.connection_id;
return (__conn_stamped||[]).map(function(it){
  if(!it||!it.json||!it.json.params) return it;
  return Object.assign({}, it, {json: Object.assign({}, it.json,
    {params: Object.assign({}, it.json.params, {connection_id: __cid})})});
});
`,
    };

    @node({
        id: 'mo-le-seed',
        name: 'LE Seed',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [300, 200],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    LeSeed = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ $json.params }}',
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
    };

    @node({
        id: 'mo-le-pre-req',
        name: 'LE Pre Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [520, 200],
    })
    LePreReq = {
        jsCode: `// __conn_stamped — every mail op names its mailbox explicitly (mailapi refuses an unnamed op).
const __conn_stamped = (function(){
const cfg=$('Config').first().json; const tok=cfg.tok;
return [{json:{op:'search', params:{query:'subject:mailorg_'+tok, limit:5, ...(cfg.connection_id?{connection_id:cfg.connection_id}:{})}}}];
})();
const __cid = $('Config').first().json.connection_id;
return (__conn_stamped||[]).map(function(it){
  if(!it||!it.json||!it.json.params) return it;
  return Object.assign({}, it, {json: Object.assign({}, it.json,
    {params: Object.assign({}, it.json.params, {connection_id: __cid})})});
});
`,
    };

    @node({
        id: 'mo-le-pre',
        name: 'LE Pre',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [740, 200],
        alwaysOutputData: true,
    })
    LePre = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ $json.params }}',
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
    };

    @node({
        id: 'mo-le-rules',
        name: 'LE Rules',
        /*__n8n__*/ notes: "[N1 2026-09-02] ONE rule store. This gate reads the organizer store mailapi serves — GET http://mailapi:8970/organizer/settings, shape {gmail:{labels:{KEY:{name}}, rows:[...]}} — the same document the engine's 'Load Settings (rules)' node and mail01's 'Load Settings' read. It used to read indox_test.tag_rules, a second store the engine never sees, so it could pass on rows the labeller was not using. One {KEY, LABEL} item per rule row, the exact shape the table query produced, so 'LE Unit Req' and 'Assert LE' read it unchanged.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [960, 200],
        alwaysOutputData: true,
    })
    LeRules = {
        jsCode: `// [N1 2026-09-02] the one rule store: mailapi's organizer document, the same GET the engine's
// 'Load Settings (rules)' node makes. One {KEY, LABEL} item per rule row — LABEL trimmed the way
// the engine trims it, blank rows dropped, and a rule the editor disabled (enabled === false;
// absent/null = enabled, the store predates the flag) dropped too, because the engine skips those
// and the gate must not expect their labels. mailapi unreachable = a thrown error naming it: the
// gate cannot judge labels it cannot read.
const d = await this.helpers.httpRequest({ method: 'GET', json: true, timeout: 15000,
  url: 'http://mailapi:8970/organizer/settings' });
const rows = (((d || {}).gmail || {}).rows) || [];
return rows
  .filter(r => r && r.KEY && r.enabled !== false)
  .map(r => ({ json: { KEY: String(r.KEY), LABEL: String(r.LABEL || '').trim(), TYPE: r.TYPE || null, row_number: r.row_number } }))
  .filter(i => i.json.LABEL);`,
    };

    @node({
        id: 'mo-le-engine-req',
        name: 'LE Engine Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1180, 200],
    })
    LeEngineReq = {
        jsCode: `const tok=$('Config').first().json.tok;
// the organizer's own sub-entry: same Get a message -> Start -> Lable Engine path the
// schedule takes, scoped to this run's mail so the assertion cannot see anyone else's.
return [{json:{query:'subject:mailorg_'+tok, limit:5, connection_id:$('Config').first().json.connection_id}}];`,
    };

    @node({
        id: 'mo-le-engine',
        name: 'LE Engine',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1400, 200],
        alwaysOutputData: true,
    })
    LeEngine = {
        workflowId: {
            __rl: true,
            value: 'mailLabelEngine01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                query: '={{ $json.query }}',
                limit: '={{ $json.limit }}',
                connection_id: '={{ $json.connection_id }}',
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'query',
                    displayName: 'query',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'limit',
                    displayName: 'limit',
                    required: false,
                    display: true,
                    type: 'number',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'connection_id',
                    displayName: 'connection_id',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
    };

    @node({
        id: 'mo-le-post-req',
        name: 'LE Post Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1620, 200],
    })
    LePostReq = {
        jsCode: `// __conn_stamped — every mail op names its mailbox explicitly (mailapi refuses an unnamed op).
const __conn_stamped = (function(){
const cfg=$('Config').first().json; const tok=cfg.tok;
return [{json:{op:'search', params:{query:'subject:mailorg_'+tok, limit:5, ...(cfg.connection_id?{connection_id:cfg.connection_id}:{})}}}];
})();
const __cid = $('Config').first().json.connection_id;
return (__conn_stamped||[]).map(function(it){
  if(!it||!it.json||!it.json.params) return it;
  return Object.assign({}, it, {json: Object.assign({}, it.json,
    {params: Object.assign({}, it.json.params, {connection_id: __cid})})});
});
`,
    };

    @node({
        id: 'mo-le-post',
        name: 'LE Post',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1840, 200],
        alwaysOutputData: true,
    })
    LePost = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ $json.params }}',
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
    };

    @node({
        id: 'mo-le-unit-req',
        name: 'LE Unit Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2060, 200],
    })
    LeUnitReq = {
        jsCode: `const tok=$('Config').first().json.tok;
const rules={}; for(const r of $('LE Rules').all()) rules[r.json.KEY]=(r.json.LABEL||'').trim();
const dts=rules['DOC_TO_SYNC']||'';
// PRODUCTION semantics: sync searches by label NAME with spaces hyphenated (SyncScanUnit/
// syncV3Unit both do this). If the organizer did not apply the label, this lists 0 and the
// assert below goes red — which is the whole point of this lane.
const q='label:'+dts.replace(/ /g,'-')+' subject:mailorg_'+tok;
// [explicit-connection 2026-08-31] The mail engine no longer falls back to /data/active.json for
// ANY caller: every op needs its connection_id passed explicitly. Same shape as the canonical
// gmail lane (syncV3SourcesTest01 GD Unit1 Req): connection_id + drive_connection_id in list_ctx.
const cid=$('Config').first().json.connection_id||'';
const dcid=(()=>{try{const r=$('Test Connections').first().json||{}; const v=r.value; const tc=(typeof v==='string')?JSON.parse(v):(v||{}); return String(tc.drive_connection_id||'');}catch(e){return '';}})();
return [{json:{__instance:'test', source:'mailorg_'+tok, src_kind:'gmail',
  list_ctx:{connection_id:cid, drive_connection_id:dcid, query:q, upload_folder_id:'mailorg_up', drive_profile_id:'admin'},
  projection:{}, proj_on:false, page_size:50, take:25, status_override:'NEEDS_REVIEW', _q:q}}];`,
    };

    @node({
        id: 'mo-le-unit',
        name: 'LE Unit',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [2280, 200],
        alwaysOutputData: true,
    })
    LeUnit = {
        workflowId: {
            __rl: true,
            value: 'syncDiscoverGmail01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'mo-le-run',
        name: 'LE Run',
        /*__n8n__*/ notes: "[sync item 2026-09-02] The old Unit discovered AND delivered in one call. Discovery is its own stage now: 'LE Unit' (syncDiscoverGmail01) upserts the labelled mail as sync items and echoes the unit; this node (syncRun01) takes them and dispatches the deliveries — still without waiting, which is why the watch below polls the ledger.",
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [2310, 200],
        alwaysOutputData: true,
    })
    LeRun = {
        workflowId: {
            __rl: true,
            value: 'syncRun01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'mo-le-w1-w',
        name: 'LE W1 Watch',
        /*__n8n__*/ notes: "Deliver Each dispatches with waitForSubWorkflow:false, so the delivery lands AFTER LE Unit has answered -- its reply freezes delivered=0 by construction (same root cause as sync_full's mixed/registry lanes, 2026-08-24). Poll the LEDGER, the authoritative record, until this run's source shows delivered>=1 or 90s pass.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [2340, 320],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 1000,
    })
    LeW1Watch = {
        operation: 'executeQuery',
        query: "=select count(*) filter (where status='delivered')::int as d, count(*)::int as rows_all from indox_test.sync_ledger where regexp_replace(source,'^[^/]*/','') = 'mailorg_{{ $('Config').first().json.tok }}'",
        options: {},
    };

    @node({
        id: 'mo-le-w1-g',
        name: 'LE W1 Guard',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2390, 320],
        alwaysOutputData: true,
    })
    LeW1Guard = {
        jsCode: `const r=($input.first()&&$input.first().json)||{};
const iter=$runIndex+1, INTERVAL=5, MAX_S=90;
const waited=(iter-1)*INTERVAL;
const d=Number(r.d||0);
const ok=d>=1;
const timeout=!ok&&waited>=MAX_S;
return [{json:{_watch:'LE W1', _ok:ok, _timeout:timeout, _done:ok||timeout,
  _iter:iter, _waited_s:waited, _d:d, _rows_all:Number(r.rows_all||0),
  _expect:'ledger delivered >= 1 for this run source'}}];`,
    };

    @node({
        id: 'mo-le-w1-r',
        name: 'LE W1 Ready?',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [2440, 320],
    })
    LeW1Ready = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'mo-le-w1-c',
                    leftValue: '={{ $json._done }}',
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
        id: 'mo-le-w1-s',
        name: 'LE W1 Sleep',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [2390, 440],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    LeW1Sleep = {
        operation: 'executeQuery',
        query: 'select pg_sleep(5)',
        options: {},
    };

    @node({
        id: 'mo-le-docs',
        name: 'LE Docs',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [2500, 200],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    LeDocs = {
        operation: 'executeQuery',
        query: `=select count(*)::int as c,
 count(*) filter (where "SOURCE_TYPE"='GMAIL_ATTACHMENT')::int as ga
 from indox_test.incoming_documents where "SYNC_NAME" like 'mailorg\\_%'`,
        options: {},
    };

    @node({
        id: 'mo-assert-le',
        name: 'Assert LE',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2720, 200],
    })
    AssertLe = {
        jsCode: `const g=n=>{try{return $(n).first().json;}catch(e){return {_err:e.message};}}
const all=n=>{try{return $(n).all().map(i=>i.json);}catch(e){return [];}}
const fails=[];
const rules={}; for(const r of all('LE Rules')) rules[r.KEY]=(r.LABEL||'').trim();
const DTS=rules['DOC_TO_SYNC'], PRC=rules['PROCESSED'];
if(!DTS) fails.push('organizer store (mailapi /organizer/settings) has no DOC_TO_SYNC rule with a label');
if(!PRC) fails.push('organizer store (mailapi /organizer/settings) has no PROCESSED rule with a label');
const pre=all('LE Pre').filter(m=>m&&m.id);
if(pre.length!==1) fails.push('seed: expected 1 message, got '+pre.length);
const preLabels=(pre[0]&&(pre[0].labels||pre[0].labelIds))||[];
// tolerate mail01's 15-min tick (the scheduler that fans the engine out once per mailbox) beating
// us to it: that is the organizer working, not a failure — it is only "not unlabelled" if
// PROCESSED is there too.
const raced=preLabels.includes(PRC);
if(!raced && DTS && preLabels.includes(DTS))
  fails.push('seed was NOT unlabelled: '+JSON.stringify(preLabels));
const post=all('LE Post').filter(m=>m&&m.id);
const postLabels=(post[0]&&(post[0].labels||post[0].labelIds))||[];
if(DTS && !postLabels.includes(DTS))
  fails.push('DOC_TO_SYNC label '+JSON.stringify(DTS)+' NOT applied (labels='+JSON.stringify(postLabels)+')');
if(PRC && !postLabels.includes(PRC))
  fails.push('PROCESSED label '+JSON.stringify(PRC)+' NOT applied (labels='+JSON.stringify(postLabels)+')');
const u=g('LE Unit');
// [sync item 2026-09-02] syncDiscoverGmail01 echoes the unit with the pass counts as _listed /
// _discovered (the Unit era answered a plain listed).
const listed=Number(u._listed!=null?u._listed:u.listed);
if(listed!==1) fails.push('label-scoped sync search listed '+listed+' (want 1) q='+g('LE Unit Req')._q);
const w1=g('LE W1 Guard');
if(Number(w1._d)<1) fails.push(w1._timeout?('W1 TIMED OUT after '+w1._waited_s+'s waiting for '+w1._expect+', ledger rows '+w1._rows_all):('ledger delivered '+w1._d+' (want >=1): '+JSON.stringify(u)));
const d=g('LE Docs');
if(Number(d.c)!==1||Number(d.ga)!==1) fails.push('incoming_documents wrong: '+JSON.stringify(d));
const n=8;
return [{json:{result: fails.length?('❌ label-engine '+fails.length+'/'+n+': '+fails.join('; '))
                                   :('✅ label-engine PASS '+n+'/'+n+(raced?' (schedule raced)':'')), fails}}];`,
    };

    @node({
        id: 'mo-sl-seed-req',
        name: 'SL Seed Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [80, 640],
    })
    SlSeedReq = {
        jsCode: `// __conn_stamped — every mail op names its mailbox explicitly (mailapi refuses an unnamed op).
const __conn_stamped = (function(){

function enchdr(s){return '=?UTF-8?B?'+Buffer.from(String(s),'utf8').toString('base64')+'?=';}
function buildMime(o){
  const b='bnd_'+Math.random().toString(36).slice(2,12);
  const att=Buffer.from(o.attContent,'utf8').toString('base64').replace(/(.{76})/g,'$1\\r\\n');
  const L=['From: '+o.from,'To: mail-organizer-test@demo.indox','Date: '+new Date().toUTCString(),
    'Subject: '+enchdr(o.subject),'MIME-Version: 1.0',
    'Content-Type: multipart/mixed; boundary="'+b+'"','',
    '--'+b,'Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
    Buffer.from(o.body,'utf8').toString('base64'),'',
    '--'+b,'Content-Type: application/pdf; name="'+o.attName+'"','Content-Transfer-Encoding: base64',
    'Content-Disposition: attachment; filename="'+enchdr(o.attName)+'"','',att,'','--'+b+'--',''];
  return Buffer.from(L.join('\\r\\n'),'utf8').toString('base64');
}
const tok=$('Config').first().json.tok;
return [{json:{op:'append', __instance:'test', params:{
  raw_base64: buildMime({from:'mailorg-test@demo.indox',
    subject:'mailorgsl_'+tok+' מסמך נכנס לבדיקה',
    body:'מצורף מסמך לבדיקת יצירת תוויות. מספר הרצה '+tok,
    attName:'mailorgsl_'+tok+'.pdf', attContent:'mail organizer label-create gate '+tok}),
  labels:[], folder:'INBOX', ...($('Config').first().json.connection_id?{connection_id:$('Config').first().json.connection_id}:{})}}}];
})();
const __cid = $('Config').first().json.connection_id;
return (__conn_stamped||[]).map(function(it){
  if(!it||!it.json||!it.json.params) return it;
  return Object.assign({}, it, {json: Object.assign({}, it.json,
    {params: Object.assign({}, it.json.params, {connection_id: __cid})})});
});
`,
    };

    @node({
        id: 'mo-sl-seed',
        name: 'SL Seed',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [300, 640],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    SlSeed = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ $json.params }}',
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
    };

    @node({
        id: 'mo-sl-engine-req',
        name: 'SL Engine Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [520, 640],
    })
    SlEngineReq = {
        jsCode: `const tok=$('Config').first().json.tok;
return [{json:{query:'subject:mailorgsl_'+tok, limit:5, connection_id:$('Config').first().json.connection_id}}];`,
    };

    @node({
        id: 'mo-sl-engine',
        name: 'SL Engine',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [740, 640],
        alwaysOutputData: true,
    })
    SlEngine = {
        workflowId: {
            __rl: true,
            value: 'mailLabelEngine01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                query: '={{ $json.query }}',
                limit: '={{ $json.limit }}',
                connection_id: '={{ $json.connection_id }}',
            },
            matchingColumns: [],
            schema: [
                {
                    id: 'query',
                    displayName: 'query',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'limit',
                    displayName: 'limit',
                    required: false,
                    display: true,
                    type: 'number',
                    canBeUsedToMatch: true,
                },
                {
                    id: 'connection_id',
                    displayName: 'connection_id',
                    required: false,
                    display: true,
                    type: 'string',
                    canBeUsedToMatch: true,
                },
            ],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
    };

    @node({
        id: 'mo-sl-rules',
        name: 'SL Rules',
        /*__n8n__*/ notes: "[N1 2026-09-02] Same read as 'LE Rules' (the lanes run alone, so each reads the store itself): every rule row with a LABEL from mailapi's /organizer/settings — the names the engine's 'Labels to create' diffs against listLabels. Disabled rules are dropped here because the engine never creates their labels.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [960, 640],
        alwaysOutputData: true,
    })
    SlRules = {
        jsCode: `// [N1 2026-09-02] the one rule store — see 'LE Rules'. Every rule row with a LABEL, minus the
// rules the editor disabled, which the engine's 'Labels to create' skips as well.
const d = await this.helpers.httpRequest({ method: 'GET', json: true, timeout: 15000,
  url: 'http://mailapi:8970/organizer/settings' });
const rows = (((d || {}).gmail || {}).rows) || [];
return rows
  .filter(r => r && r.KEY && r.enabled !== false)
  .map(r => ({ json: { KEY: String(r.KEY), LABEL: String(r.LABEL || '').trim(), TYPE: r.TYPE || null, row_number: r.row_number } }))
  .filter(i => i.json.LABEL);`,
    };

    @node({
        id: 'mo-sl-labels-req',
        name: 'SL Labels Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1180, 640],
    })
    SlLabelsReq = {
        jsCode: `// __conn_stamped — every mail op names its mailbox explicitly (mailapi refuses an unnamed op).
const __conn_stamped = (function(){
const cfg=(()=>{try{return $('Config').first().json;}catch(e){return {};}})();
return [{json:{op:'listLabels', params:{...(cfg.connection_id?{connection_id:cfg.connection_id}:{})}}}];
})();
const __cid = $('Config').first().json.connection_id;
return (__conn_stamped||[]).map(function(it){
  if(!it||!it.json||!it.json.params) return it;
  return Object.assign({}, it, {json: Object.assign({}, it.json,
    {params: Object.assign({}, it.json.params, {connection_id: __cid})})});
});
`,
    };

    @node({
        id: 'mo-sl-labels',
        name: 'SL Labels',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1400, 640],
        alwaysOutputData: true,
    })
    SlLabels = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ $json.params }}',
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
    };

    @node({
        id: 'mo-assert-sl',
        name: 'Assert SL',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1620, 640],
    })
    AssertSl = {
        jsCode: `const all=n=>{try{return $(n).all().map(i=>i.json);}catch(e){return [];}}
const fails=[];
// \`Labels to create\` diffs the rule set against listLabels and creates what is missing —
// including the SYSTEM names indox WRITES but never creates. On a fresh mailbox addLabels
// fails for a label that does not exist, so this invariant is load-bearing.
const want=[...new Set(all('SL Rules').map(r=>(r.LABEL||'').trim())
                                      .filter(n=>n && !n.startsWith('-')))];
const have=new Set(all('SL Labels').map(l=>l.name||l.id).filter(Boolean));
const missing=want.filter(n=>!have.has(n));
if(!want.length) fails.push('organizer store (mailapi /organizer/settings) produced no label names to check');
if(missing.length) fails.push(missing.length+' label(s) never created: '+JSON.stringify(missing.slice(0,6)));
const sys=all('SL Rules').filter(r=>r.KEY&&/^(IN_PROGRESS|SYNCED_|FAILED_|SAVED_|ACTION_|FOUND_|PROCESSED)/.test(r.KEY));
const sysMissing=sys.map(r=>(r.LABEL||'').trim()).filter(n=>n&&!have.has(n));
if(sysMissing.length) fails.push('SYSTEM labels missing: '+JSON.stringify(sysMissing));
const n=3;
return [{json:{result: fails.length?('❌ system-labels '+fails.length+'/'+n+': '+fails.join('; '))
                                   :('✅ system-labels PASS '+n+'/'+n+' ('+want.length+' names)'), fails}}];`,
    };

    @node({
        id: 'mo-chain-1-all-only',
        name: 'Chain 1 (all only)',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [2940, 200],
    })
    Chain1AllOnly = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'c1',
                    leftValue: "={{ $('Config').first().json.lane }}",
                    rightValue: 'all',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'mo-chain-summary-all-only',
        name: 'Chain Summary (all only)',
        type: 'n8n-nodes-base.if',
        version: 2.2,
        position: [1840, 640],
    })
    ChainSummaryAllOnly = {
        conditions: {
            options: {
                caseSensitive: true,
                typeValidation: 'loose',
                version: 2,
            },
            conditions: [
                {
                    id: 'csum',
                    leftValue: "={{ $('Config').first().json.lane }}",
                    rightValue: 'all',
                    operator: {
                        type: 'string',
                        operation: 'equals',
                    },
                },
            ],
            combinator: 'and',
        },
        options: {},
    };

    @node({
        id: 'mo-summary-test-summary',
        name: '🏁 Test Summary',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2060, 640],
    })
    TestSummary = {
        jsCode: `const g=(n)=>{try{const j=$(n).first().json;return j&&j.result?j.result:'❌ '+n+' missing';}catch(e){return '❌ '+n+' not executed';}}
const lanes=['Assert LE','Assert SL'];
const names={'Assert LE':'label-engine','Assert SL':'system-labels'};
const checks=lanes.map(n=>{const r=g(n);const ok=/PASS/.test(r);return (ok?'✅ ':'❌ ')+names[n]+' — '+r;});
const okc=checks.filter(c=>c.startsWith('✅')).length;
return [{json:{RESULT: okc===lanes.length?'✅ ALL TESTS PASS':'❌ FAILURES PRESENT',
               passed: okc+'/'+lanes.length, checks}}];`,
    };

    @node({
        id: 'mo-respond-lane',
        name: 'Respond Lane',
        type: 'n8n-nodes-base.respondToWebhook',
        version: 1.1,
        position: [2940, 420],
        onError: 'continueRegularOutput',
    })
    RespondLane = {
        respondWith: 'allIncomingItems',
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.RunMailOrganizerTest.out(0).to(this.TestConnectionsReq.in(0));
        this.LaneWebhook.out(0).to(this.TestConnectionsReq.in(0));
        this.TestConnectionsReq.out(0).to(this.TestConnections.in(0));
        this.TestConnections.out(0).to(this.Config.in(0));
        this.Config.out(0).to(this.CleanupPrior.in(0));
        this.CleanupPrior.out(0).to(this.LaneSwitch.in(0));
        this.LaneSwitch.out(0).to(this.LeSeedReq.in(0));
        this.LaneSwitch.out(1).to(this.SlSeedReq.in(0));
        this.LaneSwitch.out(2).to(this.LeSeedReq.in(0));
        this.LeSeedReq.out(0).to(this.LeSeed.in(0));
        this.LeSeed.out(0).to(this.LePreReq.in(0));
        this.LePreReq.out(0).to(this.LePre.in(0));
        this.LePre.out(0).to(this.LeRules.in(0));
        this.LeRules.out(0).to(this.LeEngineReq.in(0));
        this.LeEngineReq.out(0).to(this.LeEngine.in(0));
        this.LeEngine.out(0).to(this.LePostReq.in(0));
        this.LePostReq.out(0).to(this.LePost.in(0));
        this.LePost.out(0).to(this.LeUnitReq.in(0));
        this.LeUnitReq.out(0).to(this.LeUnit.in(0));
        this.LeUnit.out(0).to(this.LeRun.in(0));
        this.LeRun.out(0).to(this.LeW1Watch.in(0));
        this.LeW1Watch.out(0).to(this.LeW1Guard.in(0));
        this.LeW1Guard.out(0).to(this.LeW1Ready.in(0));
        this.LeW1Ready.out(0).to(this.LeDocs.in(0));
        this.LeW1Ready.out(1).to(this.LeW1Sleep.in(0));
        this.LeW1Sleep.out(0).to(this.LeW1Watch.in(0));
        this.LeDocs.out(0).to(this.AssertLe.in(0));
        this.SlSeedReq.out(0).to(this.SlSeed.in(0));
        this.SlSeed.out(0).to(this.SlEngineReq.in(0));
        this.SlEngineReq.out(0).to(this.SlEngine.in(0));
        this.SlEngine.out(0).to(this.SlRules.in(0));
        this.SlRules.out(0).to(this.SlLabelsReq.in(0));
        this.SlLabelsReq.out(0).to(this.SlLabels.in(0));
        this.SlLabels.out(0).to(this.AssertSl.in(0));
        this.AssertLe.out(0).to(this.Chain1AllOnly.in(0));
        this.AssertLe.out(0).to(this.RespondLane.in(0));
        this.Chain1AllOnly.out(0).to(this.SlSeedReq.in(0));
        this.AssertSl.out(0).to(this.ChainSummaryAllOnly.in(0));
        this.AssertSl.out(0).to(this.RespondLane.in(0));
        this.ChainSummaryAllOnly.out(0).to(this.TestSummary.in(0));
    }
}
