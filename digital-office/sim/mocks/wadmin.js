/* Mock backend for the CHAT app (formerly "בוט ווצאפ" — now "צ׳אט"): a multi-provider chat client that
   mirrors the Drive/Mail multi-account pattern. The sim's wadmin.html is a sim-authored chat UI, so this
   mock is its full backend — accounts (local / WhatsApp-Baileys / Telegram / WhatsApp-Cloud), a provider
   catalog for the connect flow, assignable bots (choose the active bot PER connection), and per-account
   conversations + threads + send. Everything is in-memory and offline. Sim-only; no real source touched.

   Endpoints (all matched loosely against the 'api'-prefixed URL the app/switcher use):
     GET  api/accounts                    -> {accounts:[{id,provider,label,identity,color,builtin,status,
                                               reason,checked,log,activeBot}], active}     (switcher + app)
     POST api/account/select {id}         -> {ok:true, active}                             (switcher)
     POST api/account/add {protocol,label}-> {id}                                          (switcher connect)
     GET  api/chat-providers              -> {providers:[{id,name,builtin,description,auth_methods:[...]}]}
     GET  api/bots                        -> {bots:[{id,name,desc}]}
     POST api/account/bot {id?,bot}       -> {ok:true, activeBot}   (set active bot for a connection)
     GET  api/conversations               -> {account, conversations:[{id,name,handle,initials,color,last,
                                               mins,unread,pinned,group,tag}]}   (for the active account)
     GET  api/conversation/<id>           -> {id, contact:{...}, messages:[{id,dir,text,mins,status}]}
     POST api/conversation/<id>/send {text}-> {message:{...}}   (+ optional bot auto-reply appended)
   Legacy bot-admin endpoints (api/bot/state, api/subscribers, …) are kept as harmless no-ops so nothing
   that still probes them errors. */
(function () {
  function J(o, status) { return Promise.resolve(new Response(JSON.stringify(o), { status: status || 200, headers: { 'Content-Type': 'application/json' } })); }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  var UID = 1; function uid(p) { return (p || 'm') + (UID++) + Math.random().toString(36).slice(2, 6); }

  // ── bots: the automations a connection can run (one active per connection) ──────────────────
  var BOTS = [
    { id: 'none',   name: 'ללא בוט — שיחה ידנית',  desc: 'ללא מענה אוטומטי; כל ההודעות מנוהלות ידנית על-ידי הצוות.' },
    { id: 'menu',   name: 'בוט תפריט בסיסי',        desc: 'מענה פתיחה עם תפריט אפשרויות ראשי (מוצרים, שעות, נציג).' },
    { id: 'orders', name: 'בוט תורים והזמנות',      desc: 'קביעת תורים, אישורי הזמנה ותזכורות אוטומטיות.' },
    { id: 'docs',   name: 'בוט מסמכים',             desc: 'שליחת חשבוניות, קבלות והוכחות תשלום לפי בקשת הלקוח.' }
  ];

  // ── providers: the connect-flow catalog (mirrors mail-providers shape for the shared switcher) ──
  var PROVIDERS = [
    { id: 'local', name: 'צ׳אט מקומי', builtin: true, description: 'שירות צ׳אט פנימי — עובד מיידית, ללא חיבור חיצוני.',
      auth_methods: [{ label: 'הפעלה מיידית', recommended: true, protocol: 'local', can: 'שיחות פנימיות בין חברי הצוות והלקוחות במערכת.' }] },
    { id: 'whatsapp', name: 'WhatsApp · Baileys', description: 'חיבור מספר וואטסאפ עסקי בסריקת קוד QR.',
      auth_methods: [{ label: 'סריקת קוד QR', recommended: true, protocol: 'wa_qr', start_url: 'about:blank#wa-qr', explain: 'ייפתח חלון עם קוד QR — סרקו אותו מ-WhatsApp ‹ מכשירים מקושרים.' }] },
    { id: 'telegram', name: 'Telegram Bot', description: 'בוט טלגרם רשמי עם Bot Token מ-BotFather.',
      auth_methods: [{ label: 'Bot Token', recommended: true, protocol: 'tg_token', needs: ['Bot Token'], can: 'שליחה וקבלת הודעות דרך בוט טלגרם.' }] },
    { id: 'whatsapp_cloud', name: 'WhatsApp Cloud API', description: 'הממשק הרשמי של Meta — תפוצה בנפח גבוה.',
      auth_methods: [{ label: 'מפתח API', recommended: false, protocol: 'wa_cloud', needs: ['API Key', 'Phone Number ID'], can: 'תפוצה רשמית מאושרת בנפחים גבוהים.' }] },
    { id: 'messenger', name: 'Facebook Messenger', description: 'עמוד עסקי בפייסבוק (חיבור עתידי).',
      auth_methods: [{ label: 'חיבור עמוד', protocol: 'fb_page', start_url: 'about:blank#fb', explain: 'התחברות לעמוד הפייסבוק העסקי.' }] }
  ];

  // ── accounts: connected chat instances (status/reason/checked/log feed the switcher health panel) ──
  var ACCOUNTS = [
    { id: 'chat-local', provider: 'local', label: 'צ׳אט מקומי', identity: 'שירות פנימי · הלשכה', color: 'var(--olive)', builtin: true,
      status: 'ok', reason: '', checked: 1, activeBot: 'menu',
      log: [{ mins: 1, level: 'info', msg: 'השירות המקומי פעיל' }, { mins: 180, level: 'info', msg: 'הופעל בוט תפריט בסיסי' }] },
    { id: 'wa-biz', provider: 'whatsapp', label: 'וואטסאפ עסקי', identity: '050-000-0007', color: '#25d366',
      status: 'ok', reason: '', checked: 2, activeBot: 'menu',
      log: [{ mins: 2, level: 'info', msg: 'המכשיר מקושר ומסונכרן' }, { mins: 1440, level: 'info', msg: 'קוד QR נסרק בהצלחה' }] },
    { id: 'tg-bot', provider: 'telegram', label: 'טלגרם — לשכה', identity: '@BinaOfficeBot', color: '#2aabee',
      status: 'warning', reason: 'טוקן הבוט יפוג בעוד 4 ימים — מומלץ לחדש מ-BotFather', checked: 12, activeBot: 'orders',
      log: [{ mins: 12, level: 'warn', msg: 'הטוקן יפוג בעוד 4 ימים' }, { mins: 3000, level: 'info', msg: 'הבוט חובר עם Bot Token' }] },
    { id: 'wa-cloud', provider: 'whatsapp_cloud', label: 'WhatsApp Cloud API', identity: 'Phone ID 104229…', color: '#128c7e',
      status: 'error', reason: 'טוקן ה-API נדחה (401) — נדרש חידוש מפתח ב-Meta', checked: 37, activeBot: 'none',
      log: [{ mins: 37, level: 'error', msg: 'קריאת /messages החזירה 401 Unauthorized' }, { mins: 60, level: 'warn', msg: 'קצב שגיאות עולה' }, { mins: 5000, level: 'info', msg: 'החיבור הוגדר' }] }
  ];
  var ACTIVE = 'wa-biz';

  function acct(id) { for (var i = 0; i < ACCOUNTS.length; i++) if (ACCOUNTS[i].id === id) return ACCOUNTS[i]; return null; }

  // ── conversations + threads, per account ────────────────────────────────────────────────────
  // message: {id, dir:'in'|'out', text, mins (ago), status:'sent'|'delivered'|'read'}
  function m(dir, text, mins, status) { return { id: uid(), dir: dir, text: text, mins: mins, status: status || (dir === 'out' ? 'read' : 'in') }; }
  // group incoming message — carries a sender name + colour so the thread can render a real group chat
  function gm(sender, color, text, mins) { return { id: uid(), dir: 'in', sender: sender, scolor: color, text: text, mins: mins, status: 'in' }; }
  var THREADS = {
    'wa-biz': [
      { id: 'c_carton', name: 'ישראל קרטון בע״מ', handle: '+972 3-555-2040', initials: 'יק', color: 'var(--sky-d)', tag: 'ספק', unread: 2, pinned: true, online: true, mins: 6,
        msgs: [ m('in', 'שלום, שלחנו את חשבונית 20458 במייל. אפשר לאשר קבלה?', 55),
                m('out', 'התקבלה, תודה. נעביר לתשלום שוטף+30.', 40),
                m('in', 'מעולה. מצרף גם תעודת משלוח לחודש הבא.', 8),
                m('in', 'מתי צפוי התשלום להיכנס?', 6) ] },
      { id: 'c_moshe', name: 'משה כהן', handle: '050-000-0006', initials: 'מכ', color: 'var(--violet)', tag: 'לקוח', unread: 0, pinned: false, mins: 26,
        msgs: [ m('in', 'היי, אפשר לקבל הצעת מחיר לשירות החודשי?', 60),
                m('out', 'בטח! שולח לך עכשיו הצעה מסודרת.', 52),
                m('out', 'הצעת מחיר OT-2026-00001 — מצורפת. תקפה ל-14 יום.', 51, 'delivered'),
                m('in', 'קיבלתי, תודה רבה 🙏', 26) ] },
      { id: 'c_bakery', name: 'מאפיית הבוקר', handle: '050-000-0018', initials: 'מה', color: 'var(--lime-d)', tag: 'לקוח', unread: 1, pinned: false, online: true, mins: 95,
        msgs: [ m('in', 'הזמנה שבועית קבועה — אפשר לחדש?', 130),
                m('out', 'חידשנו! קבלה IR-2026-00001 נשלחה.', 120),
                m('in', 'תודה, נתראה בשבוע הבא', 95) ] },
      { id: 'c_group', name: 'צוות הלשכה', handle: 'קבוצה · 6 משתתפים', initials: 'צל', color: 'var(--olive-d)', tag: 'קבוצה', unread: 0, pinned: false, group: true, mins: 220,
        msgs: [ gm('רחל לוי', 'var(--plum-d)', 'מישהו זמין לסגור את דוח המע״מ להיום?', 240),
                m('out', 'אני על זה, מגיש היום.', 232),
                gm('דוד מזרחי', 'var(--sky-d)', 'מעולה 🙌 תודה רחל', 224),
                gm('רחל לוי', 'var(--plum-d)', 'מצרפת את הקבצים הרלוונטיים', 220) ] }
    ],
    'chat-local': [
      { id: 'l_rachel', name: 'רחל לוי · עיצוב פנים', handle: 'לקוחה פנימית', initials: 'רל', color: 'var(--plum-d)', tag: 'לקוח', unread: 0, pinned: false, mins: 12,
        msgs: [ m('in', 'שלום, אפשר לתאם פגישה לשבוע הבא?', 30),
                m('out', 'כמובן, יום שלישי 10:00 מתאים?', 20),
                m('in', 'מושלם, נקבע.', 12) ] },
      { id: 'l_avi', name: 'מוסך אבי ובנו', handle: 'ספק פנימי', initials: 'מא', color: 'var(--muted)', tag: 'ספק', unread: 3, pinned: true, mins: 4,
        msgs: [ m('in', 'החשבונית האחרונה עדיין לא שולמה', 20),
                m('out', 'בודק מול הנהלת חשבונות ומעדכן.', 15),
                m('in', 'תודה', 8), m('in', 'עדכון?', 4) ] }
    ],
    'tg-bot': [
      { id: 't_orders', name: 'הזמנות · בוט תורים', handle: '@BinaOfficeBot', initials: '🤖', color: '#2aabee', tag: 'בוט', unread: 0, pinned: false, mins: 40,
        msgs: [ m('in', '/start', 60), m('out', 'ברוכים הבאים! בחרו: 1) תור חדש 2) בירור 3) נציג', 59),
                m('in', '1', 45), m('out', 'מעולה — לאיזה יום לקבוע?', 44), m('in', 'יום חמישי', 40) ] }
    ],
    'wa-cloud': []
  };

  function convList(id) {
    var list = (THREADS[id] || []).map(function (c) {
      var last = c.msgs[c.msgs.length - 1];
      return { id: c.id, name: c.name, handle: c.handle, initials: c.initials, color: c.color, tag: c.tag || '',
        group: !!c.group, unread: c.unread || 0, pinned: !!c.pinned, online: !!c.online, typing: false,
        lastDir: last ? last.dir : '', lastStatus: last ? last.status : '',
        last: last ? last.text : '', mins: c.mins || (last ? last.mins : 0) };
    });
    // pinned first, then by recency
    list.sort(function (a, b) { return (b.pinned - a.pinned) || (a.mins - b.mins); });
    return list;
  }
  function conv(accId, cid) { var arr = THREADS[accId] || []; for (var i = 0; i < arr.length; i++) if (arr[i].id === cid) return arr[i]; return null; }

  // Intent-based bot: replies only when it makes sense (a question, a menu choice, or a keyword) — NOT to
  // every message, and NEVER in group chats. Keeps the demo realistic instead of spamming identical lines.
  function botReply(botId, text, isGroup) {
    if (!botId || botId === 'none' || isGroup) return null;
    var t = (text || '').trim(), low = t.toLowerCase();
    var isQuestion = /\?$/.test(t);
    var human = /(נציג|אנושי|בן ?אדם|לדבר עם)/.test(t);
    if (human) return 'מעביר אתכם לנציג/ה מהצוות — נחזור אליכם בהקדם. אפשר גם להשאיר הודעה כאן.';
    if (botId === 'menu') {
      if (/^1\b/.test(t) || /פרטים|מוצר/.test(t)) return 'בשמחה! הצוות שלנו יחזור אליכם עם פרטים מלאים. אפשר גם לשאול אותי כאן.';
      if (/^2\b/.test(t) || /שע(ה|ות)|פתוח|פעילות/.test(t)) return 'שעות הפעילות: א׳–ה׳ 09:00–18:00. מחוץ לשעות אלו נשמח לחזור אליכם.';
      if (/^3\b/.test(t)) return 'מעביר אתכם לנציג/ה — תודה על הסבלנות 🙏';
      if (isQuestion || t.length > 24) return 'קיבלנו את הודעתך! להמשך בחרו: 1) פרטים  2) שעות פעילות  3) שיחה עם נציג.';
      return null;   // don't reply to short chatter — no spam
    }
    if (botId === 'orders') {
      if (/(תור|לקבוע|פגישה|זמן)/.test(t)) return 'לקביעת תור הקלידו יום מבוקש (א׳–ה׳) ושעה, ואאשר לכם מיד.';
      if (/(יום|ראשון|שני|שלישי|רביעי|חמישי|\d{1,2}:\d{2})/.test(t)) return 'מצוין — רשמתי את הבקשה. אישור סופי יישלח בהודעה נפרדת ✓';
      if (isQuestion) return 'אפשר לקבוע תור, לבדוק זמינות או לדבר עם נציג. מה תרצו?';
      return null;
    }
    if (botId === 'docs') {
      if (/חשבונ/.test(t)) return 'החשבונית האחרונה נשלחה אליכם כעת 📄';
      if (/קבל/.test(t)) return 'הקבלה בדרך אליכם 📄';
      if (/(תשלום|הוכחת)/.test(t)) return 'הוכחת התשלום נשלחה 📄';
      if (isQuestion) return 'ניתן לבקש: "חשבונית", "קבלה" או "הוכחת תשלום" ואשלח מיד.';
      return null;
    }
    return null;
  }

  // ── router ──────────────────────────────────────────────────────────────────────────────────
  var realFetch = window.fetch ? window.fetch.bind(window) : null;
  function body(opts) { try { return opts && opts.body ? JSON.parse(opts.body) : {}; } catch (e) { return {}; } }

  window.fetch = function (url, opts) {
    var u = String(url), method = ((opts && opts.method) || 'GET').toUpperCase();

    if (/api\/accounts(\?|$)/.test(u) && method === 'GET') return J({ accounts: clone(ACCOUNTS), active: ACTIVE });

    if (/api\/account\/select(\?|$)/.test(u) && method === 'POST') { var s = body(opts); if (acct(s.id)) ACTIVE = s.id; return J({ ok: true, active: ACTIVE }); }

    if (/api\/account\/add(\?|$)/.test(u) && method === 'POST') {
      var a = body(opts);
      var prov = { local: 'local', wa_qr: 'whatsapp', tg_token: 'telegram', wa_cloud: 'whatsapp_cloud', fb_page: 'messenger' }[a.protocol] || 'local';
      var colors = { local: 'var(--olive)', whatsapp: '#25d366', telegram: '#2aabee', whatsapp_cloud: '#128c7e', messenger: '#0084ff' };
      var id = uid('acc');
      var rec = { id: id, provider: prov, label: a.label || 'חשבון חדש', identity: 'חובר זה עתה', color: colors[prov] || 'var(--olive)',
        builtin: prov === 'local', status: 'ok', reason: '', checked: 0, activeBot: 'menu',
        log: [{ mins: 0, level: 'info', msg: 'החשבון חובר בהצלחה' }] };
      ACCOUNTS.push(rec); THREADS[id] = []; return J({ id: id, ok: true });
    }

    if (/api\/account\/reconnect(\?|$)/.test(u) && method === 'POST') {
      var rid = body(opts).id || ACTIVE, rt = acct(rid);
      if (rt) { rt.status = 'ok'; rt.reason = ''; rt.checked = 0; (rt.log = rt.log || []).unshift({ mins: 0, level: 'info', msg: 'החיבור חודש בהצלחה' }); }
      return J({ ok: true, status: rt ? rt.status : null });
    }

    if (/api\/chat-providers(\?|$)/.test(u) && method === 'GET') return J({ providers: clone(PROVIDERS) });

    if (/api\/bots(\?|$)/.test(u) && method === 'GET') return J({ bots: clone(BOTS) });

    if (/api\/account\/bot(\?|$)/.test(u) && method === 'POST') {
      var bb = body(opts); var t = acct(bb.id || ACTIVE);
      if (t) { t.activeBot = bb.bot; (t.log = t.log || []).unshift({ mins: 0, level: 'info', msg: 'הבוט הפעיל שונה ל: ' + ((BOTS.filter(function (x) { return x.id === bb.bot; })[0] || {}).name || bb.bot) }); }
      return J({ ok: true, activeBot: t ? t.activeBot : null });
    }

    if (/api\/conversations(\?|$)/.test(u) && method === 'GET') return J({ account: ACTIVE, conversations: convList(ACTIVE) });

    var mConv = u.match(/api\/conversation\/([^/?]+)\/send(\?|$)/);
    if (mConv && method === 'POST') {
      var c = conv(ACTIVE, decodeURIComponent(mConv[1])); if (!c) return J({ error: 'no conversation' }, 404);
      var txt = (body(opts).text || '').trim(); if (!txt) return J({ error: 'empty' }, 400);
      var out = m('out', txt, 0, 'sent'); c.msgs.push(out); c.unread = 0;
      var reply = null, ab = acct(ACTIVE);
      if (ab && ab.activeBot && ab.activeBot !== 'none') { var rt = botReply(ab.activeBot, txt); if (rt) reply = m('in', rt, 0); }
      if (reply) c.msgs.push(reply);
      return J({ message: out, reply: reply });
    }

    var mGet = u.match(/api\/conversation\/([^/?]+)(\?|$)/);
    if (mGet && method === 'GET') {
      var cc = conv(ACTIVE, decodeURIComponent(mGet[1])); if (!cc) return J({ error: 'no conversation' }, 404);
      return J({ id: cc.id, contact: { name: cc.name, handle: cc.handle, initials: cc.initials, color: cc.color, tag: cc.tag, group: !!cc.group }, messages: clone(cc.msgs) });
    }

    // ── legacy bot-admin no-ops (kept so any lingering probe doesn't error) ──
    if (/api\/bot\/state(\?|$)/.test(u)) return J({ is_connected: true, botNumber: '050-000-0007', users_len: 0, qr_text: null });
    if (/api\/subscribers(\?|$)/.test(u)) return J([]);

    return realFetch ? realFetch(url, opts) : Promise.reject(new Error('mock: no route ' + u));
  };
})();
