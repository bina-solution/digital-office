import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : sv3 Inject 3x Every Registry Source
// Nodes   : 31  |  Connections: 33
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// Inject3xEverySource                manualTrigger
// WhenCalled                         executeWorkflowTrigger
// SettingsReq                        code
// Settings                           executeWorkflow            [retry]
// RegistryReq                        code
// GetRegistry                        executeWorkflow            [retry]
// Plan                               code
// Loop                               splitInBatches
// GenReq                             code
// Gen                                httpRequest                [retry]
// Route                              switch
// DriveBin                           code
// DriveUpload                        executeWorkflow            [retry]
// MailReq                            code
// MailAppend                         executeWorkflow            [retry]
// MailLabelReq                       code
// MailLabel                          executeWorkflow            [retry]
// LinkMailReq                        code
// LinkAppend                         executeWorkflow            [retry]
// LinkLabelReq                       code
// LinkLabel                          executeWorkflow            [retry]
// Injected                           code                       [alwaysOutput]
// TestConnectionsReq                 code
// TestConnections                    executeWorkflow            [alwaysOutput] [retry]
// Config                             code
// SeedLabelRules                     postgres                   [creds] [retry]
// SeedRegistryReq                    code
// SeedRegistry                       executeWorkflow            [retry]
// SyncReq                            code
// Sync                               executeWorkflow            [onError→regular] [alwaysOutput]
// Cleanup                            postgres                   [onError→regular] [creds] [alwaysOutput]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// Inject3xEverySource
//    → TestConnectionsReq
//      → TestConnections
//        → Config
//          → SettingsReq
//            → Settings
//              → SeedLabelRules
//                → SeedRegistryReq
//                  → SeedRegistry
//                    → RegistryReq
//                      → GetRegistry
//                        → Plan
//                          → Loop
//                            → SyncReq
//                              → Sync
//                                → Injected
//                                  → Cleanup
//                           .out(1) → GenReq
//                              → Gen
//                                → Route
//                                  → DriveBin
//                                    → DriveUpload
//                                      → Loop (↩ loop)
//                                 .out(1) → MailReq
//                                    → MailAppend
//                                      → MailLabelReq
//                                        → MailLabel
//                                          → Loop (↩ loop)
//                                 .out(2) → LinkMailReq
//                                    → LinkAppend
//                                      → LinkLabelReq
//                                        → LinkLabel
//                                          → Loop (↩ loop)
// WhenCalled
//    → TestConnectionsReq (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"▶ Inject 3x Every Source":{"main":[[{"node":"Test Connections Req","type":"main","index":0}]]},"When Called":{"main":[[{"node":"Test Connections Req","type":"main","index":0}]]},"Test Connections Req":{"main":[[{"node":"Test Connections","type":"main","index":0}]]},"Test Connections":{"main":[[{"node":"Config","type":"main","index":0}]]},"Settings Req":{"main":[[{"node":"Settings","type":"main","index":0}]]},"Settings":{"main":[[{"node":"Seed Registry Req","type":"main","index":0}]]},"Registry Req":{"main":[[{"node":"Get Registry","type":"main","index":0}]]},"Get Registry":{"main":[[{"node":"Plan","type":"main","index":0}]]},"Plan":{"main":[[{"node":"Loop","type":"main","index":0}]]},"Loop":{"main":[[{"node":"Sync Req","type":"main","index":0}],[{"node":"Gen Req","type":"main","index":0},{"node":"Loop","type":"main","index":0}]]},"Gen Req":{"main":[[{"node":"Gen","type":"main","index":0}]]},"Gen":{"main":[[{"node":"Route","type":"main","index":0}]]},"Route":{"main":[[{"node":"Drive Bin","type":"main","index":0}],[{"node":"Mail Req","type":"main","index":0}],[{"node":"Link Mail Req","type":"main","index":0}]]},"Drive Bin":{"main":[[{"node":"Drive Upload","type":"main","index":0}]]},"Drive Upload":{"main":[[]]},"Mail Req":{"main":[[{"node":"Mail Append","type":"main","index":0}]]},"Mail Append":{"main":[[{"node":"Mail Label Req","type":"main","index":0}]]},"Mail Label Req":{"main":[[{"node":"Mail Label","type":"main","index":0}]]},"Mail Label":{"main":[[]]},"Link Mail Req":{"main":[[{"node":"Link Append","type":"main","index":0}]]},"Link Append":{"main":[[{"node":"Link Label Req","type":"main","index":0}]]},"Link Label Req":{"main":[[{"node":"Link Label","type":"main","index":0}]]},"Link Label":{"main":[[]]},"Config":{"main":[[{"node":"Settings Req","type":"main","index":0}]]},"Seed Registry Req":{"main":[[{"node":"Seed Registry","type":"main","index":0}]]},"Seed Registry":{"main":[[{"node":"Registry Req","type":"main","index":0}]]},"Sync Req":{"main":[[{"node":"Sync","type":"main","index":0}]]},"Sync":{"main":[[{"node":"Injected","type":"main","index":0}]]},"Injected":{"main":[[{"node":"Cleanup","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"c7d4bdbd-9cb8-4595-90d4-b200420c3fd2","name":"role:sync"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"sv3Inject3x001","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'sv3Inject3x001',
    name: 'sv3 Inject 3x Every Registry Source',
    active: false,
    isArchived: false,
    tags: ['app:indox', 'sync-v3', 'indox-app', 'role:sync'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        executionTimeout: 900,
        callerPolicy: 'workflowsFromSameOwner',
    },
})
export class Sv3Inject3xEveryRegistrySourceWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'inj3-001',
        name: '▶ Inject 3x Every Source',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [-1000, 300],
    })
    Inject3xEverySource = {};

    @node({
        id: 'inj3-002',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [-1000, 460],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'inj3-003',
        name: 'Settings Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-1000, 380],
    })
    SettingsReq = {
        jsCode: "return [{json:{__instance:'test', load_settings:true, load_companies:true, TRIGGERED_FROM:'sv3-inject-3x'}}];",
    };

    @node({
        id: 'inj3-004',
        name: 'Settings',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [-640, 380],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    Settings = {
        workflowId: {
            __rl: true,
            value: 'indoxSettings01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'inj3-005',
        name: 'Registry Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-260, 380],
    })
    RegistryReq = {
        jsCode: `// Reads THIS WORKFLOW'S OWN registry, seeded by \`Seed Registry\` one node upstream -- never
// \`sync_registry\`, which is the client's live pipe configuration. See \`Seed Registry Req\`.
const INSTANCE='incoming-documents-main';
return [{json:{INLINE_ACTION:'TABLE_GET', table:'settings', __instance:'test', instance:INSTANCE, filter:{key:'sv3i_registry'}}}];`,
    };

    @node({
        id: 'inj3-006',
        name: 'Get Registry',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [-140, 380],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    GetRegistry = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'inj3-007',
        name: 'Plan',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [0, 380],
    })
    Plan = {
        jsCode: `// one plan item per (test registry source x 3 docs). The registry read here is
// \`sv3i_registry\`, this workflow's own -- see \`Seed Registry Req\` for why it is not the
// live one. Every entry is re-checked below: a plan item can only be built for an
// sv3i_-prefixed source, so a mis-seeded or stale key cannot widen the blast radius.
const s=$('Settings').first().json;
let reg=[]; try{const raw=$input.first().json.value; reg=typeof raw==='string'?JSON.parse(raw):(raw||[]);}catch(e){}
if(!reg.length) throw new Error('sv3i_registry empty/unreadable - Seed Registry did not land');
const cfg=$('Config').first().json;
for(const e of reg){
  if(!String(e.name||'').startsWith('sv3i_'))
    throw new Error('REFUSING to inject into non-test registry entry '+JSON.stringify(e.name)+
      ' - sv3Inject3x001 may only ever drive sv3i_* entries');
}
const cos=s.companies||{};
let co=null,cid=null;
for(const n of Object.keys(cos).sort()){
  const hit=((cos[n]||{}).identifiers||[]).find(i=>/^\\d{8,9}$/.test(String(i)));
  if(hit){co=n; cid=String(hit); break;}
}
if(!co) throw new Error('no company with a numeric identifier');
const map=s.company_name_by_mail||{};
let sender=null, senderCo=null, senderCid=null;
for(const m of Object.keys(map).sort()){
  const c2=map[m]; const ids=((cos[c2]||{}).identifiers)||[];
  if(ids.length && !/no-?reply/i.test(m)){ sender=m; senderCo=c2; senderCid=String(ids[0]); break; }
}
if(!sender){ sender='unknown-sender@demo.indox'; senderCo=null; senderCid=null; }
const tok=String($execution.id||'0').replace(/\\D/g,'').slice(-5).padStart(5,'4');
const out=[];
for(const e of reg){
  const kind = String(e.name||'').includes('gmail-link') ? 'gmail-link' : e.source;
  for(let i=1;i<=3;i++){
    const seq=String(i);
    if(kind==='drive'){
      const folder=((e.pairs||[])[0]||{}).to_sync;
      if(!folder) throw new Error('drive source '+e.name+' has no pair.to_sync');
      out.push({json:{src:e.name, kind:'drive', bs:(e.type_hint==='BALANCE_SHEET'), i, tok,
        folder, co, cid, senderCo, senderCid,
        doc_id:'SI'+(e.name==='drive-bs'?'2':'1')+tok+seq}});
    } else {
      // registry stores label KEYS; the real label name lives in settings.gmail.labels[KEY].name
      const L=((s.gmail||{}).labels)||{};
      const key=(e.labels||{}).to_sync;
      const lbl=(L[key] && L[key].name) || key;
      if(!lbl) throw new Error('gmail source '+e.name+' has no to_sync label');
      out.push({json:{src:e.name, kind:(kind==='gmail-link'?'gmail-link':'gmail'),
        bs:(e.type_hint==='BALANCE_SHEET'), i, tok, label:lbl, sender, co, cid, senderCo, senderCid,
        // NOT e.connection: the mailbox comes from Config, which is the node that refuses a
        // non-local one. A registry row is data; it does not get to choose the account.
        connection_id: cfg.connection_id,
        doc_id:'SI'+(e.name==='gmail-bs'?'3':(e.name==='gmail-doc'?'4':'5'))+tok+seq}});
    }
  }
}
return out;`,
    };

    @node({
        id: 'inj3-008',
        name: 'Loop',
        type: 'n8n-nodes-base.splitInBatches',
        version: 3,
        position: [140, 380],
    })
    Loop = {
        batchSize: 1,
        options: {},
    };

    @node({
        id: 'inj3-009',
        name: 'Gen Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [360, 236],
    })
    GenReq = {
        jsCode: `const p=$json;
const body = p.bs
  ? {doc_type:'BALANCE_SHEET', supplier:{name:(p.kind==='gmail'?(p.senderCo||p.co):p.co),
       company_id:(p.kind==='gmail'?(p.senderCid||p.cid):p.cid)},
     customer:{name:(p.kind==='gmail'?(p.senderCo||p.co):p.co)}}
  : {doc_type:'INVOICE', doc_id:p.doc_id, doc_date:'06/07/2026',
     supplier:{name:p.co, company_id:p.cid, city:'תל אביב'},
     customer:{name:'הכהן שירותים', company_id:'515111111'},
     lines:[{description:'אספקת שירותים', qty:2, unit_price:340.0}]};
return [{json:{...p, _url:'http://apitools:8080/docGen?truth=1', _body:body}}];`,
    };

    @node({
        id: 'inj3-010',
        name: 'Gen',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [540, 380],
        retryOnFail: true,
        maxTries: 2,
        waitBetweenTries: 2000,
    })
    Gen = {
        method: 'POST',
        url: '={{ $json._url }}',
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '={{ JSON.stringify($json._body) }}',
        options: {
            timeout: 60000,
        },
    };

    @node({
        id: 'inj3-011',
        name: 'Route',
        type: 'n8n-nodes-base.switch',
        version: 3.2,
        position: [720, 380],
    })
    Route = {
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
                                id: 'd',
                                leftValue: "={{ $('Loop').first().json.kind }}",
                                rightValue: 'drive',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'drive',
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
                                id: 'g',
                                leftValue: "={{ $('Loop').first().json.kind }}",
                                rightValue: 'gmail',
                                operator: {
                                    type: 'string',
                                    operation: 'equals',
                                },
                            },
                        ],
                        combinator: 'and',
                    },
                    renameOutput: true,
                    outputKey: 'gmail',
                },
            ],
        },
        options: {
            fallbackOutput: 'extra',
            renameFallbackOutput: 'gmail-link',
        },
    };

    @node({
        id: 'inj3-012',
        name: 'Drive Bin',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [900, 240],
    })
    DriveBin = {
        jsCode: `const p=$('Loop').first().json;
const b64=$input.first().json.file_b64;
if(!b64) throw new Error('docGen returned no file_b64');
// drive-bs reads company+period from the FILENAME ("Company - MM.YY"); drive-gdoc is OCR-named.
const name = p.bs ? (p.co+' - 0'+p.i+'.26.pdf') : ('scan_'+p.tok+'_'+p.i+'.pdf');
const bin=await this.helpers.prepareBinaryData(Buffer.from(b64,'base64'), name, 'application/pdf');
return [{json:{name}, binary:{data:bin}}];`,
    };

    @node({
        id: 'inj3-013',
        name: 'Drive Upload',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1080, 240],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    DriveUpload = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: 'upload',
                params: "={{ ({ name: $json.name, folderId: $('Loop').first().json.folder, profile_id: $('Config').first().json.drive_profile_id }) }}",
            },
            matchingColumns: [],
            schema: [],
            attemptToConvertTypes: false,
            convertFieldsToString: false,
        },
    };

    @node({
        id: 'inj3-014',
        name: 'Mail Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [900, 400],
    })
    MailReq = {
        jsCode: `function enchdr(s){return '=?UTF-8?B?'+Buffer.from(String(s),'utf8').toString('base64')+'?=';}
function buildMime(o){
  const b='bnd_'+Math.random().toString(36).slice(2,12);
  const L=['From: '+o.from,'To: office@client.example','Date: '+new Date().toUTCString(),
    'Subject: '+enchdr(o.subject),'MIME-Version: 1.0'];
  const atts=o.atts||[];
  if(atts.length){
    L.push('Content-Type: multipart/mixed; boundary="'+b+'"','',
      '--'+b,'Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
      Buffer.from(o.body||'','utf8').toString('base64'),'');
    for(const a of atts){
      const raw=a.b64?a.b64:Buffer.from(a.content||'','utf8').toString('base64');
      L.push('--'+b,'Content-Type: '+(a.mime||'application/pdf')+'; name="'+a.name+'"',
        'Content-Transfer-Encoding: base64','Content-Disposition: attachment; filename="'+a.name+'"','',
        raw.replace(/(.{76})/g,'$1\\r\\n'),'');
    }
    L.push('--'+b+'--','');
  } else {
    L.push('Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
      Buffer.from(o.body||'','utf8').toString('base64'),'');
  }
  return Buffer.from(L.join('\\r\\n'),'utf8').toString('base64');
}
const p=$('Loop').first().json;
const b64=$input.first().json.file_b64;
const from = p.bs ? p.sender : 'billing@supplier.example';
const subj = p.bs ? ('דוח גיול '+p.tok+'-'+p.i) : ('חשבונית מס '+p.doc_id);
const body = p.bs ? 'מצורף דוח הגיול החודשי' : 'מצורפת חשבונית מס לתשלום';
const att  = p.bs ? ('aging_'+p.tok+'_'+p.i+'.pdf') : ('invoice_'+p.doc_id+'.pdf');
return [{json:{op:'append', __instance:'test', params:{raw_base64: buildMime({from, subject:subj, body,
  atts:[{name:att, b64}]}), labels:[], folder:'INBOX', connection_id: $('Config').first().json.connection_id  /* UNCONDITIONAL. The \`...(x?{k:v}:{})\` spread this replaced omitted the key entirely on a falsy id, and an op with no connection_id used to resolve through mailapi's ambient /data/active.json -- the client's real Gmail. An empty string fails the op loudly instead. */}}}];`,
    };

    @node({
        id: 'inj3-015',
        name: 'Mail Append',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1080, 400],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    MailAppend = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'inj3-016',
        name: 'Mail Label Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1260, 400],
    })
    MailLabelReq = {
        jsCode: `const p=$('Loop').first().json;
const id=$input.first().json.id;
if(!id) throw new Error('append returned no id');
return [{json:{op:'addLabels', __instance:'test', params:{ids:[id], labelIds:[p.label], connection_id: $('Config').first().json.connection_id  /* UNCONDITIONAL. The \`...(x?{k:v}:{})\` spread this replaced omitted the key entirely on a falsy id, and an op with no connection_id used to resolve through mailapi's ambient /data/active.json -- the client's real Gmail. An empty string fails the op loudly instead. */}}}];`,
    };

    @node({
        id: 'inj3-017',
        name: 'Mail Label',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1440, 400],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    MailLabel = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'inj3-018',
        name: 'Link Mail Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [900, 560],
    })
    LinkMailReq = {
        jsCode: `function enchdr(s){return '=?UTF-8?B?'+Buffer.from(String(s),'utf8').toString('base64')+'?=';}
function buildMime(o){
  const b='bnd_'+Math.random().toString(36).slice(2,12);
  const L=['From: '+o.from,'To: office@client.example','Date: '+new Date().toUTCString(),
    'Subject: '+enchdr(o.subject),'MIME-Version: 1.0'];
  const atts=o.atts||[];
  if(atts.length){
    L.push('Content-Type: multipart/mixed; boundary="'+b+'"','',
      '--'+b,'Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
      Buffer.from(o.body||'','utf8').toString('base64'),'');
    for(const a of atts){
      const raw=a.b64?a.b64:Buffer.from(a.content||'','utf8').toString('base64');
      L.push('--'+b,'Content-Type: '+(a.mime||'application/pdf')+'; name="'+a.name+'"',
        'Content-Transfer-Encoding: base64','Content-Disposition: attachment; filename="'+a.name+'"','',
        raw.replace(/(.{76})/g,'$1\\r\\n'),'');
    }
    L.push('--'+b+'--','');
  } else {
    L.push('Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
      Buffer.from(o.body||'','utf8').toString('base64'),'');
  }
  return Buffer.from(L.join('\\r\\n'),'utf8').toString('base64');
}
const p=$('Loop').first().json;
// a stable, fetchable URL (the same doc apitools just rendered), so the link resolver has real bytes
const seed=(Number(String(p.tok).replace(/\\D/g,''))%899999)+100000+p.i;
const url='http://apitools:8080/docGen/sample?type=INVOICE&seed='+seed+'&format=pdf';
return [{json:{op:'append', __instance:'test', params:{raw_base64: buildMime({from:'noreply@billing-portal.example',
  subject:'המסמך שלך מוכן '+p.tok+'-'+p.i,
  body:'שלום,\\nהחשבונית זמינה להורדה כאן:\\n'+url+'\\nבברכה'}), labels:[], folder:'INBOX', connection_id: $('Config').first().json.connection_id  /* UNCONDITIONAL. The \`...(x?{k:v}:{})\` spread this replaced omitted the key entirely on a falsy id, and an op with no connection_id used to resolve through mailapi's ambient /data/active.json -- the client's real Gmail. An empty string fails the op loudly instead. */}}}];`,
    };

    @node({
        id: 'inj3-019',
        name: 'Link Append',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1080, 560],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    LinkAppend = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'inj3-020',
        name: 'Link Label Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1260, 560],
    })
    LinkLabelReq = {
        jsCode: `const p=$('Loop').first().json;
const id=$input.first().json.id;
if(!id) throw new Error('append returned no id');
return [{json:{op:'addLabels', __instance:'test', params:{ids:[id], labelIds:[p.label], connection_id: $('Config').first().json.connection_id  /* UNCONDITIONAL. The \`...(x?{k:v}:{})\` spread this replaced omitted the key entirely on a falsy id, and an op with no connection_id used to resolve through mailapi's ambient /data/active.json -- the client's real Gmail. An empty string fails the op loudly instead. */}}}];`,
    };

    @node({
        id: 'inj3-021',
        name: 'Link Label',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [1440, 560],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    LinkLabel = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'inj3-022',
        name: 'Injected',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [380, 200],
        alwaysOutputData: true,
    })
    Injected = {
        jsCode: `const plan=$('Plan').all().map(i=>i.json);
const per={};
for(const p of plan) per[p.src]=(per[p.src]||0)+1;
let main={}; try{ main=$('Sync').first().json||{}; }catch(e){ main={}; }
return [{json:{__instance:'test', injected:plan.length, per_source:per, tok:(plan[0]||{}).tok,
               registry_key:'sv3i_registry', sources:Object.keys(per).sort(),
               mail_connection:$('Config').first().json.connection_id,
               main_units:main.units, main_status:main.status||main.code||null}}];`,
    };

    @node({
        id: 'inj3-testconn-req',
        name: 'Test Connections Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-960, 380],
    })
    TestConnectionsReq = {
        jsCode: `// ONE deterministic connections read for the whole injector (phase-4 tenant cutover).
// The engine-enumeration blocks (the mail engine's profile listing and the drive engine's
// connection listing) are gone: the test tenant's identities are SEEDED into indox_test.settings
// under key='test_connections' ({drive_connection_id, mail_connection_id, drive_profile_id}) and
// this is the only place this workflow may learn them. __instance:'test' selects the indox_test
// schema; instance:'*' spans that schema's component rows -- the same pair syncV3Main0001's
// Registry Req sends, for the same reason.
return [{json:{INLINE_ACTION:'TABLE_GET', table:'settings', __instance:'test', instance:'*', filter:{key:'test_connections'}}}];`,
    };

    @node({
        id: 'inj3-testconn',
        name: 'Test Connections',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [-920, 380],
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
        id: 'inj3-023',
        name: 'Config',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-880, 380],
    })
    Config = {
        jsCode: `// TENANT GATE (phase-4 cutover). This injector installs config rows and injects fixture
// documents, so it may only ever run against the test tenant -- schema indox_test. The runner
// names the tenant: pin-injected {"__instance":"test"} on the manual trigger, or __instance on
// the When Called payload. Anything else dies HERE, before a single row is written.
const __instance=(()=>{
  try{const t=($('When Called').first().json||{}); if(t.__instance) return String(t.__instance);}catch(e){}
  try{const t=($('▶ Inject 3x Every Source').first().json||{}); if(t.__instance) return String(t.__instance);}catch(e){}
  return '';
})();
if(__instance!=='test') throw new Error("sv3Inject3x001: __instance must be 'test' (got "+JSON.stringify(__instance)+") -- this injector runs only against the test tenant (indox_test); the runner pin-injects it on the trigger / When Called payload.");
// THE MAILBOX AND DRIVE IDENTITY THIS INJECTOR MAY TOUCH. Resolved here, once, and never
// inherited from a registry row — that inheritance IS the defect this node was added to close.
// Until 2026-08-09 \`Plan\` took connection_id straight off each LIVE sync_registry entry, so
// gmail-doc/gmail-bs/gmail-link handed it \`the client's app-password mail connection\`: the client's real
// Gmail. mailapi's explicit-connection guard cannot see that as wrong — the id is present and
// valid — so the only place it can be refused is here, before the op is built.
//
// CONNECTIONS COME FROM THE TENANT, NOT FROM DISCOVERY (phase-4). The mail-profile-enumeration
// block is deleted: the test tenant's identities live in indox_test.settings
// key='test_connections' and arrive via the one 'Test Connections' node upstream. A caller may
// still hand in a mailbox explicitly; everything else resolves from the seeded row.
const tc=(()=>{try{const r=$('Test Connections').first().json||{}; const v=r.value; if(v===undefined||v===null||v==='') return null; return (typeof v==='string')?JSON.parse(v):v;}catch(e){return null;}})();
if(!tc) throw new Error("sv3Inject3x001: no readable indox_test.settings row key='test_connections' -- seed it ({drive_connection_id, mail_connection_id, drive_profile_id}) before running this injector.");
let connection_id=(()=>{try{return ($('When Called').first().json||{}).connection_id||'';}catch(e){return '';}})();
if(!connection_id) connection_id=String(tc.mail_connection_id||'');
// BELTS (kept from the discovery era). A non-local id means the engine is bound to a real
// account. Refuse it — an empty id makes mailapi fail the op LOUDLY, which is the correct
// outcome; a real id makes it succeed quietly against someone's live mailbox, which is the
// incident.
if(connection_id && !connection_id.startsWith('mail_imap_local-')) connection_id='';
let drive_connection_id=String(tc.drive_connection_id||'');
if(drive_connection_id && !drive_connection_id.startsWith('drive_local-')) drive_connection_id='';
return [{json:{__instance, connection_id, drive_connection_id, drive_profile_id:String(tc.drive_profile_id||'admin'), tok:String($execution.id||Date.now())}}];`,
    };


    @node({
        id: 'inj3-025',
        name: 'Seed Registry Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-520, 380],
    })
    SeedRegistryReq = {
        jsCode: `// THE TEST REGISTRY. Five entries, written out here, covering every source kind the v3 engine
// supports. It is DECLARED, not derived: the previous version read the live \`sync_registry\` and
// fanned out over whatever it found, which meant (a) the client's real Gmail and real Drive
// folders were the injection targets, and (b) adding any production pipe silently enlarged this
// workflow's blast radius -- \`sv3f_rg_drive-whatsapp-bot\` delivered 3 rows into the real table
// that way. Kind coverage is now proven statically instead, by
// scripts/refactor/test-registry-scope-lint.py rule R5, which fails the build when the live
// registry grows a kind no test entry declares. Registry and tests still move in lockstep; the
// lockstep no longer runs through the client's data.
const c=$('Config').first().json;
const INSTANCE='incoming-documents-main';
// Refuse to build a gmail pipe with no local mailbox rather than let one default to the ambient
// pointer. Two independent things now have to fail before a real account can be reached.
if(!c.connection_id) throw new Error('sv3Inject3x001: no local test mailbox (mail_imap_local-*) resolved - refusing to build a gmail test registry rather than fall back to the ambient mailbox');
// DRIVE IDENTITY. syncV3Main0001's registry->list_ctx builder forwards a drive pipe's identity
// ONLY via \`connection\` (into list_ctx.connection_id) -- there is no profile_id fallback on that
// branch, unlike gmail. A drive_local instance id is MINTED (\`drive_local-<8hex>\`,
// apps/drive/profiles.py), not a stable literal, so it comes from Config, which read it out of
// indox_test.settings key='test_connections' (phase-4: discovery against the live engine is
// forbidden). A miss throws LOUD here, which is the correct outcome for a test.
const adminConn=c.drive_connection_id||'';
if(!adminConn) throw new Error('sv3Inject3x001: no local drive connection resolved - refusing to build a drive test pipe with no identity');
const drivePair=(p)=>[{from:p+'_src', to:p+'_done', to_sync:p+'_src', synced:p+'_done',
                       failed:p+'_fail', failed_to:p+'_fail', in_progress:p+'_wip'}];
// [thin-only 2026-08-31, owner order] processor_wf is GONE from every injected entry: the
// v1 processor path is retired, Deliver's auto-mode makes a processorless entry THIN, and
// the state machine completes what the thin rows start.
const reg=[
 {name:'sv3i_drive-gdoc', source:'drive', engine:'v3', enabled:true, type_hint:null,
  fallback_type:null, projection:'off', connection:adminConn, profile_id:c.drive_profile_id,
  pairs:drivePair('sv3i_gd'),
  // [2026-09-02] one pass must drain EVERYTHING the test scope holds: fixtures accumulate in the
  // test folders across runs (the injector never empties them), and a bounded take would leave
  // the remainder for a clock tick the suite does not get
  batch:{take:500, chunk:500, page_size:500, timeout_min:14, schedule_min:15}},
 {name:'sv3i_drive-bs', source:'drive', engine:'v3', enabled:true, type_hint:'BALANCE_SHEET',
  fallback_type:'BALANCE_SHEET', projection:'off', connection:adminConn, profile_id:c.drive_profile_id,
  pairs:drivePair('sv3i_db'),
  // [2026-09-02] one pass must drain EVERYTHING the test scope holds: fixtures accumulate in the
  // test folders across runs (the injector never empties them), and a bounded take would leave
  // the remainder for a clock tick the suite does not get
  batch:{take:500, chunk:500, page_size:500, timeout_min:14, schedule_min:15}},
 {name:'sv3i_gmail-doc', source:'gmail', engine:'v3', enabled:true, type_hint:null,
  fallback_type:null, connection:c.connection_id, drive_profile_id:c.drive_profile_id,
  labels:{to_sync:'sv3i_to_sync', synced:'sv3i_synced'}, claim_label:'sv3i_synced',
  dest_folder:'sv3i_up', search_take:25, search_extra:'',
  batch:{take:500, chunk:500, page_size:300}},
 {name:'sv3i_gmail-bs', source:'gmail', engine:'v3', enabled:true, type_hint:'BALANCE_SHEET',
  fallback_type:'BALANCE_SHEET', connection:c.connection_id, drive_profile_id:c.drive_profile_id,
  labels:{to_sync:'sv3i_to_sync', synced:'sv3i_synced'}, claim_label:'sv3i_synced',
  dest_folder:'sv3i_up', search_take:25, search_extra:'',
  batch:{take:500, chunk:500, page_size:300}},
 // v3_kind is EXPLICIT. Build Units otherwise infers gmail-link from the name containing
 // 'gmail-link', which works here by luck and stops working the moment the entry is renamed.
 {name:'sv3i_gmail-link', source:'gmail', v3_kind:'gmail-link', engine:'v3', enabled:true, type_hint:null,
  fallback_type:null, connection:c.connection_id, drive_profile_id:c.drive_profile_id,
  labels:{to_sync:'sv3i_to_sync', synced:'sv3i_synced'}, claim_label:'sv3i_synced',
  dest_folder:'sv3i_up', search_take:25, search_extra:'',
  batch:{take:500, chunk:500, page_size:300}}
];
// Belt and braces: nothing may leave this node bound to a non-local mailbox, whatever the
// literals above say.
for(const e of reg){
  if(!String(e.name||'').startsWith('sv3i_')) throw new Error('test registry entry not sv3i_-prefixed: '+e.name);
  if(e.source!=='drive' && !String(e.connection||'').startsWith('mail_imap_local-'))
    throw new Error('test registry entry '+e.name+' is not bound to a local test mailbox: '+e.connection);
}
return [{json:{INLINE_ACTION:'TABLE_UPSERT', table:'settings', __instance:'test', instance:INSTANCE,
               key:'sv3i_registry', value:JSON.stringify(reg)}}];`,
    };

    @node({
        id: 'inj3-026',
        name: 'Seed Registry',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [-400, 380],
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 2000,
    })
    SeedRegistry = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'inj3-027',
        name: 'Sync Req',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [360, 60],
    })
    SyncReq = {
        jsCode: `// Drive the reconciler against THIS registry key. syncV3Main0001/\`Registry Req\` refuses a
// blank/non-string registry_key rather than falling back to \`sync_registry\`, so the test
// registry cannot silently become the client's.
return [{json:{__instance:'test', registry_key:'sv3i_registry', lock_key:'sv3i_'+$execution.id}}];`,
    };

    @node({
        id: 'inj3-028',
        name: 'Sync',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.1,
        position: [540, 60],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    Sync = {
        workflowId: {
            __rl: true,
            value: 'syncV3Main0001',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'inj3-029',
        name: 'Cleanup',
        type: 'n8n-nodes-base.postgres',
        version: 2.4,
        position: [560, 200],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    Cleanup = {
        operation: 'executeQuery',
        query: `-- TEARDOWN. Removes the two CONFIG rows this run installed: its registry and its label rules.
-- Exact keys, never a pattern -- these are client configuration tables and a pattern standing in
-- for identity is what cost 2,432 client documents on 2026-08-06 (see
-- scripts/test-fixture-prefixes.yaml).
-- The DOCUMENT rows stay: they are the point of an injector, they are marked \`sv3i_\`, and
-- apps/indox/hooks/fixture-sweep.py removes them from outside n8n -- which is also what removes
-- these two config rows when this workflow dies before reaching this node.
with s as (delete from indox_test.settings
            where key = 'sv3i_registry' and instance = 'incoming-documents-main' returning 1)
select (select count(*) from s)::int as registry_rows_removed,
       0::int as label_rows_removed`,
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.Inject3xEverySource.out(0).to(this.TestConnectionsReq.in(0));
        this.WhenCalled.out(0).to(this.TestConnectionsReq.in(0));
        this.TestConnectionsReq.out(0).to(this.TestConnections.in(0));
        this.TestConnections.out(0).to(this.Config.in(0));
        this.SettingsReq.out(0).to(this.Settings.in(0));
        this.Settings.out(0).to(this.SeedRegistryReq.in(0));
        this.RegistryReq.out(0).to(this.GetRegistry.in(0));
        this.GetRegistry.out(0).to(this.Plan.in(0));
        this.Plan.out(0).to(this.Loop.in(0));
        this.Loop.out(0).to(this.SyncReq.in(0));
        this.Loop.out(1).to(this.GenReq.in(0));
        this.GenReq.out(0).to(this.Gen.in(0));
        this.Gen.out(0).to(this.Route.in(0));
        this.Route.out(0).to(this.DriveBin.in(0));
        this.Route.out(1).to(this.MailReq.in(0));
        this.Route.out(2).to(this.LinkMailReq.in(0));
        this.DriveBin.out(0).to(this.DriveUpload.in(0));
        this.DriveUpload.out(0).to(this.Loop.in(0));
        this.MailReq.out(0).to(this.MailAppend.in(0));
        this.MailAppend.out(0).to(this.MailLabelReq.in(0));
        this.MailLabelReq.out(0).to(this.MailLabel.in(0));
        this.MailLabel.out(0).to(this.Loop.in(0));
        this.LinkMailReq.out(0).to(this.LinkAppend.in(0));
        this.LinkAppend.out(0).to(this.LinkLabelReq.in(0));
        this.LinkLabelReq.out(0).to(this.LinkLabel.in(0));
        this.LinkLabel.out(0).to(this.Loop.in(0));
        this.Config.out(0).to(this.SettingsReq.in(0));
        this.SeedRegistryReq.out(0).to(this.SeedRegistry.in(0));
        this.SeedRegistry.out(0).to(this.RegistryReq.in(0));
        this.SyncReq.out(0).to(this.Sync.in(0));
        this.Sync.out(0).to(this.Injected.in(0));
        this.Injected.out(0).to(this.Cleanup.in(0));
    }
}
