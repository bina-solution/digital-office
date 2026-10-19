import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : INDOX Inject Demo Blueprint
// Nodes   : 36  |  Connections: 35
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenClickingExecute                manualTrigger
// WhenCalled                         executeWorkflowTrigger
// ReqTagRules                        code
// GetTagRules                        executeWorkflow            [alwaysOutput]
// ReqSettings                        code
// GetSettings                        executeWorkflow            [alwaysOutput]
// Plan                               code
// ReadCompanies                      readWriteFile
// BuildCompanies                     code
// SeedCompanies                      executeWorkflow            [onError→regular] [alwaysOutput]
// ReadGmailDoc                       readWriteFile
// BuildGmailDoc                      code
// SendGmailDoc                       executeWorkflow            [onError→regular] [alwaysOutput]
// ReadGmailBs                        readWriteFile
// BuildGmailBs                       code
// SendGmailBs                        executeWorkflow            [onError→regular] [alwaysOutput]
// ReadDriveGdoc                      readWriteFile
// BuildDriveGdoc                     code
// SendDriveGdoc                      executeWorkflow            [onError→regular] [alwaysOutput]
// ReadDriveBs                        readWriteFile
// BuildDriveBs                       code
// SendDriveBs                        executeWorkflow            [onError→regular] [alwaysOutput]
// ReadGmailLink                      readWriteFile
// BuildGmailLink                     code
// SendGmailLink                      executeWorkflow            [onError→regular] [alwaysOutput]
// ReadBlueprint                      readWriteFile
// ParseBlueprint                     code
// ReadE2eMail                        readWriteFile
// BuildE2eMail                       code
// SendE2eMail                        executeWorkflow            [onError→regular] [alwaysOutput]
// ReadE2eDriveGdoc                   readWriteFile
// BuildE2eDriveGdoc                  code
// SendE2eDriveGdoc                   executeWorkflow            [onError→regular] [alwaysOutput]
// ReadE2eDriveBs                     readWriteFile
// BuildE2eDriveBs                    code
// SendE2eDriveBs                     executeWorkflow            [onError→regular] [alwaysOutput]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenClickingExecute
//    → ReadBlueprint
//      → ParseBlueprint
//        → ReqTagRules
//          → GetTagRules
//            → ReqSettings
//              → GetSettings
//                → Plan
//                  → ReadCompanies
//                    → BuildCompanies
//                      → SeedCompanies
//                        → ReadGmailDoc
//                          → BuildGmailDoc
//                            → SendGmailDoc
//                              → ReadGmailBs
//                                → BuildGmailBs
//                                  → SendGmailBs
//                                    → ReadDriveGdoc
//                                      → BuildDriveGdoc
//                                        → SendDriveGdoc
//                                          → ReadDriveBs
//                                            → BuildDriveBs
//                                              → SendDriveBs
//                                                → ReadGmailLink
//                                                  → BuildGmailLink
//                                                    → SendGmailLink
//                        → ReadE2eMail
//                          → BuildE2eMail
//                            → SendE2eMail
//                              → ReadE2eDriveGdoc
//                                → BuildE2eDriveGdoc
//                                  → SendE2eDriveGdoc
//                                    → ReadE2eDriveBs
//                                      → BuildE2eDriveBs
//                                        → SendE2eDriveBs
// WhenCalled
//    → ReadBlueprint (↩ loop)
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When clicking Execute":{"main":[[{"node":"Read Blueprint","type":"main","index":0}]]},"When Called":{"main":[[{"node":"Read Blueprint","type":"main","index":0}]]},"Req Tag Rules":{"main":[[{"node":"Req Settings","type":"main","index":0}]]},"Req Settings":{"main":[[{"node":"Get Settings","type":"main","index":0}]]},"Get Settings":{"main":[[{"node":"Plan","type":"main","index":0}]]},"Read Companies":{"main":[[{"node":"Build Companies","type":"main","index":0}]]},"Build Companies":{"main":[[{"node":"Seed Companies","type":"main","index":0}]]},"Read gmail-doc":{"main":[[{"node":"Build gmail-doc","type":"main","index":0}]]},"Build gmail-doc":{"main":[[{"node":"Send gmail-doc","type":"main","index":0}]]},"Read gmail-bs":{"main":[[{"node":"Build gmail-bs","type":"main","index":0}]]},"Build gmail-bs":{"main":[[{"node":"Send gmail-bs","type":"main","index":0}]]},"Read drive-gdoc":{"main":[[{"node":"Build drive-gdoc","type":"main","index":0}]]},"Build drive-gdoc":{"main":[[{"node":"Send drive-gdoc","type":"main","index":0}]]},"Read drive-bs":{"main":[[{"node":"Build drive-bs","type":"main","index":0}]]},"Build drive-bs":{"main":[[{"node":"Send drive-bs","type":"main","index":0}]]},"Plan":{"main":[[{"node":"Read Companies","type":"main","index":0}]]},"Seed Companies":{"main":[[{"node":"Read gmail-doc","type":"main","index":0},{"node":"Read e2e-mail","type":"main","index":0}]]},"Send gmail-doc":{"main":[[{"node":"Read gmail-bs","type":"main","index":0}]]},"Send gmail-bs":{"main":[[{"node":"Read drive-gdoc","type":"main","index":0}]]},"Send drive-gdoc":{"main":[[{"node":"Read drive-bs","type":"main","index":0}]]},"Read gmail-link":{"main":[[{"node":"Build gmail-link","type":"main","index":0}]]},"Build gmail-link":{"main":[[{"node":"Send gmail-link","type":"main","index":0}]]},"Send drive-bs":{"main":[[{"node":"Read gmail-link","type":"main","index":0}]]},"Read Blueprint":{"main":[[{"node":"Parse Blueprint","type":"main","index":0}]]},"Parse Blueprint":{"main":[[{"node":"Req Tag Rules","type":"main","index":0}]]},"Read e2e-mail":{"main":[[{"node":"Build e2e-mail","type":"main","index":0}]]},"Build e2e-mail":{"main":[[{"node":"Send e2e-mail","type":"main","index":0}]]},"Send e2e-mail":{"main":[[{"node":"Read e2e-drive-gdoc","type":"main","index":0}]]},"Read e2e-drive-gdoc":{"main":[[{"node":"Build e2e-drive-gdoc","type":"main","index":0}]]},"Build e2e-drive-gdoc":{"main":[[{"node":"Send e2e-drive-gdoc","type":"main","index":0}]]},"Send e2e-drive-gdoc":{"main":[[{"node":"Read e2e-drive-bs","type":"main","index":0}]]},"Read e2e-drive-bs":{"main":[[{"node":"Build e2e-drive-bs","type":"main","index":0}]]},"Build e2e-drive-bs":{"main":[[{"node":"Send e2e-drive-bs","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"de8accc1-f4e8-4a42-887e-4545f489893f","name":"role:infra"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: null,
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"IndoxInjectDemo01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'IndoxInjectDemo01',
    name: 'INDOX Inject Demo Blueprint',
    active: false,
    isArchived: false,
    tags: ['indox-app', 'role:infra', 'app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class IndoxInjectDemoBlueprintWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'ij000000-0000-0000-0000-000000000001',
        name: 'When clicking Execute',
        type: 'n8n-nodes-base.manualTrigger',
        version: 1,
        position: [0, 0],
    })
    WhenClickingExecute = {};

    @node({
        id: 'ij000000-0000-0000-0000-000000000002',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1,
        position: [0, 200],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000003',
        name: 'Req Tag Rules',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    ReqTagRules = {
        jsCode: `// The label VOCABULARY lives in ONE store: the mail app's organizer settings (owner Decision N1
// 2026-09-03). One {KEY, LABEL} row per key — the shape the tag_rules TABLE_GET used to answer with.
let rows = [];
try {
  const o = await this.helpers.httpRequest({ method: 'GET', url: 'http://mailapi:8970/organizer/settings', json: true, timeout: 15000 });
  const L = (((o || {}).gmail || {}).labels) || {};
  for (const [k, v] of Object.entries(L)) if (v && v.name) rows.push({ json: { KEY: String(k), LABEL: String(v.name) } });
} catch (e) { rows = []; }
return rows.length ? rows : [{ json: { KEY: null, LABEL: null } }];`,
    };


    @node({
        id: 'ij000000-0000-0000-0000-000000000005',
        name: 'Req Settings',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [620, 0],
    })
    ReqSettings = {
        jsCode: `// INSTANCE is the in-schema discriminator COLUMN (phase 6.5) — a constant inside every
// tenant schema. __instance is the TENANT, and since the 2026-08-31 cutover the chokepoint
// THROWS without it. It rides the demo blueprint json (demo.py writes it), which Parse
// Blueprint has already loaded by the time this builder runs.
const INSTANCE='incoming-documents-main';
const __i = String(($('Parse Blueprint').first().json || {}).instance || '');
if (!/^[a-z][a-z0-9_]*$/.test(__i)) { throw new Error('IndoxInjectDemo01: the demo blueprint names no valid instance — pass --instance to bbox indox demo run'); }
return [{ json: { INLINE_ACTION: 'TABLE_GET', table: 'settings', instance: INSTANCE, __instance: __i } }];`,
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000006',
        name: 'Get Settings',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [820, 0],
        alwaysOutputData: true,
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
        id: 'ij000000-0000-0000-0000-000000000007',
        name: 'Plan',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1020, 0],
    })
    Plan = {
        jsCode: `const sc=(()=>{try{const b=$('Parse Blueprint').first().json;if(b&&Object.keys(b).length)return b;}catch(e){} try{return $('When Called').first().json||{};}catch(e){return {};}})();
const tr = $('Req Tag Rules').all().map(i=>i.json);
const st = $('Get Settings').all().map(i=>i.json);
const labels = {}; for (const r of tr) if (r.KEY) labels[r.KEY] = r.LABEL;
const sv = {}; for (const r of st) sv[r.key] = r.value;
const fid = (u) => { const m = String(u||'').match(/folders\\/([A-Za-z0-9_-]+)/); return m ? m[1] : String(u||''); };
return [{ json: { bp: sc, labels, gdocFolder: fid(sv.GeneralDocsSourceFolder1), bsFolder: fid(sv.BalanceSheetSourceFolder1), n: (Number(sc.per_sync)>0?Number(sc.per_sync):(Number(sv.demo_inject_count)>0?Number(sv.demo_inject_count):(Number(sc.count)>0?Number(sc.count):5))) } }];`,
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000008',
        name: 'Read Companies',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [1220, -500],
    })
    ReadCompanies = {
        fileSelector: '/home/node/.n8n-files/demo-docs/companies.json',
        options: {},
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000009',
        name: 'Build Companies',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1420, -500],
    })
    BuildCompanies = {
        jsCode: `// INSTANCE is the in-schema discriminator COLUMN (phase 6.5) — companies is unique per
// (instance, "מזהה 1") inside each tenant schema. __instance is the TENANT and the chokepoint
// throws without it since the 2026-08-31 cutover; it rides the demo blueprint json.
const INSTANCE='incoming-documents-main';
const __i = String(($('Parse Blueprint').first().json || {}).instance || '');
if (!/^[a-z][a-z0-9_]*$/.test(__i)) { throw new Error('IndoxInjectDemo01: the demo blueprint names no valid instance — pass --instance to bbox indox demo run'); }
// blueprint-driven: seed EXACTLY the blueprint's companies (keeps the sequential chain alive).
const bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})();
const arr=bp.companies||(bp.company?[bp.company]:[]);
const out=[];
for(const c of arr){ const id=c.id!=null?String(c.id):''; if(!id&&!c.name)continue; const row={INLINE_ACTION:'TABLE_UPSERT',table:'companies',instance:INSTANCE,__instance:__i,'מזהה 1':id}; if(c.name)row['שם חברה']=c.name; if(c.email)row['מייל 1']=c.email; out.push({json:row}); }
return out;`,
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000010',
        name: 'Seed Companies',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1620, -500],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SeedCompanies = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000011a',
        name: 'Read gmail-doc',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [1220, -300],
    })
    ReadGmailDoc = {
        fileSelector: '/home/node/.n8n-files/demo-docs/invoice/files/*',
        options: {},
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000011b',
        name: 'Build gmail-doc',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1420, -300],
    })
    BuildGmailDoc = {
        jsCode: `function enchdr(s){ return '=?UTF-8?B?'+Buffer.from(String(s),'utf8').toString('base64')+'?='; }
function buildMime(o){
  const b='bnd_'+Math.random().toString(36).slice(2,12);
  const ext=(o.filename.split('.').pop()||'').toLowerCase();
  const ct = ext==='pdf' ? 'application/pdf' : (ext==='png'?'image/png':'image/jpeg');
  const att=o.contentB64.replace(/(.{76})/g,'$1\\r\\n');
  const L=['From: '+o.from,'To: '+o.to,'Date: '+(o.date||new Date().toUTCString()),'Subject: '+enchdr(o.subject),'MIME-Version: 1.0',
    'Content-Type: multipart/mixed; boundary="'+b+'"','',
    '--'+b,'Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
    Buffer.from(o.body,'utf8').toString('base64'),'',
    '--'+b,'Content-Type: '+ct+'; name="'+o.filename+'"','Content-Transfer-Encoding: base64',
    'Content-Disposition: attachment; filename="'+enchdr(o.filename)+'"','',att,'','--'+b+'--',''];
  return Buffer.from(L.join('\\r\\n'),'utf8').toString('base64');
}
const items=$input.all();
const N=$('Plan').first().json.n;
const labelName=$('Plan').first().json.labels['DOC_TO_SYNC'];
const _bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})(); const _S=new Set(((((_bp.syncs)||{})['gmail-doc'])||[]).map(f=>(f&&f.name)||f)); const wi = items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _idByName={}; for(const f of ((((_bp.syncs)||{})['gmail-doc'])||[])) _idByName[(f&&f.name)||f]=(f&&f.company_id); const _coById={}; for(const c of (_bp.companies||(_bp.company?[_bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
// LOCAL-ONLY MAILBOX GUARD. Whatever _active-blueprint.json names, a fixture injector may only
// write into a local test account: mailapi resolves a missing/blank id through the ambient
// /data/active.json pointer, which on this deployment is the CLIENT's real Gmail. Refusing here
// (rather than omitting the key) turns that into a loud failure instead of a silent delivery.
const __local=(v)=>{const s=String(v||''); return s.startsWith('mail_imap_local-')?s:'';};
const connId=__local(_bp.mail_connection_id);
const out=[];
for(const r of wi){
  const buf=await this.helpers.getBinaryDataBuffer(r.i,'data');
  const _co=_coById[String(_idByName[r.fn])]||{}; const _from=(_co.name||'Demo Supplier')+' <'+(_co.email||('demo+'+r.i+'@example.com'))+'>';
  const cn=r.fn.replace(/\\.[^.]+$/,'');
  const mime=buildMime({from:_from,to:'person2@example.com',subject:'חשבונית '+cn,body:'חשבונית (demo inject).',filename:r.fn,contentB64:buf.toString('base64')});
  out.push({json:{op:'append',params:{raw_base64:mime,labels:[labelName],folder:'INBOX',connection_id:connId}}});
}
return out;`,
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000011c',
        name: 'Send gmail-doc',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1620, -300],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SendGmailDoc = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000012a',
        name: 'Read gmail-bs',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [1220, -100],
    })
    ReadGmailBs = {
        fileSelector: '/home/node/.n8n-files/demo-docs/balance_sheet/files/*',
        options: {},
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000012b',
        name: 'Build gmail-bs',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1420, -100],
    })
    BuildGmailBs = {
        jsCode: `function enchdr(s){ return '=?UTF-8?B?'+Buffer.from(String(s),'utf8').toString('base64')+'?='; }
function buildMime(o){
  const b='bnd_'+Math.random().toString(36).slice(2,12);
  const ext=(o.filename.split('.').pop()||'').toLowerCase();
  const ct = ext==='pdf' ? 'application/pdf' : (ext==='png'?'image/png':'image/jpeg');
  const att=o.contentB64.replace(/(.{76})/g,'$1\\r\\n');
  const L=['From: '+o.from,'To: '+o.to,'Date: '+(o.date||new Date().toUTCString()),'Subject: '+enchdr(o.subject),'MIME-Version: 1.0',
    'Content-Type: multipart/mixed; boundary="'+b+'"','',
    '--'+b,'Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
    Buffer.from(o.body,'utf8').toString('base64'),'',
    '--'+b,'Content-Type: '+ct+'; name="'+o.filename+'"','Content-Transfer-Encoding: base64',
    'Content-Disposition: attachment; filename="'+enchdr(o.filename)+'"','',att,'','--'+b+'--',''];
  return Buffer.from(L.join('\\r\\n'),'utf8').toString('base64');
}
const items=$input.all();
const N=$('Plan').first().json.n;
const labelName=$('Plan').first().json.labels['BS_TO_SYNC'];
const _bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})(); const _S=new Set(((((_bp.syncs)||{})['gmail-bs'])||[]).map(f=>(f&&f.name)||f)); const wi = items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _idByName={}; for(const f of ((((_bp.syncs)||{})['gmail-bs'])||[])) _idByName[(f&&f.name)||f]=(f&&f.company_id); const _coById={}; for(const c of (_bp.companies||(_bp.company?[_bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
// LOCAL-ONLY MAILBOX GUARD. Whatever _active-blueprint.json names, a fixture injector may only
// write into a local test account: mailapi resolves a missing/blank id through the ambient
// /data/active.json pointer, which on this deployment is the CLIENT's real Gmail. Refusing here
// (rather than omitting the key) turns that into a loud failure instead of a silent delivery.
const __local=(v)=>{const s=String(v||''); return s.startsWith('mail_imap_local-')?s:'';};
const connId=__local(_bp.mail_connection_id);
const out=[];
for(const r of wi){
  const buf=await this.helpers.getBinaryDataBuffer(r.i,'data');
  const _co=_coById[String(_idByName[r.fn])]||{}; const _from=(_co.name||'Demo Supplier')+' <'+(_co.email||('demo+'+r.i+'@example.com'))+'>';
  const cn=r.fn.replace(/\\.[^.]+$/,'');
  const mime=buildMime({from:_from,to:'person2@example.com',subject:'דוח גיול '+cn,body:'דוח גיול (demo inject).',filename:r.fn,contentB64:buf.toString('base64')});
  out.push({json:{op:'append',params:{raw_base64:mime,labels:[labelName],folder:'INBOX',connection_id:connId}}});
}
return out;`,
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000012c',
        name: 'Send gmail-bs',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1620, -100],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SendGmailBs = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000013a',
        name: 'Read drive-gdoc',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [1220, 100],
    })
    ReadDriveGdoc = {
        fileSelector: '/home/node/.n8n-files/demo-docs/invoice/files/*',
        options: {},
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000013b',
        name: 'Build drive-gdoc',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1420, 100],
    })
    BuildDriveGdoc = {
        jsCode: `const items=$input.all();
const N=$('Plan').first().json.n;
const folderId=$('Plan').first().json.gdocFolder;
const _bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})(); const _S=new Set(((((_bp.syncs)||{})['drive-gdoc'])||[]).map(f=>(f&&f.name)||f)); const wi = items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _idByName={}; for(const f of ((((_bp.syncs)||{})['drive-gdoc'])||[])) _idByName[(f&&f.name)||f]=(f&&f.company_id); const _coById={}; for(const c of (_bp.companies||(_bp.company?[_bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
// WRITE op (upload) - must land on the local drive engine, not the service account (it cannot
// upload, by design). No registry entry backs this demo-inject path, so the local admin profile
// is the correct, explicit target (matches every other seed/upload in this file's own e2e-* lane).
return wi.map(r=>({json:{op:'upload',params:{folderId,name:((_coById[String(_idByName[items[r.i].binary.data.fileName])]||{}).name?((_coById[String(_idByName[items[r.i].binary.data.fileName])]||{}).name+' '):'')+items[r.i].binary.data.fileName,profile_id:'admin'}},binary:items[r.i].binary}));`,
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000013c',
        name: 'Send drive-gdoc',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1620, 100],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SendDriveGdoc = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ ({ ...$json.params, ...($json.params.connection_id ? { connection_id: $json.params.connection_id } : ($json.params.profile_id ? { profile_id: $json.params.profile_id } : {})) }) }}',
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
        id: 'ij000000-0000-0000-0000-000000000014a',
        name: 'Read drive-bs',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [1220, 300],
    })
    ReadDriveBs = {
        fileSelector: '/home/node/.n8n-files/demo-docs/balance_sheet/files/*',
        options: {},
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000014b',
        name: 'Build drive-bs',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1420, 300],
    })
    BuildDriveBs = {
        jsCode: `const items=$input.all();
const N=$('Plan').first().json.n;
const folderId=$('Plan').first().json.bsFolder;
const _bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})(); const _S=new Set(((((_bp.syncs)||{})['drive-bs'])||[]).map(f=>(f&&f.name)||f)); const wi = items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _idByName={}; for(const f of ((((_bp.syncs)||{})['drive-bs'])||[])) _idByName[(f&&f.name)||f]=(f&&f.company_id); const _coById={}; for(const c of (_bp.companies||(_bp.company?[_bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
// WRITE op (upload) - must land on the local drive engine, not the service account (it cannot
// upload, by design). No registry entry backs this demo-inject path, so the local admin profile
// is the correct, explicit target (matches every other seed/upload in this file's own e2e-* lane).
return wi.map(r=>({json:{op:'upload',params:{folderId,name:((_coById[String(_idByName[items[r.i].binary.data.fileName])]||{}).name?((_coById[String(_idByName[items[r.i].binary.data.fileName])]||{}).name+' '):'')+items[r.i].binary.data.fileName,profile_id:'admin'}},binary:items[r.i].binary}));`,
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000014c',
        name: 'Send drive-bs',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1620, 300],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SendDriveBs = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ ({ ...$json.params, ...($json.params.connection_id ? { connection_id: $json.params.connection_id } : ($json.params.profile_id ? { profile_id: $json.params.profile_id } : {})) }) }}',
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
        id: 'ij000000-0000-0000-0000-000000000015a',
        name: 'Read gmail-link',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [1220, 500],
    })
    ReadGmailLink = {
        fileSelector: '/home/node/.n8n-files/demo-docs/invoice/files/*',
        options: {},
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000015b',
        name: 'Build gmail-link',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1420, 500],
    })
    BuildGmailLink = {
        jsCode: `function enchdr(s){ return '=?UTF-8?B?' + Buffer.from(String(s), 'utf8').toString('base64') + '?='; }
const CRLF = String.fromCharCode(13, 10), NL = String.fromCharCode(10);
const items = $input.all();
const N=$('Plan').first().json.n;
const labelName = $('Plan').first().json.labels['DOC_LINK_TO_SYNC'];
const _bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})(); const _S=new Set(((((_bp.syncs)||{})['gmail-link'])||[]).map(f=>(f&&f.name)||f)); const wi = items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _idByName={}; for(const f of ((((_bp.syncs)||{})['gmail-link'])||[])) _idByName[(f&&f.name)||f]=(f&&f.company_id); const _coById={}; for(const c of (_bp.companies||(_bp.company?[_bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
// LOCAL-ONLY MAILBOX GUARD. Whatever _active-blueprint.json names, a fixture injector may only
// write into a local test account: mailapi resolves a missing/blank id through the ambient
// /data/active.json pointer, which on this deployment is the CLIENT's real Gmail. Refusing here
// (rather than omitting the key) turns that into a loud failure instead of a silent delivery.
const __local=(v)=>{const s=String(v||''); return s.startsWith('mail_imap_local-')?s:'';};
const connId = __local(_bp.mail_connection_id);
const out = [];
for (const r of wi) {
  const url = 'http://indox-demo-docs:8088/invoice/files/' + r.fn;
  const stem = r.fn.split('.').slice(0, -1).join('.') || r.fn;
  const body = ['שלום,', 'מצורף קישור למסמך לטיפול אוטומציה:', url, 'תודה.'].join(NL);
  const L = [
    'From: Demo Link <demolink+' + r.i + '@example.com>',
    'To: person2@example.com',
    'Date: ' + new Date().toUTCString(),
    'Subject: ' + enchdr('קישור למסמך - ' + stem),
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset="UTF-8"',
    'Content-Transfer-Encoding: base64',
    '',
    Buffer.from(body, 'utf8').toString('base64'),
    '',
  ];
  const mime = Buffer.from(L.join(CRLF), 'utf8').toString('base64');
  out.push({ json: { op: 'append', params: { raw_base64: mime, labels: [labelName], folder: 'INBOX', connection_id: connId } } });
}
return out;
`,
    };

    @node({
        id: 'ij000000-0000-0000-0000-000000000015c',
        name: 'Send gmail-link',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1620, 500],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SendGmailLink = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'read_bp',
        name: 'Read Blueprint',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [-200, 0],
    })
    ReadBlueprint = {
        fileSelector: '/home/node/.n8n-files/demo-docs/_active-blueprint.json',
        options: {},
    };

    @node({
        id: 'parse_bp',
        name: 'Parse Blueprint',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [-40, 0],
    })
    ParseBlueprint = {
        jsCode: "let bp={};try{const buf=await this.helpers.getBinaryDataBuffer(0,'data');bp=JSON.parse(buf.toString('utf8'))}catch(e){bp={}}return [{json:bp}];",
    };

    @node({
        id: 'e2e0001-0000-0000-0000-00000000maila',
        name: 'Read e2e-mail',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [1820, -500],
    })
    ReadE2eMail = {
        fileSelector: '/home/node/.n8n-files/demo-docs/e2e-loadtest/files/*',
        options: {},
    };

    @node({
        id: 'e2e0001-0000-0000-0000-00000000mailb',
        name: 'Build e2e-mail',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2020, -500],
    })
    BuildE2eMail = {
        jsCode: `function enchdr(s){ return '=?UTF-8?B?'+Buffer.from(String(s),'utf8').toString('base64')+'?='; }
function b64lines(s){ return s.replace(/(.{76})/g,'$1\\r\\n'); }
function mimePart(filename, contentB64){
  const ext=(filename.split('.').pop()||'').toLowerCase();
  const ct = ext==='pdf' ? 'application/pdf' : (ext==='png'?'image/png':'image/jpeg');
  return ['Content-Type: '+ct+'; name="'+filename+'"','Content-Transfer-Encoding: base64',
    'Content-Disposition: attachment; filename="'+enchdr(filename)+'"','',b64lines(contentB64),''].join('\\r\\n');
}
function buildMime(o){
  const b='bnd_'+Math.random().toString(36).slice(2,12);
  const head=['From: '+o.from,'To: '+o.to,'Date: '+(o.date||new Date().toUTCString()),
    'Subject: '+enchdr(o.subject),'MIME-Version: 1.0',
    'Content-Type: multipart/mixed; boundary="'+b+'"','',
    '--'+b,'Content-Type: text/plain; charset="UTF-8"','Content-Transfer-Encoding: base64','',
    Buffer.from(o.body,'utf8').toString('base64'),''].join('\\r\\n');
  const parts = o.attachments.map(a => '--'+b+'\\r\\n'+mimePart(a.filename, a.contentB64)).join('');
  return Buffer.from(head+'\\r\\n'+parts+'--'+b+'--\\r\\n','utf8').toString('base64');
}
const items=$input.all();
const bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})();
const list=((bp.syncs)||{})['e2e-mail']||[];
const _S=new Set(list.map(f=>(f&&f.name)||f));
const wi=items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _byName={}; for(const f of list) _byName[(f&&f.name)||f]=f;
const _coById={}; for(const c of (bp.companies||(bp.company?[bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
// LOCAL-ONLY MAILBOX GUARD. Whatever _active-blueprint.json names, a fixture injector may only
// write into a local test account: mailapi resolves a missing/blank id through the ambient
// /data/active.json pointer, which on this deployment is the CLIENT's real Gmail. Refusing here
// (rather than omitting the key) turns that into a loud failure instead of a silent delivery.
const __local=(v)=>{const s=String(v||''); return s.startsWith('mail_imap_local-')?s:'';};
const connId=__local(bp.mail_connection_id);
const groups={};
for(const r of wi){ const meta=_byName[r.fn]||{}; const gid=meta.group||r.fn; (groups[gid]=groups[gid]||[]).push({r,meta}); }
const out=[];
for(const gid of Object.keys(groups)){
  const entries=groups[gid]; const first=entries[0].meta;
  const co=_coById[String(first.company_id)]||{};
  const from=(first.sender_name||co.name||'E2E Supplier')+' <'+(first.sender_email||co.email||('e2e+'+gid+'@e2e-loadtest.local'))+'>';
  const subj='מסמכים '+(co.name||first.company_id||gid);
  const atts=[];
  for(const e of entries){ const buf=await this.helpers.getBinaryDataBuffer(e.r.i,'data'); atts.push({filename:e.r.fn,contentB64:buf.toString('base64')}); }
  const mime=buildMime({from,to:'e2e-loadtest@e2e-loadtest.local',subject:subj,
    body:'E2E load-test injected message ('+entries.length+' attachment(s)).',attachments:atts,date:first.mail_date});
  const params={raw_base64:mime,folder:'INBOX'};
  params.connection_id=connId;   // UNCONDITIONAL: see the guard above
  out.push({json:{op:'append',params}});
}
return out;`,
    };

    @node({
        id: 'e2e0001-0000-0000-0000-00000000mailc',
        name: 'Send e2e-mail',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [2220, -500],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SendE2eMail = {
        workflowId: {
            __rl: true,
            value: 'gmailApiImap01',
            mode: 'id',
        },
        options: {},
    };

    @node({
        id: 'e2e0002-0000-0000-0000-0000000gdoca',
        name: 'Read e2e-drive-gdoc',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [2420, -500],
    })
    ReadE2eDriveGdoc = {
        fileSelector: '/home/node/.n8n-files/demo-docs/e2e-loadtest/files/*',
        options: {},
    };

    @node({
        id: 'e2e0002-0000-0000-0000-0000000gdocb',
        name: 'Build e2e-drive-gdoc',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2620, -500],
    })
    BuildE2eDriveGdoc = {
        jsCode: `const items=$input.all();
const bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})();
const list=((bp.syncs)||{})['e2e-drive-gdoc']||[];
const _S=new Set(list.map(f=>(f&&f.name)||f));
const wi=items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _byName={}; for(const f of list) _byName[(f&&f.name)||f]=f;
const _coById={}; for(const c of (bp.companies||(bp.company?[bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
const folderId=(bp.drive_folders||{})['gdoc_to_sync']||'';
// LOCAL-ONLY DRIVE GUARD -- same reasoning as the mail guard: apps/drive refuses an
// unnamed connection (_explicit_connection_required), so an omitted key is a loud failure, but a
// SERVICE-ACCOUNT id here would write demo fixtures into the client's real Drive.
const __localdrive=(v)=>{const s=String(v||''); return s.startsWith('drive_local-')?s:'';};
const connId=__localdrive(bp.drive_connection_id);
return wi.map(r=>{
  const meta=_byName[r.fn]||{}; const co=_coById[String(meta.company_id)]||{};
  const params={folderId,name:(co.name?(co.name+' '):'')+r.fn};
  if(connId) params.connection_id=connId; else params.profile_id='admin';   // local admin, never the service account
  return {json:{op:'upload',params},binary:items[r.i].binary};
});`,
    };

    @node({
        id: 'e2e0002-0000-0000-0000-0000000gdocc',
        name: 'Send e2e-drive-gdoc',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [2820, -500],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SendE2eDriveGdoc = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ ({ ...$json.params, ...($json.params.connection_id ? { connection_id: $json.params.connection_id } : ($json.params.profile_id ? { profile_id: $json.params.profile_id } : {})) }) }}',
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
        id: 'e2e0003-0000-0000-0000-00000000e-bsa',
        name: 'Read e2e-drive-bs',
        type: 'n8n-nodes-base.readWriteFile',
        version: 1,
        position: [3020, -500],
    })
    ReadE2eDriveBs = {
        fileSelector: '/home/node/.n8n-files/demo-docs/e2e-loadtest/files/*',
        options: {},
    };

    @node({
        id: 'e2e0003-0000-0000-0000-00000000e-bsb',
        name: 'Build e2e-drive-bs',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [3220, -500],
    })
    BuildE2eDriveBs = {
        jsCode: `const items=$input.all();
const bp=(()=>{try{return $('Plan').first().json.bp||{}}catch(e){return {}}})();
const list=((bp.syncs)||{})['e2e-drive-bs']||[];
const _S=new Set(list.map(f=>(f&&f.name)||f));
const wi=items.map((it,i)=>({i,fn:(it.binary&&it.binary.data&&it.binary.data.fileName)||''})).filter(r=>_S.has(r.fn));
const _byName={}; for(const f of list) _byName[(f&&f.name)||f]=f;
const _coById={}; for(const c of (bp.companies||(bp.company?[bp.company]:[]))) _coById[String(c.id)]={name:c.name,email:c.email};
const folderId=(bp.drive_folders||{})['bs_to_sync']||'';
// LOCAL-ONLY DRIVE GUARD -- same reasoning as the mail guard: apps/drive refuses an
// unnamed connection (_explicit_connection_required), so an omitted key is a loud failure, but a
// SERVICE-ACCOUNT id here would write demo fixtures into the client's real Drive.
const __localdrive=(v)=>{const s=String(v||''); return s.startsWith('drive_local-')?s:'';};
const connId=__localdrive(bp.drive_connection_id);
return wi.map(r=>{
  const meta=_byName[r.fn]||{}; const co=_coById[String(meta.company_id)]||{};
  const params={folderId,name:(co.name?(co.name+' '):'')+r.fn};
  if(connId) params.connection_id=connId; else params.profile_id='admin';   // local admin, never the service account
  return {json:{op:'upload',params},binary:items[r.i].binary};
});`,
    };

    @node({
        id: 'e2e0003-0000-0000-0000-00000000e-bsc',
        name: 'Send e2e-drive-bs',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [3420, -500],
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SendE2eDriveBs = {
        workflowId: {
            __rl: true,
            value: 'driveApi01',
            mode: 'id',
        },
        options: {},
        workflowInputs: {
            mappingMode: 'defineBelow',
            value: {
                op: '={{ $json.op }}',
                params: '={{ ({ ...$json.params, ...($json.params.connection_id ? { connection_id: $json.params.connection_id } : ($json.params.profile_id ? { profile_id: $json.params.profile_id } : {})) }) }}',
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

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenClickingExecute.out(0).to(this.ReadBlueprint.in(0));
        this.WhenCalled.out(0).to(this.ReadBlueprint.in(0));
        this.ReqTagRules.out(0).to(this.ReqSettings.in(0));
        this.ReqSettings.out(0).to(this.GetSettings.in(0));
        this.GetSettings.out(0).to(this.Plan.in(0));
        this.ReadCompanies.out(0).to(this.BuildCompanies.in(0));
        this.BuildCompanies.out(0).to(this.SeedCompanies.in(0));
        this.ReadGmailDoc.out(0).to(this.BuildGmailDoc.in(0));
        this.BuildGmailDoc.out(0).to(this.SendGmailDoc.in(0));
        this.ReadGmailBs.out(0).to(this.BuildGmailBs.in(0));
        this.BuildGmailBs.out(0).to(this.SendGmailBs.in(0));
        this.ReadDriveGdoc.out(0).to(this.BuildDriveGdoc.in(0));
        this.BuildDriveGdoc.out(0).to(this.SendDriveGdoc.in(0));
        this.ReadDriveBs.out(0).to(this.BuildDriveBs.in(0));
        this.BuildDriveBs.out(0).to(this.SendDriveBs.in(0));
        this.Plan.out(0).to(this.ReadCompanies.in(0));
        this.SeedCompanies.out(0).to(this.ReadGmailDoc.in(0));
        this.SeedCompanies.out(0).to(this.ReadE2eMail.in(0));
        this.SendGmailDoc.out(0).to(this.ReadGmailBs.in(0));
        this.SendGmailBs.out(0).to(this.ReadDriveGdoc.in(0));
        this.SendDriveGdoc.out(0).to(this.ReadDriveBs.in(0));
        this.ReadGmailLink.out(0).to(this.BuildGmailLink.in(0));
        this.BuildGmailLink.out(0).to(this.SendGmailLink.in(0));
        this.SendDriveBs.out(0).to(this.ReadGmailLink.in(0));
        this.ReadBlueprint.out(0).to(this.ParseBlueprint.in(0));
        this.ParseBlueprint.out(0).to(this.ReqTagRules.in(0));
        this.ReadE2eMail.out(0).to(this.BuildE2eMail.in(0));
        this.BuildE2eMail.out(0).to(this.SendE2eMail.in(0));
        this.SendE2eMail.out(0).to(this.ReadE2eDriveGdoc.in(0));
        this.ReadE2eDriveGdoc.out(0).to(this.BuildE2eDriveGdoc.in(0));
        this.BuildE2eDriveGdoc.out(0).to(this.SendE2eDriveGdoc.in(0));
        this.SendE2eDriveGdoc.out(0).to(this.ReadE2eDriveBs.in(0));
        this.ReadE2eDriveBs.out(0).to(this.BuildE2eDriveBs.in(0));
        this.BuildE2eDriveBs.out(0).to(this.SendE2eDriveBs.in(0));
    }
}
