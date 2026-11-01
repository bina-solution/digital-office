
// Public base of THIS dispatcher, from the deployment (apps/openhands/docker-compose.yml sets
// DISPATCH_PUBLIC_URL from ${DISPATCH_BASE_URL}, which derives from DEPLOYMENT_DOMAIN). It was a
// literal at every call site, so every link the bot handed out named the FIRST deployment's
// domain no matter which deployment sent it.
const DISPATCH_PUBLIC_URL = (process.env.DISPATCH_PUBLIC_URL || 'http://localhost:8800').replace(/\/+$/, '');
// Dashboard UI — Chat interface and Issues Web UI
// Pure rendering functions, all dependencies passed as parameters.

// The colours are the office's palette: every page this service writes opens its stylesheet with the
// block below (a copy of platform-base/bina-ui/theme-tokens.css, kept by G27) and names no colour.
export const THEME = `/* @bina-theme-tokens:start */
/* OLIVE GROVE — the one palette of the office (the owner, 2026-10-07 · DGO-450). Four hues, sampled
   from his mock-up, and the ground they stand on. A screen never writes a colour: it names one of
   these. Each hue is the colour itself (a FILL — a button, a bar, a dot), «-d» for text and thin
   lines on the ground (4.5:1 or more), «-soft» and «-line» for a tint and its hairline, and «-ink»
   for what is written ON the fill. The role names every screen already uses point at them:
   (no backtick in this block: one of its copies lives inside a script's template string)
     olive  the brand and the main action · what is well, what is done
     sky    what is in motion, what only informs · a link
     lime   look here — a warning, something waiting
     plum   a person must act — a failure, a removal, the one final action
   Contrast, measured (WCAG): ink on the ground 13.7 · muted 4.65 · light text on olive 5.51 and on
   plum 9.54 · ink on lime 6.88 · its ink on sky 6.32 · sky-d 4.61 · lime-d 4.70 · violet 5.32 ·
   on the desk: its ink 6.32 (dark: 13.96), and 11.2 where the sky pales (dark: 5.12). */
:root,:root[data-theme="light"]{
  color-scheme:light;
  accent-color:var(--accent);   /* the browser's OWN controls - a checkbox, a radio, a range, a progress bar - on both grounds: said once, here (it was said for eight single controls, and every other one was the browser's blue) */
  --bg:#f3f5f7; --surface:#fff; --surface-2:#f9fafb; --ink:#1f2a17; --muted:#6a7068; --line:#dcdfde;
  --olive:#56693f; --olive-d:#475734; --olive-soft:#e7eae4; --olive-line:#bfc6b6; --olive-ink:#f3f5f7;
  --sky:#7baae3; --sky-d:#2a6fc4; --sky-soft:#edf3fb; --sky-line:#cddff4; --sky-ink:#13263f;
  --lime:#a9b84c; --lime-d:#69732e; --lime-soft:#f3f5e6; --lime-line:#dee4bb; --lime-ink:#1f2a17;
  --plum:#5b3349; --plum-d:#4a303b; --plum-soft:#e8e2e6; --plum-line:#c1b1ba; --plum-ink:#f3f5f7;
  --accent:var(--olive); --accent-d:var(--olive-d); --accent-soft:var(--olive-soft); --accent-ink:var(--olive-ink);
  --blue:var(--sky-d); --amber:var(--lime-d); --red:var(--plum);
  --violet:#7c5c6d;   /* plum, lifted a fifth toward white: someone has to look — nothing has failed */
  --ok:var(--olive); --warn:var(--lime-d); --danger:var(--plum); --info:var(--sky-d);
  --ok-soft:var(--olive-soft); --warn-soft:var(--lime-soft); --danger-soft:var(--plum-soft); --info-soft:var(--sky-soft);
  --red-soft:var(--plum-soft); --amber-soft:var(--lime-soft); --blue-soft:var(--sky-soft); --violet-soft:var(--plum-soft);
  --side:var(--olive); --side-ink:#f3f5f7; --side-mut:#dce1da; --side-line:#788765;
  --desk:var(--sky); --desk-ink:var(--sky-ink);   /* desktop mode's ground is the sky (the owner, DGO-452), and what is written straight on it */
  --scrim:rgba(31,42,23,.5);                      /* what dims a screen behind a pop-up */
  --shadow:0 1px 3px rgba(31,42,23,.08),0 6px 24px rgba(31,42,23,.06);
  --shadow-lg:0 20px 60px rgba(31,42,23,.28);
  /* ONE COLOUR AND ONE ANIMAL PER OFFICE (the owner, 2026-10-09 · flt-002). When offices are linked,
     a person reads WHICH office a thing belongs to without opening it, so each office gets a hue of
     its own. The hue is an IDENTITY and never a health state: an office that stopped answering keeps
     its colour, and the quiet mark is the one that says "not answering". Each is an ALIAS of the
     palette's own hue — no fourth value is invented, and because the ground re-points the hue, the
     office mark follows the ground by itself. Each office's animal (elephant, deer, eagle) is a
     glyph of bina-icons.js. */
  --office-hp:var(--muted);   /* hp · elephant — grey: the heavy laptop at home, in the palette's own grey */
  --office-mac:var(--lime);   /* macbook · deer — yellow: the palette has one yellow and it is lime. A FILL, so what is written ON it is --lime-ink, never this */
  --office-vps:var(--sky-d);  /* vps · eagle — deep sky blue, «the eagle in the clouds». THE OWNER'S OWN CHOICE (2026-10-09, in writing: vps = נשר + כחול-שמיים) — this line is the colour he picked, not a default kept for him */
}

/* ── A LINKED OFFICE'S MARK, BY NAME (flt-004) ───────────────────────────────────────────────
   The link carries a NAME — mark: {color, animal} in the catalog, from the office's own identity
   — and never a value: the office that DRAWS a linked tile owns the pixels, so it paints the name
   with its own palette. These seven rules are that translation, one per family above; a screen sets
   data-office-hue="lime" and paints var(--office-hue).
   A name this file does not know paints nothing, which is why the vocabulary in
   apps/dgo-extend/identity.py may only name families that exist here — and why --red and --ok
   are not among them: they mean «danger» and «it is well» on every screen in the office. */
[data-office-hue="grey"]   { --office-hue:var(--muted); }
[data-office-hue="lime"]   { --office-hue:var(--lime); }
[data-office-hue="sky"]    { --office-hue:var(--sky-d); }
[data-office-hue="olive"]  { --office-hue:var(--olive-d); }
[data-office-hue="plum"]   { --office-hue:var(--plum); }
[data-office-hue="blue"]   { --office-hue:var(--blue); }
[data-office-hue="violet"] { --office-hue:var(--violet); }
/* the dark ground is the same four hues on the palette's own ink, and the SAME legend. Olive on that
   ink is 2.5:1, so its text step there is olive LIFTED — its own hue and saturation, lighter (7.14
   on a card, 4.82 on its own tint) — and the brand, the main action and «it is well» take that step.
   Lime stays «look here» and the sky «in motion», as on the light ground: were lime the accent here
   (it was, for a day), a warning, a selection and «it is well» were one colour. Each «-d» on its
   own «-soft» there, measured: olive 4.82 · sky 4.62 · lime 4.63 · plum 4.71. */
@media (prefers-color-scheme:dark){
  :root{ color-scheme:dark;
         --bg:#141b0f; --surface:#1f2a17; --surface-2:#192213; --ink:#f3f5f7; --muted:#a2a8a2; --line:#414a3b;
         --olive-d:#a5ba8c; --olive-soft:#384629; --olive-line:#56693f;
         --sky-d:#7baae3; --sky-soft:#2e3f38; --sky-line:#4d6a8c;
         --lime-d:#a9b84c; --lime-soft:#3b4622; --lime-line:#69732e;
         --plum-d:#ad99a4; --plum-soft:#402f33; --plum-line:#7c5c6d;
         --accent:var(--olive-d); --accent-ink:var(--surface);
         --red:#ad99a4; --violet:#bdadb6; --danger:#ad99a4; --ok:var(--olive-d); --side:var(--surface);
         --desk:var(--sky-ink); --desk-ink:var(--ink); --scrim:rgba(0,0,0,.6);
         --shadow:0 1px 3px rgba(0,0,0,.4),0 6px 24px rgba(0,0,0,.3);
         --shadow-lg:0 20px 60px rgba(0,0,0,.55); }
}
:root[data-theme="midnight"]{
  color-scheme:dark;
  --bg:#141b0f; --surface:#1f2a17; --surface-2:#192213; --ink:#f3f5f7; --muted:#a2a8a2; --line:#414a3b;
  --olive-d:#a5ba8c; --olive-soft:#384629; --olive-line:#56693f;
  --sky-d:#7baae3; --sky-soft:#2e3f38; --sky-line:#4d6a8c;
  --lime-d:#a9b84c; --lime-soft:#3b4622; --lime-line:#69732e;
  --plum-d:#ad99a4; --plum-soft:#402f33; --plum-line:#7c5c6d;
  --accent:var(--olive-d); --accent-ink:var(--surface);
  --red:#ad99a4; --violet:#bdadb6; --danger:#ad99a4; --ok:var(--olive-d); --side:var(--surface);
  --desk:var(--sky-ink); --desk-ink:var(--ink); --scrim:rgba(0,0,0,.6);
  --shadow:0 1px 3px rgba(0,0,0,.4),0 6px 24px rgba(0,0,0,.3);
  --shadow-lg:0 20px 60px rgba(0,0,0,.55);
}
/* THE KEYBOARD'S RING - what the browser draws around the stop the keyboard is on, in the palette, wherever
   a part draws none of its own. It has no specificity at all (:where), so any rule of a part wins. Two
   screens said this for themselves; on the others nearly every stop wore the browser's ring (DGO-455).
   A field keeps the offset it has - fourteen rules draw a field's own outline and say no offset. An area
   (a scroll box, a table) takes the ring inside, where nothing clips it; a control takes it outside,
   where a filled button does not hide it. */
:where(:focus-visible){outline:2px solid var(--accent)}
:where(:focus-visible:not(a,button,summary,[role=button],input,select,textarea)){outline-offset:-2px}
:where(a,button,summary,[role=button]):focus-visible{outline-offset:2px}
/* HEBREW AT A HEAVY WEIGHT - on Windows, where the first family of --font is installed. "Segoe UI" has its
   Hebrew in Light, Regular, Semibold and Bold. Asked for 800 or 900 the browser takes the family's Black
   face, which has none, and so has every family after it - so the Hebrew of every title at 800 was drawn in
   the system's last-resort serif, thin, beside Latin in Black: «חשבונות ומראות» at 20px is 150px wide at 700
   and 120px at 800 (Chrome 154; the screens ask for 800 in 167 places, the question's title among them).
   These faces give the family's HEBREW RANGE the faces that have it. A family a sheet names is no longer the
   system's for those characters, so every weight and both styles are named, each as the system resolves it:
   measured, only upright 800 and 900 change. Any other character is not theirs and goes on to the next
   family the screen names - system-ui in --font, on Windows the same faces, Black included - which is why
   G27 asks that system-ui follows wherever a screen names this family itself. Where the family is not
   installed nothing here resolves and nothing changes. */
@font-face{font-family:"Segoe UI";src:local("Segoe UI Light");font-weight:100 300;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI");font-weight:400;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Semibold");font-weight:500 600;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Bold");font-weight:700 900;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Light Italic");font-weight:100 300;font-style:italic;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Italic");font-weight:400;font-style:italic;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Semibold Italic");font-weight:500 600;font-style:italic;unicode-range:U+0590-05FF,U+FB1D-FB4F}
@font-face{font-family:"Segoe UI";src:local("Segoe UI Bold Italic");font-weight:700 900;font-style:italic;unicode-range:U+0590-05FF,U+FB1D-FB4F}
/* @bina-theme-tokens:end */`;

export function getDashboard(sessions, ohDB, OPENHANDS_PUBLIC_URL, inFlight, DEFAULT_PROFILE, AVAILABLE_MODELS) {
  var sessionsJson = [];
  for (const [uid, s] of sessions) {
    var ago = Math.round((Date.now() - s.lastActiveAt) / 1000);
    sessionsJson.push({
      userId: uid, model: s.model || 'default', turnCount: s.turnCount, lastActiveAgo: ago,
      lastActiveStr: ago < 60 ? ago + 's ago' : ago < 3600 ? Math.round(ago/60) + 'm ago' : Math.round(ago/3600) + 'h ago',
      conversationId: s.ohConvId,
      conversationUrl: s.ohConvId ? '' + DISPATCH_PUBLIC_URL + '/chat?uid=' + uid : null
    });
  }

  var dbConvsJson = [];
  try {
    if (ohDB) {
      var cur = ohDB.prepare("SELECT conversation_id, title, created_at FROM conversation_metadata WHERE user_id = 'dispatcher' ORDER BY created_at DESC LIMIT 50").all();
      for (var i = 0; i < cur.length; i++) {
        var c = cur[i];
        var cid = Array.isArray(c) ? c[0] : c.conversation_id;
        dbConvsJson.push({
          id: cid, title: (Array.isArray(c) ? c[1] : c.title) || '(untitled)',
          createdAt: Array.isArray(c) ? c[2] : c.created_at,
          url: OPENHANDS_PUBLIC_URL + '/conversations/' + cid
        });
      }
    }
  } catch(e) {}

  return '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>Dispatcher — Chat UI</title>\n<style>\n' +
    getChatCSS() + '\n</style>\n</head>\n<body>\n' +
    getChatHTML(sessionsJson, dbConvsJson, inFlight, OPENHANDS_PUBLIC_URL, DEFAULT_PROFILE, AVAILABLE_MODELS) +
    '\n<script>\n' + getChatJS() + '\n</script>\n</body>\n</html>';
}

function getChatCSS() {
  return `${THEME}*{box-sizing:border-box;margin:0;padding:0}body{font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--ink);height:100vh;display:flex;flex-direction:column;overflow:hidden}header{background:var(--surface);padding:10px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;flex-shrink:0}header h1{font-size:16px;font-weight:600}header .stats{display:flex;gap:16px;font-size:12px}header .stats span{padding:3px 10px;border-radius:12px;font-weight:500}.ok{background:var(--accent-soft);color:var(--accent-d)}.warn{background:var(--warn-soft);color:var(--amber)}.layout{display:flex;flex:1;overflow:hidden}.sidebar{width:320px;background:var(--surface);border-right:1px solid var(--line);display:flex;flex-direction:column;overflow-y:auto;flex-shrink:0}.sidebar h2{font-size:13px;font-weight:600;padding:10px 14px;border-bottom:1px solid var(--line);color:var(--muted);text-transform:uppercase;letter-spacing:.5px;position:sticky;top:0;background:var(--surface);z-index:1}.sidebar .session-item{padding:8px 14px;border-bottom:1px solid var(--surface);font-size:12px;cursor:pointer;transition:background .15s}.sidebar .session-item:hover{background:var(--surface-2)}.sidebar .session-item .uid{font-family:monospace;font-size:11px}.sidebar .session-item .meta{color:var(--muted);font-size:11px;margin-top:2px}.sidebar .session-item .url{font-size:10px;color:var(--muted);word-break:break-all}.sidebar .session-item.active-sess{background:var(--accent-soft);border-left:3px solid var(--accent)}.main{flex:1;display:flex;flex-direction:column;min-width:0}.messages{flex:1;overflow-y:auto;padding:16px}.msg{margin-bottom:12px;max-width:85%;animation:fadeIn .2s}.msg.user{margin-left:auto}.msg.user .bubble{background:var(--olive-soft);border:1px solid var(--olive-line);border-radius:12px 12px 0 12px;padding:10px 14px}.msg.agent .bubble{background:var(--surface);border:1px solid var(--line);color:var(--ink);border-radius:12px 12px 12px 0;padding:10px 14px}.msg.status .bubble{background:transparent;color:var(--muted);font-size:12px;text-align:center;padding:4px}.msg.error .bubble{background:var(--danger-soft);color:var(--red);border-radius:8px;padding:10px 14px;font-size:13px}.msg .ts{font-size:10px;color:var(--muted);margin-top:4px}.msg.user .ts{text-align:right}.chat-input-area{background:var(--surface);border-top:1px solid var(--line);padding:12px 16px;flex-shrink:0}.chat-input-area .row{display:flex;gap:8px;align-items:center}.chat-input-area input[type=text]{flex:1;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 14px;color:var(--ink);font-size:14px;outline:none;min-width:0}.chat-input-area input[type=text]:focus{border-color:var(--accent)}.chat-input-area select{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 8px;color:var(--ink);font-size:13px;outline:none;max-width:160px}.chat-input-area button{background:var(--accent);color:var(--accent-ink);border:none;border-radius:8px;padding:10px 20px;font-size:14px;cursor:pointer;white-space:nowrap;font-weight:500}.chat-input-area button:hover{background:var(--accent-d)}.chat-input-area button:disabled{background:var(--muted);cursor:default}.chat-input-area .aux-row{display:flex;gap:8px;margin-top:6px}.chat-input-area .aux-row input{font-size:12px;padding:6px 10px}.chat-input-area .aux-row label{font-size:11px;color:var(--muted);display:flex;align-items:center;gap:4px;cursor:pointer}.conv-item{padding:8px 14px;border-bottom:1px solid var(--surface);font-size:12px;cursor:pointer}.conv-item:hover{background:var(--surface-2)}.conv-item .title{color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.conv-item .date{color:var(--muted);font-size:10px;margin-top:2px}.empty-state{text-align:center;padding:40px 20px;color:var(--muted)}.empty-state .icon{font-size:48px;margin-bottom:12px}.loading-dots{display:inline-flex;gap:4px}.loading-dots span{width:6px;height:6px;border-radius:50%;background:var(--muted);animation:bounce 1.4s infinite}.loading-dots span:nth-child(2){animation-delay:.2s}.loading-dots span:nth-child(3){animation-delay:.4s}@keyframes bounce{0%,80%,100%{transform:scale(0)}40%{transform:scale(1)}}@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}a{color:var(--accent-d);text-decoration:none}a:hover{text-decoration:underline}::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--line);border-radius:3px}`;
}

function escapeHtml(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function escapeJs(s) { return (s||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'\\"').replace(/\n/g,'\\n'); }

function getChatHTML(sessionsJson, dbConvsJson, inFlight, OPENHANDS_PUBLIC_URL, DEFAULT_PROFILE, AVAILABLE_MODELS) {
  var sessionRows = '';
  if (sessionsJson.length === 0) {
    sessionRows = '<div class="empty-state" style="padding:20px;font-size:12px">No active sessions</div>';
  } else {
    for (var i = 0; i < sessionsJson.length; i++) {
      var s = sessionsJson[i];
      sessionRows += '<div class="session-item" onclick="selectUser(\'' + escapeJs(s.userId) + '\')" data-uid="' + escapeJs(s.userId) + '">' +
        '<div class="uid">' + escapeHtml(s.userId) + '</div>' +
        '<div class="meta">' + escapeHtml(s.model) + ' • ' + s.turnCount + ' turns • ' + s.lastActiveStr + '</div>' +
        (s.conversationUrl ? '<div class="url"><a href="' + escapeHtml(s.conversationUrl) + '" target="_blank" onclick="event.stopPropagation()">Open in OpenHands ↗</a></div>' : '') + '</div>';
    }
  }
  var convRows = '';
  if (dbConvsJson.length === 0) {
    convRows = '<div class="empty-state" style="padding:20px;font-size:12px">No conversations yet</div>';
  } else {
    for (var j = 0; j < dbConvsJson.length; j++) {
      var c = dbConvsJson[j];
      convRows += '<div class="conv-item"><a href="' + escapeHtml(c.url) + '" target="_blank" class="title" title="' + escapeHtml(c.title) + '">' + escapeHtml(c.title.slice(0,55)) + '</a><div class="date">' + (c.createdAt || '') + '</div></div>';
    }
  }
  var modelOptions = '<option value="">Auto (' + DEFAULT_PROFILE.replace(/'/g,"\\'") + ')</option>\n' + AVAILABLE_MODELS.map(function(m){ return '<option value="' + m.name.replace(/"/g,'&quot;') + '">' + m.name + '</option>'; }).join('\n');
  return '<header><h1>📡 Dispatcher Chat</h1><div class="stats"><span class="ok" id="inFlightStat">⬆ ' + inFlight + ' active</span><span class="ok" id="sessionsStat">📋 ' + sessionsJson.length + ' sessions</span><span style="font-size:11px;color:var(--muted)">' + OPENHANDS_PUBLIC_URL + '</span></div></header><div class="layout"><div class="sidebar"><h2>🟢 Active Sessions</h2><div id="sessionList">' + sessionRows + '</div><h2>📜 Chat History</h2><div id="convList">' + convRows + '</div></div><div class="main"><div class="messages" id="messages"><div class="empty-state"><div class="icon">💬</div><p>Send a message to start chatting with the OpenHands AI agent.</p><p style="font-size:12px;margin-top:8px;color:var(--muted)">Default model: ' + DEFAULT_PROFILE + '</p></div></div><div class="chat-input-area"><div class="row"><input type="text" id="msgInput" placeholder="Type your message..." autofocus onkeydown="if(event.key===\'Enter\'&&!event.shiftKey){event.preventDefault();sendMessage()}"><select id="modelSelect">' + modelOptions + '</select><button id="sendBtn" onclick="sendMessage()">🚀 Send</button></div><div class="aux-row"><input type="text" id="imageUrlInput" placeholder="Image URL (optional)" style="flex:1"><input type="text" id="userIdInput" placeholder="User ID (auto-generated)" value="web-chat-' + Date.now().toString(36) + '" style="width:180px"><label><input type="checkbox" id="includeCtx" checked> Session ctx</label></div></div></div></div>';
}

function getChatJS() {
  return `var currentUserId=document.getElementById('userIdInput').value;var messageCount=0;var isSending=!1;function escapeHtml(e){return(e||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}function selectUser(e){currentUserId=e,document.getElementById("userIdInput").value=e,document.getElementById("msgInput").focus(),document.querySelectorAll(".session-item").forEach(function(t){t.classList.remove("active-sess")});var t=document.querySelector('[data-uid="'+e.replace(/'/g,"\\\\'")+'"]');t&&t.classList.add("active-sess")}function addMessage(e,t,n){var o=document.getElementById("messages");0===messageCount&&(o.innerHTML=""),messageCount++;var s=document.createElement("div");s.className="msg "+e;var a='<div class="bubble">'+escapeHtml(t).replace(/\\\\n/g,"<br>")+"</div>",i='<div class="ts">'+new Date().toLocaleTimeString()+"</div>";if(s.innerHTML=a+i,n){var r=document.createElement("div");r.style.cssText="font-size:10px;color:var(--muted);margin-top:2px",r.innerHTML=n,s.appendChild(r)}return o.appendChild(s),o.scrollTop=o.scrollHeight,s}function addLoadingMsg(){var e=document.getElementById("messages");0===messageCount&&(e.innerHTML="");var t=document.createElement("div");t.className="msg status",t.id="loadingMsg",t.innerHTML='<div class="bubble"><div class="loading-dots"><span></span><span></span><span></span></div> Creating session...</div>',e.appendChild(t),e.scrollTop=e.scrollHeight}var currentStatusDiv=null;function updateStatus(e){currentStatusDiv?currentStatusDiv.querySelector(".bubble").innerHTML=escapeHtml(e):currentStatusDiv=addMessage("status",e),document.getElementById("messages").scrollTop=document.getElementById("messages").scrollHeight}async function sendMessage(){if(!isSending){var e=document.getElementById("msgInput"),t=e.value.trim();if(t){var n=currentUserId||document.getElementById("userIdInput").value.trim()||"web-chat-"+Date.now().toString(36);currentUserId=n,document.getElementById("userIdInput").value=n;var o=document.getElementById("modelSelect"),s=o.options[o.selectedIndex].value||void 0,a=document.getElementById("imageUrlInput"),i=a.value.trim()||void 0;addMessage("user",t),e.value="",a.value="",isSending=!0,document.getElementById("sendBtn").disabled=!0,currentStatusDiv=null,addLoadingMsg();var r={userId:n,message:t};s&&(r.model=s),i&&(r.imageUrls=[i]);try{var c=await fetch("/dispatch",{method:"POST",headers:{"content-type":"application/json","x-from-dashboard":"1"},body:JSON.stringify(r)});if(!c.ok){var d=await c.text().catch(function(){return""});return removeLoading(),void addMessage("error","HTTP "+c.status+": "+d.slice(0,200))}removeLoading();for(var l=c.body.getReader(),u=new TextDecoder,m="";;){var g=await l.read();if(g.done)break;m+=u.decode(g.value,{stream:!0});for(var p=m.split("\\n"),f=0;f<(m=p.pop()||"",p).length;f++){var h=p[f].trim();if(h)try{var v=JSON.parse(h),y=v.type;if("start"===y)addMessage("status","Session started \\u2022 Model: "+v.model+" \\u2022 Turn: "+v.turn);else if("status"===y)updateStatus(v.message);else if("result"===y){removeStatusDiv();var _=v.message||"Session ready",b="";v.conversationUrl&&(b='<a href="'+v.conversationUrl+'" target="_blank">🔗 Open in OpenHands →</a>'),addMessage("agent",_,b)}else"error"===y?(removeStatusDiv(),addMessage("error",v.message)):"final"===y&&v.durationMs&&addMessage("status","✓ Done in "+Math.round(v.durationMs/100)/10+"s")}catch(e){}}}}catch(e){removeLoading(),removeStatusDiv(),addMessage("error","Connection error: "+e.message)}finally{isSending=!1,document.getElementById("sendBtn").disabled=!1,document.getElementById("msgInput").focus()}}}}function removeLoading(){var e=document.getElementById("loadingMsg");e&&e.remove()}function removeStatusDiv(){currentStatusDiv&&(currentStatusDiv.style.display="none",currentStatusDiv=null)}setInterval(function(){fetch("/sessions",{headers:{"x-from-dashboard":"1"}}).then(function(e){return e.json()}).then(function(e){document.getElementById("inFlightStat").textContent="⬆ "+e.inFlight+" active",document.getElementById("sessionsStat").textContent="📋 "+e.totalActive+" sessions"}).catch(function(){})},15e3),document.getElementById("msgInput").focus();`;
}

export function getIssuesUI() {
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Issues — Dispatcher Agent</title><style>${THEME}*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--ink);min-height:100vh}.header{background:var(--surface);border-bottom:1px solid var(--line);padding:12px 24px;display:flex;align-items:center;gap:16px}.header h1{font-size:18px}.header nav{display:flex;gap:12px}.header nav a{color:var(--muted);text-decoration:none;font-size:13px;padding:4px 8px;border-radius:4px}.header nav a:hover,.header nav a.active{color:var(--accent-d);background:var(--accent-soft)}.container{max-width:1200px;margin:0 auto;padding:24px}.toolbar{display:flex;gap:12px;margin-bottom:20px;align-items:center;flex-wrap:wrap}button{padding:6px 16px;border:1px solid var(--line);border-radius:6px;cursor:pointer;font-size:13px;background:var(--surface);color:var(--ink)}button:hover{background:var(--surface-2)}button.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}.toolbar select{padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink);font-size:13px}.issue-list{display:flex;flex-direction:column;gap:2px}.issue-item{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px 16px;cursor:pointer;display:flex;gap:12px;align-items:flex-start}.issue-item:hover{background:var(--surface-2)}.issue-number{color:var(--muted);font-size:12px;min-width:60px}.issue-title{flex:1;font-size:14px;font-weight:600}.issue-title:hover{color:var(--accent-d)}.issue-meta{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:4px;font-size:12px;color:var(--muted)}.badge{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}.badge-open{background:var(--warn-soft);color:var(--amber);border:1px solid var(--lime-line)}.badge-closed{background:var(--accent-soft);color:var(--accent-d);border:1px solid var(--olive-line)}.badge-inprogress{background:var(--info-soft);color:var(--blue);border:1px solid var(--sky-line)}.badge-high{color:var(--red)}.label-tag{padding:0 6px;border-radius:4px;font-size:11px;background:var(--bg);color:var(--muted)}.images-row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.images-row img{max-width:200px;max-height:150px;border-radius:4px;border:1px solid var(--line);cursor:pointer}.images-row img:hover{border-color:var(--accent)}.modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--scrim);z-index:100;align-items:center;justify-content:center}.modal.active{display:flex}.modal-content{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:24px;max-width:500px;width:90%}.modal h3{margin-bottom:12px}input,textarea,.modal select{width:100%;padding:8px 12px;margin:6px 0;background:var(--surface);border:1px solid var(--line);border-radius:4px;color:var(--ink);font-size:13px}.modal textarea{min-height:100px;resize:vertical}.modal .actions{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}.empty{text-align:center;padding:60px;color:var(--muted)}#issueDetail{display:none}#issueDetail.active{display:block}.detail-header{padding:16px 0;border-bottom:1px solid var(--line);margin-bottom:16px}.detail-header h2{font-size:20px}.detail-body{white-space:pre-wrap;font-size:14px;line-height:1.6;padding:12px 0}.comment{padding:12px 0;border-top:1px solid var(--line)}.comment-header{font-size:12px;color:var(--muted);margin-bottom:4px}.comment-body{font-size:14px;white-space:pre-wrap}</style></head><body><div class="header"><h1>🐛 Issues</h1><nav><a href="/dashboard">Dashboard</a><a href="/issues-ui" class="active">Issues</a><a href="/vnc" target="_blank">Live VNC</a></nav></div><div class="container"><div class="toolbar"><button class="primary" onclick="showCreate()">+ New Issue</button><select id="statusFilter" onchange="loadIssues()"><option value="">All statuses</option><option value="open">Open</option><option value="in_progress">In Progress</option><option value="closed">Closed</option></select><button onclick="loadIssues()">🔄 Refresh</button><span style="font-size:12px;color:var(--muted);margin-left:auto" id="issueCount"></span></div><div id="issueList"></div><div id="issueDetail"><button onclick="closeDetail()" style="margin-bottom:12px">← Back to list</button><div class="detail-header"><h2 id="detailTitle"></h2><div id="detailMeta" style="margin-top:8px;font-size:13px;color:var(--muted)"></div></div><div id="detailImages" class="images-row"></div><div class="detail-body" id="detailBody"></div><div id="detailComments"></div><div style="margin-top:16px;border-top:1px solid var(--line);padding-top:12px"><textarea id="commentInput" placeholder="Add a comment..." rows="3"></textarea><button onclick="addComment()" class="primary" style="margin-top:8px">Comment</button></div></div></div><div class="modal" id="createModal"><div class="modal-content"><h3>New Issue</h3><input id="newTitle" placeholder="Issue title"><textarea id="newDesc" placeholder="Description (optional)"></textarea><select id="newPriority"><option value="low">Low</option><option value="medium" selected>Medium</option><option value="high">High</option></select><input id="newLabels" placeholder="Labels (comma-separated)"><input id="newImageUrls" placeholder="Image URLs (comma-separated)"><div class="actions"><button onclick="hideModal(\'createModal\')">Cancel</button><button class="primary" onclick="createIssue()">Create Issue</button></div></div></div><script>var currentIssueId=null;async function api(e,t,n){var o={method:e,headers:{"content-type":"application/json"}};return n&&(o.body=JSON.stringify(n)),(await fetch(t,o)).json()}async function loadIssues(){for(var e=document.getElementById("statusFilter").value,t=e?"?status="+e:"",n=await api("GET","/issues"+t),o="",s=0;s<n.length;s++){var a=n[s],i="badge-"+(a.status==="closed"?"closed":a.status==="in_progress"?"inprogress":"open");o+='<div class="issue-item" onclick="showIssue(\\''+a.id+'\\')"><span class="issue-number">#'+a.number+'</span><div style="flex:1"><div class="issue-title">'+esc(a.title)+'</div><div class="issue-meta"><span class="badge '+i+'">'+a.status.replace("_"," ")+'</span>',a.priority==="high"&&(o+='<span class="badge-high">🔴 '+a.priority+"</span>"),a.labels&&a.labels.forEach(function(e){o+='<span class="label-tag">'+esc(e)+"</span>"}),o+="<span>"+timeAgo(a.created_at)+"</span></div></div></div>"}document.getElementById("issueList").innerHTML=o||'<div class="empty">No issues yet. Create one with /issue in Telegram or click "New Issue".</div>',document.getElementById("issueCount").textContent=n.length+" issues"}async function showIssue(e){currentIssueId=e;var t=await api("GET","/issues/"+e),n=t.issue;document.getElementById("issueList").style.display="none",document.getElementById("issueDetail").classList.add("active"),document.getElementById("detailTitle").textContent="#"+n.number+" "+n.title,document.getElementById("detailMeta").innerHTML="<b>Status:</b> "+n.status+" &nbsp; <b>Priority:</b> "+n.priority+" &nbsp; <b>Created:</b> "+timeAgo(n.created_at),document.getElementById("detailBody").textContent=n.description||"(no description)";var o="";n.image_urls&&n.image_urls.forEach(function(e){o+='<img src="'+e+'" onclick="window.open(\\''+e+'\\')">'}),document.getElementById("detailImages").innerHTML=o;var s="";t.comments&&t.comments.forEach(function(e){s+='<div class="comment"><div class="comment-header">'+esc(e.author)+" · "+timeAgo(e.created_at)+'</div><div class="comment-body">'+esc(e.body)+"</div></div>"}),document.getElementById("detailComments").innerHTML=s}function closeDetail(){document.getElementById("issueDetail").classList.remove("active"),document.getElementById("issueList").style.display="",currentIssueId=null,loadIssues()}async function addComment(){var e=document.getElementById("commentInput").value.trim();e&&currentIssueId&&(await api("POST","/issues/"+currentIssueId+"/comments",{author:"web",body:e}),document.getElementById("commentInput").value="",showIssue(currentIssueId))}function showCreate(){document.getElementById("createModal").classList.add("active")}function hideModal(e){document.getElementById(e).classList.remove("active")}async function createIssue(){var e=document.getElementById("newTitle").value.trim();if(!e)return alert("Title required");var t=document.getElementById("newLabels").value.split(",").map(function(e){return e.trim()}).filter(Boolean),n=document.getElementById("newImageUrls").value.split(",").map(function(e){return e.trim()}).filter(Boolean);await api("POST","/issues",{title:e,description:document.getElementById("newDesc").value,priority:document.getElementById("newPriority").value,labels:t,image_urls:n,reporter:"web"}),hideModal("createModal"),document.getElementById("newTitle").value="",document.getElementById("newDesc").value="",loadIssues()}function esc(e){return String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}function timeAgo(e){var t=(Date.now()-new Date(e).getTime())/1e3;return t<60?Math.round(t)+"s ago":t<3600?Math.round(t/60)+"m ago":t<86400?Math.round(t/3600)+"h ago":Math.round(t/86400)+"d ago"}loadIssues();</script></body></html>`;
}
