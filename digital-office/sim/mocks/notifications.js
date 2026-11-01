/* Mock backend for notifications (התראות) — serves a self-contained in-memory
   notification feed for "בינה פתרונות בע״מ" so the real UI (production/notifications/static/
   index.html) runs standalone, no backend/SQLite/GlitchTip required.

   Real UI code is untouched; only window.fetch is intercepted. Shapes mirror
   production/notifications/app.py exactly:
     - GET  api/notifications?limit=&unread=1&level=&source=   -> {notifications:[...], count}
     - GET  api/notifications/stats                            -> {total, unread, by_level,
                                                                     unread_by_level, by_source,
                                                                     unread_by_source}
     - POST api/notifications/<id>/read   {read?:bool}         -> {ok, is_read}
     - DELETE api/notifications/<id>                           -> {ok} | 404 {error}
     - POST api/notifications/read-all                         -> {ok, updated}
     - POST api/notifications/clear-read                       -> {ok, deleted}
   Notification row: {id, source, source_id, title, body, level, link, meta, is_read,
                       created_at, updated_at, last_seen} — same field names as _row() in app.py.
   The UI polls GET api/notifications + GET api/notifications/stats every 15s (setInterval). */
(function(){
  var realFetch = window.fetch ? window.fetch.bind(window) : null;

  function iso(minsAgo){ return new Date(Date.now() - minsAgo*60000).toISOString(); }

  // ── in-memory store (mutations from mark-read/dismiss/read-all/clear-read persist) ──
  var seq = 0;
  function mk(o){
    seq++;
    var now = iso(0);
    return {
      id: seq,
      source: o.source,
      source_id: o.source_id || ("seed-" + seq),
      title: o.title,
      body: o.body || "",
      level: o.level || "info",
      link: o.link || "",
      meta: o.meta || {},
      is_read: !!o.read,
      created_at: iso(o.created_mins != null ? o.created_mins : o.mins),
      updated_at: now,
      last_seen: iso(o.mins)
    };
  }

  // Doc-processing alert derives from the shared business spine's failed document, so this alert names
  // the SAME supplier/number that mail shows labelled "נכשל" and INDOX shows as FAILED.
  var _fail = window.__biz && window.__biz.byStatus("failed")[0];
  var FAIL_BODY = _fail
    ? ("נכשל חילוץ שדות ממסמך של \"" + _fail.supplier + "\" (מס' " + _fail.number + ") — " + (_fail.fail_reason || "שגיאת חילוץ") + ".")
    : "נכשל חילוץ שדות מחשבונית של \"רהיטי הצפון בע\"מ\" — קובץ PDF פגום (עמוד 2 לא קריא).";

  var store = [
    mk({source:"indox", level:"error", mins:4,
        title:"שגיאה בעיבוד מסמך — חשבונית ספק",
        body:FAIL_BODY,
        meta:{project:"invoices-il", count:1, firstSeen:iso(180), lastSeen:iso(4)},
        link:"/a/indox/documents/8842", read:false}),

    mk({source:"gmail-sync", level:"error", mins:22,
        title:"סנכרון Gmail נכשל — אימות פג תוקף",
        // …with an ADDRESS in its text, as a real office's notifications carry one (a hub link, a consent link): a
        // screen that prints it as text spends the two lines a notification's text is given on it
        body:"OAuth token לכתובת person187@example.com פג תוקף. נדרש חיבור מחדש: https://accounts.google.com/o/oauth2/v2/auth?client_id=1182-bina-office&redirect_uri=https%3A%2F%2Foffice.bina-solutions.co.il%2Fa%2Fconnections%2Fcallback&scope=gmail.readonly",
        meta:{account:"person187@example.com", count:6},
        link:"/a/connections/gmail", read:false}),

    mk({source:"system", level:"error", mins:61,
        title:"דיסק כמעט מלא בשרת",
        body:"נפח האחסון בכרך /data הגיע ל-92% ניצול. מומלץ לפנות מקום או להרחיב את הכרך.",
        meta:{volume:"/data", pct:92}, read:false}),

    mk({source:"connections", level:"warning", mins:135,
        title:"חיבור WhatsApp Business מתנתק לסירוגין",
        body:"זוהו 4 ניתוקים בשעה האחרונה מול WhatsApp Business API — ייתכן צורך בחידוש הטוקן.",
        meta:{count:4, provider:"whatsapp-business"}, read:false}),

    mk({source:"indox", level:"warning", mins:300,
        title:"קובץ נכנס גדול מהרגיל",
        body:"מסמך בגודל 42MB התקבל מ-\"לוגיסטיקה ים תיכונית בע\"מ\" — עיבוד עשוי להימשך זמן רב.",
        meta:{project:"logistics", size_mb:42}, read:true}),

    mk({source:"gmail-sync", level:"warning", mins:340,
        title:"תיבת דואר מתקרבת למכסה",
        body:"תיבת person116@example.com בשימוש 88% מהמכסה. שקלו לפנות ארכיון ישן.",
        meta:{account:"person116@example.com", pct:88}, read:true}),

    mk({source:"system", level:"info", mins:900,
        title:"גיבוי לילי הושלם בהצלחה",
        body:"גיבוי מסד הנתונים של בינה פתרונות הושלם ב-03:00, גודל 1.2GB.",
        meta:{size_gb:1.2}, read:true}),

    mk({source:"connections", level:"info", mins:960,
        title:"חיבור Google Drive חודש",
        body:"החיבור ל-Google Drive של בינה פתרונות בע״מ חודש אוטומטית — אין נדרשת פעולה.",
        meta:{provider:"google-drive"}, read:true}),

    // (25 hours old: ONE day. A list of 17 hours and 48 asks nobody how one day is said - it was «לפני 1 ימ׳»)
    mk({source:"indox", level:"info", mins:1500,
        title:"עדכון תבנית חילוץ",
        body:"תבנית חילוץ הנתונים לחשבוניות ספק עודכנה לגרסה 2.3 — דיוק חילוץ שיפר ב-4%.",
        meta:{project:"invoices-il", version:"2.3"}, read:false}),

    mk({source:"system", level:"error", mins:2900,
        title:"שירות ההתראות הופעל מחדש",
        body:"השירות עלה מחדש לאחר שדרוג גרסה 1.4.2 — אין השפעה על נתונים קיימים.",
        meta:{version:"1.4.2"}, read:true})
  ];

  function bucket(level){
    var l = (level||"info").toLowerCase();
    if (l==="error"||l==="fatal"||l==="critical") return "error";
    if (l==="warning"||l==="warn") return "warning";
    return "info";
  }

  function computeStats(){
    var total = store.length, unread = 0;
    var by_level = {error:0, warning:0, info:0};
    var unread_by_level = {error:0, warning:0, info:0};
    var by_source = {}, unread_by_source = {};
    store.forEach(function(n){
      var b = bucket(n.level);
      by_level[b]++;
      var src = n.source || "system";
      by_source[src] = (by_source[src]||0) + 1;
      if (!n.is_read){
        unread++;
        unread_by_level[b]++;
        unread_by_source[src] = (unread_by_source[src]||0) + 1;
      }
    });
    return { total:total, unread:unread, by_level:by_level, unread_by_level:unread_by_level,
             by_source:by_source, unread_by_source:unread_by_source };
  }

  function ok(body, status){
    return Promise.resolve(new Response(JSON.stringify(body),
      { status: status||200, headers:{"Content-Type":"application/json"} }));
  }

  function parseBody(opts){
    try{ return opts && opts.body ? JSON.parse(opts.body) : {}; }catch(e){ return {}; }
  }

  window.fetch = function(url, opts){
    var u = String(url);
    var method = ((opts && opts.method) || "GET").toUpperCase();
    var path = u.split("?")[0];
    var qs = u.indexOf("?")!==-1 ? u.slice(u.indexOf("?")+1) : "";
    var params = {};
    qs.split("&").forEach(function(p){
      if(!p) return;
      var kv = p.split("=");
      params[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1]||"");
    });

    // GET api/notifications/stats
    if (/api\/notifications\/stats(?:$|[/?])/.test(path) && method==="GET"){
      return ok(computeStats());
    }

    // POST api/notifications/read-all
    if (/api\/notifications\/read-all(?:$|[/?])/.test(path) && method==="POST"){
      var updated = 0;
      store.forEach(function(n){ if(!n.is_read){ n.is_read = true; n.updated_at = iso(0); updated++; } });
      return ok({ ok:true, updated:updated });
    }

    // POST api/notifications/clear-read
    if (/api\/notifications\/clear-read(?:$|[/?])/.test(path) && method==="POST"){
      var before = store.length;
      store = store.filter(function(n){ return !n.is_read; });
      return ok({ ok:true, deleted: before - store.length });
    }

    // POST api/notifications/unread-count (kept for completeness even though UI doesn't poll it)
    if (/api\/notifications\/unread-count(?:$|[/?])/.test(path) && method==="GET"){
      return ok({ count: store.filter(function(n){ return !n.is_read; }).length });
    }

    // POST api/notifications/<id>/read
    var mRead = path.match(/api\/notifications\/(\d+)\/read(?:$|[/?])/);
    if (mRead && method==="POST"){
      var id = Number(mRead[1]);
      var n = store.filter(function(x){ return x.id===id; })[0];
      if (!n) return ok({ error:"not_found" }, 404);
      var b = parseBody(opts);
      var read = b.read === false ? false : true;
      n.is_read = read; n.updated_at = iso(0);
      return ok({ ok:true, is_read:n.is_read });
    }

    // GET/DELETE api/notifications/<id>
    var mId = path.match(/api\/notifications\/(\d+)(?:$|[/?])/);
    if (mId){
      var idN = Number(mId[1]);
      var idx = -1;
      store.forEach(function(x,i){ if(x.id===idN) idx = i; });
      if (method==="DELETE"){
        if (idx===-1) return ok({ error:"not_found" }, 404);
        store.splice(idx,1);
        return ok({ ok:true });
      }
      if (method==="GET"){
        if (idx===-1) return ok({ error:"not_found" }, 404);
        return ok(store[idx]);
      }
    }

    // GET api/notifications (list, with filters) / POST api/notifications (create)
    if (/api\/notifications(?:$|[/?])/.test(path) && !/\/(stats|read-all|clear-read|unread-count)/.test(path)){
      if (method==="GET"){
        var rows = store.slice();
        if (params.unread === "1") rows = rows.filter(function(n){ return !n.is_read; });
        if (params.source) rows = rows.filter(function(n){ return n.source === params.source; });
        if (params.level && ["error","warning","info"].indexOf(params.level)!==-1){
          rows = rows.filter(function(n){ return bucket(n.level) === params.level; });
        }
        rows.sort(function(a,b){
          var ta = Date.parse(a.last_seen||a.created_at)||0, tb = Date.parse(b.last_seen||b.created_at)||0;
          if (tb!==ta) return tb-ta;
          return b.id - a.id;
        });
        var limit = 100;
        try{ limit = Math.max(1, Math.min(500, parseInt(params.limit||"100",10))); }catch(e){}
        rows = rows.slice(0, limit);
        return ok({ notifications: rows, count: rows.length });
      }
      if (method==="POST"){
        var body = parseBody(opts);
        if (!body.source || !body.title) return ok({ error:"source and title required" }, 400);
        var row = mk({ source:body.source, level:body.level||"info", mins:0,
                       title:body.title, body:body.body||"", meta:body.meta||{},
                       link:body.link||"", read:false, source_id:body.source_id });
        store.push(row);
        return ok({ id:row.id, created:true }, 201);
      }
    }

    // any other /api/ call this mock doesn't know about → empty-valid, never an error
    if (path.indexOf("/api/") !== -1 || path.indexOf("api/") === 0){
      return ok({});
    }

    // non-api (the static shell itself, favicon, etc.) → let the real network handle it
    return realFetch ? realFetch(url, opts) : Promise.reject(new Error("mock: no route "+u));
  };
})();
