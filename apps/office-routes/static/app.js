/* network — the office's routes screen. Hebrew RTL, relative URLs only (DGO-543).
 *
 * Two rules this file follows, because breaking them is invisible until it is expensive:
 *
 *   · EVERY request is RELATIVE (`api/routes`, not `/api/routes`). The console embeds this app at
 *     /a/network/ and injects <base href>; an absolute path would address the CONSOLE's origin and
 *     this screen would silently talk to the shell's routes instead of its own.
 *   · NOTHING IS PAINTED BECAUSE A CALL RETURNED 200. "Open" is what the ADDRESS answers: the server
 *     probes the edge for the route it declares and hands back the reading, and this screen draws
 *     the reading — never the button that was pressed.
 */
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

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let S = { view: null, busy: false };

async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  let doc = null;
  try { doc = await r.json(); } catch (e) { doc = null; }
  if (!r.ok) {
    const why = (doc && (doc.error || (doc.refused || []).join(" · "))) || binaSaid(r.status);
    throw new Error(why);
  }
  return doc || {};
}

const chip = (open, bad, text) =>
  `<span class="chip ${bad ? "bad" : open ? "open" : "shut"}">${esc(text)}</span>`;

function lanCard(r, view) {
  const suggested = view.suggested || [];
  const declared = r.address || "";
  const state = !r.open
    ? chip(false, false, "סגור")
    : (r.reachable ? chip(true, false, "פתוח ועונה") : chip(false, true, "פתוח · הכתובת לא עונה"));
  const list = suggested.length
    ? `<datalist id="addrs">${suggested.map((a) => `<option value="${esc(a)}"></option>`).join("")}</datalist>`
    : "";
  const hint = suggested.length
    ? `<div class="why">הכתובת שהלשכה מצהירה על המכונה הזו: <span class="addr">${suggested.map(esc).join(" · ")}</span>
         (נמדדה על המכונה עצמה בהרצה שלה. אם החכירה זזה — «מצא את כתובת המכונה» יחפש אותה ברשת הזו
         ויחזיר רק כתובת שהלשכה עצמה עונה בה.)</div>`
    : `<div class="why">הלשכה עוד לא הצהירה כתובת של המכונה הזו. אפשר להקליד כתובת, או ללחוץ
         «מצא את כתובת המכונה» — החיפוש עובר על הכתובות ברשת של הכתובת שתקלידו ומקבל רק כתובת
         שהלשכה עצמה עונה בה.</div>`;
  return `
    <div class="card">
      <h3><span>ברשת המקומית</span>${state}</h3>
      <div class="why">${r.open
        ? "מכשיר באותה רשת פותח את הקונסולה בכתובת הזו, וכל אפליקציה מבעד לקונסול. הכניסה של הלשכה נשארת השער היחיד."
        : "כל עוד הנתיב סגור, שום מכשיר שאינו המכונה אינו יכול לפתוח את הלשכה — אין כלל בקצה, אין ספק זהות ואין פתח בחומה."}</div>
      ${declared ? `<div class="addr">${esc(declared)}${r.port ? ":" + esc(String(r.port)) : ""}</div>` : ""}
      <div class="row">
        ${list}
        <input type="text" id="addr" list="addrs" placeholder="192.168.1.23" value="${esc(declared || (suggested[0] || ""))}">
        <button class="btn ghost" id="find" ${S.busy ? "disabled" : ""}>מצא את כתובת המכונה</button>
        <button class="btn ghost" id="probe" ${S.busy ? "disabled" : ""}>בדוק שהמכונה עונה</button>
        <button class="btn" id="open" ${S.busy ? "disabled" : ""}>${r.open ? "החלף כתובת" : "פתח נתיב"}</button>
        ${r.open ? `<button class="btn ghost" id="close" ${S.busy ? "disabled" : ""}>סגור</button>` : ""}
      </div>
      <div class="why" id="probeOut">${r.open && r.probe_why ? "הבדיקה: " + esc(r.probe_why) : ""}</div>
      ${hint}
    </div>`;
}

function render() {
  const view = S.view || { routes: [], suggested: [] };
  const local = view.routes.find((r) => r.kind === "localhost") || {};
  const lan = view.routes.find((r) => r.kind === "lan") || {};
  $("routes").innerHTML = `
    <div class="card">
      <h3><span>${esc(local.title || "על המכונה עצמה")}</span>${chip(true, false, "פתוח תמיד")}</h3>
      <div class="addr">${esc(local.address || "*.localhost")}</div>
      <div class="why">${esc(local.why || "")}</div>
    </div>
    ${lanCard(lan, view)}`;
  $("history").innerHTML = `
    <h3>מה קרה כאן</h3>
    <div class="why">כל ניסיון — פתיחה, סגירה או סירוב — נרשם באפליקציה עצמה, ואינו נמחק.</div>
    ${(view.history || []).length
      ? `<div class="row" style="flex-direction:column;align-items:stretch">${(view.history || []).map((e) => `
          <div class="ev ${e.result === "ok" ? "ok" : e.result === "refused" ? "bad" : ""}">
            <span class="addr">${esc(e.at)}</span> · ${esc({open: "פתיחה", close: "סגירה", find: "חיפוש כתובת"}[e.action] || e.action)}
            ${e.address ? `· <span class="addr">${esc(e.address)}</span>` : ""} · ${esc(e.by || "—")}
            ${e.result === "refused" ? `· ${esc(e.detail || "נדחה")}` : ""}
          </div>`).join("")}</div>`
      : `<div class="why">עוד לא נעשה כאן כלום.</div>`}`;
  const openBtn = $("open"), closeBtn = $("close"), probeBtn = $("probe"), findBtn = $("find");
  if (openBtn) openBtn.onclick = askOpen;
  if (closeBtn) closeBtn.onclick = askClose;
  if (probeBtn) probeBtn.onclick = checkAddress;
  if (findBtn) findBtn.onclick = findAddress;
}

// What a knock came back with, said as two different facts: something answered there, and WHOSE
// answer it was. Only the second one makes the address the machine's own.
function knockReading(address, r) {
  if (!r.answers) return `לא ענה כלום בכתובת ${address}. ${r.why || ""}`;
  if (r.ours === true) return `בכתובת ${address} עונה הלשכה הזו (הקצה שלה) — אפשר לפתוח. השער נשאר הכניסה של הלשכה.`;
  if (r.ours === false) return `בכתובת ${address} ענה משהו על פורט 80 — אבל זו אינה הלשכה הזו. `
    + "אפשר ללחוץ «מצא את כתובת המכונה» ולפתוח את הכתובת שהיא תמצא.";
  return `בכתובת ${address} ענה משהו על פורט 80 — אפשר לפתוח. השער נשאר הכניסה של הלשכה.`;
}

async function checkAddress() {
  const address = (($("addr") || {}).value || "").trim();
  if (!address) { binaTell("צריך כתובת", "bad"); return; }
  const out = $("probeOut");
  out.textContent = "בודק…";
  let r;
  try { r = await api("POST", "api/probe", { address }); }
  catch (e) { out.textContent = "הבדיקה נכשלה: " + String(e.message || e); return; }
  out.textContent = knockReading(address, r);
  if (!r.answers || r.ours === false) binaTell("הכתובת הזו אינה של הלשכה", "bad");
}

// The search: the machine's own address on its own network, measured by knocking — started here, by
// a person, and never on page load. It accepts an answer only if it is THIS office's edge.
async function findAddress() {
  const from = (($("addr") || {}).value || "").trim();
  const out = $("probeOut");
  out.textContent = from ? `מחפש כתובת שהלשכה עונה בה, החל מ-${from}…` : "מחפש כתובת שהלשכה עונה בה…";
  let r;
  try { r = await api("POST", "api/find", from ? { address: from } : {}); }
  catch (e) { out.textContent = "החיפוש נכשל: " + String(e.message || e); return; }
  const found = r.found || [];
  if (found.length) {
    ($("addr") || {}).value = found[0];
    out.textContent = `נמצאה ${found.join(" · ")} — נבדקו ${r.probed} כתובות ב-${r.ms}ms, `
      + "והתשובה שהתקבלה היא של הלשכה הזו.";
    binaTell("נמצאה הכתובת של המכונה", "ok");
    return;
  }
  out.textContent = `לא נמצאה כתובת שהלשכה עונה בה (נבדקו ${r.probed} כתובות ב-${r.ms}ms). ${r.why || ""}`;
  binaTell("לא נמצאה הכתובת של המכונה", "bad");
}

async function askOpen() {
  const address = (($("addr") || {}).value || "").trim();
  if (!address) { binaTell("צריך לבחור כתובת של המכונה", "bad"); return; }
  const ok = await binaAsk({
    title: "לפתוח את הנתיב?",
    ok: "פתח את הנתיב",
    body: "הלשכה תענה בכתובת " + address + " — הקונסול, כל האפליקציות והכניסה.\n"
        + "מה זה פותח: כל מכשיר ברשת שבה המכונה נמצאת יגיע לעמוד הכניסה של הלשכה. הכניסה עצמה "
        + "נשארת השער — בלי משתמש ומפתח אין כניסה לשום מסך.\n"
        + "ומה נדרש בצד המכונה: כלל ב-Windows Firewall ל-TCP 80, מוגבל לרשתות של המכונה עצמה. "
        + "הוא נוצר בהרצה של bbox.cmd run — קליק אחד של הרשאה.",
    facts: [["כתובת", address], ["מה ייחשף", "עמוד הכניסה של הלשכה"], ["השער", "הכניסה של הלשכה"]],
  });
  if (!ok) return;
  S.busy = true; render();
  try {
    const r = await api("PUT", "api/routes/lan", { address });
    const applied = r.applied && r.applied.ok;
    binaTell(applied ? "הנתיב נכתב והוחל" : "הנתיב נכתב; ההחלה מסתיימת בהרצה של bbox.cmd run",
             applied ? "ok" : "warn");
  } catch (e) { binaTell(String(e.message || e), "bad"); }
  S.busy = false;
  await load(false);
}

async function askClose() {
  const ok = await binaAsk({
    title: "לסגור את הנתיב?",
    ok: "סגור",
    danger: true,
    body: "הלשכה תפסיק לענות בכתובת הזו, וכלל החומה נמחק בהרצה של bbox.cmd run.\n"
        + "מה זה מחזיר: המצב הקודם בדיוק — הקונסול נגיש רק על המכונה עצמה.",
  });
  if (!ok) return;
  S.busy = true; render();
  try {
    await api("DELETE", "api/routes/lan");
    binaTell("הנתיב נסגר", "ok");
  } catch (e) { binaTell(String(e.message || e), "bad"); }
  S.busy = false;
  await load(false);
}

async function load(spin = true) {
  if (spin) { S.busy = true; render(); }
  try {
    S.view = await api("GET", "api/routes");
    if (S.view.declared_error) binaTell("קריאת ההצהרה נכשלה: " + S.view.declared_error, "bad");
  } catch (e) {
    binaTell("טעינת המצב נכשלה: " + String(e.message || e), "bad");
  }
  S.busy = false;
  render();
}

load();
