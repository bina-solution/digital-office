/* Mock backend for "חיבורים ומפתחות" (connections/secrets manager) — development/connections/ui.html.
   Real UI code is untouched; only window.fetch is intercepted. Data is for the fictitious
   client "בינה פתרונות בע״מ" (company_id 514789234, person127@example.com), matching the
   other digital-office/sim mocks (console.js, my-docs.js, mailview.js).

   Endpoints implemented (see ui.html's api() calls):
     GET    api/connections            -> {connections, summary}
     POST   api/reveal/:id             -> {value, note?}          body: {field?}
     GET    api/cred/:id               -> {fields}
     POST   api/set/:id                -> {ok}                    body: {field, value}
     DELETE api/set/:id                -> {ok}                    body: {field?}
     POST   api/conn/:id/test          -> {ok, status, detail}
     POST   api/regenerate/:id         -> {ok, impact}            (as the service answers; the screen reads `ok`)
     POST   api/disconnect/:id         -> {ok}
     POST   api/vault/wipe             -> {ok, wiped:{overrides,instances,minted}}  body: {confirm}
     POST   api/add                    -> {ok}                    body: {id,value,title,pillar}
     GET    api/qr/:id                 -> {qr_png, is_connected}
     GET    api/qr/:id/png             -> image/png (tiny placeholder; not reachable via fetch —
                                          the real <img> tag hits it directly, outside fetch's reach —
                                          kept only so a direct fetch() to it doesn't hard-fail)
     GET    api/audit                  -> {audit}

   In-memory store persists add/set/revert/rotate/disconnect/wipe mutations for the session. */
(function(){
  var realFetch = window.fetch ? window.fetch.bind(window) : null;

  function now(){ return Date.now()/1000; }
  function clone(o){ return JSON.parse(JSON.stringify(o)); }
  function randHex(n){ var s=''; var chars='0123456789abcdef'; for(var i=0;i<n;i++) s+=chars[Math.floor(Math.random()*16)]; return s; }
  function maskHint(v){ if(v==null) return null; var s=String(v); return s.length<=8?'••••'+s.slice(-2):'••••'+s.slice(-4); }

  /* ── seed rows (row-level fields consumed by the table: id, pillar, title/title_he, app,
     status, source, kind, protocol, consumers, masked, clear, secret, reveal_ok, rotatable,
     rotate_warn, impact) ── */
  var ROWS = [
    /* ── app-password: login passwords to the deployment's own apps ── */
    { id:'n8n-admin', pillar:'app-password', title:'n8n', title_he:'n8n',
      app:{name:'n8n', user:'person133@example.com', url:'https://n8n.bina-solutions.co.il'},
      kind:'password', status:'healthy', source:'db', secret:true, masked:'••••nX9k', clear:null,
      reveal_ok:true, rotatable:true },
    { id:'portainer-admin', pillar:'app-password', title:'Portainer', title_he:'Portainer',
      app:{name:'Portainer', user:'admin', url:'https://portainer.bina-solutions.co.il'},
      kind:'password', status:'needs_action', source:'env', secret:true, masked:'••••fault', clear:null,
      reveal_ok:true, rotatable:true, rotate_warn:'הסיסמה הנוכחית היא ברירת המחדל מההתקנה — מומלץ להחליף.' },
    { id:'glitchtip-admin', pillar:'app-password', title:'GlitchTip', title_he:'GlitchTip',
      app:{name:'GlitchTip', user:'person136@example.com', url:'https://glitchtip.bina-solutions.co.il'},
      kind:'password', status:'healthy', source:'minted', secret:true, masked:'••••7qLp', clear:null,
      reveal_ok:true, rotatable:true },
    { id:'supabase-studio-admin', pillar:'app-password', title:'Supabase Studio', title_he:'Supabase Studio',
      app:{name:'Supabase Studio', user:'person133@example.com', url:'https://supabase.bina-solutions.co.il'},
      kind:'password', status:'healthy', source:'db', secret:true, masked:'••••2Vt8', clear:null,
      reveal_ok:true, rotatable:true },
    { id:'authentik-admin', pillar:'app-password', title:'Authentik', title_he:'Authentik',
      app:{name:'Authentik', user:'akadmin', url:'https://auth.bina-solutions.co.il'},
      kind:'password', status:'missing', source:'unset', secret:true, masked:null, clear:null,
      reveal_ok:true, rotatable:true },

    /* ── auth: connections to external services ── */
    { id:'gmail-oauth', pillar:'auth', title:'Gmail', title_he:'Gmail',
      kind:'oauth-grant', protocol:'oauth2', consumers:['poll-inbox','sync-drive'],
      status:'healthy', source:'minted', secret:true, masked:'ya29.a0Ae••••', clear:null,
      reveal_ok:true, rotatable:false },
    { id:'gdrive-service-account', pillar:'auth', title:'Google Drive Service Account', title_he:'חשבון שירות — Drive',
      kind:'sa-key', protocol:'service-account', consumers:['sync-drive-files'],
      status:'healthy', source:'db', secret:true, masked:'••••.json', clear:null,
      reveal_ok:true, rotatable:true,
      rotate_warn:'יבטל את הגישה לקבצים המחוברים עד לטעינת מפתח שירות חדש.',
      impact:['sync-drive'] },
    { id:'whatsapp-qr', pillar:'auth', title:'WhatsApp Bot', title_he:'בוט ווצאפ',
      kind:'qr-session', protocol:'qr', consumers:['whatsapp-hacohanim'],
      status:'healthy', source:'minted', secret:true, masked:'linked', clear:null,
      reveal_ok:false, rotatable:false },
    { id:'openai-api-key', pillar:'auth', title:'OpenAI API Key', title_he:'מפתח API — OpenAI',
      kind:'text-secret', protocol:'api-key', consumers:['apitools OCR','extract-invoice'],
      status:'healthy', source:'db', secret:true, masked:'sk-proj-••••af3d', clear:null,
      reveal_ok:true, rotatable:true },
    { id:'green-api-bearer', pillar:'auth', title:'Green API Webhook', title_he:'Webhook — Green API',
      kind:'text-secret', protocol:'bearer-token', consumers:['notify'],
      status:'missing', source:'unset', secret:true, masked:null, clear:null,
      reveal_ok:true, rotatable:true },

    /* ── infra: system secrets, auto-managed ── */
    { id:'n8n-encryption-key', pillar:'infra', title:'n8n Encryption Key', title_he:'מפתח הצפנה — n8n',
      kind:'text-secret', status:'healthy', source:'minted', secret:true, masked:'••••e91c', clear:null,
      reveal_ok:true, rotatable:true,
      rotate_warn:'החלפת המפתח תבטל את הפענוח של credentials קיימים ב-n8n — נדרש ידע מוקדם בשחזור.',
      impact:['n8n','n8n-worker'] },
    { id:'postgres-root-password', pillar:'infra', title:'Postgres Root Password', title_he:'סיסמת root — Postgres',
      kind:'text-secret', status:'healthy', source:'minted', secret:true, masked:'••••Ps7q', clear:null,
      reveal_ok:true, rotatable:true,
      rotate_warn:'שינוי הסיסמה ידרוש עדכון בכל השירותים המחוברים למסד הנתונים ועלול לגרום להשבתה זמנית.',
      impact:['postgres','n8n','apitools'] },
    { id:'supabase-jwt-secret', pillar:'infra', title:'Supabase JWT Secret', title_he:'JWT Secret — Supabase',
      kind:'text-secret', status:'healthy', source:'minted', secret:true, masked:'••••eyJh', clear:null,
      reveal_ok:true, rotatable:true,
      rotate_warn:'יפסול את כל אסימוני ה-JWT הקיימים — כל המשתמשים המחוברים ינותקו.',
      impact:['supabase','authentik'] },
    { id:'traefik-basic-auth-hash', pillar:'infra', title:'Traefik Basic-Auth Hash', title_he:'Basic-Auth Hash — Traefik',
      kind:'derived', status:'healthy', source:'derived', secret:false, masked:null, clear:null,
      reveal_ok:true, rotatable:false }
  ];

  var CREDS = {
    'n8n-admin': { fields:[
      { key:'username', label:'שם משתמש', source:'db', primary:false, secret:false, clear:'person133@example.com' },
      { key:'password', label:'סיסמה', source:'db', primary:true, secret:true }
    ]},
    'portainer-admin': { fields:[
      { key:'username', label:'שם משתמש', source:'env', primary:false, secret:false, clear:'admin' },
      { key:'password', label:'סיסמה', source:'env', primary:true, secret:true }
    ]},
    'glitchtip-admin': { fields:[
      { key:'username', label:'שם משתמש', source:'db', primary:false, secret:false, clear:'person136@example.com' },
      { key:'password', label:'סיסמה', source:'minted', primary:true, secret:true }
    ]},
    'supabase-studio-admin': { fields:[
      { key:'username', label:'שם משתמש', source:'db', primary:false, secret:false, clear:'person133@example.com' },
      { key:'password', label:'סיסמה', source:'db', primary:true, secret:true }
    ]},
    'authentik-admin': { fields:[
      { key:'username', label:'שם משתמש', source:'unset', primary:false, secret:false, clear:null },
      { key:'password', label:'סיסמה', source:'unset', primary:true, secret:true }
    ]},
    'gmail-oauth': { fields:[
      { key:'access_token', label:'Access Token', source:'minted', primary:true, secret:true },
      { key:'refresh_token', label:'Refresh Token', source:'minted', primary:false, secret:true },
      { key:'client_id', label:'Client ID', source:'env', primary:false, secret:false, clear:'812345609-a1b2c3d4e5f6.apps.googleusercontent.com' },
      { key:'scope', label:'הרשאות', source:'env', primary:false, secret:false, clear:'gmail.readonly drive.file' }
    ]},
    'gdrive-service-account': { fields:[
      { key:'client_email', label:'Service Account Email', source:'db', primary:false, secret:false, clear:'person137@example.com' },
      { key:'private_key', label:'מפתח פרטי', source:'db', primary:true, secret:true }
    ]},
    'whatsapp-qr': { fields:[
      { key:'session', label:'סשן WhatsApp', source:'minted', primary:true, secret:true },
      { key:'phone', label:'מספר מקושר', source:'minted', primary:false, secret:false, clear:'050-000-0007' }
    ]},
    'openai-api-key': { fields:[
      { key:'api_key', label:'מפתח API', source:'db', primary:true, secret:true }
    ]},
    'green-api-bearer': { fields:[
      { key:'token', label:'Bearer Token', source:'unset', primary:true, secret:true }
    ]},
    'n8n-encryption-key': { fields:[
      { key:'value', label:'מפתח הצפנה', source:'minted', primary:true, secret:true }
    ]},
    'postgres-root-password': { fields:[
      { key:'value', label:'סיסמת root', source:'minted', primary:true, secret:true }
    ]},
    'supabase-jwt-secret': { fields:[
      { key:'value', label:'JWT Secret', source:'minted', primary:true, secret:true }
    ]},
    'traefik-basic-auth-hash': { fields:[
      { key:'hash', label:'Basic-Auth Hash', source:'derived', primary:true, derived:true, secret:true }
    ]}
  };

  /* actual secret values behind the masks, keyed 'id:field' — never sent unless revealed */
  var VAULT = {
    'n8n-admin:password': 'REDACTED-value-6',
    'portainer-admin:password': 'REDACTED-value-7',
    'glitchtip-admin:password': 'REDACTED-value-8',
    'supabase-studio-admin:password': 'REDACTED-value-9',
    'gmail-oauth:access_token': 'ya29.a0AfH6SMBx7k2Lq9pR3vTz8wYc1dE5fG6hI7jK8lM9nO0pQ1rS2tU3vW4xY5zA6bC7dE8fG9hI0jK',
    'gmail-oauth:refresh_token': '1//0gL8k2Jx9mNq3rTz5vYw8xAb1cD4eF7gH0iJ3kM',
    'gdrive-service-account:private_key': '-----BEGIN PRIVATE KEY-----
REDACTED
-----END PRIVATE KEY-----',
    'whatsapp-qr:session': 'session-active-9f8e7d6c5b4a',
    'openai-api-key:api_key': 'REDACTED-value-10',
    'n8n-encryption-key:value': 'e91c4f7a2b8d3e6f1a9c5b7d2e4f8a1c',
    'postgres-root-password:value': 'Ps7qXm2Vn9LtBk4Rw6',
    'supabase-jwt-secret:value': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.super-secret-signing-key-do-not-share',
    'traefik-basic-auth-hash:hash': 'admin:$apr1$xg9k2p1q$Fz3nR8mQjK1sT7wYc0dEa'
  };

  /* .env baseline defaults — what a field reverts to on DELETE api/set/:id */
  var ENV_DEFAULTS = {
    'portainer-admin:username': { source:'env', clear:'admin' },
    'portainer-admin:password': { source:'env', value:'tryportainer123' },
    'gmail-oauth:client_id': { source:'env', clear:'812345609-a1b2c3d4e5f6.apps.googleusercontent.com' },
    'gmail-oauth:scope': { source:'env', clear:'gmail.readonly drive.file' }
  };

  var AUDIT = [
    { event:'connect', id:'gmail-oauth', t: now()-86400*6 },
    { event:'rotate', id:'n8n-encryption-key', t: now()-86400*4 },
    { event:'edit', id:'supabase-studio-admin', field:'password', t: now()-86400*2 },
    { event:'test', id:'openai-api-key', t: now()-3600*5 },
    { event:'reveal', id:'n8n-admin', field:'password', t: now()-3600 }
  ];

  function findRow(id){ for(var i=0;i<ROWS.length;i++) if(ROWS[i].id===id) return ROWS[i]; return null; }
  function primaryField(id){
    var c = CREDS[id]; if(!c) return null;
    for(var i=0;i<c.fields.length;i++) if(c.fields[i].primary) return c.fields[i];
    return c.fields[0]||null;
  }
  function summarize(){
    var by = {};
    ROWS.forEach(function(r){ by[r.status] = (by[r.status]||0)+1; });
    return { total: ROWS.length, by_status: by };
  }
  function log(event,id,field){ AUDIT.unshift({event:event,id:id,field:field,t:now()}); }

  function J(o){ return Promise.resolve(new Response(JSON.stringify(o), {status:200, headers:{'Content-Type':'application/json'}})); }
  function parseBody(opts){ try{ return (opts&&opts.body)?JSON.parse(opts.body):{}; }catch(e){ return {}; } }

  /* 1x1 transparent PNG, for the (unreachable-via-fetch) api/qr/:id/png route */
  var TINY_PNG_B64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
  function pngBytes(){
    var bin = atob(TINY_PNG_B64), len = bin.length, bytes = new Uint8Array(len);
    for (var i=0;i<len;i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }

  window.fetch = function(url, opts){
    var u = String(url);
    var method = ((opts&&opts.method)||'GET').toUpperCase();

    if (/api\/connections(\?|$)/.test(u)) {
      return J({ connections: clone(ROWS), summary: summarize() });
    }

    if (/api\/reveal\/([^\/\?]+)/.test(u) && method==='POST') {
      var id = u.match(/api\/reveal\/([^\/\?]+)/)[1];
      var body = parseBody(opts);
      var field = body.field ? { key:body.field } : primaryField(id);
      if (!field) return J({ value:null, note:'אין ערך להצגה' });
      var val = VAULT[id+':'+field.key];
      if (val==null) return J({ value:null, note:'אין ערך להצגה' });
      log('reveal', id, body.field||undefined);
      return J({ value: val });
    }

    if (/api\/cred\/([^\/\?]+)/.test(u) && method==='GET') {
      var cid = u.match(/api\/cred\/([^\/\?]+)/)[1];
      var cred = CREDS[cid];
      return J({ fields: cred ? clone(cred.fields) : [] });
    }

    if (/api\/set\/([^\/\?]+)/.test(u)) {
      var sid = u.match(/api\/set\/([^\/\?]+)/)[1];
      var sbody = parseBody(opts);
      var cred2 = CREDS[sid];
      var row = findRow(sid);
      if (method==='DELETE') {
        var key = sbody.field || (primaryField(sid)||{}).key;
        if (cred2 && key) {
          var f = cred2.fields.find(function(x){return x.key===key;});
          var def = ENV_DEFAULTS[sid+':'+key];
          if (f) {
            f.source = def ? 'env' : 'unset';
            if (f.secret) { if (def && def.value!=null) VAULT[sid+':'+key]=def.value; else delete VAULT[sid+':'+key]; }
            else f.clear = def ? def.clear : null;
          }
          log('edit', sid, key);
        }
        return J({ ok:true });
      }
      // POST (create/update)
      var key2 = sbody.field || (primaryField(sid)||{}).key;
      if (cred2 && key2) {
        var f2 = cred2.fields.find(function(x){return x.key===key2;});
        if (f2) {
          f2.source = 'db';
          if (f2.secret) VAULT[sid+':'+key2] = sbody.value;
          else f2.clear = sbody.value;
        }
      }
      if (row && (!cred2 || (primaryField(sid)&&primaryField(sid).key===key2))) {
        row.source = 'db';
        row.masked = maskHint(sbody.value);
        if (row.status==='missing'||row.status==='unset'||row.status==='needs_action') row.status='healthy';
      }
      log('edit', sid, key2);
      return J({ ok:true });
    }

    if (/api\/conn\/([^\/]+)\/test/.test(u) && method==='POST') {
      var tid = u.match(/api\/conn\/([^\/]+)\/test/)[1];
      var trow = findRow(tid) || {};
      log('test', tid);
      var ok = trow.status==='healthy';
      return J({ ok: ok, status: trow.status||'unset', detail: ok?'תגובה תקינה מהשירות':'לא ניתן להתחבר לשירות' });
    }

    if (/api\/regenerate\/([^\/\?]+)/.test(u) && method==='POST') {
      var rid = u.match(/api\/regenerate\/([^\/\?]+)/)[1];
      var rrow = findRow(rid);
      var rcred = CREDS[rid];
      var newVal = randHex(16);
      if (rrow){
        var pf = primaryField(rid);
        if (pf) { VAULT[rid+':'+pf.key] = newVal; if(rcred){ var f3=rcred.fields.find(function(x){return x.key===pf.key;}); if(f3) f3.source = rrow.source==='env'?'minted':rrow.source; } }
        rrow.masked = maskHint(newVal);
        rrow.status = 'healthy';
        if (rrow.source==='env'||rrow.source==='unset') rrow.source='minted';
      }
      log('rotate', rid);
      return J({ ok:true, impact: (rrow&&rrow.impact)||[] });
    }

    if (/api\/disconnect\/([^\/\?]+)/.test(u) && method==='POST') {
      var did = u.match(/api\/disconnect\/([^\/\?]+)/)[1];
      var drow = findRow(did);
      if (drow) {
        drow.status = 'missing';
        drow.source = 'unset';
        drow.masked = null;
        var dcred = CREDS[did];
        if (dcred) dcred.fields.forEach(function(f){ if(f.secret) delete VAULT[did+':'+f.key]; else f.clear=null; f.source='unset'; });
      }
      log('revoke', did);
      return J({ ok:true });
    }

    if (/api\/vault\/wipe/.test(u) && method==='POST') {
      var wbody = parseBody(opts);
      if (wbody.confirm!=='wipe') return J({ ok:false });
      var overrides=0, instances=0, minted=0;
      ROWS.forEach(function(r){
        if (r.source==='db') overrides++;
        if (r.source==='minted') minted++;
        if (r.pillar==='auth' && (r.kind==='oauth-grant'||r.kind==='qr-session'||r.kind==='sa-key') && r.status==='healthy') instances++;
        if (r.source==='db' || r.source==='minted') {
          var hasEnvDefault = Object.keys(ENV_DEFAULTS).some(function(k){ return k.indexOf(r.id+':')===0; });
          r.source = hasEnvDefault ? 'env' : 'unset';
          r.status = hasEnvDefault ? 'needs_action' : 'missing';
          r.masked = null; r.clear = null;
        }
        if (r.pillar==='auth' && (r.kind==='oauth-grant'||r.kind==='qr-session')) { r.status='missing'; r.source='unset'; r.masked=null; }
      });
      Object.keys(CREDS).forEach(function(id){
        CREDS[id].fields.forEach(function(f){
          var def = ENV_DEFAULTS[id+':'+f.key];
          f.source = def ? 'env' : (f.derived?'derived':'unset');
          if (f.secret) { if(def&&def.value!=null) VAULT[id+':'+f.key]=def.value; else delete VAULT[id+':'+f.key]; }
          else f.clear = def ? def.clear : null;
        });
      });
      log('edit', 'vault-wipe');
      return J({ ok:true, wiped:{ overrides:overrides, instances:instances, minted:minted } });
    }

    if (/api\/add(\?|$)/.test(u) && method==='POST') {
      var abody = parseBody(opts);
      var aid = abody.id;
      ROWS.push({ id:aid, pillar:abody.pillar||'auth', title:abody.title||aid, title_he:abody.title||aid,
        kind:'text-secret', status:'healthy', source:'db', secret:true, masked:maskHint(abody.value), clear:null,
        reveal_ok:true, rotatable:true });
      CREDS[aid] = { fields:[ { key:'value', label:'ערך', source:'db', primary:true, secret:true } ] };
      VAULT[aid+':value'] = abody.value;
      log('edit', aid, 'value');
      return J({ ok:true });
    }

    if (/api\/qr\/([^\/\?]+)\/png/.test(u) && method==='GET') {
      return Promise.resolve(new Response(pngBytes(), {status:200, headers:{'Content-Type':'image/png'}}));
    }

    if (/api\/qr\/([^\/\?]+)(\?|$)/.test(u) && method==='GET') {
      var qid = u.match(/api\/qr\/([^\/\?]+)/)[1];
      var qrow = findRow(qid) || {};
      return J({ qr_png:false, is_connected: qrow.status==='healthy' });
    }

    if (/api\/audit(\?|$)/.test(u)) {
      return J({ audit: clone(AUDIT) });
    }

    return realFetch ? realFetch(url, opts) : Promise.reject(new Error('mock: no route '+u));
  };
})();
