/* ═══════════════════════════════════════════════════════════════════════════════════════════════
   «אבטחה» — the screen. One hash route per view, each a URL that survives a reload:
     #/            סקירה      the numbers, the map, what was opened and from where, what is working
     #/in          נכנס       every address that reached the office; #/in/<ip> one address
     #/out         יוצא       every destination the office called;    #/out/<ip> one destination
     #/signins     כניסות     sign-ins at the office and SSH keys on the machine
     #/links       קישורים    what other offices opened here, and what we opened there
     #/bans        חסימות     the built-in fail2ban: mode, jails, bans, the owner's lists
     #/net         רשת ונתב   interfaces, listening ports, the router, the sensor
     #/herd        העדר       every linked office's security, side by side
   Everything is relative (the console embeds the app at /a/<alias>/): no URL here starts with "/".
   ═══════════════════════════════════════════════════════════════════════════════════════════════ */
/* @bina-said:start */
var binaSaid = (status) => (!status ? "אין תשובה מהשירות"
  : status < 300 ? "התשובה אינה מה שהמסך ציפה לו — רענן את הדף"
  : status === 401 ? "הכניסה פגה — רענן את הדף" : status === 403 ? "אין הרשאה לפעולה הזאת"
  : status === 404 ? "השירות לא מכיר את הבקשה הזאת"
  : status > 501 && status < 505 ? "השירות אינו זמין כרגע" : status >= 500 ? "השירות נתקל בשגיאה"
  : "הבקשה נדחתה");
// a request that could not even be sent answers like one that was refused, with status 0
var binaNoAnswer = () => ({ ok: false, status: 0, json: async () => ({}), text: async () => "" });
/* @bina-said:end */
/* @bina-ask:start */
var binaAsk, binaTell;
(function () {
  var doc = document;
  var CSS = ".bask{position:fixed;inset:0;z-index:2147483000;display:grid;grid-template:minmax(0,1fr)/minmax(0,1fr);place-items:center;padding:16px;background:var(--scrim)}"
    + ".bask-card{display:flex;flex-direction:column;width:min(440px,100%);max-height:100%;overflow:auto;box-sizing:border-box;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:var(--shadow-lg);font:14px/1.5 var(--font,system-ui,sans-serif);text-align:start;outline:0}"
    + ".bask-card h2{margin:0 0 8px;font-size:16px;font-weight:800;line-height:1.35}"
    + ".bask-read{overflow:auto}.bask-read:not(:empty){min-height:19px}"   // never squeezed to nothing: a line of it stays, and past that the card itself scrolls
    + ".bask-card p{margin:0 0 6px;font-size:13px;color:var(--muted)}"
    + ".bask-read p:last-child{margin:0}"
    + ".bask-facts{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:10px 0 0;padding:10px 12px;background:var(--surface-2);border:1px solid var(--line);border-radius:9px}"
    + ".bask-facts dt{color:var(--muted);font-size:11px;font-weight:600;line-height:1.7}"
    + ".bask-facts dd{margin:0;font-size:12.5px;font-weight:600;overflow-wrap:anywhere;unicode-bidi:plaintext;text-align:right}"
    + ".bask-field{display:grid;gap:5px;margin-top:10px;font-size:12px;font-weight:600;color:var(--muted)}"
    + ".bask-field input{font:inherit;font-size:13px;font-weight:400;height:36px;padding:0 10px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink)}"
    + ".bask-said{margin-top:10px;padding:8px 12px;border-radius:9px;border-inline-start:4px solid var(--red);background:color-mix(in srgb,var(--red) 14%,var(--surface));font-size:12.5px;overflow-wrap:anywhere}"
    + ".bask-said:empty{display:none}"
    + ".bask-acts{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}"
    + ".bask-btn{height:34px;padding:0 16px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--ink);font:inherit;font-size:13px;font-weight:700;cursor:pointer}"
    + ".bask-btn.primary{background:var(--accent);border-color:transparent;color:var(--accent-ink)}"
    + ".bask-btn.danger{background:var(--red);border-color:transparent;color:var(--surface)}"
    + ".bask-btn:disabled{opacity:.5;cursor:default}"
    + ".bask-field input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}"
    + "@media (pointer:coarse){.bask-btn{height:44px}.bask-field input{height:44px}}"
    + "@media (max-height:399px){.bask{padding:8px}.bask-card{padding:12px}.bask-acts{margin-top:10px}}"   // the side menu's own short frame
    + "#bina-tell{position:fixed;inset-block-end:16px;inset-inline-start:16px;z-index:2147483001;display:grid;gap:8px;max-width:min(420px,calc(100vw - 32px))}"
    + ".btell{--c:var(--ok);padding:10px 14px;border-radius:12px;background:color-mix(in srgb,var(--c) 14%,var(--surface));color:var(--ink);border:1px solid color-mix(in srgb,var(--c) 38%,var(--surface));border-inline-start:4px solid var(--c);font:13px/1.45 var(--font,system-ui,sans-serif);box-shadow:var(--shadow-lg);cursor:pointer;text-align:start}"
    + ".btell.warn{--c:var(--lime)}.btell.bad{--c:var(--red)}"   // --ok and --red, not the bare hues: they are the steps that are lifted on the dark ground
    + ".btell small{display:block;margin-top:2px;font-size:11.5px;color:var(--muted);overflow-wrap:anywhere;unicode-bidi:plaintext}"
    + ".btell button{margin-inline-start:12px;padding:0;border:0;background:none;font:inherit;font-weight:800;color:var(--blue);text-decoration:underline;cursor:pointer}";

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function style() {
    if (doc.getElementById("bina-ask-css")) return;
    var s = el("style", "", CSS);
    s.id = "bina-ask-css";
    doc.head.appendChild(s);
  }

  binaAsk = function (q) {
    style();
    return new Promise(function (resolve) {
      var back = doc.activeElement, field = null, must = q.input && q.input.must;
      var scrim = el("div", "bask"), card = el("div", "bask-card"), read = el("div", "bask-read"), said = el("div", "bask-said");
      card.setAttribute("role", "alertdialog");
      card.setAttribute("aria-modal", "true");
      card.setAttribute("dir", "rtl");
      card.setAttribute("tabindex", "-1");
      said.setAttribute("role", "alert");
      card.appendChild(el("h2", "", q.title));
      card.appendChild(read);
      String(q.body || "").split(/\n+/).forEach(function (line) { if (line.trim()) read.appendChild(el("p", "", line)); });
      if (q.facts && q.facts.length) {
        var dl = el("dl", "bask-facts");
        q.facts.forEach(function (f) { dl.appendChild(el("dt", "", f[0])); dl.appendChild(el("dd", "", f[1])); });
        read.appendChild(dl);
      }
      if (q.input) {
        var lab = el("label", "bask-field", q.input.label || "");
        field = el("input");
        field.value = q.input.value || "";
        if (q.input.dir) field.setAttribute("dir", q.input.dir);
        lab.appendChild(field);
        card.appendChild(lab);
      }
      var acts = el("div", "bask-acts"), no = el("button", "bask-btn", q.cancel || "ביטול"),
          yes = el("button", "bask-btn " + (q.danger ? "danger" : "primary"), q.ok || "אישור");
      no.setAttribute("type", "button");
      yes.setAttribute("type", "button");
      acts.appendChild(no);
      acts.appendChild(yes);
      card.appendChild(said);
      card.appendChild(acts);
      scrim.appendChild(card);
      doc.body.appendChild(scrim);

      function fit() { if (must) yes.disabled = field.value.trim() !== must; }
      function home() { (field || (q.danger ? no : yes)).focus(); }
      function done(v) {
        doc.removeEventListener("keydown", key, true);
        scrim.remove();
        if (back && back.focus) back.focus();
        resolve(v);
      }
      function cancel() { if (!no.disabled) done(field ? null : false); }
      function agree() {
        if (yes.disabled) return;
        var v = field ? field.value : true;
        if (!q.run) return done(v);
        yes.disabled = no.disabled = true;                // in flight: busy, and there is nothing left to cancel
        yes.textContent = "מבצע…";
        said.textContent = "";
        card.focus();
        Promise.resolve(v).then(q.run).then(function () { done(v); }, function (e) {
          yes.textContent = q.ok || "אישור";
          yes.disabled = no.disabled = false;
          fit();
          said.textContent = (e && e.message) || "הפעולה נכשלה";
          home();
        });
      }
      function key(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
        else if (e.key === "Enter" && field && doc.activeElement === field) { e.preventDefault(); agree(); }
        else if (e.key === "Tab") {                       // the page behind is not reachable while asked
          var ring = [field, no, yes].filter(function (n) { return n && !n.disabled; });
          var i = ring.indexOf(doc.activeElement);
          e.preventDefault();
          if (ring.length) ring[(i + (e.shiftKey ? ring.length - 1 : 1)) % ring.length].focus();
        }
        else if (/^(Arrow|Page)(Up|Down)$/.test(e.key) && doc.activeElement !== field && read.scrollHeight > read.clientHeight) {
          e.preventDefault();                               // the focus lives on the buttons, outside what scrolls
          read.scrollTop += (/Up$/.test(e.key) ? -1 : 1) * (/^Page/.test(e.key) ? read.clientHeight : 40);
        }
      }
      yes.addEventListener("click", agree);
      no.addEventListener("click", cancel);
      scrim.addEventListener("mousedown", function (e) { if (e.target === scrim) cancel(); });
      if (field) field.addEventListener("input", fit);
      doc.addEventListener("keydown", key, true);
      fit();
      home();
    });
  };

  // The third word is how long the notice stays (ms) — or what more it carries: { ms, more, act, stay }.
  //   more  the service's own sentence, on a line of its own under the notice's words
  //   act   [label, fn] — one way on from the notice (an undo, a refresh): pressing it runs fn and takes the notice down
  //   stay  no clock: the notice is there until it is pressed
  binaTell = function (text, kind, opt) {
    style();
    var o = opt && typeof opt === "object" ? opt : { ms: opt };
    var box = doc.getElementById("bina-tell");
    if (!box) { box = el("div"); box.id = "bina-tell"; doc.body.appendChild(box); }
    var n = el("div", "btell " + (kind || "ok"), text);
    n.setAttribute("role", kind === "bad" ? "alert" : "status");
    n.setAttribute("dir", "rtl");
    if (o.more) n.appendChild(el("small", "", o.more));
    if (o.act) {
      var go = el("button", "", o.act[0]);
      go.setAttribute("type", "button");
      go.addEventListener("click", function (e) { e.stopPropagation(); n.remove(); o.act[1](); });
      n.appendChild(go);
    }
    n.addEventListener("click", function () { n.remove(); });
    box.appendChild(n);
    if (!o.stay) setTimeout(function () { n.remove(); }, o.ms || (kind === "bad" ? 9000 : 5200));
    return n;
  };
})();
/* @bina-ask:end */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var S = { hours: 24, view: "", arg: "", data: {}, world: null, sort: {}, q: "", kind: "", mapMode: "both", shown: {} };
  try { var h0 = Number(localStorage.getItem("sec:hours")); if ([1, 24, 168, 720].indexOf(h0) >= 0) S.hours = h0; } catch (e) { /* private window */ }

  // ── words ──────────────────────────────────────────────────────────────────────────────────────
  var KIND = { "public": "ציבורי", "private": "פרטי", "remote": "לשכה מקושרת", "auth": "כניסה", "door": "דלת הקישור",
               "none": "ללא נתב", "link": "דרך הקישור" };
  var KIND_HINT = { "public": "אתר או אפליקציה בלי הכניסה של הלשכה", "private": "אפליקציה מאחורי הכניסה של הלשכה",
                    "remote": "אפליקציה של לשכה אחרת שנפתחה כאן דרך הקישור", "auth": "דף הכניסה עצמו",
                    "door": "לשכה אחרת שמחברת את הקישור דרך 443", "none": "בקשה שאף נתב לא קיבל — סריקה של הכתובת או שם שאיש לא הגדיר",
                    "link": "לשכה אחרת פתחה אפליקציה שלנו" };
  var STATE = { banned: ["חסום", "bad"], would: ["היה נחסם", "warn"], trusted: ["מחובר", "ok"], allowed: ["מותר", "ok"],
                herd: ["העדר", "ok"], own: ["הלשכה", "ok"], seen: ["נראה", "muted"], blocked: ["חסום", "bad"] };
  var JAIL = { scan: "סריקה", auth: "כניסות שנכשלו", sshd: "SSH", manual: "ידני" };
  var VERDICT = { ok: ["הצליחה", "ok"], fail: ["נכשלה", "bad"], out: ["יציאה", "muted"], probe: ["ניסיון", "warn"] };
  var SRC = { sso: "כניסה ללשכה", ssh: "SSH" };
  var ACTION = { ban: "נחסם", unban: "שוחרר", expire: "פג תוקף" };
  var regionHe = null;
  try { regionHe = new Intl.DisplayNames(["he"], { type: "region" }); } catch (e) { regionHe = null; }
  function country(cc) { if (!cc) return ""; try { return (regionHe && regionHe.of(cc)) || cc; } catch (e) { return cc; } }
  function esc(v) { return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function n(v) { return (Number(v) || 0).toLocaleString("he-IL"); }
  function bytes(b) { b = Number(b) || 0; var u = ["B", "KB", "MB", "GB", "TB"], i = 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return (i ? b.toFixed(b < 10 ? 1 : 0) : b) + " " + u[i]; }
  function ago(ts) {
    if (!ts) return "—";
    var s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return "עכשיו";
    if (s < 3600) return "לפני " + Math.round(s / 60) + " דק׳";
    if (s < 86400) return "לפני " + Math.round(s / 3600) + " שע׳";
    return "לפני " + Math.round(s / 86400) + " ימים";
  }
  function when(ts) { if (!ts) return "—"; try { return new Date(ts * 1000).toLocaleString("he-IL", { dateStyle: "short", timeStyle: "medium" }); } catch (e) { return String(ts); } }
  function left(ts) {
    if (!ts) return "לצמיתות";
    var s = ts - Date.now() / 1000;
    if (s <= 0) return "פג";
    if (s < 3600) return "עוד " + Math.ceil(s / 60) + " דק׳";
    if (s < 86400) return "עוד " + Math.round(s / 3600) + " שע׳";
    return "עוד " + Math.round(s / 86400) + " ימים";
  }
  function pill(label, kind, title) { return '<span class="pill ' + (kind || "muted") + '"' + (title ? ' title="' + esc(title) + '"' : "") + ">" + esc(label) + "</span>"; }
  function statePill(st) { var s = STATE[st] || [st, "muted"]; return pill(s[0], s[1]); }
  function kindPill(k) { return pill(KIND[k] || k, k === "none" || k === "public" ? "warn" : (k === "private" || k === "remote" ? "info" : "muted"), KIND_HINT[k] || k); }
  function ip(v) { return '<span class="addr">' + esc(v) + "</span>"; }
  // a country and city — or, for an address that is not on the internet, what it IS (this machine, an app
  // of the office, a linked office, the internal network): never «unknown» about the office's own
  function placeText(r) { return [country(r.cc), r.city].filter(Boolean).join(" · ") || r.local || ""; }
  function place(r) { var t = placeText(r); return t ? esc(t) : '<span class="muted">לא ידוע</span>'; }
  function ICON(name) { return (typeof BinaNav !== "undefined" && BinaNav.svg) ? BinaNav.svg(name) : ""; }

  // ── requests ───────────────────────────────────────────────────────────────────────────────────
  async function api(path, opt) {
    var r = await fetch(path, Object.assign({ headers: { "Accept": "application/json" }, credentials: "same-origin" }, opt || {})).catch(binaNoAnswer);
    var d = await r.json().catch(function () { return {}; });
    return { ok: r.ok, status: r.status, d: d };
  }
  async function send(method, path, body) {
    var r = await api(path, { method: method, headers: { "Content-Type": "application/json", "Accept": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) throw new Error((r.d && (r.d.message || r.d.error)) || binaSaid(r.status));
    return r.d;
  }
  function failed(where, r) {
    return '<div class="callout bad"><div class="txt"><b>' + esc(where) + "</b> — " + esc((r.d && (r.d.message || r.d.error)) || binaSaid(r.status)) + "</div></div>";
  }

  // ── the live chip ──────────────────────────────────────────────────────────────────────────────
  var lastLoad = 0;
  function markLive() { lastLoad = Date.now(); paintLive(); }
  function paintLive() {
    var el = $("live"), t = $("liveText");
    if (!el || !t) return;
    var age = (Date.now() - lastLoad) / 1000;
    el.setAttribute("data-stale", !lastLoad || age > 90 ? "1" : "0");
    t.textContent = !lastLoad ? "טוען…" : age < 15 ? "חי" : "עודכן " + ago(lastLoad / 1000);
  }
  setInterval(paintLive, 5000);

  // ── the navigator ──────────────────────────────────────────────────────────────────────────────
  var VIEWS = [
    { id: "", label: "סקירה", icon: "home", title: "אבטחה", sub: "כל מי שניגש ללשכה וכל מה שהלשכה קוראת החוצה — על מפה, עם חסימה מובנית." },
    { id: "in", label: "נכנס", icon: "users", title: "מי ניגש ללשכה", sub: "כל כתובת שפנתה לאתר ציבורי, לאפליקציה פרטית או לדלת הקישור — מאיפה, דרך מי, ומה קרה." },
    { id: "out", label: "יוצא", icon: "send", title: "לאן הלשכה פונה", sub: "כל חיבור שהמכונה והאפליקציות שלה פתחו החוצה — יעד, שם, מי פנה ומתי." },
    { id: "signins", label: "כניסות", icon: "key", title: "כניסות", sub: "כניסות ללשכה וכניסות SSH למכונה — מי, מאיפה, ובאיזה מפתח." },
    { id: "links", label: "קישורים", icon: "share", title: "תנועה בין הלשכות", sub: "מה לשכות אחרות פתחו כאן דרך הקישור, ומה נפתח מכאן אצלן." },
    { id: "bans", label: "חסימות", icon: "lock", title: "חסימות", sub: "fail2ban מובנה: הכללים, החסימות שבתוקף, רשימת המותרים וחסימות היציאה." },
    { id: "net", label: "רשת ונתב", icon: "globe", title: "רשת ונתב", sub: "הממשקים, הפורטים הפתוחים, הנתב שמאחורי השער, והחיישן." },
    { id: "herd", label: "העדר", icon: "grid", title: "העדר", sub: "האבטחה של כל לשכה מקושרת, אחת ליד השנייה." }
  ];
  var NAV = null;
  function renderNav() {
    var el = $("sideNav");
    if (!el || typeof BinaNav === "undefined") return;
    var s = S.data.summary || {};
    var k = s.kpi || {};
    var items = VIEWS.map(function (v) {
      var it = { id: v.id || "home", label: v.label, icon: v.icon, href: "#/" + v.id };
      if (v.id === "bans" && (k.bans || k.would_ban)) it.badge = String((k.bans || 0) + (k.would_ban || 0));
      return it;
    });
    el.innerHTML = "";
    el.classList.remove("bnv");
    NAV = BinaNav.mount(el, {
      id: "security",
      brand: { name: "אבטחה", sub: s.office ? "לשכה " + s.office : "", avatar: "א", href: "#/" },
      sections: [{ items: items }],
      footer: { text: s.mode === "enforce" ? "אכיפה פעילה" : "מצב צפייה" }
    });
    var t = $("navToggle");
    if (t && !t.innerHTML.trim()) t.innerHTML = BinaNav.svg("menu");
    if (NAV && NAV.setActive) NAV.setActive(S.view || "home");
  }

  // ── the window chips ───────────────────────────────────────────────────────────────────────────
  function paintWin() {
    var bs = $("win").querySelectorAll("button");
    for (var i = 0; i < bs.length; i++) bs[i].setAttribute("aria-pressed", Number(bs[i].getAttribute("data-h")) === S.hours ? "true" : "false");
  }
  $("win").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-h]");
    if (!b) return;
    S.hours = Number(b.getAttribute("data-h"));
    try { localStorage.setItem("sec:hours", String(S.hours)); } catch (er) { /* fine */ }
    paintWin();
    route(true);
  });

  // ── a sortable table that becomes blocks on a narrow screen ────────────────────────────────────
  function table(id, cols, rows, opts) {
    opts = opts || {};
    var st = S.sort[id] || { key: opts.sort || cols[0].key, dir: opts.dir || -1 };
    var col = cols.filter(function (c) { return c.key === st.key; })[0] || cols[0];
    var val = col.sortVal || function (r) { return r[col.key]; };
    var sorted = rows.slice().sort(function (a, b) {
      var x = val(a), y = val(b);
      if (x == null) x = ""; if (y == null) y = "";
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "he")) * st.dir;
    });
    var limit = S.shown[id] || 300;
    var head = cols.map(function (c) {
      var s = c.key === st.key ? (st.dir > 0 ? ' aria-sort="ascending"' : ' aria-sort="descending"') : "";
      return '<th data-sort="' + esc(c.key) + '"' + s + (c.title ? ' title="' + esc(c.title) + '"' : "") + ">" + esc(c.label) + "</th>";
    }).join("");
    var body = sorted.slice(0, limit).map(function (r, i) {
      return '<tr data-row="' + i + '"' + (opts.href ? ' data-href="' + esc(opts.href(r)) + '"' : "") + ">" + cols.map(function (c) {
        return '<td data-th="' + esc(c.label) + '"><div class="cell">' + c.html(r) + "</div></td>";
      }).join("") + "</tr>";
    }).join("");
    var more = sorted.length > limit ? '<div class="more"><button class="btn ghost" type="button" data-more="' + esc(id) + '">עוד ' + n(sorted.length - limit) + " שורות</button></div>" : "";
    return '<div class="tblwrap" data-table="' + esc(id) + '"><table class="table"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div>" + more;
  }
  document.addEventListener("click", function (e) {
    var th = e.target.closest("th[data-sort]");
    if (th) {
      var id = th.closest("[data-table]").getAttribute("data-table"), key = th.getAttribute("data-sort");
      var cur = S.sort[id] || {};
      S.sort[id] = { key: key, dir: cur.key === key ? -cur.dir : -1 };
      paint();
      return;
    }
    var more = e.target.closest("[data-more]");
    if (more) { var mid = more.getAttribute("data-more"); S.shown[mid] = (S.shown[mid] || 300) + 500; paint(); return; }
    var tr = e.target.closest("tr[data-href]");
    if (tr && !e.target.closest("a,button")) { location.hash = tr.getAttribute("data-href"); }
  });

  // ── the map ────────────────────────────────────────────────────────────────────────────────────
  var A1 = 1.340264, A2 = -0.081106, A3 = 0.000893, A4 = 0.003796, M = Math.sqrt(3) / 2;
  function ee(lon, lat) {
    var l = lon * Math.PI / 180, p = lat * Math.PI / 180, t = Math.asin(M * Math.sin(p)), t2 = t * t, t6 = t2 * t2 * t2;
    return [l * Math.cos(t) / (M * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2))), t * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))];
  }
  var XMAX = ee(180, 0)[0], YMAX = ee(0, 90)[1], SCALE = 1000 / (2 * XMAX);
  function px(lon, lat) { var q = ee(lon, lat); return [(q[0] + XMAX) * SCALE, (YMAX - q[1]) * SCALE]; }
  async function world() {
    if (S.world) return S.world;
    var r = await fetch("static/world.json").catch(binaNoAnswer);
    S.world = r.ok ? await r.json().catch(function () { return null; }) : null;
    return S.world;
  }
  function mapSvg(w, m) {
    if (!w) return '<div class="empty">המפה לא נטענה.</div>';
    var hot = {};
    (m.pins || []).forEach(function (p) { if (p.dir === "in" && p.cc) hot[p.cc] = 1; });
    var land = Object.keys(w.countries).map(function (cc) {
      return '<path class="land' + (hot[cc] && S.mapMode !== "out" ? " hot" : "") + '" d="' + w.countries[cc] + '"><title>' + esc(country(cc)) + "</title></path>";
    }).join("");
    var pins = "", arcs = "";
    var me = m.me && m.me.lat != null ? px(m.me.lon, m.me.lat) : null;
    (m.pins || []).slice().reverse().forEach(function (p, i) {
      if (S.mapMode !== "both" && S.mapMode !== p.dir) return;
      var xy = px(p.lon, p.lat), r = Math.min(16, 2.5 + Math.sqrt(p.n || 1) * 0.55);
      var where = [country(p.cc), p.city].filter(Boolean).join(" · ");
      var tip, cls;
      if (p.dir === "in") {
        cls = "pin-in" + (p.banned ? " banned" : (p.private && !p.public ? " private" : ""));
        tip = where + " — " + n(p.ips) + " כתובות, " + n(p.n) + " בקשות" + (p.fails ? ", " + n(p.fails) + " נכשלו" : "") + (p.banned ? ", " + n(p.banned) + " חסומות" : "");
      } else {
        cls = "pin-out";
        tip = where + " — " + n(p.ips) + " יעדים, " + n(p.n) + " חיבורים" + (p.names && p.names.length ? ": " + p.names.join(", ") : "");
        if (me) {
          var mx = (me[0] + xy[0]) / 2, my = Math.min(me[1], xy[1]) - Math.abs(me[0] - xy[0]) * 0.18 - 10;
          arcs += '<path class="arc" d="M' + me[0].toFixed(1) + "," + me[1].toFixed(1) + " Q" + mx.toFixed(1) + "," + my.toFixed(1) + " " + xy[0].toFixed(1) + "," + xy[1].toFixed(1) + '"/>';
        }
      }
      pins += '<circle class="' + cls + '" cx="' + xy[0].toFixed(1) + '" cy="' + xy[1].toFixed(1) + '" r="' + r.toFixed(1) + '" data-tip="' + esc(tip) + '"><title>' + esc(tip) + "</title></circle>";
    });
    var mine = "";
    if (me) {
      mine = '<circle class="me" cx="' + me[0].toFixed(1) + '" cy="' + me[1].toFixed(1) + '" r="6"><title>' + esc("הלשכה — " + [country(m.me.cc), m.me.city].filter(Boolean).join(" · ")) + "</title></circle>" +
        '<text class="me-label" x="' + (me[0] + 9).toFixed(1) + '" y="' + (me[1] - 8).toFixed(1) + '" text-anchor="end">' + esc(m.office || "הלשכה") + "</text>";
    }
    return '<svg viewBox="0 0 1000 ' + w.h + '" role="img" aria-label="מפת הכתובות">' + land + arcs + pins + mine + "</svg>";
  }

  // ── views ──────────────────────────────────────────────────────────────────────────────────────
  async function vOverview() {
    var res = await Promise.all([api("api/summary?hours=" + S.hours), api("api/map?hours=" + S.hours), world()]);
    if (!res[0].ok) return failed("הסיכום לא נקרא", res[0]);
    var s = S.data.summary = res[0].d, k = s.kpi || {}, m = res[1].ok ? res[1].d : { pins: [] };
    S.data.map = m;
    renderNav();
    var html = modeCallout(s, k);
    var banState = k.bans ? "failed" : (k.would_ban ? "todo" : null);
    html += '<div class="pg-kpis">' +
      kpi("בקשות נכנסות", n(k.requests), k.requests ? null : "zero", kindSub(k.kinds)) +
      kpi("כתובות", n(k.addrs), k.addrs ? null : "zero", n(k.countries) + " מדינות") +
      kpi(s.mode === "enforce" ? "חסומות עכשיו" : "היו נחסמות", n(s.mode === "enforce" ? k.bans : k.would_ban), banState, k.watching ? n(k.watching) + " במעקב" : "אין במעקב") +
      kpi("כניסות שנכשלו", n(k.signin_fail), k.signin_fail ? "todo" : null, n(k.signin_ok) + " הצליחו") +
      kpi("יעדים יוצאים", n(k.out_dests), k.out_dests ? null : "zero", n(k.out_conns) + " חיבורים") +
      "</div>";
    html += '<section class="pg-card"><div class="pg-cardhead"><h3>מפה</h3><span class="hint">' + mapHint(m) + '</span>' +
      '<div class="pg-actions"><div class="seg" id="mapMode" role="group" aria-label="מה מוצג במפה">' +
      ["both", "in", "out"].map(function (x) { return '<button type="button" data-mm="' + x + '" aria-pressed="' + (S.mapMode === x) + '">' + { both: "שניהם", "in": "נכנס", out: "יוצא" }[x] + "</button>"; }).join("") +
      "</div></div></div>" +
      '<div class="map" id="map">' + mapSvg(res[2], m) + "</div>" +
      '<div class="legend"><span><i class="in"></i>ניגשו לאתרים ולדלתות הציבוריים</span><span><i class="pv"></i>נכנסו לאפליקציות הפרטיות</span>' +
      '<span><i class="bn"></i>חסומים</span><span><i class="out"></i>הלשכה פנתה אליהם</span><span class="attr">מיקום הכתובות: DB-IP (CC BY 4.0)</span></div></section>';
    html += '<div class="cols">' + topApps(s) + topCountries(s) + "</div>";
    html += '<section class="pg-card" style="margin-top:14px"><div class="pg-cardhead"><h3>מה עובד</h3><span class="hint">המקורות שהמסך הזה נשען עליהם</span></div>' + health(s) + "</section>";
    return html;
  }
  function kindSub(kinds) {
    kinds = kinds || {};
    var pub = (kinds["public"] || 0) + (kinds.none || 0) + (kinds.door || 0), prv = (kinds["private"] || 0) + (kinds.remote || 0) + (kinds.auth || 0);
    return n(prv) + " פרטי · " + n(pub) + " ציבורי";
  }
  function kpi(label, value, state, sub) {
    var attr = state === "zero" ? ' class="pg-kpi is-zero"' : (state ? ' class="pg-kpi" data-state="' + state + '"' : ' class="pg-kpi"');
    return "<div" + attr + '><span class="pg-kpi-k" title="' + esc(label) + '">' + esc(label) + '</span><span class="pg-kpi-v num">' + value + "</span>" +
      (sub ? '<span class="sub">' + esc(sub) + "</span>" : "") + "</div>";
  }
  function mapHint(m) {
    var ins = (m.pins || []).filter(function (p) { return p.dir === "in"; }).length, outs = (m.pins || []).filter(function (p) { return p.dir === "out"; }).length;
    return n(ins) + " מקומות נכנסים · " + n(outs) + " מקומות יוצאים";
  }
  function modeCallout(s, k) {
    if (s.mode === "enforce") {
      return '<div class="callout ok"><div class="txt"><b>אכיפה פעילה.</b> מי שנחסם נעצר בליבת המחשב, לפני כל אפליקציה. ' + n(k.bans) + " כתובות חסומות עכשיו.</div>" +
        '<a class="btn ghost" href="#/bans">לחסימות</a></div>';
    }
    return '<div class="callout warn"><div class="txt"><b>מצב צפייה.</b> האבטחה רואה ורושמת הכול, ומי שהיה נחסם מסומן «היה נחסם» — אף אחד לא נחסם בפועל עד שעוברים לאכיפה. ' +
      (k.would_ban ? n(k.would_ban) + " כתובות היו נחסמות עכשיו." : "") + "</div>" +
      '<a class="btn" href="#/bans" title="המעבר לאכיפה נעשה במסך החסימות, אחרי שרואים מי היה נחסם">לאכיפה</a></div>';
  }
  function topApps(s) {
    var rows = (s.top && s.top.apps) || [];
    var body = rows.length ? table("topapps", [
      { key: "title", label: "אפליקציה", html: function (r) { return "<b>" + esc(r.title || r.app || "ללא נתב") + "</b>" + (r.office ? '<span class="t2">לשכה ' + esc(r.office) + "</span>" : ""); }, sortVal: function (r) { return r.title || r.app; } },
      { key: "kind", label: "סוג", html: function (r) { return kindPill(r.kind); } },
      { key: "addrs", label: "כתובות", html: function (r) { return '<span class="num">' + n(r.addrs) + "</span>"; } },
      { key: "n", label: "בקשות", html: function (r) { return '<span class="num">' + n(r.n) + "</span>"; } }
    ], rows, { sort: "n", href: function () { return "#/in"; } }) : '<div class="empty">אף בקשה בחלון הזה.</div>';
    return '<section class="pg-card"><div class="pg-cardhead"><h3>מה נפתח</h3></div>' + body + "</section>";
  }
  function topCountries(s) {
    var rows = (s.top && s.top.countries) || [];
    var body = rows.length ? table("topcc", [
      { key: "cc", label: "מדינה", html: function (r) { return "<b>" + esc(country(r.cc)) + "</b>"; }, sortVal: function (r) { return country(r.cc); } },
      { key: "addrs", label: "כתובות", html: function (r) { return '<span class="num">' + n(r.addrs) + "</span>"; } },
      { key: "n", label: "בקשות", html: function (r) { return '<span class="num">' + n(r.n) + "</span>"; } }
    ], rows, { sort: "n", href: function () { return "#/in"; } }) : '<div class="empty">' + noCountries(s) + "</div>";
    return '<section class="pg-card"><div class="pg-cardhead"><h3>מאיפה</h3></div>' + body + "</section>";
  }
  // which of the three empty cases this is: no location database yet, only internal addresses, or nobody
  function noCountries(s) {
    var g = ((s.health || {}).geo) || {}, k = s.kpi || {};
    if (!g.files || !Object.keys(g.files).length) return "מסד המיקום עדיין יורד — המדינות יופיעו כאן כשהוא מוכן.";
    if (k.requests) return "כל הכתובות בחלון הזה הן מהרשת הפנימית, ולכתובת פנימית אין מיקום.";
    return "אף בקשה בחלון הזה.";
  }
  function health(s) {
    var h = s.health || {}, parts = h.sensor_parts || {};
    function cell(k, ok, why) {
      var p = ok === true ? pill("עובד", "ok") : ok === false ? pill("לא עובד", "bad") : pill("לא מוגדר", "muted");
      return '<div><span class="k">' + esc(k) + "</span>" + p + '<span class="why" title="' + esc(why || "") + '">' + esc(why || "") + "</span></div>";
    }
    var g = h.geo || {}, gf = Object.keys(g.files || {});
    return '<div class="health">' +
      cell("יומן הכניסה ללשכה", (h.edge || {}).ok, (h.edge || {}).error || (h.edge && h.edge.parsed ? n(h.edge.parsed) + " בקשות נקראו" : "")) +
      cell("כניסות", (h.auth || {}).ok, (h.auth || {}).error || "") +
      cell("החיישן", (h.sensor || {}).ok, (h.sensor || {}).ok === false ? "לא כתב " + ((h.sensor || {}).age_s || "?") + " שניות" : "") +
      cell("מעקב חיבורים", (parts.conntrack || {}).ok, (parts.conntrack || {}).error || ((parts.conntrack || {}).events ? n(parts.conntrack.events) + " אירועים" : "")) +
      cell("שמות יעדים", (parts.sniffer || {}).ok, (parts.sniffer || {}).error || ((parts.sniffer || {}).packets ? n(parts.sniffer.packets) + " מנות" : "")) +
      cell("SSH במכונה", (parts.journal || {}).ok, (parts.journal || {}).error || "") +
      cell("אכיפה בליבה", (parts.nft || {}).ok, (parts.nft || {}).error || "") +
      cell("נפח בליבה", (parts.volume || {}).ok, (parts.volume || {}).error || ((parts.volume || {}).addrs ? n(parts.volume.addrs) + " כתובות" : "")) +
      cell("מיקום כתובות", gf.length ? true : (g.error ? false : null), g.error || (gf.length ? gf.join(" + ") : "יורד בהפעלה הראשונה")) +
      cell("דלת הקישור", (h.door || {}).ok, (h.door || {}).error || "") +
      cell("התראות", (h.notify || {}).ok, (h.notify || {}).error || "") +
      "</div>";
  }

  async function vInbound() {
    var r = await api("api/inbound?hours=" + S.hours + (S.kind ? "&kind=" + encodeURIComponent(S.kind) : ""));
    if (!r.ok) return failed("רשימת הכתובות לא נקראה", r);
    S.data.inbound = r.d.rows || [];
    return filterBar(true) + '<section class="pg-card"><div class="pg-cardhead"><h3>כתובות</h3><span class="hint" id="cnt"></span></div><div id="tbl"></div></section>';
  }
  function paintInbound() {
    var rows = filtered(S.data.inbound || []);
    $("cnt") && ($("cnt").textContent = n(rows.length) + " כתובות");
    $("tbl").innerHTML = rows.length ? table("in", [
      { key: "ip", label: "כתובת", html: function (r) { return ip(r.ip); } },
      { key: "cc", label: "מקום ורשת", html: function (r) { return place(r) + (r.org ? '<span class="t2" title="' + esc(r.asn ? "AS" + r.asn : "") + '">' + esc(r.org) + "</span>" : ""); }, sortVal: function (r) { return placeText(r); } },
      { key: "n", label: "בקשות", html: function (r) { return '<span class="num">' + n(r.n) + "</span>"; } },
      { key: "fails", label: "נכשלו", html: function (r) { return r.fails ? '<span class="num">' + n(r.fails) + "</span>" : '<span class="muted">0</span>'; } },
      { key: "apps", label: "מה נפתח", html: function (r) { return '<div class="chips">' + (r.apps || []).slice(0, 4).map(function (a) { return '<span class="chip" title="' + esc(a.app) + '">' + esc(a.title || a.app) + "</span>"; }).join("") + ((r.apps || []).length > 4 ? '<span class="chip">+' + ((r.apps || []).length - 4) + "</span>" : "") + "</div>"; }, sortVal: function (r) { return (r.apps || []).length; } },
      { key: "users", label: "משתמש", html: function (r) { return (r.users || []).length ? esc(r.users.join(", ")) : '<span class="muted">—</span>'; }, sortVal: function (r) { return (r.users || []).join(","); } },
      { key: "last", label: "אחרון", html: function (r) { return '<span title="' + esc(when(r.last)) + '">' + esc(ago(r.last)) + "</span>"; } },
      { key: "state", label: "מצב", html: function (r) { return statePill(r.state); } }
    ], rows, { sort: "n", href: function (x) { return "#/in/" + x.ip; } }) : '<div class="empty">אף כתובת בחלון הזה' + (S.q ? " שמתאימה לחיפוש" : "") + ".</div>";
  }
  function filtered(rows) {
    var q = (S.q || "").trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(function (r) { return JSON.stringify(r).toLowerCase().indexOf(q) >= 0 || country(r.cc).indexOf(q) >= 0; });
  }
  function filterBar(withKinds) {
    var kinds = withKinds ? '<div class="seg" id="kinds" role="group" aria-label="סוג">' + [["", "הכול"], ["public", "ציבורי"], ["private", "פרטי"], ["remote", "לשכה מקושרת"], ["auth", "כניסה"], ["door", "דלת"], ["none", "ללא נתב"]].map(function (x) {
      return '<button type="button" data-kind="' + x[0] + '" aria-pressed="' + (S.kind === x[0]) + '" title="' + esc(KIND_HINT[x[0]] || "כל הסוגים") + '">' + x[1] + "</button>";
    }).join("") + "</div>" : "";
    return '<div class="toolbar"><input type="search" id="q" placeholder="חיפוש: כתובת, מדינה, רשת, אפליקציה, משתמש…" value="' + esc(S.q) + '">' + kinds + "</div>";
  }

  async function vOutbound() {
    var r = await api("api/outbound?hours=" + S.hours);
    if (!r.ok) return failed("רשימת היעדים לא נקראה", r);
    S.data.outbound = r.d.rows || [];
    S.data.inports = r.d.inbound_ports || [];
    return filterBar(false) + '<section class="pg-card"><div class="pg-cardhead"><h3>יעדים</h3><span class="hint" id="cnt"></span></div><div id="tbl"></div></section>' +
      '<section class="pg-card"><div class="pg-cardhead"><h3>פורטים שנפתחו מבחוץ, לא דרך הכניסה של הלשכה</h3><span class="hint">SSH, דואר, המנהרה של הקישור</span></div><div id="tbl2"></div></section>';
  }
  function paintOutbound() {
    var rows = filtered(S.data.outbound || []);
    $("cnt") && ($("cnt").textContent = n(rows.length) + " יעדים");
    $("tbl").innerHTML = rows.length ? table("out", [
      // the destination is its NAME when one was seen (a DNS answer, a TLS server name, its reverse
      // name), with the address under it; an address nobody named is the title itself
      { key: "names", label: "יעד", html: function (r) {
        return r.names && r.names.length
          ? '<b class="ltr" title="' + esc(r.names.join(", ")) + '">' + esc(r.names[0]) + "</b>" + '<span class="t2">' + ip(r.dst) + "</span>"
          : ip(r.dst);                  // what an unnamed address IS (r.local) is said once, in the place column
      }, sortVal: function (r) { return (r.names || [])[0] || "~" + r.dst; } },
      { key: "cc", label: "מקום ורשת", html: function (r) { return place(r) + (r.org ? '<span class="t2">' + esc(r.org) + "</span>" : ""); }, sortVal: function (r) { return placeText(r); } },
      { key: "apps", label: "מי פנה", html: function (r) { return '<div class="chips">' + (r.apps || []).map(function (a) { return '<span class="chip">' + esc(a === "@host" ? "המכונה עצמה" : a) + "</span>"; }).join("") + "</div>"; }, sortVal: function (r) { return (r.apps || []).join(","); } },
      { key: "n", label: "חיבורים", html: function (r) { return '<span class="num">' + n(r.n) + "</span>" + (r.bytes_out || r.bytes_in ? '<span class="t2 num">↑' + bytes(r.bytes_out) + " ↓" + bytes(r.bytes_in) + "</span>" : ""); } },
      { key: "ports", label: "פורטים", html: function (r) { return '<span class="num">' + esc((r.ports || []).slice(0, 4).join(" ")) + "</span>"; }, sortVal: function (r) { return (r.ports || []).join(","); } },
      { key: "last", label: "אחרון", html: function (r) { return '<span title="' + esc(when(r.last)) + '">' + esc(ago(r.last)) + "</span>"; } },
      { key: "state", label: "מצב", html: function (r) { return statePill(r.state); } }
    ], rows, { sort: "n", href: function (x) { return "#/out/" + x.dst; } }) : '<div class="empty">אף חיבור יוצא בחלון הזה' + (S.q ? " שמתאים לחיפוש" : "") + ". החיישן כותב כל חמש שניות.</div>";
    var ports = S.data.inports || [];
    $("tbl2").innerHTML = ports.length ? table("inports", [
      { key: "port", label: "פורט", html: function (r) { return '<span class="num">' + esc(r.port + "/" + r.proto) + "</span>"; } },
      { key: "addrs", label: "כתובות", html: function (r) { return '<span class="num">' + n(r.addrs) + "</span>"; } },
      { key: "n", label: "חיבורים", html: function (r) { return '<span class="num">' + n(r.n) + "</span>"; } },
      { key: "last", label: "אחרון", html: function (r) { return esc(ago(r.last)); } }
    ], ports, { sort: "n" }) : '<div class="empty">אף חיבור נכנס שלא דרך הכניסה של הלשכה.</div>';
  }

  async function vSignins() {
    var r = await api("api/signins?hours=" + Math.max(S.hours, 24));
    if (!r.ok) return failed("הכניסות לא נקראו", r);
    var d = S.data.signins = r.d;
    var keys = d.keys || [];
    var html = '<section class="pg-card"><div class="pg-cardhead"><h3>מפתחות SSH שנכנסו למכונה</h3><span class="hint">לפי טביעת המפתח; השם הוא ההערה שבקובץ המפתחות המורשים</span></div>' +
      (keys.length ? table("keys", [
        { key: "label", label: "מפתח", html: function (r) { return "<b>" + esc(r.label || "מפתח בלי הערה") + "</b>" + (r.authorized ? "" : ' ' + pill("לא בקובץ המורשים", "warn")); } },
        { key: "type", label: "סוג", html: function (r) { return '<span class="mono small">' + esc(r.type || "—") + "</span>"; } },
        { key: "fp", label: "טביעה", html: function (r) { return '<span class="mono small ltr" title="' + esc(r.fp) + '">' + esc((r.fp || "").slice(0, 18)) + "…</span>"; } },
        { key: "n", label: "כניסות", html: function (r) { return '<span class="num">' + n(r.n) + "</span>"; } },
        { key: "addrs", label: "כתובות", html: function (r) { return '<span class="num">' + n(r.addrs) + "</span>"; } },
        { key: "last", label: "אחרונה", html: function (r) { return esc(ago(r.last)); } }
      ], keys, { sort: "n" }) : '<div class="empty">אף כניסת SSH בחלון הזה — או שלמכונה הזאת אין יומן SSH (מחשב נייד, Windows).</div>') + "</section>";
    var rows = d.rows || [];
    html += '<section class="pg-card"><div class="pg-cardhead"><h3>כל הכניסות</h3><span class="hint">' + n(rows.length) + " אחרונות</span></div>" +
      (rows.length ? table("signins", [
        { key: "ts", label: "מתי", html: function (r) { return '<span title="' + esc(when(r.ts)) + '">' + esc(ago(r.ts)) + "</span>"; } },
        { key: "src", label: "איפה", html: function (r) { return esc(SRC[r.src] || r.src); } },
        { key: "verdict", label: "תוצאה", html: function (r) { var v = VERDICT[r.verdict] || [r.verdict, "muted"]; return pill(v[0], v[1]); } },
        { key: "user", label: "משתמש", html: function (r) { return esc(r.user || "—") + (r.key_label ? '<span class="t2">' + esc(r.key_label) + "</span>" : ""); } },
        { key: "ip", label: "כתובת", html: function (r) { return ip(r.ip); } },
        { key: "cc", label: "מקום", html: function (r) { return place(r); } }
      ], rows, { sort: "ts", href: function (x) { return "#/in/" + x.ip; } }) : '<div class="empty">אף כניסה בחלון הזה.</div>') + "</section>";
    return html;
  }

  async function vLinks() {
    var r = await api("api/links?hours=" + S.hours);
    if (!r.ok) return failed("תנועת הקישורים לא נקראה", r);
    var d = r.d, labels = d.offices || {};
    function office(o) { return esc(labels[o] || o || "—"); }
    var html = "";
    if (d.door && d.door.ok === false) html += '<div class="callout warn"><div class="txt"><b>יומן הדלת לא נקרא.</b> ' + esc(d.door.error || "") + " — מה שלשכות אחרות פתחו כאן לא מוצג עד שהדלת עונה.</div></div>";
    html += '<div class="cols"><section class="pg-card"><div class="pg-cardhead"><h3>מה לשכות אחרות פתחו כאן</h3></div>' +
      ((d.served || []).length ? table("served", [
        { key: "office", label: "לשכה", html: function (x) { return "<b>" + office(x.office) + "</b>"; } },
        { key: "title", label: "אפליקציה", html: function (x) { return esc(x.title || x.app); } },
        { key: "user", label: "בתור", html: function (x) { return esc(x.user || "—"); } },
        { key: "n", label: "בקשות", html: function (x) { return '<span class="num">' + n(x.n) + "</span>" + (x.fails ? '<span class="t2">' + n(x.fails) + " נכשלו</span>" : ""); } },
        { key: "last", label: "אחרון", html: function (x) { return esc(ago(x.last)); } }
      ], d.served, { sort: "n" }) : '<div class="empty">אף בקשה דרך דלת הקישור בחלון הזה.</div>') + "</section>" +
      '<section class="pg-card"><div class="pg-cardhead"><h3>מה נפתח מכאן אצל לשכות אחרות</h3></div>' +
      ((d.used || []).length ? table("used", [
        { key: "office", label: "לשכה", html: function (x) { return "<b>" + office(x.office) + "</b>"; } },
        { key: "title", label: "אפליקציה", html: function (x) { return esc(x.title || x.app); } },
        { key: "addrs", label: "כתובות", html: function (x) { return '<span class="num">' + n(x.addrs) + "</span>"; } },
        { key: "n", label: "בקשות", html: function (x) { return '<span class="num">' + n(x.n) + "</span>"; } },
        { key: "last", label: "אחרון", html: function (x) { return esc(ago(x.last)); } }
      ], d.used, { sort: "n" }) : '<div class="empty">אף אפליקציה של לשכה אחרת לא נפתחה כאן בחלון הזה.</div>') + "</section></div>";
    var rec = d.recent || [];
    html += '<section class="pg-card" style="margin-top:14px"><div class="pg-cardhead"><h3>הבקשות האחרונות דרך הדלת</h3></div>' +
      (rec.length ? table("door", [
        { key: "ts", label: "מתי", html: function (x) { return '<span title="' + esc(when(x.ts)) + '">' + esc(ago(x.ts)) + "</span>"; } },
        { key: "office", label: "לשכה", html: function (x) { return office(x.office); } },
        { key: "title", label: "אפליקציה", html: function (x) { return esc(x.title || x.app); } },
        { key: "path", label: "בקשה", html: function (x) { return '<span class="mono small ltr">' + esc(x.method + " " + (x.path || "").slice(0, 80)) + "</span>"; } },
        { key: "status", label: "תשובה", html: function (x) { return pill(String(x.status), x.status >= 500 ? "bad" : x.status >= 400 ? "warn" : "ok"); } },
        { key: "ms", label: "זמן", html: function (x) { return '<span class="num">' + n(x.ms) + " ms</span>"; } }
      ], rec, { sort: "ts" }) : '<div class="empty">אין בקשות אחרונות.</div>') + "</section>";
    return html;
  }

  async function vBans() {
    var r = await api("api/bans");
    if (!r.ok) return failed("החסימות לא נקראו", r);
    var d = S.data.bans = r.d;
    var rr = await api("api/rules");
    var rules = rr.ok ? rr.d : { allow: [], block: [] };
    var enforce = d.mode === "enforce";
    var html = '<section class="pg-card"><div class="pg-cardhead"><h3>מצב</h3>' +
      '<div class="pg-actions">' + (enforce ? '<button class="btn ghost" type="button" id="toObserve" title="להפסיק לאכוף: החסימות נשארות ברשימה ולא נעצרות בליבה">חזרה לצפייה</button>'
        : '<button class="btn" type="button" id="toEnforce" title="מכאן והלאה מי שנחסם נעצר בליבת המחשב">מעבר לאכיפה</button>') + "</div></div>" +
      '<div class="facts">' +
      fact("מצב", enforce ? "אכיפה" : "צפייה") +
      fact("בתוקף בליבה", n((d.applied || {}).bans || 0) + " חסימות") +
      fact("נעצרו בליבה", n(dropCount(d.applied)) + " מנות") +
      fact("למידה עד", d.learning_until && d.learning_until * 1000 > Date.now() ? when(d.learning_until) : "הסתיימה") +
      "</div></section>";
    var jails = d.jails || {};
    html += '<section class="pg-card"><div class="pg-cardhead"><h3>הכללים</h3><span class="hint">כתובת שעוברת סף נחסמת לשעה, ופי ארבעה בכל פעם חוזרת (עד שבוע)</span></div><div class="facts">' +
      fact("סריקה", (jails.scan ? n(jails.scan.fails) + " כשלים או " + n(jails.scan.probes) + " נתיבי סריקה ב־" + Math.round(jails.scan.window / 60) + " דק׳" : "—")) +
      fact("כניסות שנכשלו", (jails.auth ? n(jails.auth.fails) + " ב־" + Math.round(jails.auth.window / 60) + " דק׳" : "—")) +
      fact("SSH", (jails.sshd ? n(jails.sshd.fails) + " ב־" + Math.round(jails.sshd.window / 60) + " דק׳" : "—")) +
      fact("לעולם לא נחסמים", "הרשת הפרטית, הלשכה עצמה, העדר, מי שנכנס בהצלחה, הרשימה למטה") +
      "</div></section>";
    var active = d.active || [];
    html += '<section class="pg-card"><div class="pg-cardhead"><h3>' + (enforce ? "חסומים עכשיו" : "היו נחסמים עכשיו") + '</h3><span class="hint">' + n(active.length) + "</span></div>" +
      (active.length ? table("bans", [
        { key: "ip", label: "כתובת", html: function (b) { return ip(b.ip); } },
        { key: "cc", label: "מקום ורשת", html: function (b) { return place(b) + '<span class="t2">' + esc(b.org || "") + "</span>"; } },
        { key: "jail", label: "כלל", html: function (b) { return esc(JAIL[b.jail] || b.jail) + '<span class="t2" title="' + esc(b.reason) + '">' + esc(b.reason || "") + "</span>"; } },
        { key: "until", label: "עד", html: function (b) { return esc(left(b.until)); }, sortVal: function (b) { return b.until || 9e12; } },
        { key: "offences", label: "פעמים", html: function (b) { return '<span class="num">' + n(b.offences) + "</span>"; } },
        { key: "mode", label: "מצב", html: function (b) { return b.mode === "enforce" ? pill("חסום", "bad") : pill("היה נחסם", "warn"); } },
        { key: "act", label: "", html: function (b) { return '<button class="btn ghost" type="button" data-unban="' + esc(b.ip) + '" title="להסיר את החסימה של ' + esc(b.ip) + ' עכשיו">שחרור</button>'; }, sortVal: function () { return 0; } }
      ], active, { sort: "since", href: function (b) { return "#/in/" + b.ip; } }) : '<div class="empty">אף כתובת לא ' + (enforce ? "חסומה" : "הייתה נחסמת") + " עכשיו.</div>") + "</section>";
    var watching = d.watching || [];
    if (watching.length) {
      html += '<section class="pg-card"><div class="pg-cardhead"><h3>במעקב</h3><span class="hint">כתובות שצברו ראיות ועוד לא עברו סף</span></div>' + table("watch", [
        { key: "ip", label: "כתובת", html: function (w) { return ip(w.ip); } },
        { key: "fails", label: "כשלים", html: function (w) { return '<span class="num">' + n(w.fails) + "</span>"; } },
        { key: "probes", label: "נתיבי סריקה", html: function (w) { return '<span class="num">' + n(w.probes) + "</span>"; } },
        { key: "auth", label: "כניסות שנכשלו", html: function (w) { return '<span class="num">' + n(w.auth) + "</span>"; } },
        { key: "ssh", label: "SSH", html: function (w) { return '<span class="num">' + n(w.ssh) + "</span>"; } }
      ], watching, { sort: "fails", href: function (w) { return "#/in/" + w.ip; } }) + "</section>";
    }
    html += '<div class="cols">' + ruleCard("allow", "מותרים תמיד", "כתובת או טווח שלעולם לא נחסמים", rules.allow || []) +
      ruleCard("block", "חסימות יציאה", "יעד שהלשכה לא תגיע אליו — המכונה והאפליקציות שלה", rules.block || []) + "</div>";
    var hist = d.history || [];
    html += '<section class="pg-card" style="margin-top:14px"><div class="pg-cardhead"><h3>היסטוריה</h3></div>' + (hist.length ? table("hist", [
      { key: "ts", label: "מתי", html: function (x) { return '<span title="' + esc(when(x.ts)) + '">' + esc(ago(x.ts)) + "</span>"; } },
      { key: "ip", label: "כתובת", html: function (x) { return ip(x.ip); } },
      { key: "action", label: "מה", html: function (x) { return esc(ACTION[x.action] || x.action) + (x.mode && x.mode !== "enforce" && x.action === "ban" ? " " + pill("צפייה", "warn") : ""); } },
      { key: "jail", label: "כלל", html: function (x) { return esc(JAIL[x.jail] || x.jail || "—"); } },
      { key: "by", label: "על ידי", html: function (x) { return esc(x.by === "jail" ? "הכלל" : x.by === "clock" ? "השעון" : (x.by || "—")); } }
    ], hist, { sort: "ts", href: function (x) { return "#/in/" + x.ip; } }) : '<div class="empty">עוד לא נחסם אף אחד.</div>') + "</section>";
    return html;
  }
  function dropCount(applied) {
    var c = (applied || {}).counters || {}, t = 0;
    Object.keys(c).forEach(function (k) { t += (c[k] || {}).packets || 0; });
    return t;
  }
  function fact(k, v) { return '<div><div class="k">' + esc(k) + '</div><div class="v" title="' + esc(v) + '">' + esc(v) + "</div></div>"; }
  function ruleCard(kind, title, hint, rows) {
    return '<section class="pg-card"><div class="pg-cardhead"><h3>' + esc(title) + '</h3><span class="hint">' + esc(hint) + "</span></div>" +
      (rows.length ? table("rule-" + kind, [
        { key: "value", label: kind === "allow" ? "כתובת או טווח" : "יעד", html: function (r) { return ip(r.value); } },
        { key: "note", label: "הערה", html: function (r) { return esc(r.note || "—"); } },
        { key: "until", label: "עד", html: function (r) { return esc(left(r.until)); } },
        { key: "act", label: "", html: function (r) { return '<button class="btn ghost" type="button" data-unrule="' + esc(kind) + '" data-value="' + esc(r.value) + '" title="להסיר את הכלל">הסרה</button>'; }, sortVal: function () { return 0; } }
      ], rows, { sort: "since" }) : '<div class="empty">הרשימה ריקה.</div>') +
      '<form class="formrow" data-rule="' + kind + '"><div class="field"><label>' + (kind === "allow" ? "כתובת או טווח" : "כתובת יעד") + '</label><input name="value" class="ltr" required placeholder="' + (kind === "allow" ? "203.0.113.7 או 203.0.113.0/24" : "203.0.113.50") + '"></div>' +
      '<div class="field"><label>הערה</label><input name="note" placeholder="למה"></div><button class="btn' + (kind === "block" ? " danger" : "") + '" type="submit">' + (kind === "allow" ? "הוספה" : "חסימה") + "</button></form></section>";
  }

  // the volume is counted by the sensor's own kernel sets; conntrack's switch is the older, host-wide way
  function volText(v, ct) {
    if (v && v.ok) return "נספר בליבה · " + n(v.addrs || 0) + " כתובות";
    if (ct && ct.acct === 1) return "נספר במעקב החיבורים";
    return v && v.error ? "לא נספר — " + v.error : "לא נספר — רואים חיבורים, לא נפחים";
  }
  async function vNet() {
    var r = await api("api/network");
    if (!r.ok) return failed("פרטי הרשת לא נקראו", r);
    var f = r.d.facts || {}, ap = r.d.applied || {};
    if (!f.at) return '<div class="callout warn"><div class="txt"><b>החיישן עוד לא כתב.</b> הוא כותב את פרטי הרשת כל 30 שניות מרגע שהוא עולה.</div></div>';
    var ct = f.conntrack || {};
    var html = '<section class="pg-card"><div class="pg-cardhead"><h3>המכונה ברשת</h3><span class="hint">עודכן ' + esc(ago(f.at)) + "</span></div>" +
      '<div class="facts">' + fact("שם", f.hostname || "—") + fact("ליבה", f.kernel || "—") + fact("כתובת ציבורית", f.public_ip || "לא ידועה") +
      fact("שער", f.gateway || "—") + fact("חיבורים במעקב", (ct.count != null ? n(ct.count) : "—") + (ct.max ? " מתוך " + n(ct.max) : "")) +
      fact("נפח לכל כתובת", volText(f.health && f.health.volume, ct)) + "</div></section>";
    var ifs = (f.interfaces || []).filter(function (i) { return (i.addrs || []).length && !/^veth/.test(i.name); });
    var br = r.d.bridges || {};
    html += '<section class="pg-card"><div class="pg-cardhead"><h3>ממשקים</h3></div>' + table("ifaces", [
      { key: "name", label: "ממשק", html: function (i) {
        return br[i.name] ? '<b class="ltr">' + esc(br[i.name]) + '</b><span class="t2 mono">' + esc(i.name) + "</span>" : '<span class="mono">' + esc(i.name) + "</span>";
      }, sortVal: function (i) { return br[i.name] || i.name; } },
      { key: "addrs", label: "כתובות", html: function (i) { return '<span class="mono small ltr">' + esc((i.addrs || []).join("  ")) + "</span>"; }, sortVal: function (i) { return (i.addrs || []).join(); } },
      { key: "state", label: "מצב", html: function (i) { return pill(i.state === "UP" ? "פעיל" : i.state === "UNKNOWN" ? "פעיל" : "כבוי", i.state === "DOWN" ? "muted" : "ok"); } }
    ], ifs, { sort: "name", dir: 1 }) + "</section>";
    var ls = f.listen || [];
    html += '<section class="pg-card"><div class="pg-cardhead"><h3>פורטים מאזינים</h3><span class="hint">פתוח לכל הרשתות = כל מי שמגיע למכונה יכול לנסות</span></div>' + table("listen", [
      { key: "port", label: "פורט", html: function (l) { return '<span class="num">' + esc(l.port + "/" + l.proto) + "</span>"; } },
      { key: "scope", label: "פתוח ל־", html: function (l) { return l.scope === "all" ? pill("כל הרשתות", "warn") : l.scope === "loopback" ? pill("המכונה בלבד", "ok") : pill("כתובת אחת", "info"); } },
      { key: "addr", label: "כתובת", html: function (l) { return ip(l.addr); } },
      { key: "apps", label: "שייך ל־", html: function (l) { return (l.apps || []).length ? '<div class="chips">' + l.apps.map(function (a) { return '<span class="chip">' + esc(a) + "</span>"; }).join("") + "</div>" : '<span class="muted">שירות של המכונה</span>'; }, sortVal: function (l) { return (l.apps || []).join(); } }
    ], ls, { sort: "port", dir: 1 }) + "</section>";
    html += routerCard(f.router || {});
    var hp = f.health || {};
    html += '<section class="pg-card"><div class="pg-cardhead"><h3>החיישן</h3><span class="hint">תהליך אחד ברשת של המכונה, בלי פורט ובלי מאזין; שתי הרשאות בלבד</span></div><div class="facts">' +
      fact("מעקב חיבורים", (hp.conntrack || {}).ok ? "עובד · " + n((hp.conntrack || {}).events) + " אירועים" : ((hp.conntrack || {}).error || "לא עובד")) +
      fact("שמות יעדים", (hp.sniffer || {}).ok ? "עובד · " + n((hp.sniffer || {}).packets) + " מנות" : ((hp.sniffer || {}).error || "לא עובד")) +
      fact("יומן SSH", (hp.journal || {}).ok ? "עובד · " + n((hp.journal || {}).lines) + " שורות" : ((hp.journal || {}).error || "לא עובד")) +
      fact("אכיפה בליבה", (hp.nft || {}).ok ? "טבלה inet dgo_security פעילה" : ((hp.nft || {}).error || "לא עובד")) +
      fact("נפח בליבה", (hp.volume || {}).ok ? "עובד · " + n((hp.volume || {}).addrs) + " כתובות" : ((hp.volume || {}).error || "לא עובד")) +
      fact("מצב שנאכף", ap.mode === "enforce" ? "אכיפה" : "צפייה") + "</div></section>";
    return html;
  }
  function routerCard(r) {
    var rs = r.routers || [];
    var declared = rs.some(function (x) { return x.role === "declared"; });
    var html = '<section class="pg-card"><div class="pg-cardhead"><h3>' + (rs.length > 1 ? "השער והנתב" : "הנתב") + '</h3><span class="hint">' + (r.at ? "נבדק " + esc(ago(r.at)) : "נבדק כל 5 דקות") + "</span></div>";
    if (!rs.length) {
      return html + '<div class="empty">' + ((r.candidates || []).length ? "השער " + esc(r.candidates.join(", ")) + " לא ענה באף פורט ניהול." : "השער של המכונה הזאת אינו כתובת פרטית — שרת בחוות שרתים, בלי נתב ביתי מולו.") + "</div></section>";
    }
    rs.forEach(function (x, i) {
      var hdr = x.http || {}, up = x.upnp;
      // the first hop, when the owner also declared a router behind it, is the VM host's virtual router
      var virt = x.role === "gateway" && declared;
      if (rs.length > 1) {
        html += '<h4 class="blockhead"' + (i ? ' style="margin-top:16px"' : "") + ">" + (x.role === "declared" ? "הנתב הפיזי" : virt ? "הנתב הווירטואלי — המחשב שמריץ את המנוע" : "השער הראשון") + "</h4>" +
          (virt ? '<div class="pg-note" style="margin-bottom:8px">המכונה של הלשכה רצה בתוך מכונה וירטואלית, והשער שלה הוא המחשב המארח. הפורטים כאן הם שלו; הנתב שבבית הוא הבא בתור.</div>' : "");
      }
      html += '<div class="facts">' + fact("כתובת", x.ip) + fact("דגם (לפי דף הניהול)", hdr.title || "—") + fact("שרת", hdr.server || "—") +
        fact("פורטי ניהול פתוחים", (x.open || []).join(" ")) +
        fact("UPnP", up ? (up.device ? [up.device.manufacturer, up.device.modelName].filter(Boolean).join(" ") || "עונה" : "עונה") : "כבוי — אף אפליקציה ברשת לא יכולה לפתוח פורט בנתב") +
        fact("כתובת חיצונית", (up && up.external_ip) || "—") + "</div>";
      if (up && (up.mappings || []).length) {
        html += '<h4 style="margin:12px 0 6px">פורטים שהנתב מעביר פנימה</h4>' + table("upnp", [
          { key: "external_port", label: "חיצוני", html: function (m) { return '<span class="num">' + esc(m.external_port + "/" + m.protocol) + "</span>"; } },
          { key: "client", label: "אל", html: function (m) { return ip(m.client + ":" + m.internal_port); } },
          { key: "description", label: "תיאור", html: function (m) { return esc(m.description || "—"); } },
          { key: "enabled", label: "פעיל", html: function (m) { return m.enabled === "1" ? pill("פעיל", "warn") : pill("כבוי", "muted"); } }
        ], up.mappings, { sort: "external_port", dir: 1 });
      }
      html += '<div class="pg-row" style="margin-top:10px"><a class="btn ghost" target="_blank" rel="noopener noreferrer" href="http://' + esc(x.ip) + '/" title="דף הניהול של הנתב נפתח בחלון חדש — הסיסמה מוקלדת שם, לא כאן">דף הניהול של הנתב</a>' +
        '<span class="pg-note">ניהול מלא של הנתב (מכשירים מחוברים, העברות פורטים, חומת אש) דורש את סיסמת הניהול שלו, שמורה בכספת החיבורים.</span></div>';
    });
    return html + "</section>";
  }

  async function vHerd() {
    var r = await api("api/herd?hours=" + S.hours);
    if (!r.ok) return failed("העדר לא נקרא", r);
    var d = r.d, rows = [];
    var me = d.self || {};
    rows.push({ office: d.office, label: "הלשכה הזאת", ok: true, self: true, data: me });
    (d.offices || []).forEach(function (o) { rows.push(o); });
    return '<section class="pg-card"><div class="pg-cardhead"><h3>הלשכות</h3><span class="hint">כל אחת קוראת את המכונה שלה; כאן נאסף מה שהן אומרות, דרך הקישור</span></div>' + table("herd", [
      { key: "office", label: "לשכה", html: function (o) { return "<b>" + esc(o.label || o.office) + '</b><span class="t2 mono">' + esc(o.office) + "</span>"; } },
      { key: "ok", label: "מצב", html: function (o) { return o.ok ? (((o.data || {}).mode === "enforce") ? pill("אכיפה", "ok") : pill("צפייה", "warn")) : (o.installed === false ? pill("לא מותקן", "muted", o.error) : pill("לא עונה", "bad", o.error)); }, sortVal: function (o) { return o.ok ? 1 : 0; } },
      { key: "req", label: "בקשות", html: function (o) { return o.ok ? '<span class="num">' + n(((o.data || {}).kpi || {}).requests) + "</span>" : "—"; }, sortVal: function (o) { return ((o.data || {}).kpi || {}).requests || 0; } },
      { key: "addrs", label: "כתובות", html: function (o) { return o.ok ? '<span class="num">' + n(((o.data || {}).kpi || {}).addrs) + "</span>" : "—"; }, sortVal: function (o) { return ((o.data || {}).kpi || {}).addrs || 0; } },
      { key: "bans", label: "חסימות", html: function (o) { var k = (o.data || {}).kpi || {}; return o.ok ? '<span class="num">' + n((k.bans || 0) + (k.would_ban || 0)) + "</span>" : "—"; }, sortVal: function (o) { var k = (o.data || {}).kpi || {}; return (k.bans || 0) + (k.would_ban || 0); } },
      { key: "out", label: "יעדים יוצאים", html: function (o) { return o.ok ? '<span class="num">' + n(((o.data || {}).kpi || {}).out_dests) + "</span>" : "—"; }, sortVal: function (o) { return ((o.data || {}).kpi || {}).out_dests || 0; } },
      { key: "why", label: "", html: function (o) { return o.self ? '<a class="btn ghost" href="#/">כאן</a>' : (o.ok ? '<a class="btn ghost" href="../security.' + encodeURIComponent(o.office) + '/" title="האבטחה של הלשכה הזאת, כפי שהיא רואה את עצמה">פתיחה</a>' : '<span class="muted small">' + esc(o.error || "") + "</span>"); }, sortVal: function () { return 0; } }
    ], rows, { sort: "ok" }) + "</section>";
  }

  // ── the drawers ────────────────────────────────────────────────────────────────────────────────
  function openDrawer(title, pillHtml, body, foot) {
    $("drawerTitle").innerHTML = title;
    $("drawerPill").innerHTML = pillHtml || "";
    $("drawerBody").innerHTML = body;
    $("drawerFoot").innerHTML = foot || "";
    $("drawer").classList.remove("hidden");
    $("scrim").classList.remove("hidden");
    $("drawerClose").focus();
  }
  function closeDrawer() {
    if ($("drawer").classList.contains("hidden")) return;
    $("drawer").classList.add("hidden");
    $("scrim").classList.add("hidden");
    var base = "#/" + (S.view || "");
    if (location.hash !== base) history.replaceState(null, "", base);
  }
  $("drawerClose").addEventListener("click", closeDrawer);
  $("scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawer(); });

  async function dInbound(addr) {
    openDrawer(ip(addr), "", '<div class="skel">טוען…</div>', "");
    var r = await api("api/inbound/" + encodeURIComponent(addr));
    if (!r.ok) { $("drawerBody").innerHTML = failed("הכתובת לא נקראה", r); return; }
    var d = r.d, a = d.addr || {}, b = d.ban && d.ban.active ? d.ban : null;
    var st = b ? (b.mode === "enforce" ? "banned" : "would") : ({ "signed-in": "trusted", allowed: "allowed", herd: "herd", own: "own", "private": "own" }[d.trust] || "seen");
    var body = '<div class="facts">' + fact("מקום", placeText(a) || "לא ידוע") + fact("רשת", (a.org || "—") + (a.asn ? " · AS" + a.asn : "")) +
      fact("נראתה לראשונה", when(a.first)) + fact("נראתה לאחרונה", when(a.last)) + fact("משתמשים", (a.users || []).join(", ") || "—") +
      fact("אמון", { "signed-in": "נכנסה בהצלחה", allowed: "ברשימת המותרים", herd: "לשכה בעדר", own: "הלשכה עצמה", "private": "רשת פרטית" }[d.trust] || "אין") + "</div>";
    if (b) body += '<div class="callout ' + (b.mode === "enforce" ? "bad" : "warn") + '" style="margin-top:12px"><div class="txt"><b>' + (b.mode === "enforce" ? "חסומה" : "הייתה נחסמת") + "</b> — " + esc(JAIL[b.jail] || b.jail) + ": " + esc(b.reason || "") + " · " + esc(left(b.until)) + " · פעם " + n(b.offences) + "</div></div>";
    var hits = d.hits || [];
    body += '<h3 style="margin:16px 0 8px;font-size:15px">הבקשות האחרונות</h3>' + (hits.length ? table("ip-hits", [
      { key: "ts", label: "מתי", html: function (h) { return '<span title="' + esc(when(h.ts)) + '">' + esc(ago(h.ts)) + "</span>"; } },
      { key: "kind", label: "סוג", html: function (h) { return kindPill(h.kind); } },
      { key: "title", label: "אפליקציה", html: function (h) { return esc(h.title || h.app || "—") + (h.office ? '<span class="t2">לשכה ' + esc(h.office) + "</span>" : ""); } },
      { key: "path", label: "בקשה", html: function (h) { return '<span class="mono small ltr" title="' + esc(h.ua || "") + '">' + esc((h.method || "") + " " + (h.path || "").slice(0, 70)) + "</span>"; } },
      { key: "status", label: "תשובה", html: function (h) { return pill(String(h.status), h.status >= 500 ? "bad" : h.status >= 400 ? "warn" : "ok"); } }
    ], hits, { sort: "ts" }) : '<div class="empty">אין בקשות שמורות (נשמרות שלושה ימים).</div>');
    var sig = d.signins || [];
    if (sig.length) body += '<h3 style="margin:16px 0 8px;font-size:15px">כניסות מהכתובת הזאת</h3>' + table("ip-sig", [
      { key: "ts", label: "מתי", html: function (s) { return esc(ago(s.ts)); } },
      { key: "src", label: "איפה", html: function (s) { return esc(SRC[s.src] || s.src); } },
      { key: "verdict", label: "תוצאה", html: function (s) { var v = VERDICT[s.verdict] || [s.verdict, "muted"]; return pill(v[0], v[1]); } },
      { key: "user", label: "משתמש", html: function (s) { return esc(s.user || "—"); } }
    ], sig, { sort: "ts" });
    var trusted = d.trust === "private" || d.trust === "own";
    var foot = b ? '<button class="btn" type="button" id="dUnban">שחרור החסימה</button>'
      : (trusted ? '<span class="pg-note">כתובת של הלשכה עצמה או של הרשת הפרטית — לא נחסמת.</span>'
        : '<select id="dMinutes" aria-label="לכמה זמן"><option value="60">לשעה</option><option value="1440">ליום</option><option value="10080" selected>לשבוע</option><option value="0">לצמיתות</option></select>' +
          '<button class="btn ghost" type="button" id="dAllow" title="הכתובת לא תיחסם לעולם">התרה תמיד</button>' +
          '<button class="btn danger" type="button" id="dBan">חסימה</button>');
    openDrawer(ip(addr), statePill(st), body, foot);
    var bb = $("dBan"), ub = $("dUnban"), al = $("dAllow");
    if (bb) bb.onclick = async function () {
      var minutes = Number($("dMinutes").value);
      var ok = await binaAsk({ title: "לחסום את " + addr + "?", body: S.data.summary && S.data.summary.mode !== "enforce" ? "המסך במצב צפייה: החסימה תירשם ותיאכף רק אחרי מעבר לאכיפה." : "הכתובת תיעצר בליבת המחשב, לפני כל אפליקציה.",
        ok: "חסימה", danger: true, facts: [["כתובת", addr], ["מקום", placeText(a) || "לא ידוע"], ["רשת", a.org || "—"], ["משך", $("dMinutes").selectedOptions[0].textContent], ["בקשות שמורות", n(hits.length)]] });
      if (!ok) return;
      try { await send("POST", "api/bans", { ip: addr, minutes: minutes, reason: "חסימה ידנית" }); binaTell("הכתובת נחסמה", "ok"); dInbound(addr); }
      catch (e) { binaTell(e.message, "bad"); }
    };
    if (ub) ub.onclick = async function () {
      try { await send("DELETE", "api/bans/" + encodeURIComponent(addr)); binaTell("החסימה שוחררה", "ok"); dInbound(addr); }
      catch (e) { binaTell(e.message, "bad"); }
    };
    if (al) al.onclick = async function () {
      var ok = await binaAsk({ title: "להתיר את " + addr + " תמיד?", body: "הכללים לא יחסמו אותה לעולם, גם אם תסרוק או תיכשל בכניסה.", ok: "התרה", facts: [["כתובת", addr], ["רשת", a.org || "—"]] });
      if (!ok) return;
      try { await send("POST", "api/rules", { kind: "allow", value: addr, note: "הותרה מהמסך" }); binaTell("הכתובת ברשימת המותרים", "ok"); dInbound(addr); }
      catch (e) { binaTell(e.message, "bad"); }
    };
  }

  async function dOutbound(addr) {
    openDrawer(ip(addr), "", '<div class="skel">טוען…</div>', "");
    var r = await api("api/outbound/" + encodeURIComponent(addr));
    if (!r.ok) { $("drawerBody").innerHTML = failed("היעד לא נקרא", r); return; }
    var d = r.d, a = d.addr || {};
    var title = (d.names && d.names[0] ? '<span class="ltr">' + esc(d.names[0].name) + "</span> · " : "") + ip(addr);
    var body = '<div class="facts">' + fact("מקום", placeText(a) || "לא ידוע") + fact("רשת", (a.org || "—") + (a.asn ? " · AS" + a.asn : "")) +
      fact("שמות", (d.names || []).map(function (x) { return x.name; }).join(", ") || "—") + fact("נראה לראשונה", when(a.first)) + "</div>";
    body += '<h3 style="margin:16px 0 8px;font-size:15px">מי פנה, לאן ומתי</h3>' + ((d.flows || []).length ? table("dst-flows", [
      { key: "app", label: "מי", html: function (f) { return esc(f.app === "@host" ? "המכונה עצמה" : f.app); } },
      { key: "port", label: "פורט", html: function (f) { return '<span class="num">' + esc(f.port + "/" + f.proto) + "</span>"; } },
      { key: "n", label: "חיבורים", html: function (f) { return '<span class="num">' + n(f.n) + "</span>"; } },
      { key: "day", label: "יום", html: function (f) { return '<span class="num">' + esc(f.day) + "</span>"; } },
      { key: "last", label: "אחרון", html: function (f) { return esc(ago(f.last)); } }
    ], d.flows, { sort: "last" }) : '<div class="empty">אין חיבורים שמורים.</div>');
    var foot = d.blocked ? '<button class="btn" type="button" id="dUnblock">הסרת החסימה</button>' : '<button class="btn danger" type="button" id="dBlock">חסימת יציאה ליעד</button>';
    openDrawer(title, d.blocked ? pill("חסום", "bad") : pill("פתוח", "ok"), body, foot);
    var bl = $("dBlock"), ub = $("dUnblock");
    if (bl) bl.onclick = async function () {
      var apps = Array.from(new Set((d.flows || []).map(function (f) { return f.app === "@host" ? "המכונה עצמה" : f.app; })));
      var ok = await binaAsk({ title: "לחסום יציאה ל־" + addr + "?", body: "אף אפליקציה של הלשכה, וגם לא המכונה עצמה, לא תגיע ליעד הזה. מה שעובד מולו יפסיק לעבוד.",
        ok: "חסימה", danger: true, facts: [["יעד", ((d.names || [])[0] || {}).name || addr], ["כתובת", addr], ["מי פונה אליו", apps.join(", ") || "—"]] });
      if (!ok) return;
      try { await send("POST", "api/rules", { kind: "block", value: addr, note: ((d.names || [])[0] || {}).name || "" }); binaTell("היציאה ליעד נחסמה", "ok"); dOutbound(addr); }
      catch (e) { binaTell(e.message, "bad"); }
    };
    if (ub) ub.onclick = async function () {
      try { await send("DELETE", "api/rules/block/" + encodeURIComponent(addr)); binaTell("החסימה הוסרה", "ok"); dOutbound(addr); }
      catch (e) { binaTell(e.message, "bad"); }
    };
  }

  // ── wiring ─────────────────────────────────────────────────────────────────────────────────────
  document.addEventListener("click", async function (e) {
    var mm = e.target.closest("[data-mm]");
    if (mm) { S.mapMode = mm.getAttribute("data-mm"); var w = await world(); $("map").innerHTML = mapSvg(w, S.data.map || {}); var bs = $("mapMode").querySelectorAll("button"); for (var i = 0; i < bs.length; i++) bs[i].setAttribute("aria-pressed", bs[i] === mm ? "true" : "false"); return; }
    var kb = e.target.closest("[data-kind]");
    if (kb && kb.closest("#kinds")) { S.kind = kb.getAttribute("data-kind"); route(true); return; }
    var unb = e.target.closest("[data-unban]");
    if (unb) {
      var who = unb.getAttribute("data-unban");
      unb.disabled = true;
      try { await send("DELETE", "api/bans/" + encodeURIComponent(who)); binaTell("החסימה של " + who + " שוחררה", "ok"); route(true); }
      catch (er) { binaTell(er.message, "bad"); unb.disabled = false; }
      return;
    }
    var unr = e.target.closest("[data-unrule]");
    if (unr) {
      try { await send("DELETE", "api/rules/" + unr.getAttribute("data-unrule") + "/" + encodeURIComponent(unr.getAttribute("data-value"))); binaTell("הכלל הוסר", "ok"); route(true); }
      catch (er) { binaTell(er.message, "bad"); }
      return;
    }
    if (e.target.id === "toEnforce") {
      var d = S.data.bans || {}, would = (d.active || []).filter(function (b) { return b.mode !== "enforce"; });
      var ok = await binaAsk({ title: "לעבור לאכיפה?", body: "מכאן והלאה כל כתובת שעוברת סף נעצרת בליבת המחשב, לפני כל אפליקציה. הכתובות שהיו נחסמות נחסמות עכשיו.",
        ok: "מעבר לאכיפה", danger: true, facts: [["ייחסמו מיד", n(would.length) + " כתובות"], ["לעולם לא נחסמים", "הלשכה, העדר, מי שנכנס בהצלחה, רשימת המותרים"], ["אפשר לחזור", "כן, בכל רגע"]] });
      if (!ok) return;
      try { await send("PUT", "api/settings", { mode: "enforce" }); binaTell("האכיפה פעילה", "ok"); route(true); } catch (er) { binaTell(er.message, "bad"); }
      return;
    }
    if (e.target.id === "toObserve") {
      try { await send("PUT", "api/settings", { mode: "observe" }); binaTell("חזרה למצב צפייה", "ok"); route(true); } catch (er) { binaTell(er.message, "bad"); }
    }
  });
  document.addEventListener("submit", async function (e) {
    var f = e.target.closest("form[data-rule]");
    if (!f) return;
    e.preventDefault();
    var kind = f.getAttribute("data-rule"), value = f.value.value.trim(), note = f.note.value.trim();
    if (kind === "block") {
      var ok = await binaAsk({ title: "לחסום יציאה ל־" + value + "?", body: "אף אפליקציה של הלשכה לא תגיע ליעד הזה.", ok: "חסימה", danger: true, facts: [["יעד", value], ["הערה", note || "—"]] });
      if (!ok) return;
    }
    try { await send("POST", "api/rules", { kind: kind, value: value, note: note }); binaTell(kind === "allow" ? "נוסף לרשימת המותרים" : "היציאה נחסמה", "ok"); route(true); }
    catch (er) { binaTell(er.message, "bad"); }
  });
  document.addEventListener("input", function (e) {
    if (e.target.id !== "q") return;
    S.q = e.target.value;
    clearTimeout(S._qt);
    S._qt = setTimeout(paint, 120);
  });

  function paint() {
    if (S.view === "in") paintInbound();
    else if (S.view === "out") paintOutbound();
    else route(false);
  }

  var routing = 0;
  async function route(refresh) {
    var parts = (location.hash || "#/").replace(/^#\/?/, "").split("/");
    var view = parts[0] || "", arg = decodeURIComponent(parts.slice(1).join("/") || "");
    if (["", "in", "out", "signins", "links", "bans", "net", "herd"].indexOf(view) < 0) view = "";
    var v = VIEWS.filter(function (x) { return x.id === view; })[0] || VIEWS[0];
    var changed = view !== S.view || refresh;
    S.view = view;
    $("viewTitle").textContent = v.title;
    $("viewSub").textContent = v.sub;
    if (NAV && NAV.setActive) NAV.setActive(view || "home");
    if (changed) {
      var my = ++routing;
      if (!S.data.summary) $("view").innerHTML = '<div class="skel">טוען…</div>';
      var html;
      try {
        html = await ({ "": vOverview, "in": vInbound, out: vOutbound, signins: vSignins, links: vLinks, bans: vBans, net: vNet, herd: vHerd }[view])();
      } catch (er) { html = '<div class="callout bad"><div class="txt"><b>המסך לא נטען</b> — ' + esc(er.message || er) + "</div></div>"; }
      if (my !== routing) return;
      $("view").innerHTML = html;
      if (view === "in") paintInbound();
      if (view === "out") paintOutbound();
      markLive();
    }
    if (arg && view === "in") dInbound(arg);
    else if (arg && view === "out") dOutbound(arg);
    else if (!arg) { $("drawer").classList.add("hidden"); $("scrim").classList.add("hidden"); }
  }
  window.addEventListener("hashchange", function () { route(false); });
  setInterval(function () { if (!document.hidden && $("drawer").classList.contains("hidden")) route(true); }, 60000);

  // The console opens an app at a PATH (`#/m/security/out/93.184.216.7` is `/a/security/out/93.184.216.7`,
  // G83), and this screen keeps its views in the hash. So a path that arrives under the app's mount
  // is the view, moved into the hash before the first paint.
  (function () {
    var mount = new URL(document.baseURI).pathname.replace(/\/+$/, "");
    var p = location.pathname;
    var tail = p.indexOf(mount + "/") === 0 ? p.slice(mount.length + 1) : "";
    if (tail) history.replaceState(null, "", mount + "/#/" + tail);
  })();

  paintWin();
  renderNav();
  api("api/summary?hours=" + S.hours).then(function (r) { if (r.ok) { S.data.summary = r.d; renderNav(); } });
  route(true);
})();
