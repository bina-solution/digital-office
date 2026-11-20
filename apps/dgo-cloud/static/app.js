/* DGO Cloud — the one page (DGO-1893): the offer, sign-in, «my DGO», billing, and the admin («ניהול»).
   Plain JS, no build. Every write carries X-DGO: 1; the server answers {ok, data} | {ok:false, error}. */
"use strict";
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
    + "#bina-tell[data-at~=top]{inset-block-start:16px;inset-block-end:auto}#bina-tell[data-at~=end]{inset-inline-start:auto;inset-inline-end:16px}"   // where it covers nothing (place())
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

  // The notice never sits on a control of the page (DGO-618): it keeps its corner while that covers nothing, and
  // otherwise takes the first corner that does — at every frame size, a desktop window of 380 x 260 included,
  // where the bottom corner is where a window keeps its buttons. With no corner free at its full width, the corners
  // again at two thirds and at half of it (a narrower notice fits over a title, beside a window's ✕); with none
  // free at all, the place that covers fewest.
  var CONTROLS = "button,a[href],input:not([type=hidden]),select,textarea,summary,[role=button],[tabindex]:not([tabindex='-1'])";
  function covered(box) {
    var b = box.getBoundingClientRect(), n = 0;
    if (b.width < 2 || b.height < 2) return 0;
    doc.querySelectorAll(CONTROLS).forEach(function (c) {
      var r = c.getBoundingClientRect();     // the cheap test first: on a screen of thousands of rows most are far away
      if (Math.min(b.right, r.right) - Math.max(b.left, r.left) <= 1 || Math.min(b.bottom, r.bottom) - Math.max(b.top, r.top) <= 1) return;
      // inside the notice, in a part of the page made inert (a window the page put over it), or not drawn: not a control here
      if (box.contains(c) || c.closest("[inert]") || (c.checkVisibility && !c.checkVisibility({ checkVisibilityCSS: true }))) return;
      n++;
    });
    return n;
  }
  function put(box, at, w) {
    if (at) box.setAttribute("data-at", at); else box.removeAttribute("data-at");
    box.style.maxWidth = w;
    // a top spot lets go of the bottom, written on the element: a page's own rule that lifts the notice off its bar
    // (`body:has(…) #bina-tell{inset-block-end:…}`) out-ranks the attribute, and the box stretched to the full height
    box.style.insetBlockEnd = at.indexOf("top") < 0 ? "" : "auto";
  }
  function place(box) {
    var best = null;
    ["", "min(280px,calc((100vw - 32px) * .66))", "min(210px,calc((100vw - 32px) * .5))"].some(function (w) {
      return ["", "end", "top", "top end"].some(function (at) {
        put(box, at, w);
        var n = covered(box);
        if (!best || n < best.n) best = { at: at, w: w, n: n };
        return n === 0;
      });
    });
    put(box, best.at, best.w);
  }
  var placing = 0;
  function replace() { var box = doc.getElementById("bina-tell"); if (box && box.firstChild) place(box); }
  window.addEventListener("resize", function () { clearTimeout(placing); placing = setTimeout(replace, 120); });

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
      go.addEventListener("click", function (e) { e.stopPropagation(); n.remove(); replace(); o.act[1](); });
      n.appendChild(go);
    }
    n.addEventListener("click", function () { n.remove(); replace(); });
    box.appendChild(n);
    place(box);
    if (!o.stay) setTimeout(function () { n.remove(); replace(); }, o.ms || (kind === "bad" ? 9000 : 5200));
    return n;
  };
})();
/* @bina-ask:end */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const h = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const S = {me: null, cfg: {}, viewing: null, timer: null};

async function api(method, path, body) {
  const opt = {method, headers: {"X-DGO": "1"}, credentials: "same-origin"};
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch("/api/" + path, opt); } catch (e) { throw new Error("אין חיבור לשרת. בדקו את הרשת ונסו שוב."); }
  let d = {};
  try { d = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok || !d.ok) throw new Error(d.error || "משהו השתבש (" + r.status + ")");
  return d.data;
}
const money = (a) => { a = Number(a || 0); const neg = a < 0; a = Math.abs(a);
  const s = (a % 100 ? (a / 100).toFixed(2) : String(a / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (neg ? "-" : "") + "₪" + s; };
const when = (iso, withTime) => { if (!iso) return "—"; const d = new Date(iso); if (isNaN(d)) return "—";
  return d.toLocaleDateString("he-IL", {day: "numeric", month: "numeric", year: "numeric"}) +
    (withTime ? " " + d.toLocaleTimeString("he-IL", {hour: "2-digit", minute: "2-digit"}) : ""); };
const ago = (iso) => { if (!iso) return "—"; const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 90) return "עכשיו"; if (s < 3600) return "לפני " + Math.round(s / 60) + " דק׳";
  if (s < 86400) return "לפני " + Math.round(s / 3600) + " שע׳"; return when(iso); };
const num = (n) => Number(n || 0).toLocaleString("he-IL");
function count(n, one, many) { return n === 1 ? one : num(n) + " " + many; }
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(t._t); t._t = setTimeout(() => { t.hidden = true; }, 4200); }
function chip(state, label) {
  const k = {active: "ok", claimed: "ok", paid: "ok", ready: "ok", past_due: "wait", pending: "wait", installing: "go",
    booting: "go", ordering: "go", claiming: "go", cancelled: "bad", failed: "bad", suspended: "wait", ended: "",
    disabled: "bad", refunded: "", abandoned: "", destroyed: "", destroying: "wait", live: "ok", test: "wait",
    simulate: "wait", off: "bad", on: "ok"}[state] || "";
  return `<span class="chip ${k}"><span class="dot"></span>${h(label || state)}</span>`;
}
function busy(btn, on) { if (!btn) return; btn.disabled = on; if (on) { btn._t = btn.innerHTML; btn.innerHTML = '<span class="spin" style="width:18px;height:18px;border-width:2px"></span>'; } else if (btn._t) btn.innerHTML = btn._t; }
function stopTimer() { if (S.timer) clearTimeout(S.timer); S.timer = null; }
function view(html) { stopTimer(); $("#drawer").innerHTML = ""; $("#view").innerHTML = html; window.scrollTo(0, 0); }
const GOOGLE = '<svg viewBox="0 0 48 48" aria-hidden="true"><path fill="currentColor" d="M44.5 20H24v8.5h11.8C34.7 33.9 30.1 37 24 37c-7.2 0-13-5.8-13-13s5.8-13 13-13c3.1 0 5.9 1.1 8.1 2.9l6.4-6.4C34.6 4.1 29.6 2 24 2 11.8 2 2 11.8 2 24s9.8 22 22 22c11 0 21-8 21-22 0-1.3-.2-2.7-.5-4z"/></svg>';

// ── the frame ───────────────────────────────────────────────────────────────────────────────────────────────
async function loadMe() {
  const d = await api("GET", "me");
  S.me = d.account; S.cfg = d.config || {}; S.viewing = d.viewing || null;
  nav();
}
function nav() {
  const n = $("#nav");
  if (!S.me) n.innerHTML = `<a class="btn small" href="#/signin">כניסה</a><a class="btn small primary" href="#/signup">להתחיל</a>`;
  else n.innerHTML = `<a class="btn small" href="#/app">הלשכה שלי</a>` + (S.me.admin ? `<a class="btn small" href="#/admin">ניהול</a>` : "") +
    `<button class="btn small" id="logout">יציאה</button>`;
  const lo = $("#logout"); if (lo) lo.onclick = async () => { await api("POST", "auth/logout"); S.me = null; location.hash = "#/"; nav(); };
  $("#banner").innerHTML = S.viewing ? `<div class="banner"><div class="wrap"><b>צפייה בתור ${h(S.viewing.name)} (${h(S.viewing.email)})</b>
    <span class="muted">— רק קריאה, שום שינוי לא נשמר</span><button class="btn small" id="unview">חזרה לחשבון שלי</button></div></div>` : "";
  const uv = $("#unview"); if (uv) uv.onclick = async () => { await api("POST", "view-as/stop"); await loadMe(); location.hash = "#/admin/accounts"; };
}

async function route() {
  // Cardcom sends the buyer back to /pay/return?p=<id>[&failed=1]: the page is this one, the route a hash
  if (location.pathname === "/pay/return") {
    const q = new URLSearchParams(location.search);
    history.replaceState(null, "", "/#/pay/" + (q.get("p") || "") + (q.get("failed") ? "/failed" : ""));
  }
  const parts = (location.hash || "#/").slice(2).split("/");
  const r = parts[0] || "";
  try {
    if (r === "") return landing();
    if (r === "signup") return S.me ? (location.hash = "#/app") : signup();
    if (r === "signin") return S.me ? (location.hash = "#/app") : signin();
    if (r === "forgot") return forgot();
    if (r === "reset") return reset(parts[1]);
    if (r === "verify") return verify(parts[1]);
    if (r === "terms" || r === "privacy") return legal(r);
    if (!S.me) { location.hash = "#/signin"; return; }
    if (r === "app") return app();
    if (r === "pay") return payReturn(parts[1], parts[2] === "failed");
    if (r === "admin" && S.me.admin) return admin(parts[1] || "overview", parts[2]);
    location.hash = "#/app";
  } catch (e) { view(`<main class="wrap"><div class="bad">${h(e.message)}</div></main>`); }
}

// ── the offer ───────────────────────────────────────────────────────────────────────────────────────────────
function landing() {
  const p = (S.cfg.plans || [])[0] || {price_he: "99", credit_he: "24", features: [], server: ""};
  view(`<main class="wrap">
  <section class="hero">
    <h1>הלשכה הדיגיטלית שלך, בענן, בתוך דקה.</h1>
    <p class="lead">מערכת משרדית מלאה על שרת פרטי שרק שלך — מסמכים, מיילים, אוטומציות, צ׳אט, יומן, פגישות ועוזר בינה מלאכותית שעובד בשבילך. נרשמים, משלמים, והלשכה שלך כבר רצה. אנחנו מנהלים, מאבטחים ומעדכנים.</p>
    <div class="cta"><a class="btn primary big" href="#/signup">לפתוח לשכה — ₪${h(p.price_he)} לחודש</a><a class="btn big" href="#/signin">כבר יש לי חשבון</a></div>
  </section>
  <section class="grid g3 steps">
    <div class="step"><b>1</b><h3>נרשמים</h3><p class="muted">עם Google או עם מייל וסיסמה. עשר שניות.</p></div>
    <div class="step"><b>2</b><h3>משלמים</h3><p class="muted">בכרטיס אשראי, בדף המאובטח של Cardcom. חשבונית מס מגיעה למייל.</p></div>
    <div class="step"><b>3</b><h3>הלשכה שלך פתוחה</h3><p class="muted">שרת פרטי, כתובת משלך, תעודת אבטחה — מוכנים מראש, נמסרים לך מיד.</p></div>
  </section>
  <section class="grid g2" style="align-items:start">
    <div class="price">
      <h2>${h(p.name || "DGO Cloud בסיסי")}</h2>
      <div class="amount">₪${h(p.price_he)} <small>לחודש, כולל מע״מ</small></div>
      <ul>${(p.features || []).map((f) => `<li>${h(f)}</li>`).join("")}<li>${h(p.server)}</li></ul>
      <a class="btn primary block big" href="#/signup">להתחיל עכשיו</a>
      <p class="small muted" style="margin-top:10px">₪${h(p.credit_he)} קרדיט בינה מלאכותית מתחדש כל חודש. אפשר לטעון עוד בכל רגע.</p>
    </div>
    <div class="faq">
      <h2>שאלות</h2>
      <details><summary>מה זה בעצם?</summary><p>«הלשכה הדיגיטלית» (DGO) היא מערכת הפעלה למשרד: כל הכלים של העסק במקום אחד, על שרת שלך, עם כניסה אחת. DGO Cloud מקים אותה בשבילך ומנהל אותה.</p></details>
      <details><summary>של מי השרת והמידע?</summary><p>השרת מוקצה לך בלבד, והמידע שלך נשאר עליו. אנחנו מנהלים את השרת (עדכונים, גיבויים, אבטחה) ולא קוראים את התוכן שלך.</p></details>
      <details><summary>איך עובד הקרדיט לבינה מלאכותית?</summary><p>הלשכה שלך כבר מחוברת לנתב המודלים שלנו: DeepSeek, Claude ו-OpenAI. כל שימוש יורד מהקרדיט לפי מחיר הספק. ₪24 בכל חודש כלולים, ואפשר לטעון עוד.</p></details>
      <details><summary>אפשר לבטל?</summary><p>בכל רגע, מהמסך שלך. השרת ממשיך לעבוד עד סוף החודש ששולם, והמידע נשמר עוד 14 יום.</p></details>
    </div>
  </section>
  <footer>DGO Cloud — שירות של בינה סולושנס · <a href="#/terms">תנאי שימוש</a> · <a href="#/privacy">פרטיות</a> · <a href="mailto:person12@example.com">person12@example.com</a></footer>
  </main>`);
}

function legal(which) {
  const t = which === "terms" ? `<h1>תנאי שימוש</h1>
    <p>DGO Cloud הוא שירות מנוי חודשי של בינה סולושנס: שרת פרטי עם הלשכה הדיגיטלית מותקנת ומנוהלת, וקרדיט חודשי לשימוש במודלים של בינה מלאכותית דרך הנתב שלנו.</p>
    <p>המנוי מתחדש כל חודש ומחויב בכרטיס האשראי שנשמר אצל Cardcom. אפשר לבטל בכל רגע; השירות נמשך עד סוף התקופה ששולמה. חיוב שנכשל ינוסה שוב, ואם לא יצליח השרת יושהה והמידע יישמר 14 יום.</p>
    <p>אסור להשתמש בשירות לפעילות בלתי חוקית, לשליחת דואר זבל, להתחזות או לפגיעה באחרים. שימוש כזה יביא להשעיה מיידית.</p>
    <p>קרדיט הבינה המלאכותית של המנוי תקף לחודש שבו ניתן. קרדיט שנטען בתשלום נפרד אינו פג.</p>` :
    `<h1>מדיניות פרטיות</h1>
    <p>אנחנו שומרים את מה שצריך כדי לתת את השירות: שם, מייל, פרטי חשבונית, היסטוריית תשלומים (מספר עסקה ו-4 ספרות אחרונות — את פרטי הכרטיס שומרת Cardcom), ורישום שימוש במודלים (איזה מודל, כמה טוקנים, כמה עלה).</p>
    <p>את תוכן השיחות עם המודלים אנחנו לא שומרים; הן עוברות דרך הנתב לספק המודל שבחרת (DeepSeek, Anthropic או OpenAI), לפי תנאי הפרטיות שלו.</p>
    <p>המידע שבלשכה שלך נשאר על השרת שלך. לבקשות בנושא פרטיות: person12@example.com.</p>`;
  view(`<main class="wrap"><div class="sheet" style="max-width:760px;margin:auto">${t}<p class="small muted">עודכן: 15.11.2026</p></div></main>`);
}

// ── signing in ──────────────────────────────────────────────────────────────────────────────────────────────
function googleBtn() { return S.cfg.google ? `<a class="btn block gbtn" href="/api/auth/google">${GOOGLE}המשך עם Google</a><p class="muted small" style="text-align:center;margin:12px 0">או</p>` : ""; }
function signup() {
  view(`<main class="wrap"><div class="sheet narrow"><h2>פותחים חשבון</h2>${googleBtn()}
    <form id="f"><label for="n">שם</label><input id="n" autocomplete="name" required>
    <label for="e">מייל</label><input id="e" type="email" autocomplete="email" required>
    <label for="p">סיסמה (לפחות 8 תווים)</label><input id="p" type="password" autocomplete="new-password" minlength="8" required>
    <div class="err" id="err"></div><button class="btn primary block">ליצור חשבון</button></form>
    <p class="small muted" style="margin-top:12px">יש לך חשבון? <a href="#/signin">כניסה</a>. ההרשמה היא הסכמה ל<a href="#/terms">תנאי השימוש</a>.</p></div></main>`);
  $("#f").onsubmit = async (ev) => { ev.preventDefault(); const b = ev.submitter; busy(b, true);
    try { await api("POST", "auth/signup", {name: $("#n").value, email: $("#e").value, password: $("#p").value}); await loadMe(); location.hash = "#/app"; }
    catch (e) { $("#err").textContent = e.message; } finally { busy(b, false); } };
}
function signin() {
  const bad = /error=google/.test(location.hash) ? `<div class="bad" style="margin-bottom:12px">הכניסה עם Google לא הצליחה. נסו שוב או היכנסו עם מייל.</div>` : "";
  view(`<main class="wrap"><div class="sheet narrow"><h2>כניסה</h2>${bad}${googleBtn()}
    <form id="f"><label for="e">מייל</label><input id="e" type="email" autocomplete="email" required>
    <label for="p">סיסמה</label><input id="p" type="password" autocomplete="current-password" required>
    <div class="err" id="err"></div><button class="btn primary block">להיכנס</button></form>
    <p class="small" style="margin-top:12px"><a href="#/forgot">שכחתי סיסמה</a> · <a href="#/signup">חשבון חדש</a></p></div></main>`);
  $("#f").onsubmit = async (ev) => { ev.preventDefault(); const b = ev.submitter; busy(b, true);
    try { await api("POST", "auth/login", {email: $("#e").value, password: $("#p").value}); await loadMe(); location.hash = S.me.admin ? "#/admin" : "#/app"; }
    catch (e) { $("#err").textContent = e.message; } finally { busy(b, false); } };
}
function forgot() {
  view(`<main class="wrap"><div class="sheet narrow"><h2>סיסמה חדשה</h2><p class="muted">נשלח לך קישור לבחירת סיסמה חדשה.</p>
    <form id="f"><label for="e">מייל</label><input id="e" type="email" required><div class="err" id="err"></div>
    <button class="btn primary block">לשלוח קישור</button></form></div></main>`);
  $("#f").onsubmit = async (ev) => { ev.preventDefault(); const b = ev.submitter; busy(b, true);
    try { await api("POST", "auth/forgot", {email: $("#e").value}); $("#f").outerHTML = `<div class="note">אם יש חשבון עם המייל הזה, הקישור כבר בדרך (תקף שעתיים).</div>`; }
    catch (e) { $("#err").textContent = e.message; } finally { busy(b, false); } };
}
function reset(tok) {
  view(`<main class="wrap"><div class="sheet narrow"><h2>בוחרים סיסמה חדשה</h2><form id="f">
    <label for="p">סיסמה חדשה</label><input id="p" type="password" autocomplete="new-password" minlength="8" required>
    <div class="err" id="err"></div><button class="btn primary block">לשמור ולהיכנס</button></form></div></main>`);
  $("#f").onsubmit = async (ev) => { ev.preventDefault(); const b = ev.submitter; busy(b, true);
    try { await api("POST", "auth/reset", {token: tok, password: $("#p").value}); await loadMe(); location.hash = "#/app"; }
    catch (e) { $("#err").textContent = e.message; } finally { busy(b, false); } };
}
async function verify(tok) {
  view(`<main class="wrap"><div class="sheet narrow"><p><span class="spin"></span> מאשרים את המייל…</p></div></main>`);
  try { await api("POST", "auth/verify", {token: tok}); $("#view").innerHTML = `<main class="wrap"><div class="sheet narrow"><h2>המייל אושר ✓</h2><a class="btn primary" href="#/app">להמשיך</a></div></main>`; }
  catch (e) { $("#view").innerHTML = `<main class="wrap"><div class="sheet narrow"><div class="bad">${h(e.message)}</div></div></main>`; }
}

// ── «my DGO» ────────────────────────────────────────────────────────────────────────────────────────────────
async function app() {
  view(`<main class="wrap" id="dash"><p><span class="spin"></span></p></main>`);
  await drawDash();
}
async function drawDash() {
  stopTimer();
  let d;
  try { d = await api("GET", "dashboard"); } catch (e) { $("#dash").innerHTML = `<div class="bad">${h(e.message)}</div>`; return; }
  const sub = d.subscription, node = d.node;
  const paying = sub && ["active", "past_due", "cancelled"].includes(sub.status);
  let html = `<div class="row between" style="margin-bottom:14px"><h1 style="font-size:26px;margin:0">שלום ${h(d.account.name)}</h1>${sub ? chip(sub.status, sub.status_he) : ""}</div>`;
  if (!paying) html += buyCard(d);
  else {
    html += `<div class="grid g2">${dgoCard(d)}${aiCard(d)}${billCard(d)}${accountCard(d)}</div>`;
  }
  $("#dash").innerHTML = html;
  wireDash(d);
  // while the server is being handed over, keep the screen current by itself
  const moving = paying && (d.waiting || (node && ["claiming", "ready"].includes(node.state)));
  if (moving) S.timer = setTimeout(drawDash, 3000);
}
function buyCard(d) {
  const p = (S.cfg.plans || [])[0] || {};
  const off = S.cfg.payments === "off";
  const a = d.account;
  return `<div class="grid g2" style="align-items:start"><div class="price">
    <h2>${h(p.name)}</h2><div class="amount">₪${h(p.price_he)} <small>לחודש, כולל מע״מ</small></div>
    <ul>${(p.features || []).map((f) => `<li>${h(f)}</li>`).join("")}</ul>
    ${off ? `<div class="warn">התשלום נפתח בקרוב. נעדכן אותך במייל.</div>` : `<button class="btn primary block big" id="buy">לתשלום מאובטח — ₪${h(p.price_he)}</button>`}
    <p class="small muted" style="margin-top:10px">התשלום בדף המאובטח של Cardcom. חשבונית מס/קבלה נשלחת למייל.${S.cfg.payments === "test" || S.cfg.payments === "simulate" ? " <b>מצב בדיקה — אין חיוב אמיתי.</b>" : ""}</p>
    <div class="err" id="err"></div></div>
    <div class="card"><h3>פרטים לחשבונית</h3><p class="small muted">לא חובה. עסק? מלאו שם עסק ומספר עוסק כדי שהחשבונית תצא עליו.</p>
    <form id="acc"><label for="co">שם העסק</label><input id="co" value="${h(a.company)}">
    <label for="tax">ח.פ. / עוסק מורשה</label><input id="tax" inputmode="numeric" value="${h(a.tax_id)}">
    <label for="ph">טלפון</label><input id="ph" type="tel" dir="ltr" value="${h(a.phone)}">
    <div class="err" id="err2"></div><button class="btn small">לשמור</button></form></div></div>`;
}
function dgoCard(d) {
  const n = d.node;
  let body;
  if (!n) body = `<p><span class="spin"></span> מכינים לך שרת. זה לוקח רגע — המסך יתעדכן לבד.</p>
    <p class="small muted">אם כל השרתים המוכנים נלקחו ממש עכשיו, הקמת שרת חדש לוקחת עד 20 דקות. נשלח לך מייל.</p>`;
  else if (n.state === "claiming" || n.state === "ready") body = `<p><span class="spin"></span> מוסרים לך את הלשכה — עוד כמה שניות…</p>`;
  else if (n.state === "suspended") body = `<div class="warn">הלשכה מושהית (המנוי לא בתוקף). המידע שמור. חידוש המנוי מפעיל אותה מחדש.</div>`;
  else {
    body = `<dl class="facts"><dt>הכתובת</dt><dd><span class="mono">${h(n.domain)}</span></dd><dt>מצב</dt><dd>${chip(n.state, n.state_he)}</dd>
      <dt>שם משתמש</dt><dd><span class="mono">${h(n.admin_user || d.account.email)}</span></dd><dt>נפתחה</dt><dd>${when(n.claimed_at)}</dd></dl>
      <div class="row" style="margin-top:14px"><a class="btn primary" href="${h(n.console)}" target="_blank" rel="noopener">לפתוח את הלשכה</a>
      ${n.password_waiting ? `<button class="btn" id="reveal">להציג את הסיסמה (פעם אחת)</button>` : `<button class="btn" id="newpw">סיסמה חדשה ללשכה</button>`}</div>
      <div id="pw"></div>`;
  }
  return `<div class="card" style="grid-column:1/-1"><h3>הלשכה שלי</h3>${body}</div>`;
}
function aiCard(d) {
  const w = d.wallet;
  const rows = (d.usage || []).map((u) => `<tr><td class="ltr">${h(u.model)}</td><td>${num(u.calls)}</td><td>${num((u.tin || 0) + (u.tout || 0))}</td><td>${h(money(u.cost))}</td></tr>`).join("");
  return `<div class="card"><h3>בינה מלאכותית</h3>
    <div class="kpi">${h(money(w.total))} <small>יתרה</small></div>
    <p class="small muted">מהחודש: ${h(money(w.plan))} · נטען: ${h(money(w.topup))}</p>
    ${rows ? `<div class="scroll"><table><thead><tr><th>מודל</th><th>קריאות</th><th>טוקנים</th><th>עלות</th></tr></thead><tbody>${rows}</tbody></table></div>` : `<p class="muted small">עוד לא היה שימוש החודש. העוזר בלשכה שלך כבר מחובר.</p>`}
    <p class="small" style="margin-top:10px">טעינת קרדיט (לא פג):</p>
    <div class="row">${(d.topups || []).map((t) => `<button class="btn small" data-topup="${t.amount}">₪${h(t.amount_he)}</button>`).join("")}</div>
    <details class="small" style="margin-top:12px"><summary>איך זה מחובר?</summary><p class="muted">הלשכה שלך פונה לנתב בכתובת <span class="mono">${h(d.llm_url)}</span> עם מפתח משלה, לכל המודלים: DeepSeek, Claude, OpenAI. המחיר הוא מחיר הספק, והוא יורד מהיתרה.</p></details>
    <div class="err" id="errai"></div></div>`;
}
function billCard(d) {
  const s = d.subscription;
  // rows, not a table: a narrow card never scrolls sideways
  const pays = (d.payments || []).map((p) => `<div class="pay"><div><b>${h(money(p.amount))}</b> · ${h(p.kind_he)}<br><span class="small muted">${when(p.paid_at || p.created_at)}</span></div>
    <div class="row">${chip(p.status, p.status_he)}${p.doc_url ? `<a class="small" href="${h(p.doc_url)}" target="_blank" rel="noopener">${h(p.doc_number || "חשבונית")}</a>` : (p.doc_number ? `<span class="small muted">${h(p.doc_number)}</span>` : "")}</div></div>`).join("");
  let state = "";
  if (s.status === "past_due") state = `<div class="warn">החיוב האחרון נכשל${s.last_error ? " (" + h(s.last_error) + ")" : ""}. ננסה שוב ב-${when(s.next_charge_at)}.
    <div style="margin-top:8px"><button class="btn small primary" id="paynow">לשלם עכשיו בכרטיס אחר</button></div></div>`;
  if (s.cancel_at_end) state = `<div class="warn">המנוי בוטל. הלשכה פעילה עד ${when(s.period_end)}.</div>`;
  return `<div class="card"><h3>מנוי וחיובים</h3>${state}
    <dl class="facts"><dt>תוכנית</dt><dd>${h(s.plan_name)} · ₪${h(s.price_he)} לחודש</dd>
    <dt>${s.cancel_at_end ? "בתוקף עד" : "החיוב הבא"}</dt><dd>${when(s.cancel_at_end ? s.period_end : s.next_charge_at)}</dd>
    <dt>כרטיס</dt><dd><span class="ltr">•••• ${h(s.card_last4 || "—")}</span></dd></dl>
    ${pays ? `<div style="margin-top:12px">${pays}</div>` : ""}
    <div class="row" style="margin-top:12px">${s.cancel_at_end ? `<button class="btn" id="resume">לחדש את המנוי</button>` : `<button class="btn danger small" id="cancel">לבטל את המנוי</button>`}</div>
    <div class="err" id="errbill"></div></div>`;
}
function accountCard(d) {
  const a = d.account;
  return `<div class="card"><h3>החשבון</h3><form id="acc">
    <label for="nm">שם</label><input id="nm" value="${h(a.name)}">
    <label for="co">שם העסק (לחשבונית)</label><input id="co" value="${h(a.company)}">
    <label for="tax">ח.פ. / עוסק מורשה</label><input id="tax" inputmode="numeric" value="${h(a.tax_id)}">
    <label for="ph">טלפון</label><input id="ph" type="tel" dir="ltr" value="${h(a.phone)}">
    <div class="err" id="err2"></div><button class="btn small">לשמור</button></form>
    <p class="small muted" style="margin-top:10px">${h(a.email)} ${a.proven ? "· מאומת ✓" : `· <a href="#" id="again">לשלוח שוב אישור מייל</a>`}</p></div>`;
}
function wireDash(d) {
  const buy = $("#buy");
  if (buy) buy.onclick = async () => { busy(buy, true);
    try { const r = await api("POST", "checkout", {plan: "basic"}); location.href = r.url; }
    catch (e) { $("#err").textContent = e.message; busy(buy, false); } };
  const acc = $("#acc");
  if (acc) acc.onsubmit = async (ev) => { ev.preventDefault(); const body = {company: $("#co").value, tax_id: $("#tax").value, phone: $("#ph").value};
    if ($("#nm")) body.name = $("#nm").value;
    try { await api("POST", "account", body); toast("נשמר"); } catch (e) { $("#err2").textContent = e.message; } };
  const again = $("#again");
  if (again) again.onclick = async (ev) => { ev.preventDefault(); const r = await api("POST", "account/verify-again"); toast(r.sent ? "שלחנו שוב" : "המייל לא נשלח — נסו מאוחר יותר"); };
  const rv = $("#reveal");
  if (rv) rv.onclick = async () => { busy(rv, true);
    try { const r = await api("POST", "my-dgo/reveal"); $("#pw").innerHTML = `<p class="small" style="margin-top:12px">שם משתמש: <span class="mono">${h(r.user)}</span></p><div class="secret">${h(r.password)}</div>
      <p class="small muted">שמרו אותה עכשיו (מנהל סיסמאות). היא לא תוצג שוב — אפשר תמיד לבקש סיסמה חדשה.</p>`; rv.remove(); }
    catch (e) { toast(e.message); busy(rv, false); } };
  const np = $("#newpw");
  if (np) np.onclick = async () => { if (!await binaAsk({ title: "ליצור סיסמה חדשה ללשכה?", body: "הסיסמה הנוכחית תפסיק לעבוד.", ok: "סיסמה חדשה", danger: true })) return; busy(np, true);
    try { await api("POST", "my-dgo/new-password"); toast("הסיסמה החדשה תופיע כאן בעוד כמה שניות"); setTimeout(drawDash, 6000); } catch (e) { toast(e.message); busy(np, false); } };
  $$("[data-topup]").forEach((b) => { b.onclick = async () => { busy(b, true);
    try { const r = await api("POST", "topup", {amount: Number(b.dataset.topup)}); location.href = r.url; } catch (e) { $("#errai").textContent = e.message; busy(b, false); } }; });
  const cancel = $("#cancel");
  if (cancel) cancel.onclick = async () => { if (!await binaAsk({ title: "לבטל את המנוי?", body: "הלשכה תמשיך לעבוד עד סוף החודש ששולם, והמידע יישמר עוד 14 יום אחרי.", ok: "ביטול המנוי", danger: true })) return;
    try { await api("POST", "subscription/cancel"); drawDash(); } catch (e) { $("#errbill").textContent = e.message; } };
  const paynow = $("#paynow");
  if (paynow) paynow.onclick = async () => { busy(paynow, true);
    try { const r = await api("POST", "subscription/pay-now"); location.href = r.url; } catch (e) { $("#errbill").textContent = e.message; busy(paynow, false); } };
  const resume = $("#resume");
  if (resume) resume.onclick = async () => { try { await api("POST", "subscription/resume"); drawDash(); } catch (e) { $("#errbill").textContent = e.message; } };
}

// ── back from Cardcom ───────────────────────────────────────────────────────────────────────────────────────
async function payReturn(pid, failed) {
  view(`<main class="wrap"><div class="sheet narrow" id="pay"><p><span class="spin"></span> מאמתים את התשלום מול Cardcom…</p></div></main>`);
  const started = Date.now();
  const tick = async () => {
    let p;
    try { p = await api("POST", `pay/${pid}/verify`); } catch (e) { $("#pay").innerHTML = `<div class="bad">${h(e.message)}</div><a class="btn" href="#/app">חזרה</a>`; return; }
    if (p.status === "paid") {
      $("#pay").innerHTML = `<h2>התשלום התקבל ✓</h2><p>${p.kind === "topup" ? "הקרדיט נטען." : "הלשכה שלך נמסרת אליך עכשיו."}</p>`;
      setTimeout(() => { location.hash = "#/app"; }, 1200); return;
    }
    if (p.status === "failed" || (failed && Date.now() - started > 8000)) {
      $("#pay").innerHTML = `<h2>התשלום לא הושלם</h2><p class="muted">${h(p.error || "לא חויבת.")}</p><a class="btn primary" href="#/app">לנסות שוב</a>`; return;
    }
    if (Date.now() - started > 180000) { $("#pay").innerHTML = `<div class="warn">Cardcom עוד לא אישרו. אם חויבת — הלשכה תיפתח לבד בדקות הקרובות.</div><a class="btn" href="#/app">למסך שלי</a>`; return; }
    S.timer = setTimeout(tick, 2000);
  };
  tick();
}

// ── the admin («ניהול») ─────────────────────────────────────────────────────────────────────────────────────
const TABS = [["overview", "סקירה"], ["accounts", "לקוחות"], ["nodes", "שרתים"], ["payments", "תשלומים"], ["prices", "מודלים ומחירים"], ["audit", "יומן"]];
async function admin(tab, arg) {
  view(`<main class="wrap"><div class="tabs">${TABS.map(([k, l]) => `<button data-tab="${k}" class="${k === tab ? "on" : ""}">${l}</button>`).join("")}</div><div id="adm"><p><span class="spin"></span></p></div></main>`);
  $$("[data-tab]").forEach((b) => { b.onclick = () => { location.hash = "#/admin/" + b.dataset.tab; }; });
  try { await ({overview: aOverview, accounts: aAccounts, nodes: aNodes, payments: aPayments, prices: aPrices, audit: aAudit}[tab] || aOverview)(arg); }
  catch (e) { $("#adm").innerHTML = `<div class="bad">${h(e.message)}</div>`; }
}
function auditRows(rows) {
  return `<div class="scroll"><table><thead><tr><th>מתי</th><th>מי</th><th>מה</th><th>על מה</th><th>פרטים</th></tr></thead><tbody>${rows.map((r) =>
    `<tr><td>${when(r.at, true)}</td><td class="ltr">${h(r.actor)}</td><td class="ltr">${h(r.action)}</td><td class="ltr">${h(r.target)}</td><td class="mono small">${h(r.detail === "{}" ? "" : r.detail)}</td></tr>`).join("")}</tbody></table></div>`;
}
async function aOverview() {
  const o = await api("GET", "admin/overview");
  const c = o.config;
  const warn = [];
  if (c.payments === "off") warn.push("התשלומים כבויים: חסרים CARDCOM_TERMINAL ו-CARDCOM_API_NAME.");
  if (c.payments === "simulate") warn.push("תשלומים בסימולציה (CARDCOM_SIMULATE=1) — אף כרטיס לא מחויב.");
  if (c.payments === "test") warn.push("Cardcom במסוף בדיקות (1000) — אין חיוב אמיתי.");
  if (c.compute === "off") warn.push("ספק השרתים לא מוגדר: חסר HOSTINGER_API_TOKEN.");
  if (c.compute !== "off" && c.compute !== "simulate" && !c.ops_key) warn.push("חסר DGOCLOUD_OPS_KEY — המאגר לא יקנה שרתים בלעדיו.");
  Object.entries(c.llm_providers).forEach(([p, ok]) => { if (!ok) warn.push(`הנתב: אין מפתח ל-${p}.`); });
  if (!c.google) warn.push("כניסה עם Google כבויה (GOOGLE_OAUTH_CLIENT_ID/SECRET).");
  if (o.to_refund) warn.push(o.to_refund === 1 ? "תשלום אחד מסומן להחזר ללקוח (כפול או אחרי ביטול) — בלשונית תשלומים." : `${num(o.to_refund)} תשלומים מסומנים להחזר ללקוח — בלשונית תשלומים.`);
  if (o.pool.paused) warn.push("קניית שרתים מושהית" + (o.pool_paused_why ? " — " + o.pool_paused_why : "") + ".");
  if (o.waiting) warn.push(o.waiting === 1 ? "לקוח אחד שילם ומחכה לשרת." : `${num(o.waiting)} לקוחות שילמו ומחכים לשרת.`);
  const n = o.nodes;
  $("#adm").innerHTML = `
  ${warn.length ? `<div class="warn" style="margin-bottom:14px"><b>לטיפול:</b><ul style="margin:6px 0 0">${warn.map((w) => `<li>${h(w)}</li>`).join("")}</ul></div>` : ""}
  <div class="grid g3">
    <div class="card"><p class="muted small">הכנסה חודשית חוזרת</p><div class="kpi">${h(money(o.mrr))}</div><p class="small muted">${count(o.subs.active || 0, "מנוי פעיל אחד", "מנויים פעילים")}${o.subs.past_due ? " · " + count(o.subs.past_due, "אחד בפיגור", "בפיגור") : ""}</p></div>
    <div class="card"><p class="muted small">נגבה החודש</p><div class="kpi">${h(money(o.revenue_month))}</div><p class="small muted">${count(o.payments_month, "תשלום אחד", "תשלומים")}</p></div>
    <div class="card"><p class="muted small">לקוחות רשומים</p><div class="kpi">${num(o.accounts)}</div></div>
    <div class="card"><p class="muted small">מאגר שרתים מוכנים</p><div class="kpi">${num(n.ready || 0)} <small>מתוך יעד ${num(o.pool.target)}${o.pool.paused ? " · מושהה" : ""}</small></div>
      <p class="small muted">בהקמה: ${num((n.ordering || 0) + (n.booting || 0) + (n.installing || 0))} · פעילים: ${num(n.claimed || 0)} · תקלה: ${num(n.failed || 0)}</p></div>
    <div class="card"><p class="muted small">בינה מלאכותית החודש</p><div class="kpi">${h(o.llm_month.charged_he === "0" ? "₪0" : "₪" + o.llm_month.charged_he)}</div><p class="small muted">${count(o.llm_month.calls, "קריאה אחת", "קריאות")} · עלות לספקים $${h(o.llm_month.cost_usd)}</p></div>
    <div class="card"><p class="muted small">הגדרות</p><div class="row">${chip(c.payments, "תשלומים: " + c.payments)}${chip(c.compute === "off" ? "off" : "on", "שרתים: " + c.compute)}${chip(c.google ? "on" : "off", "Google")}</div>
      <p class="small muted" style="margin-top:8px">אזור: <span class="mono">${h(c.zone)}</span></p></div>
  </div>
  <h3 style="margin-top:20px">אחרון ביומן</h3>${auditRows(o.audit.slice(0, 15))}`;
}
async function aAccounts(arg) {
  $("#adm").innerHTML = `<div class="row" style="margin-bottom:12px"><input id="q" placeholder="חיפוש לפי מייל, שם או עסק" style="max-width:360px"></div><div id="list"></div>`;
  const draw = async () => {
    const rows = await api("GET", "admin/accounts?q=" + encodeURIComponent($("#q").value));
    $("#list").innerHTML = `<div class="scroll"><table><thead><tr><th>לקוח</th><th>מנוי</th><th>לשכה</th><th>יתרת AI</th><th class="hide-sm">נראה</th></tr></thead><tbody>${rows.map((a) =>
      `<tr class="click" data-id="${a.id}"><td><b>${h(a.name)}</b>${a.admin ? " " + chip("on", "מנהל") : ""}${a.status === "disabled" ? " " + chip("disabled", "מושבת") : ""}<br><span class="small muted ltr">${h(a.email)}</span>${a.company ? `<br><span class="small">${h(a.company)}</span>` : ""}</td>
      <td>${a.subscription ? chip(a.subscription.status, a.subscription.status_he) : '<span class="muted">—</span>'}</td><td>${a.node ? chip(a.node.state, a.node.state_he) + `<br><span class="small mono">${h(a.node.name)}</span>` : '<span class="muted">—</span>'}</td>
      <td>₪${h(a.balance_he)}</td><td class="hide-sm">${ago(a.last_seen)}</td></tr>`).join("")}</tbody></table></div>${rows.length ? "" : '<p class="muted">אין תוצאות.</p>'}`;
    $$("tr[data-id]").forEach((tr) => { tr.onclick = () => accountDrawer(Number(tr.dataset.id)); });
  };
  let t; $("#q").oninput = () => { clearTimeout(t); t = setTimeout(draw, 250); };
  await draw();
  if (arg) accountDrawer(Number(arg));
}
async function accountDrawer(id) {
  const d = await api("GET", "admin/account/" + id);
  const a = d.account;
  const sub = d.subscriptions[0];
  const sec = (t, body) => `<div class="card" style="margin-top:12px"><h3>${t}</h3>${body}</div>`;
  $("#drawer").innerHTML = `<div class="drawer" id="dr"><div>
    <div class="row between"><div><h2 style="margin:0">${h(a.name)}</h2><span class="ltr muted">${h(a.email)}</span></div><button class="btn small" id="close">סגירה</button></div>
    <div class="row" style="margin:10px 0">${chip(a.status, a.status === "active" ? "פעיל" : "מושבת")}${a.google ? chip("on", "Google") : ""}${a.proven ? chip("ok", "מייל מאומת") : chip("pending", "מייל לא מאומת")}${a.admin ? chip("on", "מנהל") : ""}</div>
    <dl class="facts small"><dt>נרשם</dt><dd>${when(a.created_at, true)}</dd><dt>נראה</dt><dd>${ago(a.last_seen)} · <span class="ltr">${h(a.last_ip)}</span></dd><dt>עסק</dt><dd>${h(a.company || "—")} ${a.tax_id ? "· " + h(a.tax_id) : ""}</dd><dt>טלפון</dt><dd class="ltr">${h(a.phone || "—")}</dd></dl>
    <div class="row" style="margin-top:12px"><button class="btn small" id="viewas">לצפות בתור</button><button class="btn small" id="credit">זיכוי AI</button>
      <button class="btn small ${a.status === "active" ? "danger" : ""}" id="status">${a.status === "active" ? "להשבית" : "להפעיל"}</button>
      <button class="btn small" id="mkadmin">${a.admin ? "להסיר מנהל" : "לעשות מנהל"}</button>
      ${sub && ["active", "past_due"].includes(sub.status) ? `<button class="btn small danger" id="cancelsub">לבטל מנוי</button>` : ""}<button class="btn small" id="mkkey">מפתח נתב</button></div>
    <div id="dmsg"></div>
    ${sec("מנויים", d.subscriptions.length ? `<div class="scroll"><table><tr><th>#</th><th>מצב</th><th>תקופה</th><th>עד</th><th>כרטיס</th></tr>${d.subscriptions.map((s) => `<tr><td>${s.id}</td><td>${chip(s.status, s.status_he)}${s.cancel_at_end ? " (בוטל)" : ""}</td><td>${num(s.period)}</td><td>${when(s.period_end)}</td><td class="ltr">${h(s.card_last4)}</td></tr>`).join("")}</table></div>` : '<p class="muted">אין.</p>')}
    ${sec("שרתים", d.nodes.length ? d.nodes.map((n) => `<div style="margin-bottom:10px"><div class="row">${chip(n.state, n.state_he)}<b class="mono">${h(n.name)}</b><span class="ltr small">${h(n.ip)}</span></div><p class="small muted">${h(n.progress)} ${n.last_error ? `· <span style="color:var(--plum)">${h(n.last_error)}</span>` : ""}</p>${n.console ? `<a class="small" href="${h(n.console)}" target="_blank" rel="noopener">${h(n.console)}</a>` : ""}</div>`).join("") : '<p class="muted">אין.</p>')}
    ${sec("תשלומים", d.payments.length ? `<div class="scroll"><table><tr><th>מתי</th><th>מה</th><th>סכום</th><th>מצב</th><th>מסמך</th></tr>${d.payments.map((p) => `<tr><td>${when(p.paid_at || p.created_at)}</td><td>${h(p.kind_he)}</td><td>${h(money(p.amount))}</td><td>${chip(p.status, p.status_he)}</td><td>${h(p.doc_number)}</td></tr>`).join("")}</table></div>` : '<p class="muted">אין.</p>')}
    ${sec("ארנק AI", `<p>יתרה: <b>${h(money(d.balance.total))}</b> (חודש ${h(money(d.balance.plan))} · נטען ${h(money(d.balance.topup))})</p><div class="scroll"><table><tr><th>מתי</th><th>סוג</th><th>סכום</th><th>הערה</th></tr>${d.wallet.slice(0, 40).map((w) => `<tr><td>${when(w.created_at, true)}</td><td>${h(w.kind)}/${h(w.bucket)}</td><td>${h(money(w.delta))}</td><td>${h(w.note)}</td></tr>`).join("")}</table></div>`)}
    ${sec("שימוש במודלים", d.usage.length ? `<table><tr><th>מודל</th><th>קריאות</th><th>טוקנים</th><th>חויב</th><th>עלות $</th></tr>${d.usage.map((u) => `<tr><td class="ltr">${h(u.model)}</td><td>${num(u.calls)}</td><td>${num((u.tin || 0) + (u.tout || 0))}</td><td>${h(money(u.cost))}</td><td>${(Number(u.usd || 0) / 1e6).toFixed(3)}</td></tr>`).join("")}</table>` : '<p class="muted">אין.</p>')}
    ${sec("יומן", auditRows(d.audit))}
  </div></div>`;
  const msg = (t, bad) => { $("#dmsg").innerHTML = `<div class="${bad ? "bad" : "note"}" style="margin-top:10px">${h(t)}</div>`; };
  $("#close").onclick = () => { $("#drawer").innerHTML = ""; };
  $("#dr").onclick = (ev) => { if (ev.target.id === "dr") $("#drawer").innerHTML = ""; };
  $("#viewas").onclick = async () => { try { await api("POST", "admin/view-as", {account: id}); await loadMe(); location.hash = "#/app"; } catch (e) { msg(e.message, 1); } };
  $("#credit").onclick = async () => { const v = await binaAsk({ title: "זיכוי AI", ok: "המשך", input: { label: "כמה ₪ לזכות (מינוס לחיוב)", value: "10" } }); if (!v) return;
    const note = (await binaAsk({ title: "סיבת הזיכוי", ok: "זיכוי", input: { label: "סיבה", value: "זיכוי שירות" } })) || "";
    try { await api("POST", `admin/account/${id}/credit`, {amount: Number(v), note}); accountDrawer(id); } catch (e) { msg(e.message, 1); } };
  $("#status").onclick = async () => { if (!await binaAsk(a.status === "active"
      ? { title: "להשבית את החשבון?", body: "הוא יוצא מכל המכשירים.", ok: "השבתה", danger: true }
      : { title: "להפעיל את החשבון?", ok: "הפעלה" })) return;
    try { await api("POST", `admin/account/${id}/status`, {status: a.status === "active" ? "disabled" : "active"}); accountDrawer(id); } catch (e) { msg(e.message, 1); } };
  $("#mkadmin").onclick = async () => { try { await api("POST", `admin/account/${id}/admin`, {admin: !a.admin}); accountDrawer(id); } catch (e) { msg(e.message, 1); } };
  const cs = $("#cancelsub"); if (cs) cs.onclick = async () => { if (!await binaAsk({ title: "לבטל את המנוי של הלקוח בסוף התקופה?", ok: "ביטול המנוי", danger: true })) return;
    try { await api("POST", `admin/account/${id}/cancel`); accountDrawer(id); } catch (e) { msg(e.message, 1); } };
  $("#mkkey").onclick = async () => { try { const r = await api("POST", "admin/keys/new", {account: id, name: "admin"}); $("#dmsg").innerHTML = `<div class="note" style="margin-top:10px">מפתח לנתב (מוצג פעם אחת):<div class="secret" style="font-size:14px">${h(r.key)}</div></div>`; } catch (e) { msg(e.message, 1); } };
}
async function aNodes() {
  const [rows, o] = await Promise.all([api("GET", "admin/nodes"), api("GET", "admin/overview")]);
  const health = (x) => { const hh = x.health || {}; if (!Object.keys(hh).length) return "—";
    // a node writes this: never trust its shape
    const sick = Array.isArray(hh.unhealthy) ? hh.unhealthy.map(String) : (hh.unhealthy ? [String(hh.unhealthy)] : []);
    return `${count(Number(hh.containers) || 0, "קונטיינר אחד", "קונטיינרים")}${sick.length ? ` · <span style="color:var(--plum)">${h(sick.join(", "))}</span>` : ""} · דיסק ${h(hh.disk_free_gb)}GB · RAM ${num(hh.mem_free_mb)}MB`; };
  $("#adm").innerHTML = `<div class="card" style="margin-bottom:12px"><h3>המאגר</h3><div class="row">
    <label for="ps" style="margin:0">שרתים מוכנים מראש:</label><input id="ps" type="number" min="0" max="10" value="${o.pool.target}" style="width:90px">
    <button class="btn small" id="savepool">לשמור</button><button class="btn small" id="pause">${o.pool.paused ? "להמשיך לקנות" : "לעצור קנייה"}</button>
    <button class="btn small primary" id="order">לקנות שרת עכשיו</button></div>
    <p class="small muted" style="margin-top:8px">כל שרת במאגר הוא שרת שנקנה ומחכה ללקוח — זה מה שהופך את ההקמה לשניות. ${o.config.compute === "off" ? "<b>ספק השרתים לא מוגדר.</b>" : ""}</p><div class="err" id="perr"></div></div>
  <div class="scroll"><table><thead><tr><th>שרת</th><th>מצב</th><th>לקוח</th><th class="hide-sm">בריאות</th><th>פעולות</th></tr></thead><tbody>${rows.map((n) =>
    `<tr><td><b class="mono">${h(n.name)}</b><br><span class="small ltr muted">${h(n.ip || "")} ${h(n.datacenter || "")}</span><br><span class="small muted">נוצר ${when(n.created_at, true)}</span></td>
    <td>${chip(n.state, n.state_he)}<br><span class="small muted">${h(n.progress)}</span>${n.last_error ? `<br><span class="small" style="color:var(--plum)">${h(n.last_error)}</span>` : ""}<br><span class="small muted">דיווח ${ago(n.last_seen)}</span></td>
    <td class="small ltr">${h(n.email || "—")}</td><td class="small hide-sm">${health(n)}</td>
    <td><select data-job="${n.id}" style="min-height:34px;width:auto"><option value="">פעולה…</option><option value="health">בדיקת בריאות</option><option value="update">עדכון גרסה</option><option value="suspend">השהיה</option><option value="resume">הפעלה</option>${n.email ? `<option value="password">סיסמה חדשה ללקוח</option>` : ""}${n.state === "failed" ? `<option value="retry">לנסות שוב</option>` : ""}<option value="release">לשחרר אצל הספק</option></select>
    ${n.console ? `<br><a class="small" href="${h(n.console)}" target="_blank" rel="noopener">קונסול</a>` : ""}</td></tr>`).join("")}</tbody></table></div>${rows.length ? "" : '<p class="muted">עוד אין שרתים.</p>'}`;
  $("#savepool").onclick = async () => { try { await api("POST", "admin/pool", {size: Number($("#ps").value)}); toast("נשמר"); } catch (e) { $("#perr").textContent = e.message; } };
  $("#pause").onclick = async () => { try { await api("POST", "admin/pool", {paused: !o.pool.paused}); aNodes(); } catch (e) { $("#perr").textContent = e.message; } };
  $("#order").onclick = async (ev) => { if (!await binaAsk({ title: "לקנות עכשיו שרת אחד אצל הספק?", body: "זה חיוב אמיתי בחשבון הספק.", ok: "קנייה" })) return; busy(ev.target, true);
    try { await api("POST", "admin/nodes/order"); aNodes(); } catch (e) { $("#perr").textContent = e.message; busy(ev.target, false); } };
  $$("[data-job]").forEach((s) => { s.onchange = async () => {
    const id = s.dataset.job, v = s.value, n = rows.find((x) => String(x.id) === id); s.value = "";
    if (!v) return;
    try {
      if (v === "release") { const conf = n.email
          ? await binaAsk({ title: "לשחרר את השרת אצל הספק?", body: `השרת של ${n.email}. לשחרור כתבו את שמו.`, ok: "שחרור", danger: true,
                            facts: [["שרת", n.name]], input: { label: "שם השרת", must: n.name } })
          : ((await binaAsk({ title: `לשחרר את ${n.name} אצל הספק?`, body: "המידע עליו יימחק.", ok: "שחרור", danger: true })) ? n.name : null);
        if (!conf) return; await api("POST", `admin/nodes/${id}/release`, {confirm: conf, why: "admin"}); }
      else if (v === "retry") await api("POST", `admin/nodes/${id}/retry`);
      else { if (["suspend", "password"].includes(v) && !await binaAsk({ title: v === "suspend" ? "להשהות את השרת?" : "ליצור סיסמה חדשה ללקוח?",
                                                                          ok: "לבצע", facts: [["שרת", n.name]] })) return; await api("POST", `admin/nodes/${id}/job`, {verb: v, email: v === "password" ? n.email : undefined}); }
      toast("נשלח"); aNodes();
    } catch (e) { toast(e.message); } }; });
}
async function aPayments() {
  const rows = await api("GET", "admin/payments");
  $("#adm").innerHTML = `<div class="scroll"><table><thead><tr><th>#</th><th>מתי</th><th>לקוח</th><th>מה</th><th>סכום</th><th>מצב</th><th>מסמך</th><th></th></tr></thead><tbody>${rows.map((p) =>
    `<tr><td>${p.id}</td><td>${when(p.paid_at || p.created_at, true)}</td><td class="ltr small">${h(p.email)}</td><td>${h(p.kind_he)}</td><td>${h(money(p.amount))}</td><td>${chip(p.status, p.status_he)}${p.error ? `<br><span class="small muted">${h(p.error)}</span>` : ""}</td>
    <td>${p.doc_url ? `<a href="${h(p.doc_url)}" target="_blank" rel="noopener">${h(p.doc_number)}</a>` : h(p.doc_number)}</td><td>${p.status === "paid" ? `<button class="btn small danger" data-refund="${p.id}">החזר</button>` : ""}</td></tr>`).join("")}</tbody></table></div>${rows.length ? "" : '<p class="muted">עוד אין תשלומים.</p>'}`;
  $$("[data-refund]").forEach((b) => { b.onclick = async () => { if (!await binaAsk({ title: "להחזיר את הסכום המלא לכרטיס?", body: "זה לא הפיך.", ok: "החזר", danger: true })) return;
    try { await api("POST", `admin/payments/${b.dataset.refund}/refund`); aPayments(); } catch (e) { toast(e.message); } }; });
}
async function aPrices() {
  const [o, use] = await Promise.all([api("GET", "admin/overview"), api("GET", "admin/usage")]);
  const p = o.config.prices, prov = o.config.llm_providers;
  $("#adm").innerHTML = `<div class="card"><h3>המרה ומרווח</h3><form class="row" id="pf"><label style="margin:0">שער $→₪</label><input id="fx" type="number" step="0.01" value="${p.usd_ils}" style="width:100px">
    <label style="margin:0">מרווח</label><input id="mg" type="number" step="0.01" value="${p.margin}" style="width:90px"><button class="btn small">לשמור</button></form>
    <p class="small muted">מחיר קריאה = עלות הספק בדולרים × השער × (1 + המרווח). טבלת המחירים עודכנה ${h(p.updated)} (prices.json).</p><div class="err" id="perr"></div></div>
    <div class="card" style="margin-top:12px"><h3>מודלים</h3><div class="row" style="margin-bottom:8px">${Object.entries(prov).map(([k, v]) => chip(v ? "on" : "off", k)).join("")}</div>
    <div class="scroll"><table><thead><tr><th>מודל</th><th>ספק</th><th>קלט $/M</th><th>מטמון $/M</th><th>פלט $/M</th></tr></thead><tbody>${p.models.map((m) => `<tr><td class="ltr">${h(m.id)}</td><td>${h(m.provider)}</td><td>${m.in}</td><td>${m.cached ?? "—"}</td><td>${m.out}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="card" style="margin-top:12px"><h3>החודש</h3>${use.length ? `<div class="scroll"><table><tr><th>מודל</th><th>קריאות</th><th>טוקנים</th><th>חויב</th><th>עלות $</th></tr>${use.map((u) => `<tr><td class="ltr">${h(u.model)}</td><td>${num(u.calls)}</td><td>${num((u.tin || 0) + (u.tout || 0))}</td><td>${h(money(u.cost))}</td><td>${(Number(u.usd || 0) / 1e6).toFixed(3)}</td></tr>`).join("")}</table></div>` : '<p class="muted">אין שימוש החודש.</p>'}</div>`;
  $("#pf").onsubmit = async (ev) => { ev.preventDefault(); try { await api("POST", "admin/pricing", {usd_ils: Number($("#fx").value), margin: Number($("#mg").value)}); toast("נשמר"); } catch (e) { $("#perr").textContent = e.message; } };
}
async function aAudit() { $("#adm").innerHTML = auditRows(await api("GET", "admin/audit")); }

window.addEventListener("hashchange", route);
(async () => { try { await loadMe(); } catch (e) { /* the offer still shows */ } route(); })();
