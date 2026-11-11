/* telegram — the screen: the account, the chats the office listens to, and the live stream.
 *
 * One page with three places; the place is the URL (`/a/telegram/chats`), read on load and written on a
 * click, so a copied address lands on the same card (G83). URLs are RELATIVE to document.baseURI: the
 * console serves this app under /a/telegram/. */
"use strict";

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

// The mount is where this script came from, minus `static/app.js`: `/a/telegram/` framed (the console's
// <base>), `/` on the app's own host — and right on a deep address (`/flow`) where baseURI is the page itself.
const BASE = new URL("../", document.currentScript.src);
const $ = (id) => document.getElementById(id);
const one = (n, single, many) => (Number(n) === 1 ? single : `${Number(n).toLocaleString("he-IL")} ${many}`);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, body) {
  const r = await fetch(new URL(path, BASE), body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).catch(binaNoAnswer);
  let doc = {};
  try { doc = await r.json(); } catch (_) { /* no JSON: said below */ }
  if (!r.ok) {
    const err = new Error(doc.detail || doc.error || binaSaid(r.status));
    err.status = r.status;                // a caller tells «not there» (404) from «not answering» (5xx)
    throw err;
  }
  return doc;
}

// ── the place in the URL ─────────────────────────────────────────────────────────────────
const ROUTES = ["", "account", "chats", "flow"];
function route() {
  const rest = location.pathname.startsWith(BASE.pathname) ? location.pathname.slice(BASE.pathname.length) : "";
  const r = rest.split("/")[0];
  return ROUTES.includes(r) ? r : "";
}
function showRoute(scroll) {
  const r = route();
  document.querySelectorAll("#tabs .tab").forEach((a) => a.toggleAttribute("aria-current", a.dataset.route === r));
  if (r) a11yCurrent(r);
  if (scroll && r) $(r)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
function a11yCurrent(r) { document.querySelectorAll("#tabs .tab").forEach((a) => a.dataset.route === r && a.setAttribute("aria-current", "page")); }
$("tabs").addEventListener("click", (e) => {
  const a = e.target.closest("a.tab");
  if (!a) return;
  e.preventDefault();
  history.pushState(null, "", new URL(a.dataset.route || "./", BASE));
  showRoute(true);
});
addEventListener("popstate", () => showRoute(true));

// ── the account ──────────────────────────────────────────────────────────────────────────
let STATUS = null;
let loginTimer = null;
let drawn = "";   // what the account card shows: redrawn only when that changes, so a refresh never wipes a field

function flowChip(s) {
  const c = $("flow-chip");
  if (!c) return;
  c.className = "chip" + (s.flow.error ? " bad" : "");
  c.textContent = s.flow.error ? "הזרם אינו נכתב" : "נכתבו " + s.flow.published + " אירועים מאז ההפעלה";
}

function renderAccount() {
  const s = STATUS, el = $("acc"), lg = s.login || {};
  const live = $("live");
  live.dataset.stale = s.connected ? "0" : "1";
  $("live-t").textContent = s.connected ? "מחובר ומאזין" : "לא מחובר";
  const key = JSON.stringify([s.connected, s.me, s.reason, lg.step, lg.qr_svg, lg.error, lg.hint]);
  if (key === drawn) { flowChip(s); return; }
  drawn = key;
  if (s.connected) {
    const me = s.me || {};
    el.innerHTML = `<div class="who"><div class="av">${esc((me.name || me.username || "ט").slice(0, 1))}</div>
      <div><div class="nm">${esc(me.name || "")}</div>
      <div class="note ltr">${me.username ? "@" + esc(me.username) : ""}</div></div></div>
      <div class="row" style="margin-top:12px"><span class="chip ok">מחובר</span><span id="flow-chip"></span></div>
      <h3 style="margin:16px 0 4px;font-size:14px">טוקן של בוט לחיבורים</h3>
      <div class="note">הלשכה שואלת את BotFather בשמך ושומרת את הטוקן ישר בחיבורים ומפתחות של הלשכה הזאת — הוא לא מוצג ולא עובר בצ׳אט.</div>
      <label for="bot">שם המשתמש של הבוט</label><input id="bot" class="ltr" placeholder="bina_solution_agent_bot">
      <label for="bot-label">השם בחיבורים</label><input id="bot-label" value="בוט טלגרם ראשי">
      <div class="row" style="margin-top:10px"><button class="btn" id="bot-go">הבא את הטוקן לחיבורים</button></div>`;
    $("bot-go").onclick = botToken;
    flowChip(s);
    return;
  }
  const step = lg.step || "idle";
  let h = s.reason ? `<div class="row"><span class="chip warn">${esc(s.reason)}</span></div>` : "";
  if (step === "qr") {
    h += `<div class="qr"><img alt="קוד QR להתחברות" src="${esc(lg.qr_svg)}"></div><div class="note">${esc(lg.hint || "")}</div>`;
  } else if (step === "code") {
    h += `<label for="code">הקוד מטלגרם</label><input id="code" class="ltr" inputmode="numeric" autocomplete="one-time-code">
      <div class="row" style="margin-top:10px"><button class="btn primary" id="code-go">אישור</button></div>`;
  } else if (step === "password") {
    h += `<div class="note">${esc(lg.hint || "")}</div><label for="pw">סיסמת האימות הדו-שלבי</label><input id="pw" type="password" autocomplete="current-password">
      <div class="row" style="margin-top:10px"><button class="btn primary" id="pw-go">אישור</button></div>`;
  } else {
    h += `<div class="note" style="margin:8px 0">מחברים את חשבון הטלגרם שלך: סורקים קוד בטלפון, או מספר טלפון וקוד.</div>
      <div class="row"><button class="btn primary" id="go-qr">התחברות בסריקת QR</button></div>
      <label for="phone">או בטלפון</label><input id="phone" class="ltr" inputmode="tel" placeholder="+972…">
      <div class="row" style="margin-top:8px"><button class="btn" id="go-phone">שלחו לי קוד</button></div>
      <div class="list" id="known"></div>`;
  }
  if (["qr", "code", "password"].includes(step)) h += `<div class="row" style="margin-top:10px"><button class="btn sm" id="cancel">ביטול</button></div>`;
  if (lg.error) h += `<div class="row" style="margin-top:8px"><span class="chip bad">${esc(lg.error)}</span></div>`;
  el.innerHTML = h;
  const on = (id, f) => { const b = $(id); if (b) b.onclick = f; };
  on("go-qr", () => login({ mode: "qr" }));
  on("go-phone", () => login({ mode: "phone", phone: $("phone").value }));
  on("code-go", () => step2("code", { code: $("code").value }));
  on("pw-go", () => step2("password", { password: $("pw").value }));
  on("cancel", async () => { STATUS.login = await api("api/login/cancel", {}); renderAccount(); });
  if (step === "idle" || step === "failed") knownAccounts();
  clearTimeout(loginTimer);
  if (["qr", "starting"].includes(step)) loginTimer = setTimeout(refresh, 2500);
}

async function knownAccounts() {
  try {
    const d = await api("api/accounts");
    const box = $("known");
    if (!box || !(d.accounts || []).length) return;
    box.innerHTML = `<label>או חשבון שכבר נמצא בחיבורים</label>` + d.accounts.map((a) =>
      `<div class="item"><div><div class="t">${esc(a.label)}</div><div class="s ltr">${esc(a.account_hint || a.id)}</div></div>
       <button class="btn sm" data-use="${esc(a.id)}">להשתמש בו</button></div>`).join("");
    box.querySelectorAll("[data-use]").forEach((b) => b.onclick = async () => {
      try { STATUS = await api("api/accounts/select", { id: b.dataset.use }); render(); binaTell(STATUS.connected ? "החשבון מחובר" : (STATUS.reason || "החשבון לא התחבר"), STATUS.connected ? "ok" : "bad"); }
      catch (e) { binaTell(e.message, "bad"); }
    });
  } catch (_) { /* the list is a convenience; the login above works without it */ }
}

async function login(body) {
  try { STATUS.login = await api("api/login/start", body); renderAccount(); }
  catch (e) { binaTell(e.message, "bad"); }
}
async function step2(kind, body) {
  try { STATUS.login = await api("api/login/" + kind, body); await refresh(); }
  catch (e) { binaTell(e.message, "bad"); }
}

async function botToken() {
  const bot = $("bot").value.trim(), label = $("bot-label").value.trim();
  if (!bot || !label) { binaTell("צריך את שם המשתמש של הבוט ואת השם בחיבורים", "warn"); return; }
  let res = null;   // the question resolves to the answer, not to what `run` returned
  const yes = await binaAsk({
    title: "להביא את הטוקן מ-BotFather?",
    body: "הלשכה תכתוב ל-BotFather בשמך את ‎/token‎, תבחר את הבוט, ותשמור את התשובה בחיבורים ומפתחות של הלשכה הזאת.",
    facts: [["בוט", bot], ["השם בחיבורים", label]],
    ok: "הבא את הטוקן",
    run: async () => { res = await api("api/bots/token", { bot, label }); },
  });
  if (yes && res) binaTell(`הטוקן של ‎@${res.bot}‎ נשמר בחיבורים בשם «${res.label}»`, "ok");
}

// ── the chats ────────────────────────────────────────────────────────────────────────────
function renderWatched() {
  const w = STATUS.watched || [];
  $("watched").innerHTML = w.length ? w.map((c) =>
    `<div class="item"><div><div class="t">${esc(c.title)}</div><div class="s">${esc(kindName(c.kind))}</div></div>
     <button class="btn sm" data-off="${esc(c.id)}" data-title="${esc(c.title)}">להפסיק להאזין</button></div>`).join("")
    : `<div class="empty">${STATUS.connected ? "הלשכה לא מאזינה לאף צ׳אט." : "אחרי החיבור בוחרים כאן את הצ׳אטים."}</div>`;
  $("watched").querySelectorAll("[data-off]").forEach((b) => b.onclick = () => watch(b.dataset.off, false, b.dataset.title));
  $("q").disabled = !STATUS.connected;
}
const kindName = (k) => ({ group: "קבוצה", channel: "ערוץ", user: "צ׳אט פרטי", bot: "בוט" }[k] || k || "");

let qTimer = null;
$("q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(search, 350); });
async function search() {
  const q = $("q").value.trim();
  if (!q) { $("found").innerHTML = ""; return; }
  try {
    const d = await api("api/chats?limit=20&q=" + encodeURIComponent(q));
    $("found").innerHTML = (d.chats || []).map((c) =>
      `<div class="item"><div><div class="t">${esc(c.title)}</div><div class="s">${esc(kindName(c.kind))}</div></div>
       ${c.watched ? `<span class="chip ok">מאזין</span>` : `<button class="btn sm" data-on="${esc(c.id)}" data-kind="${esc(c.kind)}" data-title="${esc(c.title)}">להאזין</button>`}</div>`).join("")
      || `<div class="empty">אין צ׳אט בשם הזה.</div>`;
    $("found").querySelectorAll("[data-on]").forEach((b) => b.onclick = () => watch(b.dataset.on, true, b.dataset.title, b.dataset.kind));
  } catch (e) { binaTell(e.message, "bad"); }
}

async function watch(id, on, title, kind) {
  if (on && (kind === "user" || kind === "bot")) {
    const yes = await binaAsk({ title: "להאזין לצ׳אט פרטי?", body: "כל הודעה בו תגיע לזרם, וכל סוכן ואוטומציה בלשכה יראו אותה.",
      facts: [["צ׳אט", title]], ok: "להאזין" });
    if (!yes) return;
  }
  try {
    const d = await api("api/watch", { chat_id: Number(id), on });
    STATUS.watched = d.watched;
    renderWatched();
    if (on) search();
    binaTell(on ? `מאזין ל«${title}»` : `הפסיק להאזין ל«${title}»`, "ok");
  } catch (e) { binaTell(e.message, "bad"); }
}

// ── the stream ───────────────────────────────────────────────────────────────────────────
// A message that came with a file carries «שמור בקבצים»: its file, any size, into the office's drive, streamed in
// pieces (POST api/media/save, DGO-1805). The save runs in the app's background — a large file takes minutes — so
// the button says «שומר…» from the click until the app's own record of the save (GET api/media/save) says how it
// ended — never a clock compared with the stream's (redis's may lag the browser's), never an event that may be missed.
// "chat:message" → "starting" (its POST has not answered: the app has no record yet, so it is not asked) or "saving"
const SAVING = new Map();
async function settleSaves() {
  for (const [key, phase] of [...SAVING]) {
    if (phase !== "saving") continue;
    const [chat, msg] = key.split(":");
    try {
      const d = await api(`api/media/save?chat_id=${encodeURIComponent(chat)}&message_id=${encodeURIComponent(msg)}`);
      if (d.state === "saving") continue;
      if (!SAVING.delete(key)) continue;    // another redraw, overlapping this one, already said it
      if (d.state === "saved") binaTell(`נשמר בקבצים: ${d.path}`, "ok");
      else binaTell(`לא נשמר: ${d.error || "בלי סיבה"}`, "bad");
    } catch (e) {
      // 404: the app restarted, and the save with it. Anything else — the door, a blip — is asked again next time.
      if (e.status === 404 && SAVING.delete(key)) binaTell(e.message, "bad");
    }
  }
}
function saveButton(e) {
  const d = e.data || {}, m = d.media || {};
  if (e.type !== "message.new" || !m.size || d.chat_id == null || d.message_id == null) return "";
  const key = `${d.chat_id}:${d.message_id}`, busy = SAVING.has(key);
  const mb = (m.size / 1048576).toFixed(1);
  return ` <button class="btn sm ev-save" data-chat="${esc(d.chat_id)}" data-msg="${esc(d.message_id)}"${busy ? " disabled" : ""}
    title="מוריד את הקובץ (${esc(mb)}MB) מטלגרם לקבצים של הלשכה, לתיקייה «טלגרם»">${busy ? "שומר…" : "שמור בקבצים"}</button>`;
}
async function saveMedia(btn) {
  const key = `${btn.dataset.chat}:${btn.dataset.msg}`;
  if (SAVING.has(key)) return;
  SAVING.set(key, "starting");
  btn.disabled = true; btn.textContent = "שומר…";
  try {
    const d = await api("api/media/save", { chat_id: Number(btn.dataset.chat), message_id: Number(btn.dataset.msg) });
    if (d.state === "saving") { SAVING.set(key, "saving"); binaTell(`שומר בקבצים: ${d.path} — תופיע הודעה כשיסתיים`, "ok"); }
    else { SAVING.delete(key); binaTell(`כבר בקבצים: ${d.path}`, "ok"); }
  } catch (e) { SAVING.delete(key); binaTell(e.message, "bad"); }
  renderFlow();
}
$("events").addEventListener("click", (ev) => {
  const b = ev.target.closest(".ev-save");
  if (b && !b.disabled) saveMedia(b);
});

async function renderFlow() {
  try {
    const d = await api("api/flow?last=60");
    const evs = d.events || [];
    await settleSaves();
    // one is said as one (G89): «האחרון», never «1 אחרונים»
    $("flow-n").textContent = d.error ? "· הזרם אינו זמין" : `· ${one(evs.length, "האחרון", "אחרונים")}`;
    $("events").innerHTML = evs.length ? evs.map((e) => {
      const t = new Date(Number(String(e.id).split("-")[0]));
      return `<div class="ev"><time datetime="${esc(e.at)}">${t.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
        <span class="ty ${esc(String(e.type).split(".")[0])}">${esc(e.type)}</span><span class="tt">${esc(e.title)}${saveButton(e)}</span></div>`;
    }).join("") : `<div class="empty">עוד אין אירועים. כשיגיעו הודעות בצ׳אטים שהלשכה מאזינה להם, הן יופיעו כאן.</div>`;
  } catch (e) { $("flow-n").textContent = "· " + e.message; }
}

// ── the loop ─────────────────────────────────────────────────────────────────────────────
function render() { renderAccount(); renderWatched(); }
async function refresh() {
  try { STATUS = await api("api/status"); render(); }
  catch (e) { $("live-t").textContent = e.message; $("live").dataset.stale = "1"; }
}
(async function start() {
  showRoute(false);
  await refresh();
  await renderFlow();
  showRoute(true);
  setInterval(renderFlow, 4000);
  setInterval(() => { if (!["qr", "code", "password"].includes(STATUS?.login?.step)) refresh(); }, 15000);
})();
