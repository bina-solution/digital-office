/* מייל SPA — reading + tagging over the gmail-imap abstraction, the rules editor, the mailbox settings.
   URL = state: / (inbox) · /attention · /v/<view> · /label/<name> · /?q= · /message/<id> · /organizer ·
   /settings[/<section>]. Every route is served by mailview/app.py and re-read by applyUrl() on load,
   so a refresh lands on the same screen — standalone at mail.localhost and mounted under the
   console's /a/mailview/ (see MOUNT).

   Honesty rules this file follows (RELEASE-DECISIONS N11): nothing is faked in memory — archive,
   read/unread, star and importance are requests to api/mark and the undo is the INVERSE request;
   the rail shows no counts because the service reports none; every failure carries the service's
   own sentence to ONE notice channel; every action has a busy state. */
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
const $ = s => document.querySelector(s);
const enc = encodeURIComponent;

/* ── the mount ─────────────────────────────────────────────────────────────────────────────────
   index.html guarantees a <base>: "/" standalone, "/a/mailview/" when the console proxies this app.
   Every path this file pushes or parses is MOUNT-relative, and the inner route (what comes after the
   mount) is what the console shell mirrors into its own address bar (bina:route). */
const MOUNT = (() => {
  try {
    const p = new URL(document.baseURI).pathname;
    return p.endsWith("/") ? p : p.replace(/[^/]*$/, "");
  } catch (e) { return "/"; }
})();
const EMBEDDED = (() => { try { return window.parent !== window; } catch (e) { return false; } })();
const href = inner => MOUNT + String(inner || "/").replace(/^\//, "");
function innerPath() {
  let p = location.pathname;
  if (p === MOUNT.replace(/\/$/, "")) return "/";
  if (p.startsWith(MOUNT)) p = "/" + p.slice(MOUNT.length);
  return p || "/";
}

/* ── state ── */
let LABELS = [], MSGS = [], CURLABEL = "", QUERY = "", OPEN = null, VIEW = "", SCREEN = "list";
let MODE = "gmail";                                 // local | gmail — decides what read-state means
let TESTSHOW = null, TESTTOTAL = 0, TESTHIDDEN = false;   // null = backend-mode default
let TOTAL = 0, HASMORE = false, CURSOR = 0, LOADING = false;   // cursor pagination
const SELECTED = new Set();
/* Rows removed from the CURRENT scope by an action that succeeded (archive from the inbox, unstar
   in the starred view). The server is the truth on the next load; this set only keeps the list
   consistent between the action and that load, and undo empties it. */
const HIDDEN = new Set();
const BUSY_IDS = new Set();                         // rows with a request in flight
/* Message bodies already fetched: the reader, the neighbour prefetch and the rules preview share
   it, so a message opened twice costs one IMAP round trip. Bounded — see cacheSet. */
const MSGCACHE = new Map();
const CACHE_MAX = 60;
function cacheSet(id, m) {
  if (MSGCACHE.has(id)) MSGCACHE.delete(id);
  MSGCACHE.set(id, m);
  while (MSGCACHE.size > CACHE_MAX) MSGCACHE.delete(MSGCACHE.keys().next().value);
}
let _tagBusy = false;   // re-entrancy guard: a label add/remove in flight

const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/* ONE IS SAID AS ONE, AND A NUMBER READS ONE WAY. A count was the number and the plural whatever the number —
   «1 הודעות», «1 שיחות», «1 שגיאות» — and a mailbox of «4421» stood a tile away from an archive of «13,811».
   A count of one is its own sentence, which only the place that says it knows; any other is the number, written
   as the office writes a number, and the plural. */
const num = n => Number(n).toLocaleString("he-IL");
const one = (n, single, many) => (Number(n) === 1 ? single : `${num(n)} ${many}`);
/* A left-to-right token inside a Hebrew line where markup cannot go (a placeholder): the two isolate marks
   around it, written by their numbers — a mark nobody can see is not left lying in the source. */
const ltr = s => String.fromCharCode(0x2066) + s + String.fromCharCode(0x2069);
const post = body => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const put = body => ({ method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/* ── ONE notice channel: the office's (`binaTell`, the copied block above) ─────────────────────
   Success: a short line that fades. Failure: a line that STAYS until it is pressed and carries the
   service's own sentence (mailview/app.py forwards {error, upstream_status, upstream_path}), because
   "שגיאה (500)" is a number and the sentence behind it is the diagnosis.
   One failure at a time: a notice that stays would otherwise pile up, one per request, while the
   service is down — the newest takes the place of the one before it. */
let FAIL_N = null;
const fail = (t, detail) => { if (FAIL_N) FAIL_N.remove(); FAIL_N = binaTell(t, "bad", { more: detail, stay: true }); };

/* The upstream sentence, when there is one. `upstream_status` differs from the hop's own status
   when mailview translated it (a 5xx becomes a 502 gateway answer), and then both are shown. */
function errText(body, status) {
  const m = body && (body.error || body.message);
  if (m) return String(m);
  return binaSaid(status);               // (it said «שגיאה (502)»: a number, where the office has words)
}
function errDetail(body, status) {
  if (!body) return `קוד ${status}`;
  const parts = [];
  if (body.upstream_status) parts.push(`שירות המייל השיב ${body.upstream_status}`);
  if (body.upstream_path) parts.push(String(body.upstream_path));
  if (!parts.length) parts.push(`קוד ${status}`);
  return parts.join(" · ");
}
async function jf(u, opt) {
  opt = opt || {};
  let r;
  try { r = await fetch(u, opt); }
  catch (e) {
    const err = new Error(binaSaid(0)); err.network = true;        // the office's one name for it (it said «שגיאת רשת — …»)
    if (!opt.silent) fail(err.message);
    throw err;
  }
  let body = null;
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("json")) body = await r.json().catch(() => null);
  if (!r.ok) {
    const err = new Error(errText(body, r.status)); err.status = r.status; err.body = body;
    err.detail = errDetail(body, r.status);
    if (!opt.silent) fail(err.message, err.detail);
    throw err;
  }
  if (body === null) {
    const t = await r.text().catch(() => "");
    try { body = JSON.parse(t); } catch (e) { body = {}; }
  }
  return body;
}
/* disable a control while its request is in flight — a double-click must never send twice */
async function busy(btn, fn) {
  if (!btn) return fn();
  if (btn.disabled) return undefined;
  btn.disabled = true; btn.setAttribute("aria-busy", "true");
  try { return await fn(); }
  finally { btn.disabled = false; btn.removeAttribute("aria-busy"); }
}

/* Mail is a MAIL app. It has no opinion about INDOX. The pipeline's labels are filtered out of every
   surface by ONE namespace rule (isMachineLabel) — not by a state machine. */
const SYS = new Set(["INBOX", "SENT", "DRAFT", "DRAFTS", "SPAM", "TRASH", "STARRED", "IMPORTANT", "UNREAD", "SENT-COPY"]);
/* `/^\\+/` — leading BACKSLASHES: Gmail hands its system labels over IMAP as `\Starred` / `\Inbox`. */
const nonSys = ls => (ls || []).filter(l => !SYS.has(String(l).replace(/^\\+/, "").toUpperCase()) && !String(l).startsWith("[Gmail]") && !/^Label_\d+$/.test(l));
const INDOX_NS = /^אינדוקס(\s|-|$)/;
const SYNC_NS = /^(sv3s[_-]|SENT-COPY$)/i;
const isMachineLabel = l => INDOX_NS.test(String(l)) || SYNC_NS.test(String(l));
/* Mail's own triage state — "did the label engine get to this yet". KEY -> name resolved through
   /api/label-map (mailapi's /organizer/settings), the exact lookup the engine uses; never a literal. */
const TRIAGE_KEYS = {
  failed:    ["FAILED_DOC", "FAILED_BS", "ACTION_FAILED", "FOUND_UNKNOWN"],
  processed: ["SYNCED_DOC", "SYNCED_BS", "SAVED_INVOICE", "SAVED_SHIPMENT", "ACTION_DONE"],
  waiting:   ["DOC_TO_SYNC", "BS_TO_SYNC", "DOC_LINK_TO_SYNC", "IN_PROGRESS"],
};
const TRIAGE_ORDER = ["failed", "processed", "waiting"];
const TRIAGE_TITLE = { waiting: "ממתין למנוע התוויות", processed: "טופל על ידי מנוע התוויות",
                       failed: "נכשל במנוע התוויות" };
let TRIAGE_NAMES = { failed: new Set(), processed: new Set(), waiting: new Set() };
let TRIAGE_ALL_NAMES = new Set();
async function loadLabelMap() {
  try {
    const L = ((await jf("api/label-map", { silent: true })).gmail || {}).labels || {};
    const nameOf = k => (L[k] || {}).name;
    TRIAGE_ALL_NAMES = new Set();
    for (const state of TRIAGE_ORDER) {
      const names = new Set(TRIAGE_KEYS[state].map(nameOf).filter(Boolean));
      TRIAGE_NAMES[state] = names;
      for (const n of names) TRIAGE_ALL_NAMES.add(n);
    }
  } catch (e) { /* label-map unavailable — rows simply render with no triage dot */ }
}
function triageState(m) {
  const ls = m.labels || [];
  for (const state of TRIAGE_ORDER)
    if (ls.some(l => TRIAGE_NAMES[state].has(l))) return state;
  return "";
}
/* the year is dropped ONLY for the current year — where it would be noise — and shown otherwise */
const fmtDate = s => {
  if (!s) return "";
  const d = new Date(s);
  if (isNaN(d)) return String(s).slice(0, 16);
  const today = new Date(), y = new Date(); y.setDate(today.getDate() - 1);
  const hm = d.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return "היום " + hm;
  if (d.toDateString() === y.toDateString()) return "אתמול " + hm;
  if (d.getFullYear() !== today.getFullYear())
    return d.toLocaleDateString("he-IL", { day: "numeric", month: "short", year: "numeric" });
  return d.toLocaleDateString("he-IL", { day: "numeric", month: "short" }) + " " + hm;
};
const HE_MONTHS = ["ינואר","פברואר","מרץ","אפריל","מאי","יוני","יולי","אוגוסט","ספטמבר","אוקטובר","נובמבר","דצמבר"];
function dayKey(s) {
  const d = new Date(s);
  if (isNaN(d)) return "מוקדם יותר";
  const now = new Date();
  const sod = x => { const c = new Date(x); c.setHours(0, 0, 0, 0); return c.getTime(); };
  const diff = Math.round((sod(now) - sod(d)) / 864e5);
  if (diff <= 0) return "היום";
  if (diff === 1) return "אתמול";
  if (diff < 7) return "השבוע";
  if (diff < 31 && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()) return "החודש";
  return HE_MONTHS[d.getMonth()] + (d.getFullYear() === now.getFullYear() ? "" : " " + d.getFullYear());
}
const fromName = f => (f || "").replace(/<[^>]*>/, "").replace(/^["']|["']$/g, "").trim() || (f || "");
const addrOf = f => (String(f || "").match(/<([^>]+)>/) || [null, String(f || "").trim()])[1];

/* ── icons (Lucide line paths, never emoji) ── */
const ICONS = {
  inbox:    '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  star:     '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>',
  clock:    '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  send:     '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  pencil:   '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/>',
  alert:    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  flag:     '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>',
  mail:     '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
  'mail-open': '<path d="M21.2 8.4c.5.38.8.97.8 1.6v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V10a2 2 0 0 1 .8-1.6l8-6a2 2 0 0 1 2.4 0z"/><path d="m22 10-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 10"/>',
  ban:      '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
  trash:    '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  archive:  '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
  paperclip:'<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  tag:      '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5"/>',
  search:   '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  check:    '<path d="M20 6 9 17l-5-5"/>',
  'check-circle': '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  chevron:  '<path d="m6 9 6 6 6-6"/>',
  back:     '<path d="m9 18 6-6-6-6"/>',
  prev:     '<path d="m15 18-6-6 6-6"/>',
  reply:    '<polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
  'reply-all': '<polyline points="7 17 2 12 7 7"/><polyline points="12 17 7 12 12 7"/><path d="M22 18v-2a4 4 0 0 0-4-4H7"/>',
  forward:  '<polyline points="15 17 20 12 15 7"/><path d="M4 18v-2a4 4 0 0 1 4-4h12"/>',
  print:    '<polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect width="12" height="8" x="6" y="14"/>',
  refresh:  '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  x:        '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  plus:     '<path d="M5 12h14"/><path d="M12 5v14"/>',
  'arrow-up': '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
  'arrow-down': '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
  play:     '<polygon points="6 3 20 12 6 21 6 3"/>',
  info:     '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  server:   '<rect width="20" height="8" x="2" y="2" rx="2"/><rect width="20" height="8" x="2" y="14" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
  key:      '<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/><path d="m21 2-9.6 9.6"/><circle cx="7.5" cy="15.5" r="5.5"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  copy:     '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  shield:   '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  menu:     '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>',
  folder:   '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  list:     '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
  book:     '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
  'chevron-right': '<path d="m9 18 6-6-6-6"/>',
};
const ic = n => ICONS[n]
  ? `<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`
  : "";

/* ── modal ── */
function modal(title, bodyHtml, footBtns, opt) {
  opt = opt || {};
  $("#mTitle").textContent = title;
  $("#mBody").innerHTML = bodyHtml;
  const foot = $("#mFoot"); foot.innerHTML = "";
  for (const b of footBtns || []) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = b.cls || "ghost"; el.innerHTML = (b.icon ? ic(b.icon) + " " : "") + esc(b.label);
    el.onclick = e => b.onclick && b.onclick(e);
    foot.appendChild(el);
  }
  foot.classList.toggle("hidden", !(footBtns || []).length);
  $("#modal").classList.toggle("wide", !!opt.wide);
  $("#modal").classList.remove("hidden"); $("#overlay").classList.remove("hidden");
}
function closeModal() {
  $("#modal").classList.add("hidden");
  $("#overlay").classList.add("hidden");
}
$("#mClose").innerHTML = ic("x");
$("#mClose").onclick = closeModal;
$("#overlay").onclick = closeModal;
/* A question is the office's (`binaAsk`, the copied block above) — never window.confirm, and no longer a
   dialog of this screen's own. Where the answer is a request that cannot be taken back (a mailbox, an
   account) the question sends it (`run`): its action is busy while the request is out and the service's
   refusal is said IN the question, with the action offered again. */
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  /* Escape dismisses the TOPMOST layer and nothing else — a question, when one is asked, is that layer
     and takes the key itself. */
  if (document.querySelector(".bask, .mlc-ov")) return;
  if (GEAR_OPEN) { setGear(false); return; }
  if (NAV && NAV.isOpen()) return;              // the menu, standing over the page, is that layer — and shuts itself
  if (SELMENU) { SELMENU = false; renderList(); return; }
  if (!$("#modal").classList.contains("hidden")) { closeModal(); return; }
  if (SCREEN === "reader") closeReader();
}, true);
document.addEventListener("click", e => {
  if (SELMENU && !e.target.closest(".gm-selwrap")) { SELMENU = false; renderList(); }
  if (GEAR_OPEN && !e.target.closest(".gearwrap")) setGear(false);
}, true);

/* ── URL routing ─────────────────────────────────────────────────────────────────────────────── */
const pathFor = () =>
    SCREEN === "organizer" ? "/organizer"
  : SCREEN === "settings"  ? "/settings" + (SETTINGS_SECTION ? "/" + SETTINGS_SECTION : "")
  : OPEN ? "/message/" + enc(OPEN)
  : VIEW === "attention" ? "/attention"
  : VIEW ? "/v/" + enc(VIEW)
  : CURLABEL ? "/label/" + enc(CURLABEL)
  : QUERY ? "/?q=" + enc(QUERY) : "/";
function reportRoute(inner) {
  if (!EMBEDDED) return;
  try { window.parent.postMessage({ type: "bina:route", path: inner }, location.origin); }
  catch (e) { /* opaque parent — nothing to mirror */ }
}
const nav = replace => {
  const inner = pathFor();
  const target = href(inner);
  if (location.pathname + location.search !== target)
    history[replace ? "replaceState" : "pushState"]({}, "", target);
  reportRoute(inner);
};
/* Leaving the rules editor with unsaved changes asks first — every navigation entry point goes
   through here (rail, gear menu, search, back buttons, browser history). */
async function leaveGuard() {
  if (SCREEN !== "organizer" || !orgDirty()) return true;
  return binaAsk({ danger: true, ok: "עזיבה בלי שמירה", cancel: "הישארות",
                   title: "לעזוב את העורך בלי לשמור?", body: "יש שינויים בחוקי התיוג שלא נשמרו." });
}
window.addEventListener("beforeunload", e => {
  if (SCREEN === "organizer" && orgDirty()) { e.preventDefault(); e.returnValue = ""; }
});
window.addEventListener("popstate", async () => {
  if (!(await leaveGuard())) { history.pushState({}, "", href("/organizer")); return; }
  applyUrl();
});
async function applyUrl() {
  closeModal();
  const p = innerPath();
  const mm = p.match(/^\/message\/([^/]+)$/);
  const ml = p.match(/^\/label\/([^/]+)$/);
  const mv = p.match(/^\/v\/([^/]+)$/);
  const ms = p.match(/^\/settings(?:\/([^/]+))?$/);
  if (p === "/organizer") { reportRoute(p); return openOrganizer(false); }
  if (ms) { reportRoute(p); return openSettings(ms[1] ? decodeURIComponent(ms[1]) : "", false); }
  const v = mv ? decodeURIComponent(mv[1]) : "";
  VIEW = p === "/attention" ? "attention"
       : v && v !== "inbox" && SYS_VIEWS.some(x => x.id === v) ? v : "";
  QUERY = new URLSearchParams(location.search).get("q") || "";
  CURLABEL = ml ? decodeURIComponent(ml[1]) : "";
  if (NAV) NAV.setSearch(QUERY);
  reportRoute(p);
  if (mm) {
    OPEN = decodeURIComponent(mm[1]);
    /* the list behind the message loads in the background — the reader must not wait for it; once
       it is there, the bar learns its position and its neighbours */
    loadList().then(() => {
      if (SCREEN === "reader" && OPEN) { renderReadBar(MSGCACHE.get(OPEN) || { id: OPEN, labels: [] }); prefetchNeighbours(OPEN); }
    }).catch(() => {});
    return openMessage(OPEN, false);
  }
  OPEN = null;
  showScreen("list");
  await loadList();
}
function showScreen(s) {
  SCREEN = s;
  $("#msgTable").classList.toggle("hidden", s !== "list");
  $("#reader").classList.toggle("hidden", s !== "reader");
  $("#orgPane").classList.toggle("hidden", s !== "organizer");
  $("#setPane").classList.toggle("hidden", s !== "settings");
  $("#statusbar").classList.toggle("hidden", s !== "list");
  markActive(); renderSide();
}
/* the one way to change scope from the UI: guard, set, push, load */
/* `goList` is every entry point's way to the list, and asks first when rules are unsaved. `showList` is
   the list itself, for the one caller that has already asked: the editor's back button, which stops a
   running preview between the two. While it went through `goList` as well, leaving took two yeses. */
async function goList(o) { if (await leaveGuard()) await showList(o); }
async function showList(o) {
  VIEW = o.view || ""; CURLABEL = o.label || ""; QUERY = o.q || ""; OPEN = null;
  if (NAV) NAV.setSearch(QUERY);
  SELECTED.clear(); HIDDEN.clear();
  showScreen("list"); nav(); await loadList();
}

/* ── system views ──────────────────────────────────────────────────────────────────────────────
   Fixed, frequency-ordered. NO counts: the mail service reports none, and a number computed from
   the loaded page of a 10,000-message box is a plausible-looking lie. No "snoozed": there is no
   snooze in the backend model, so there is no such place for mail to be. */
const SYS_VIEWS = [
  { id: 'inbox',   he: 'דואר נכנס',   icon: 'inbox', primary: true },
  { id: 'starred', he: 'מסומן בכוכב', icon: 'star' },
  { id: 'sent',    he: 'נשלח',        icon: 'send' },
  { id: 'drafts',  he: 'טיוטות',      icon: 'pencil' },
  { id: 'attention', he: 'דורש טיפול', icon: 'alert' },
  { id: 'important', he: 'חשוב',      icon: 'flag', more: true },
  { id: 'all',     he: 'כל הדואר',    icon: 'mail', more: true },
  { id: 'spam',    he: 'ספאם',        icon: 'ban',  more: true },
  { id: 'trash',   he: 'אשפה',        icon: 'trash', more: true },
];
let SELMENU = false;                       // select-all predicate menu open?
let DENSITY = "cozy";                      // comfortable · cozy · compact
let GEAR_OPEN = false;
let SETTINGS_SECTION = "";

/* ── the time window — SERVER-SIDE (an IMAP SINCE term), `tz` = the browser's own offset ── */
const WINDOWS = [
  { id: 'all',   he: 'הכל' },
  { id: '30m',   he: '30 דק׳' },
  { id: '1h',    he: 'שעה' },
  { id: 'today', he: 'היום' },
  { id: 'month', he: 'החודש' },
];
const WIN_KEY = "win";
function loadWin() {
  try {
    const v = localStorage.getItem(WIN_KEY);
    return WINDOWS.some(w => w.id === v) ? v : "all";
  } catch (e) { return "all"; }
}
let WIN = loadWin();
let WINBUSY = false;

/* Labels are compared in their CANONICAL form: local reports `UNREAD`, Gmail hands `\Starred`. */
const canonLbl = l => String(l == null ? '' : l).replace(/^\\+/, '').toUpperCase();
const hasLbl = (m, l) => (m.labels || []).some(x => canonLbl(x) === canonLbl(l));
const isUnread = m => hasLbl(m, 'UNREAD');
const isStarred = m => hasLbl(m, 'STARRED');
const isImportant = m => hasLbl(m, 'IMPORTANT');
/* Read state exists only where the backend can report AND write it: the local backend reports \Seen
   as UNREAD and honours UNREAD on add/remove; the Gmail backend exposes neither (X-GM-LABELS carries
   no read flag), so on Gmail the controls are not offered rather than offered and broken. */
const canReadState = () => MODE === "local";

/* ── the side menu — DECLARED, not drawn ───────────────────────────────────────────────────────
   The menu is the office's shared component (BinaNav, spliced into index.html by gate G27). This
   app states WHAT the menu holds — brand, the one primary action, its sections, its search — and
   the component owns how a row looks, what a rail shows instead, and what a phone gets. The seven
   things this screen used to get wrong by itself — a brand row of its own, a compose button of its
   own, a list with no second column, a search box on the PAGE instead of in the menu, a
   hand-rolled "עוד", rows that wrapped, a footer that could be pushed off the bottom — are none of
   them this file's business any more: mailview carries no sidebar markup at all. */
let NAV = null;
let ACCOUNT_LINE = "…";                        // the brand's second line: whose mailbox this is
let LABELS_ERROR = "";                         // set when the label list could not be read
let LABELS_READ = false;                       // …and until it WAS read nothing is said of it: unread is not empty
const SYS_TAIL = SYS_VIEWS.filter(v => !v.more).length;   // the rest is the component's "הצג עוד"

function mountSide() {
  if (NAV || typeof BinaNav === "undefined") return NAV;
  const el = $("#sideNav"); if (!el) return null;
  NAV = BinaNav.mount(el, {
    id: "mail",
    brand: { name: "מייל", sub: ACCOUNT_LINE, avatar: "מ" },
    /* the one action that is always in the same place, at finger size */
    primary: { label: "כתיבה", icon: ic("pencil"), onClick: () => compose() },
    /* The search lives in the MENU and it searches MAIL (`filter:false` is how it says so): the top
       bar belongs to the reader, and a 260px input up there was the first thing a narrow window
       lost. Enter runs it — the same grammar as before, label:"…" from: and all. */
    search: {
      /* (each operator is its own left-to-right token inside the Hebrew hint — ltr(): written bare, the
         line reordered them and the box read «'וכו :label:"…" from חיפוש… (גם», cut at its end) */
      placeholder: `חיפוש… (גם ${ltr("label:")} ו־${ltr("from:")})`,
      filter: false,
      value: QUERY,
      onInput: q => { QUERY = q.trim(); },
    },
    sections: [
      { id: "views",  title: "תיבות", items: viewItems(),  showMore: SYS_TAIL },
      { id: "labels", title: "תוויות", items: labelItems(), showMore: 8,
        actions: [{ icon: ic("refresh"), label: "רענון תוויות", onClick: () => loadLabels() }] },
    ],
    footer: {
      items: [{
        id: "settings", label: "הגדרות", icon: ic("settings"), keepOpen: true,
        onClick: e => { e.stopPropagation(); setGear(!GEAR_OPEN); },
      }],
      /* the popup itself: the component owns rows, and an app still owns a menu that opens over them */
      html: '<div class="gearwrap"><div class="gearmenu hidden" id="gearMenu" role="menu"></div></div>',
    },
  });
  if (!NAV) return null;
  const si = el.querySelector(".bnv-search input");
  if (si) si.addEventListener("keydown", e => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    if (NAV.isOpen()) NAV.close();            // the answer is on the page — behind a menu that stands over it
    goList({ q: si.value.trim() });
  });
  /* The top bar keeps two controls, and only where the menu is a drawer (the component's own
     container query shows them there and nowhere else): the hamburger opens the menu, the magnifier
     opens it ON the search, because on a phone the search cannot live on the page — it would be a
     stub next to the title, and it can be a whole drawer instead. The page only places them
     (`data-nav-toggle`, `data-nav-find`); the component draws and wires them. */
  return NAV;
}

/* where mail can be — a fixed, frequency-ordered list, the tail kept behind "הצג עוד". No counts:
   the mail service reports none, and a number computed from the loaded page of a 10,000-message box
   is a plausible-looking lie. No "snoozed": there is no snooze in the backend model. */
function viewItems() {
  return SYS_VIEWS.map(v => ({
    id: v.id,
    label: v.he,
    icon: ic(v.icon),
    href: href(v.id === 'inbox' ? '/' : v.id === 'attention' ? '/attention' : '/v/' + v.id),
    onClick: e => { e.preventDefault(); goList({ view: v.id === 'inbox' ? '' : v.id }); },
  }));
}

/* the reader's OWN labels, flat; the dot rides in the row's TRAILING slot so a long label keeps the
   whole width and the dot can never be what pushes it out of the row. */
function labelItems() {
  if (LABELS_ERROR) return [{ id: "labels-error", label: "לא ניתן לטעון תוויות", icon: ic("alert"), disabled: true, title: LABELS_ERROR }];
  // (a mailbox that could not be reached said «אין תוויות עדיין» under «לא ניתן להתחבר לתיבה»: its labels were never asked)
  if (!LABELS_READ) return [];
  if (!LABELS.length) return [{ id: "labels-empty", label: "אין תוויות עדיין", disabled: true }];
  return LABELS.slice().sort().map(name => ({
    id: "label:" + name,
    label: name,
    href: href("/label/" + enc(name)),
    tail: '<span class="dot n"></span>',
    onClick: e => { e.preventDefault(); goList({ label: name }); },
  }));
}

function renderSide() {
  const nav = mountSide(); if (!nav) return;
  nav.setBrand({ sub: ACCOUNT_LINE });
  nav.setItems("views", viewItems(), SYS_TAIL);
  nav.setItems("labels", labelItems(), 8);
  markActive();
}

/* ── the settings menu ── */
function setGear(open) {
  GEAR_OPEN = open;
  const menu = $("#gearMenu"); if (!menu) return;
  menu.classList.toggle("hidden", !open);
  const row = document.querySelector('#sideNav [data-bnv-id="settings"]');
  if (row) row.setAttribute("aria-expanded", String(open));
}
function renderGear() {
  if (!mountSide()) return;
  const menu = $("#gearMenu"); if (!menu) return;
  menu.innerHTML = `
    <a href="${esc(href('/organizer'))}" data-go="organizer" role="menuitem"><span class="ic">${ic('tag')}</span>
      <span><span>חוקי תיוג</span><span class="sub">מה מתויג אוטומטית, לפי אילו חוקים, באיזה סדר</span></span></a>
    <a href="${esc(href('/settings'))}" data-go="settings" role="menuitem"><span class="ic">${ic('server')}</span>
      <span><span>הגדרות תיבה</span><span class="sub">כתובות בחברה · דואר פרטי · חיבור חשבון</span></span></a>`;
  menu.querySelectorAll("[data-go]").forEach(a => a.onclick = async e => {
    e.preventDefault(); setGear(false);
    /* The row that opens this menu keeps the drawer open (`keepOpen`: the menu lives inside it), so a
       choice made here has to close it — on a phone the screen just chosen opened BEHIND the drawer. */
    if (NAV && NAV.isOpen()) NAV.close();
    if (a.dataset.go === "organizer") openOrganizer(true); else openSettings("", true);
  });
}

/* ── undo — act now, offer the REAL reversal for a few seconds. The offer is the office's notice with
   «ביטול» in it, and there is one offer at a time: a new action takes the place of the last one's. ── */
let UNDO_N = null;
function snack(text, undoFn) {
  if (UNDO_N) UNDO_N.remove();
  // (a reversal that fails is said by its own request — `jf` — so nothing is left to catch but the rejection)
  UNDO_N = binaTell(text, "ok", undoFn ? { ms: 7000, act: ["ביטול", () => { Promise.resolve(undoFn()).catch(() => {}); }] } : 7000);
}

/* ── sidebar: the reader's own labels, flat (the rows are the component's) ── */
async function loadLabels() {
  try {
    LABELS = nonSys((await jf("api/labels", { silent: true })).labels || []).filter(n => !isMachineLabel(n));
    LABELS_ERROR = ""; LABELS_READ = true;
  } catch (e) {
    LABELS_ERROR = e.message || "שגיאה";
  }
  renderSide();
}
/* ONE row is current, and which one it is has exactly three answers: a label, a view, or nothing
   while a search is what the list is showing. */
function markActive() {
  if (!NAV) return;
  const inList = SCREEN === "list" || SCREEN === "reader";
  NAV.setActive(!inList ? null
    : CURLABEL ? "label:" + CURLABEL
    : QUERY ? null
    : VIEW === "attention" ? "attention"
    : (VIEW || "inbox"));
}

/* ── message list ── */
function listQuery(limit, cursor) {
  return "api/messages?limit=" + limit
    + (VIEW ? "&view=" + enc(VIEW) : "")
    + (CURLABEL ? "&label=" + enc(CURLABEL) : "")
    + (QUERY ? "&q=" + enc(QUERY) : "")
    + (cursor ? "&before_uid=" + cursor : "")
    /* `tz` rides along only WITH a window: the calendar windows are cut in the reader's own day */
    + (WIN !== "all" ? "&win=" + WIN + "&tz=" + new Date().getTimezoneOffset() : "")
    + (TESTSHOW === null ? "" : "&test=" + (TESTSHOW ? "1" : "0"));
}
let LIST_SEQ = 0;
async function fetchPage(seq) {
  if (LOADING) return;
  LOADING = true;
  try {
    const d = await jf(listQuery(100, CURSOR), { silent: true });
    if (seq !== LIST_SEQ) return;               // an abandoned scope's page must not land
    MSGS.push(...d.messages);
    TOTAL = d.total ?? MSGS.length;
    HASMORE = !!d.has_more; CURSOR = d.next_cursor || 0;
    TESTTOTAL += d.test_total || 0; TESTHIDDEN = !!d.test_hidden;
  } finally { LOADING = false; }
}
function viewTitleHtml() {
  const sv = SYS_VIEWS.find(v => v.id === (VIEW || "inbox"));
  return CURLABEL ? `${ic("tag")} <bdi>${esc(CURLABEL)}</bdi>`
    : QUERY   ? `${ic("search")} חיפוש: <bdi>${esc(QUERY)}</bdi>`
    : sv      ? `${ic(sv.icon)} ${esc(sv.he)}` : `${ic("inbox")} דואר נכנס`;
}
let LIST_ERR = null;
async function loadList() {
  const seq = ++LIST_SEQ;
  $("#viewTitle").innerHTML = viewTitleHtml();
  markActive();
  MSGS = []; TOTAL = 0; HASMORE = false; CURSOR = 0; TESTTOTAL = 0; LIST_ERR = null;
  EXPTHREADS.clear(); SHOWCHIPS.clear();
  if (SCREEN === "list") $("#msgTable").innerHTML = `<div class="empty">טוען…</div>`;
  $("#statusbar").textContent = "טוען…";
  try {
    await fetchPage(seq);
    // pages can come back mostly test-filtered — keep pulling until the screen has content
    for (let i = 0; seq === LIST_SEQ && HASMORE && MSGS.length < 30 && i < 8; i++) await fetchPage(seq);
  } catch (e) {
    if (seq !== LIST_SEQ) return;
    LIST_ERR = e;
  }
  if (seq !== LIST_SEQ) return;
  renderList(); renderSide();
}
let DIGGING = false;
async function digMore(target = 25) {
  if (DIGGING || LIST_ERR) return;
  DIGGING = true;
  const seq = LIST_SEQ, start = MSGS.length;
  try {
    for (let i = 0; seq === LIST_SEQ && HASMORE && MSGS.length - start < target && i < 20; i++) {
      await fetchPage(seq);
      $("#statusbar").textContent = `טוען עוד… (${one(MSGS.length, "הודעה אחת", "הודעות")}, נסרקו עד ${num(TOTAL)})`;
    }
  } catch (e) { /* the notice already carries the reason; the list keeps what it has */ }
  finally { DIGGING = false; }
  if (seq === LIST_SEQ) renderList();
}
$("#msgTable").addEventListener("scroll", () => {
  const el = $("#msgTable");
  if (!HASMORE || DIGGING) return;
  if (el.scrollTop + el.clientHeight < el.scrollHeight - 500) return;
  digMore();
});

const EXPTHREADS = new Set(), SHOWCHIPS = new Set();
function initials(name) {
  const t = String(name || '?').trim().replace(/^["']+/, '');
  return (t[0] || '?').toUpperCase();
}
function avatarColor(name) {
  // the office palette's line steps: they turn with the theme, so the initial written on them in the
  // surface's colour reads on a light ground and on a dark one
  const P = ['sky-d', 'olive-d', 'plum-d', 'lime-d', 'violet', 'muted'].map(n => `var(--${n})`);
  let h = 0; const t = String(name || '');
  for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) >>> 0;
  return P[h % P.length];
}
/* Row: checkbox · star · important · sender · subject+snippet · attachment · triage dot · date, and
   on hover the date is REPLACED by the quick actions that the backend can actually perform. */
function rowHtml(m, cls) {
  const chips = nonSys(m.labels).filter(l => !isMachineLabel(l) && !TRIAGE_ALL_NAMES.has(l));
  const chipHtml = SHOWCHIPS.has(m.id)
    ? chips.map(l => `<span class="chip"><bdi>${esc(l)}</bdi></span>`).join("")
    : (chips.length ? `<span class="plusn" data-chips="${esc(m.id)}">+${chips.length}</span>` : "");
  const unread = isUnread(m);
  const triage = triageState(m);
  const who = fromName(m.from);
  const snip = m.snippet ? ` <span class="gm-snip">— ${esc(m.snippet)}</span>` : "";
  const picked = SELECTED.has(m.id);
  const rowBusy = BUSY_IDS.has(m.id);
  return `<div class="gm-row ${cls || ""} ${unread ? "unread" : ""} ${picked ? "sel" : ""} ${rowBusy ? "busy" : ""}"
               data-id="${esc(m.id)}" role="listitem" tabindex="0" aria-selected="${picked}" ${rowBusy ? 'aria-busy="true"' : ""}>
    <span class="gm-cb ${picked ? "on" : ""}" data-cb="${esc(m.id)}" role="checkbox"
          aria-checked="${picked}" aria-label="בחירה"></span>
    <button class="gm-star ${isStarred(m) ? "on" : ""}" data-star="${esc(m.id)}" type="button" aria-label="סימון בכוכב" title="סימון בכוכב">${ic("star")}</button>
    <button class="gm-imp ${isImportant(m) ? "on" : ""}" data-imp="${esc(m.id)}" type="button" aria-label="סימון כחשוב" title="סימון כחשוב">${ic("flag")}</button>
    <span class="gm-av" style="background:${avatarColor(who)}">${esc(initials(who))}</span>
    <span class="gm-from"><bdi>${esc(who)}</bdi></span>
    <span class="gm-main">
      <bdi class="gm-sub">${esc(m.subject || "(ללא נושא)")}</bdi>${snip}
      ${chipHtml}
    </span>
    ${m.hasAttachment ? `<span class="gm-att" title="קובץ מצורף">${ic("paperclip")}</span>` : `<span class="gm-att"></span>`}
    ${triage
      ? `<span class="gm-triage ${triage}" role="img" aria-label="${TRIAGE_TITLE[triage]}" title="${TRIAGE_TITLE[triage]}"></span>`
      : `<span class="gm-triage"></span>`}
    <span class="gm-when">${fmtDate(m.date)}</span>
    <span class="gm-acts">
      <button class="gm-act" data-act="archive" data-id="${esc(m.id)}" type="button" title="העברה לארכיון" aria-label="העברה לארכיון">${ic("archive")}</button>
      ${canReadState() ? `<button class="gm-act" data-act="read" data-id="${esc(m.id)}" type="button" title="${unread ? "סימון כנקרא" : "סימון כלא נקרא"}" aria-label="${unread ? "סימון כנקרא" : "סימון כלא נקרא"}">${ic(unread ? "mail-open" : "mail")}</button>` : ""}
    </span>
  </div>`;
}
function emptyText() {
  if (WIN !== "all") {
    const w = WINDOWS.find(x => x.id === WIN);
    return `אין הודעות בטווח „${w ? w.he : WIN}” · <a class="testline" data-win="all">הצג את הכל</a>`;
  }
  if (QUERY) return "לא נמצאו הודעות תואמות";
  if (CURLABEL) return "אין הודעות בתווית זו";
  return { "": "סיימת! אין דואר חדש", inbox: "סיימת! אין דואר חדש",
           attention: "אין מסמכים שדורשים טיפול",
           starred: "לא סימנת הודעות בכוכב",
           sent: "לא נשלחו הודעות", drafts: "אין טיוטות",
           important: "אין הודעות שסומנו כחשובות", spam: "אין ספאם", trash: "האשפה ריקה"
         }[VIEW] || "אין הודעות";
}
/* every scope is server-side; only rows an action just removed are hidden here until the next load */
function visibleMsgs() { return MSGS.filter(m => !HIDDEN.has(m.id)); }

function winSeg() {
  return `<span class="seg gm-win${WINBUSY ? " busy" : ""}" role="radiogroup" aria-label="טווח זמן">`
    + WINDOWS.map(w => `<button role="radio" type="button" aria-checked="${w.id === WIN}"`
        + ` class="${w.id === WIN ? "on" : ""}" data-win="${w.id}">${w.he}</button>`).join("")
    + `</span>`;
}
async function setWin(id) {
  if (id === WIN || WINBUSY) return;
  if (!WINDOWS.some(w => w.id === id)) return;
  WIN = id;
  try { localStorage.setItem(WIN_KEY, id); } catch (e) { /* storage disabled — the window still works */ }
  WINBUSY = true;
  renderList();
  try { await loadList(); } finally { WINBUSY = false; renderList(); }
}

let REFRESHING = false;
function renderList() {
  if (SCREEN !== "list") return;
  const order = [], byThread = new Map();
  for (const m of visibleMsgs()) {
    const k = m.threadId || m.id;
    if (byThread.has(k)) byThread.get(k).push(m);
    else { byThread.set(k, [m]); order.push(k); }
  }
  let html = "", lastDay = null;
  for (const k of order) {
    const items = byThread.get(k), head = items[0];
    const day = dayKey(head.date);
    if (day !== lastDay) { html += `<div class="gm-day">${day}</div>`; lastDay = day; }
    let row = rowHtml(head, "");
    if (items.length > 1) {
      const pill = `<span class="thx" data-th="${esc(k)}" title="הודעות בשיחה">${EXPTHREADS.has(k) ? ic("chevron") : items.length}</span>`;
      row = row.replace('</span>\n    <span class="gm-att"', pill + '</span>\n    <span class="gm-att"');
    }
    html += row;
    if (items.length > 1 && EXPTHREADS.has(k))
      for (const sub of items.slice(1)) html += rowHtml(sub, "subrow");
  }
  const nSel = SELECTED.size;
  const shown = visibleMsgs().length;
  const selMenu = SELMENU ? `<div class="gm-selmenu" role="menu">
      ${[["all", "הכל"], ["none", "כלום"], ...(canReadState() ? [["read", "נקראו"], ["unread", "לא נקראו"]] : []),
         ["starred", "מסומנים בכוכב"], ["unstarred", "ללא כוכב"]]
        .map(([k, t]) => `<button data-sel="${k}" type="button" role="menuitem">${t}</button>`).join("")}
    </div>` : "";
  /* the window and the refresh stay visible during a bulk selection — a selection is not a mode */
  const toolbar = `<div class="gm-tools">
      <span class="gm-selwrap">
        <span class="gm-cb ${nSel ? (nSel === shown ? "on" : "some") : ""}" id="gmAll"
              role="checkbox" aria-checked="${nSel > 0}" aria-label="בחירת הכל"></span>
        <button class="gm-caret" id="gmAllCaret" type="button" aria-haspopup="menu" aria-expanded="${SELMENU}" aria-label="אפשרויות בחירה">${ic("chevron")}</button>
        ${selMenu}
      </span>
      ${nSel ? `<span class="gm-selinfo">${nSel === 1 ? "נבחרה" : "נבחרו"} ${num(nSel)}</span>
           <span class="gm-bulk">
           <button class="gm-tbtn" data-bulk="archive" type="button">${ic("archive")} ארכיון</button>
           ${canReadState() ? `<button class="gm-tbtn" data-bulk="read" type="button">${ic("mail-open")} סימון כנקרא</button>
           <button class="gm-tbtn" data-bulk="unread" type="button">${ic("mail")} סימון כלא נקרא</button>` : ""}
           <button class="gm-tbtn" data-bulk="clear" type="button">${ic("x")} ביטול הבחירה</button></span>` : ""}
      <button class="gm-tbtn" id="gmRefresh" type="button" title="רענון" aria-label="רענון" ${REFRESHING ? 'disabled aria-busy="true"' : ""}>${ic("refresh")}</button>
      <button class="gm-tbtn" id="gmDensity" type="button" title="צפיפות התצוגה" aria-label="צפיפות התצוגה">${ic("menu")}</button>
      ${winSeg()}
      <span class="gm-count">${shown ? `${num(shown)} מתוך ${num(TOTAL)}` : ""}</span>
    </div>`;
  let body;
  if (LIST_ERR) {
    body = `<div class="failbox">${ic("alert")}<b>לא ניתן לטעון את ההודעות</b>
      <span class="why"><bdi>${esc(LIST_ERR.message)}</bdi>${LIST_ERR.detail ? ` · <bdi>${esc(LIST_ERR.detail)}</bdi>` : ""}</span>
      <button class="btn" id="listRetry" type="button">${ic("refresh")} נסה שוב</button></div>`;
  } else {
    body = order.length ? `<div class="gm-list" role="list">${html}</div>` : `<div class="empty">${emptyText()}</div>`;
  }
  $("#msgTable").innerHTML = toolbar + body;
  const retry = $("#listRetry"); if (retry) retry.onclick = () => busy(retry, refreshView);
  $("#statusbar").innerHTML = LIST_ERR ? "" :
    (TOTAL > shown ? `מציג ${num(shown)} מתוך ${num(TOTAL)}` : one(shown, "הודעה אחת", "הודעות"))
    + (order.length !== shown ? ` · ${one(order.length, "שיחה אחת", "שיחות")}` : "")
    + (HASMORE ? ` · <a class="testline" id="moreBtn">טען עוד</a>` : "")
    + (TESTTOTAL
      ? ` · <a class="testline" id="testTog">${TESTHIDDEN ? `דואר בדיקה מוסתר (${TESTTOTAL}) — הצג` : `הסתר דואר בדיקה (${TESTTOTAL})`}</a>` : "");
  const tog = $("#testTog");
  if (tog) tog.onclick = () => { TESTSHOW = TESTHIDDEN; loadList(); };
  const mb = $("#moreBtn");
  if (mb) mb.onclick = () => digMore();
  reportWidget();
}
/* The console's desktop mode draws a window pushed far to the side as a small widget; this is what
   that widget says about the list on screen. A label only — no action — and nothing if not embedded. */
function reportWidget() {
  if (!EMBEDDED) return;
  const n = visibleMsgs().filter(isUnread).length;
  try { window.parent.postMessage({ type: "bina:widget", label: n ? one(n, "1 לא נקראה", "לא נקראו") : "אין חדשות" }, location.origin); }   // (it said «1 לא נקראו»; the words the notifications' widget says, which has no room for «אחת»)
  catch (e) { /* opaque parent — nothing to report */ }
}
function toggleSet(set, id) { set.has(id) ? set.delete(id) : set.add(id); }

/* ── marks: the ONE path every state change takes ─────────────────────────────────────────────
   Optimistic paint, then the request, then either the undo offer (a real inverse request) or the
   revert. `leavesScope` says whether the message no longer belongs to the list being shown (archive
   from the inbox, unstar in the starred view) — then the row is hidden until the next load. */
const MARK_LABEL = { starred: "STARRED", important: "IMPORTANT", unread: "UNREAD", archived: "INBOX" };
function setLocalLabel(m, label, present) {
  m.labels = (m.labels || []).filter(l => canonLbl(l) !== label);
  if (present) m.labels.push(label);
}
function leavesScope(mark, on) {
  const scope = CURLABEL || QUERY ? "" : (VIEW || "inbox");
  return (scope === "inbox" && mark === "archived" && on)
      || (scope === "starred" && mark === "starred" && !on)
      || (scope === "important" && mark === "important" && !on);
}
const MARK_TEXT = {
  "archived:on": ["הועברה לארכיון", "הועברו לארכיון"], "archived:off": ["הוחזרה לדואר הנכנס", "הוחזרו לדואר הנכנס"],
  "unread:off": ["סומנה כנקראה", "סומנו כנקראו"],      "unread:on": ["סומנה כלא נקראה", "סומנו כלא נקראו"],
  "starred:on": ["סומנה בכוכב", "סומנו בכוכב"],        "starred:off": ["הכוכב הוסר", "הכוכב הוסר"],
  "important:on": ["סומנה כחשובה", "סומנו כחשובות"],   "important:off": ["סימון החשיבות הוסר", "סימון החשיבות הוסר"],
};
async function applyMark(ids, mark, on, o) {
  o = o || {};
  ids = ids.filter(id => !BUSY_IDS.has(id));
  if (!ids.length) return false;
  const label = MARK_LABEL[mark];
  const present = mark === "archived" ? !on : on;
  const prev = ids.map(id => { const m = MSGS.find(x => x.id === id); return { id, labels: m ? (m.labels || []).slice() : null, hidden: HIDDEN.has(id) }; });
  for (const id of ids) {
    const m = MSGS.find(x => x.id === id);
    if (m) setLocalLabel(m, label, present);
    const cached = MSGCACHE.get(id); if (cached) setLocalLabel(cached, label, present);
    if (leavesScope(mark, on)) HIDDEN.add(id); else if (leavesScope(mark, !on)) HIDDEN.delete(id);
    SELECTED.delete(id); BUSY_IDS.add(id);
  }
  renderList(); if (SCREEN === "reader" && ids.includes(OPEN)) renderReadBar(MSGCACHE.get(OPEN) || MSGS.find(x => x.id === OPEN) || { id: OPEN, labels: [] });
  try {
    await jf("api/mark", post({ ids, mark, on }));
  } catch (e) {
    for (const p of prev) {
      const m = MSGS.find(x => x.id === p.id);
      if (m && p.labels) m.labels = p.labels;
      const cached = MSGCACHE.get(p.id); if (cached && p.labels) cached.labels = p.labels.slice();
      if (p.hidden) HIDDEN.add(p.id); else HIDDEN.delete(p.id);
    }
    ids.forEach(id => BUSY_IDS.delete(id));
    renderList(); if (SCREEN === "reader") renderReadBar(MSGCACHE.get(OPEN) || { id: OPEN, labels: [] });
    return false;
  }
  ids.forEach(id => BUSY_IDS.delete(id));
  renderList();
  if (!o.quiet) {
    const t = MARK_TEXT[mark + ":" + (on ? "on" : "off")] || ["בוצע", "בוצע"];
    const text = ids.length === 1 ? "ההודעה " + t[0] : `${ids.length} הודעות ${t[1]}`;
    snack(text, () => applyMark(ids, mark, !on, { quiet: true }));
  }
  return true;
}

$("#msgTable").addEventListener("click", e => {
  const pn = e.target.closest(".plusn");
  if (pn) { SHOWCHIPS.add(pn.dataset.chips); renderList(); return; }
  const th = e.target.closest(".thx");
  if (th) { EXPTHREADS.has(th.dataset.th) ? EXPTHREADS.delete(th.dataset.th) : EXPTHREADS.add(th.dataset.th); renderList(); return; }

  const star = e.target.closest("[data-star]");
  if (star) { const m = MSGS.find(x => x.id === star.dataset.star); if (m) applyMark([m.id], "starred", !isStarred(m)); return; }
  const imp = e.target.closest("[data-imp]");
  if (imp) { const m = MSGS.find(x => x.id === imp.dataset.imp); if (m) applyMark([m.id], "important", !isImportant(m)); return; }
  const cb = e.target.closest("[data-cb]");
  if (cb) { toggleSet(SELECTED, cb.dataset.cb); renderList(); return; }

  const act = e.target.closest(".gm-act");
  if (act) {
    const id = act.dataset.id, m = MSGS.find(x => x.id === id);
    if (!m) return;
    if (act.dataset.act === "archive") applyMark([id], "archived", true);
    else if (act.dataset.act === "read") applyMark([id], "unread", !isUnread(m));
    return;
  }

  const all = e.target.closest("#gmAll");
  if (all) {
    const vis = visibleMsgs();
    if (SELECTED.size) SELECTED.clear(); else vis.forEach(m => SELECTED.add(m.id));
    SELMENU = false; renderList(); return;
  }
  if (e.target.closest("#gmAllCaret")) { SELMENU = !SELMENU; renderList(); return; }
  const sel = e.target.closest("[data-sel]");
  if (sel) {
    const vis = visibleMsgs(), k = sel.dataset.sel;
    const pred = { all: () => true, none: () => false,
                   read: m => !isUnread(m), unread: isUnread,
                   starred: isStarred, unstarred: m => !isStarred(m) }[k];
    SELECTED.clear();
    vis.filter(pred).forEach(m => SELECTED.add(m.id));
    SELMENU = false; renderList(); return;
  }

  const bulk = e.target.closest("[data-bulk]");
  if (bulk) {
    const ids = Array.from(SELECTED), k = bulk.dataset.bulk;
    if (k === "clear") { SELECTED.clear(); renderList(); return; }
    if (k === "read")    applyMark(ids, "unread", false);
    if (k === "unread")  applyMark(ids, "unread", true);
    if (k === "archive") applyMark(ids, "archived", true);
    return;
  }
  const winBtn = e.target.closest("[data-win]");
  if (winBtn) { setWin(winBtn.dataset.win); return; }
  if (e.target.closest("#gmRefresh")) { refreshView(); return; }
  if (e.target.closest("#gmDensity")) {
    DENSITY = DENSITY === "cozy" ? "compact" : DENSITY === "compact" ? "comfortable" : "cozy";
    document.body.dataset.density = DENSITY;
    binaTell({ comfortable: "צפיפות: נוחה", cozy: "צפיפות: רגילה", compact: "צפיפות: צפופה" }[DENSITY]);
    renderList(); return;
  }

  const row = e.target.closest(".gm-row[data-id]");
  if (row) openMessage(row.dataset.id);
});
$("#msgTable").addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  const row = e.target.closest(".gm-row[data-id]");
  if (row) openMessage(row.dataset.id);
});

async function refreshView() {
  if (REFRESHING) return;
  REFRESHING = true; renderList();
  try { await loadList(); } finally { REFRESHING = false; renderList(); }
  renderSide();
}

/* ── reader ──────────────────────────────────────────────────────────────────────────────────── */
let OPEN_SEQ = 0;
function readerState(kind, text, retry) {
  const st = $("#rState");
  if (!kind) { st.classList.add("hidden"); $("#rContent").classList.remove("hidden"); return; }
  $("#rContent").classList.add("hidden");
  st.className = "rp-state" + (kind === "err" ? " err" : "");
  st.innerHTML = kind === "loading"
    ? `<div class="skel"><div style="width:52%"></div><div style="width:34%"></div><div style="width:88%"></div><div style="width:76%"></div><div style="width:81%"></div></div><span>טוען הודעה…</span>`
    : `${ic("alert")}<b>לא ניתן לטעון את ההודעה</b><span class="why"><bdi>${esc(text)}</bdi></span>
       <button class="btn" id="rRetry" type="button">${ic("refresh")} נסה שוב</button>`;
  st.classList.remove("hidden");
  const b = $("#rRetry"); if (b && retry) b.onclick = () => busy(b, retry);
}
async function fetchMessage(id, silent) {
  const cached = MSGCACHE.get(id);
  if (cached) return cached;
  const m = await jf("api/message/" + enc(id), { silent: !!silent });
  cacheSet(id, m);
  return m;
}
async function openMessage(id, push = true) {
  OPEN = id;
  showScreen("reader");
  if (push) nav();
  const seq = ++OPEN_SEQ;
  const listRow = MSGS.find(x => x.id === id);
  renderReadBar(listRow || { id, labels: [] });
  $("#rSubject").innerHTML = listRow ? `<bdi>${esc(listRow.subject || "(ללא נושא)")}</bdi>` : "";
  let m = MSGCACHE.get(id);
  if (!m) {
    readerState("loading");
    try { m = await fetchMessage(id, true); }
    catch (e) { if (seq !== OPEN_SEQ) return; readerState("err", e.detail ? `${e.message} · ${e.detail}` : e.message, () => openMessage(id, false)); return; }
  }
  if (seq !== OPEN_SEQ) return;
  readerState(null);
  renderMessage(m, seq);
}
function renderMessage(m, seq) {
  $("#rSubject").innerHTML = `<bdi>${esc(m.subject || "(ללא נושא)")}</bdi>`;
  $("#rMeta").innerHTML =
    `<div>מאת: <b><bdi>${esc(m.from || "")}</bdi></b></div>` +
    `<div>אל: <bdi>${esc(m.to || "")}</bdi> · ${esc(fmtDate(m.date))}</div>`;
  renderReadBar(m);
  renderTags(m);
  const doc = $("#rDoc"); doc.className = "rp-doc hidden";
  jf("api/doc-context/" + enc(m.id), { silent: true })
    .then(d => { if (seq === OPEN_SEQ) renderDocPanel(d); })
    .catch(e => { if (seq === OPEN_SEQ) renderDocPanel({ found: 0, docs: [], unavailable: true, error: e.message }); });
  const body = $("#rBody");
  if (m.body_html) {
    body.innerHTML = "";
    const f = document.createElement("iframe");
    f.sandbox = ""; f.srcdoc = m.body_html; f.title = "תוכן ההודעה";
    body.appendChild(f);
  } else {
    body.innerHTML = `<pre>${esc(m.body_text || "")}</pre>`;
  }
  $("#rAtts").innerHTML = attCards(m, m.id);
  renderThread(m, seq);
  $("#rReply").innerHTML =
    `<button data-r="reply" type="button">${ic("reply")} השב</button>
     <button data-r="replyall" type="button">${ic("reply-all")} השב לכולם</button>
     <button data-r="forward" type="button">${ic("forward")} העבר</button>
     <button data-r="print" type="button">${ic("print")} הדפס</button>`;
  $("#rReply").querySelectorAll("[data-r]").forEach(b => b.onclick = () => readAction(b.dataset.r, b));
  $("#rScroll").scrollTop = 0;
  /* the message the reader is likeliest to open next is already on its way — after this one has
     painted, sequentially, so the prefetch never competes with the open on the mailbox's one lock */
  if (listRowIndex(m.id) !== -1) setTimeout(() => prefetchNeighbours(m.id), 150);
  /* opening a message is reading it — a real write, where the backend can take it */
  if (canReadState() && isUnread(m)) applyMark([m.id], "unread", false, { quiet: true });
}
const listRowIndex = id => visibleMsgs().findIndex(x => x.id === id);
let PREFETCH_CHAIN = Promise.resolve();
function prefetchNeighbours(id) {
  const vis = visibleMsgs(), at = vis.findIndex(x => x.id === id);
  if (at === -1) return;
  for (const n of [vis[at + 1], vis[at - 1]]) {
    if (!n || MSGCACHE.has(n.id)) continue;
    PREFETCH_CHAIN = PREFETCH_CHAIN.then(() => MSGCACHE.has(n.id) ? null : fetchMessage(n.id, true)).catch(() => {});
  }
}
/* Bar state depends on the message: the ← always goes back, the actions act on THIS message, and
   ‹ › walk the same list the user was reading. RTL: "previous" sits on the right and points right. */
function renderReadBar(m) {
  const vis = visibleMsgs(), at = vis.findIndex(x => x.id === m.id);
  $("#rClose").innerHTML = ic("back");
  $("#rPos").textContent = at === -1 ? "" : `${num(at + 1)} מתוך ${num(vis.length)}`;
  const b = (k, icon, title, cls) => `<button class="gm-act ${cls || ""}" data-r="${k}" type="button" title="${title}" aria-label="${title}">${ic(icon)}</button>`;
  $("#rActs").innerHTML =
    b("archive", "archive", "העברה לארכיון")
    + (canReadState() ? b("unread", "mail", "סימון כלא נקרא") : "")
    + b("star", "star", isStarred(m) ? "הסרת הכוכב" : "סימון בכוכב", isStarred(m) ? "on" : "")
    + b("print", "print", "הדפסה");
  $("#rActs").querySelectorAll("[data-r]").forEach(x => x.onclick = () => readAction(x.dataset.r, x));
  const prev = $("#rPrev"), next = $("#rNext");
  prev.innerHTML = ic("back"); next.innerHTML = ic("prev");
  prev.disabled = at <= 0; next.disabled = at === -1 || at >= vis.length - 1;
  prev.onclick = () => readAction("prev"); next.onclick = () => readAction("next");
}
async function readAction(k, btn) {
  const id = OPEN; if (!id) return;
  const vis = visibleMsgs(), at = vis.findIndex(x => x.id === id);
  if (k === "prev" && vis[at - 1]) return openMessage(vis[at - 1].id);
  if (k === "next" && vis[at + 1]) return openMessage(vis[at + 1].id);
  const m = MSGCACHE.get(id) || vis[at] || { id, labels: [] };
  if (k === "star") return busy(btn, () => applyMark([id], "starred", !isStarred(m)));
  if (k === "print") return printMessage(MSGCACHE.get(id));
  if (k === "reply" || k === "replyall" || k === "forward") return busy(btn, () => composeFrom(k));
  if (k === "unread") {
    /* mark unread and go back: a message you just marked unread is one you are done with */
    const ok = await busy(btn, () => applyMark([id], "unread", true));
    if (ok) closeReader();
    return;
  }
  if (k === "archive") {
    const ok = await busy(btn, () => applyMark([id], "archived", true));
    if (ok) closeReader();
  }
}
/* Print = a real print of the open message: a fresh window with only the headers and the body
   (scripts and remote content locked out by its own CSP), then the browser's print dialog. When
   the window is blocked, the page prints itself with the print stylesheet instead. */
function printMessage(m) {
  if (!m) return binaTell("ההודעה עדיין לא נטענה", "warn");
  let w = null;
  try { w = window.open("about:blank", "_blank", "width=900,height=720"); } catch (e) { w = null; }
  if (!w) { window.print(); return; }
  const html = m.body_html
    ? (String(m.body_html).match(/<body[^>]*>([\s\S]*)<\/body>/i) || [null, m.body_html])[1].replace(/<script[\s\S]*?<\/script>/gi, "")
    : `<pre style="white-space:pre-wrap;font:inherit">${esc(m.body_text || "")}</pre>`;
  const csp = "default-src 'none'; style-src 'unsafe-inline'; img-src data: https: http:; font-src data:";
  const atts = (m.attachments || []).map(a => esc(a.filename || "")).filter(Boolean).join(" · ");
  const doc = `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="${csp}"><title>${esc(m.subject || "הודעה")}</title>
    <style>body{font:14px/1.6 "Segoe UI",system-ui,"Noto Sans Hebrew",Arial,sans-serif;color:#000;margin:24px}
      h1{font-size:19px;margin:0 0 8px}.h{color:#444;font-size:12.5px;border-bottom:1px solid #ccc;padding-bottom:10px;margin-bottom:14px}
      .h div{margin:2px 0}img{max-width:100%;height:auto}table{max-width:100%}</style></head>
    <body><h1><bdi>${esc(m.subject || "(ללא נושא)")}</bdi></h1>
    <div class="h"><div>מאת: <bdi>${esc(m.from || "")}</bdi></div><div>אל: <bdi>${esc(m.to || "")}</bdi></div>
    <div>תאריך: ${esc(m.date || "")}</div>${atts ? `<div>קבצים מצורפים: ${atts}</div>` : ""}</div>
    <div dir="auto">${html}</div></body></html>`;
  try {
    w.document.open(); w.document.write(doc); w.document.close();
    w.focus();
    setTimeout(() => { try { w.print(); } catch (e) { /* the window is open — the user can print it */ } }, 350);
  } catch (e) { fail("ההדפסה נכשלה", e.message); }
}
async function composeFrom(kind) {
  if (!OPEN) return;
  let m;
  try { m = await fetchMessage(OPEN); } catch (e) { return; }
  const subj = m.subject || "";
  const plain = m.body_text != null && m.body_text !== "" ? m.body_text
    : (() => { const d = document.createElement("div"); d.innerHTML = m.body_html || ""; return d.textContent || ""; })();
  const when = String(m.date || "").replace("T", " ").slice(0, 16);
  if (kind === "forward") {
    compose({ to: "", subject: /^fwd:/i.test(subj) ? subj : "Fwd: " + subj,
      body: `\n\n---------- הודעה שהועברה ----------\nמאת: ${m.from || ""}\nתאריך: ${when}\n` +
            `אל: ${m.to || ""}\nנושא: ${subj}\n\n${plain}` });
    return;
  }
  let to = addrOf(m.from);
  if (kind === "replyall" && m.to && addrOf(m.to) !== to) to += ", " + m.to;
  compose({ to, subject: /^re:/i.test(subj) ? subj : "Re: " + subj,
    body: `\n\nבתאריך ${when}, ${fromName(m.from)} כתב/ה:\n` +
          plain.split("\n").map(l => "> " + l).join("\n") });
}

/* ── attachments: cards, type first, size second ── */
const ATT_KIND = m => {
  m = String(m || "");
  // a kind's colour is a NAME in the office's palette (the same five the drive's file icons use)
  if (m === "application/pdf" || /\.pdf$/i.test(m)) return ["pdf", "var(--red)", "PDF"];
  if (/^image\//.test(m)) return ["img", "var(--blue)", "תמונה"];
  if (/spreadsheet|excel|csv/.test(m)) return ["sheet", "var(--accent-d)", "גיליון"];
  if (/word|document/.test(m)) return ["doc", "var(--violet)", "מסמך"];
  if (/presentation|powerpoint/.test(m)) return ["slide", "var(--amber)", "מצגת"];
  if (/zip|rar|tar|gzip/.test(m)) return ["zip", "var(--muted)", "ארכיון"];
  if (/rfc822/.test(m)) return ["mail", "var(--muted)", "הודעה"];
  return ["file", "var(--muted)", "קובץ"];
};
const attSize = n => !n ? "" : n >= 1048576 ? (n / 1048576).toFixed(1) + " MB"
  : Math.max(1, Math.round(n / 1024)) + " kB";
function attCards(m, id) {
  const list = m.attachments || [];
  if (!list.length) return "";
  return `<div class="att-h">${list.length === 1 ? "קובץ מצורף אחד" : list.length + " קבצים מצורפים"}</div>`
    + list.map((a, i) => {
      const [, color, word] = ATT_KIND(a.mimeType || a.mime || a.filename || "");
      return `<a class="attcard" href="api/attachment/${enc(id)}/${i}" target="_blank" rel="noopener"
                 title="${esc(a.filename)}">
        <span class="attic" style="background:color-mix(in srgb,${color} 10%,transparent);color:${color}">${ic("paperclip")}</span>
        <span class="attx"><b><bdi>${esc(a.filename)}</bdi></b>
          <span>${esc(word)}${a.size ? " · " + attSize(a.size) : ""}</span></span></a>`;
    }).join("");
}

/* ── the conversation ────────────────────────────────────────────────────────────────────────────
   Headers only (`bodies=false`): the earlier turns collapse to one line each and a turn's body is
   fetched when it is opened. Skipped entirely when the loaded list knows of no other message in
   this thread — the most common case, and the one that used to cost a full RFC822 fetch. */
async function renderThread(head, seq) {
  const box = $("#rThread");
  box.innerHTML = "";
  const tid = head.threadId || head.id;
  const known = MSGS.filter(x => (x.threadId || x.id) === tid && x.id !== head.id);
  if (!known.length) return;
  box.innerHTML = `<div class="th-h">טוען את השיחה…</div>`;
  let chain = [];
  try { chain = (await jf("api/thread/" + enc(tid) + "?bodies=false", { silent: true })).messages || []; }
  catch (e) { if (seq === OPEN_SEQ) box.innerHTML = `<div class="th-h">השיחה לא נטענה — <bdi>${esc(e.message)}</bdi></div>`; return; }
  if (seq !== OPEN_SEQ) return;
  const earlier = chain.filter(x => x.id !== head.id);
  if (!earlier.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="th-h">${one(earlier.length, "הודעה נוספת אחת בשיחה", "הודעות נוספות בשיחה")}</div>` + earlier.map(x =>
    `<div class="thmsg" data-tid="${esc(x.id)}">
       <div class="thm-h" role="button" tabindex="0">
         <span class="gm-av" style="background:${avatarColor(fromName(x.from))}">${esc(initials(fromName(x.from)))}</span>
         <b><bdi>${esc(fromName(x.from))}</bdi></b>
         <span class="thm-snip"><bdi>${esc(x.snippet || x.subject || "")}</bdi></span>
         <span class="thm-when">${esc(fmtDate(x.date))}</span>
       </div>
       <div class="thm-b hidden"></div>
     </div>`).join("");
  box.querySelectorAll(".thmsg").forEach(el => {
    const open = async () => {
      el.classList.toggle("open");
      const b = el.querySelector(".thm-b");
      b.classList.toggle("hidden");
      if (b.dataset.loaded || b.classList.contains("hidden")) return;
      b.innerHTML = `<div class="muted">טוען…</div>`;
      try {
        const full = await fetchMessage(el.dataset.tid, true);
        b.innerHTML = (full.body_html
          ? `<iframe sandbox srcdoc="${esc(full.body_html)}" title="הודעה קודמת"></iframe>`
          : `<pre>${esc(full.body_text || "")}</pre>`) + attCards(full, full.id);
        b.dataset.loaded = "1";
      } catch (e) {
        b.innerHTML = `<div class="muted">ההודעה לא נטענה — <bdi>${esc(e.message)}</bdi> · <a class="testline" data-retry>נסה שוב</a></div>`;
        b.querySelector("[data-retry]").onclick = () => { b.classList.add("hidden"); el.classList.remove("open"); open(); };
      }
    };
    el.querySelector(".thm-h").onclick = open;
    el.querySelector(".thm-h").onkeydown = e => { if (e.key === "Enter") open(); };
  });
}

/* the document system's answer about this message — three different answers, three renderings */
/* A document's TYPE in the words the document system itself shows it in (INDOX: webapp/src/vocab.ts,
   TYPE_LABEL) — the panel printed the enum, `BALANCE_SHEET` beside a Hebrew name. A type nobody has
   named yet stays the enum, as a token: raw and seen to be raw, never passed off as a word. */
const DOC_TYPE_HE = { INVOICE: "חשבונית", BALANCE_SHEET: "דוח גיול", SHIPMENT: "תעודת משלוח", ORDER: "הזמנה",
                      RECEIPT: "קבלה", UNKNOWN: "לא מזוהה" };
const docType = t => !t ? "" : DOC_TYPE_HE[t]
  ? `<span class="muted" title="${esc(t)}">${DOC_TYPE_HE[t]}</span>` : `<span class="muted mono"><bdi>${esc(t)}</bdi></span>`;
function renderDocPanel(d) {
  const el = $("#rDoc");
  if (!d || d.unavailable) {
    // the line says what happened; the service's own words for why (an exception's text) are one hover away
    el.className = "rp-doc err";
    el.innerHTML = `<div class="docline" title="${esc((d && d.error) || "")}">${ic("alert")} לא ניתן היה לבדוק מול מערכת המסמכים</div>`;
    return;
  }
  if (!d.found) {
    el.className = "rp-doc none";
    el.innerHTML = `${ic("info")} לא מזוהה כמסמך במערכת המסמכים`;
    return;
  }
  el.className = "rp-doc";
  el.innerHTML = `<div class="dochead">מסמך במערכת (${d.found})</div>` + d.docs.map(doc => {
    const s = String(doc.STATUS || "?");
    const stCls = /COMPLETED|DONE/.test(s) ? "g" : /FAIL|NEEDS_REVIEW|MISSING/.test(s) ? "r" : "a";
    const stHe = /COMPLETED|DONE/.test(s) ? "הושלם" : /NEEDS_REVIEW/.test(s) ? "דורש בדיקה" : /FAIL/.test(s) ? "נכשל" : /MISSING/.test(s) ? "חסר" : "בתהליך";
    let err = "";
    if (doc.ERROR) { try { err = String(JSON.parse(doc.ERROR).message || "").slice(0, 140); } catch (e) { err = String(doc.ERROR).slice(0, 140); } }
    return `<div class="docrow">
      <div class="docline"><span class="badge ${stCls}" title="${esc(s)}">${stHe}</span>
        <b><bdi>${esc(doc.NAME || doc.ID || "")}</bdi></b>${docType(doc.TYPE)}</div>
      <div class="docline muted">${doc.COMPANY_NAME ? `ספק: <bdi>${esc(doc.COMPANY_NAME)}</bdi> · ` : ""}${doc.DOC_TOTAL_AMOUNT ? `סכום: ₪${esc(doc.DOC_TOTAL_AMOUNT)} · ` : ""}${doc.DOC_ID ? `מס׳ מסמך: ${esc(doc.DOC_ID)}` : ""}</div>
      ${err && stCls === "r" ? `<div class="docline docerr"><bdi>${esc(err)}</bdi></div>` : ""}
      ${doc.LINK ? `<div class="docline"><a class="doclink" href="${esc(doc.LINK)}" target="_blank" rel="noopener">${ic("folder")} פתח בדרייב</a></div>` : ""}
    </div>`;
  }).join("");
}

function renderTags(m) {
  const tags = nonSys(m.labels).filter(l => !isMachineLabel(l));
  $("#rTags").innerHTML = ""
    + tags.map(l =>
      `<span class="chip"><bdi>${esc(l)}</bdi><button class="rm" data-rm="${esc(l)}" type="button" title="הסרת התווית" aria-label="הסרת התווית ${esc(l)}">${ic("x")}</button></span>`).join("")
    + `<span class="chip addtag" id="addTag" role="button" tabindex="0">${ic("plus")} תווית</span>`;
  $("#rTags").querySelectorAll(".rm").forEach(x => x.onclick = () => busy(x, async () => {
    if (_tagBusy) return; _tagBusy = true;
    try { await jf("api/tag", post({ id: m.id, remove: [x.dataset.rm] })); binaTell("התווית הוסרה"); await reloadOpen(); }
    catch (e) { /* jf already surfaced the error */ }
    finally { _tagBusy = false; }
  }));
  $("#addTag").onclick = () => tagPicker(m);
  $("#addTag").onkeydown = e => { if (e.key === "Enter") tagPicker(m); };
}
/* The picker lists the reader's labels and can CREATE one: POST api/labels — the mail app is the one
   place a tag is made. */
function tagPicker(m) {
  const have = new Set(m.labels || []);
  const opts = LABELS.filter(l => !have.has(l));
  modal("הוספת תווית",
    `<input type="search" id="mSearch" placeholder="חיפוש תווית…" aria-label="חיפוש תווית">
     <div class="pick-list" id="pickList">` +
    (opts.length ? opts.map(l => `<div class="pick" data-t="${esc(l)}" role="button" tabindex="0"><span class="dot n"></span><bdi>${esc(l)}</bdi></div>`).join("")
                 : `<div class="empty small">אין תוויות נוספות להוספה</div>`) +
    `</div>
     <div class="pick-new"><input type="text" id="mNew" placeholder="שם לתווית חדשה" aria-label="שם לתווית חדשה" dir="auto">
       <button class="btn" id="mCreate" type="button">${ic("plus")} צור תווית</button></div>`,
    [{ label: "ביטול", onclick: closeModal }]);
  $("#mSearch").oninput = () => {
    const q = $("#mSearch").value.trim();
    document.querySelectorAll("#pickList .pick").forEach(p =>
      p.style.display = !q || p.dataset.t.includes(q) ? "" : "none");
  };
  const add = async name => {
    if (_tagBusy) return; _tagBusy = true;
    try { await jf("api/tag", post({ id: m.id, add: [name] })); closeModal(); binaTell("התווית נוספה"); await reloadOpen(); }
    catch (e) { /* jf already surfaced the error */ }
    finally { _tagBusy = false; }
  };
  $("#pickList").onclick = e => { const p = e.target.closest(".pick"); if (p) add(p.dataset.t); };
  $("#pickList").onkeydown = e => { const p = e.target.closest(".pick"); if (p && e.key === "Enter") add(p.dataset.t); };
  const create = () => busy($("#mCreate"), async () => {
    const name = $("#mNew").value.trim();
    if (!name) { $("#mNew").focus(); return; }
    try { await jf("api/labels", post({ name })); }
    catch (e) { return; }
    binaTell("התווית נוצרה");
    loadLabels();
    await add(name);
  });
  $("#mCreate").onclick = create;
  $("#mNew").onkeydown = e => { if (e.key === "Enter") create(); };
  $("#mSearch").focus();
}
async function reloadOpen() {
  if (OPEN) {
    MSGCACHE.delete(OPEN);
    try { const m = await fetchMessage(OPEN); renderTags(m); const row = MSGS.find(x => x.id === OPEN); if (row) row.labels = (m.labels || []).slice(); }
    catch (e) { /* the notice carries it */ }
  }
}
function closeReader() {
  if (SCREEN !== "reader") return;
  OPEN = null;
  showScreen("list"); nav();
  renderList();
}
$("#rClose").onclick = () => closeReader();
document.addEventListener("keydown", e => {
  if (SCREEN !== "reader" || !OPEN || e.target.matches("input,textarea,select")) return;
  /* RTL: LEFT points at the NEXT message, because the list reads right-to-left */
  if (e.key === "ArrowLeft") { e.preventDefault(); readAction("next"); }
  if (e.key === "ArrowRight") { e.preventDefault(); readAction("prev"); }
});

/* ── compose ─────────────────────────────────────────────────────────────────────────────────────
   ONE window, four entry points. Sending disables the button (aria-busy) and, on success, the
   client goes to נשלח and opens the sent message — the proof that it left. */
function compose(pre) {
  pre = pre || {};
  const ov = document.createElement("div");
  ov.className = "mlc-ov";
  ov.setAttribute("role", "dialog"); ov.setAttribute("aria-modal", "true");
  ov.setAttribute("aria-label", "הודעה חדשה");
  ov.innerHTML =
    `<div class="mlc-win"><div class="mlc-h"><span>הודעה חדשה</span><button data-x type="button" title="סגירה" aria-label="סגירה">${ic("x")}</button></div>
      <div class="mlc-b">
        <div class="mlc-f"><label for="mlcTo">אל</label><input id="mlcTo" data-to dir="ltr" value="${esc(pre.to || "")}"></div>
        <div class="mlc-f"><label for="mlcSubj">נושא</label><input id="mlcSubj" data-subj value="${esc(pre.subject || "")}"></div>
        <textarea class="mlc-body" data-body placeholder="כתוב הודעה…" aria-label="תוכן ההודעה">${esc(pre.body || "")}</textarea>
      </div>
      <div class="mlc-foot"><button class="mlc-send" data-send type="button">${ic("send")} שליחה</button>
        <span class="mlc-err" data-err></span></div></div>`;
  const prevFocus = document.activeElement;
  document.body.appendChild(ov);
  const onkey = e => { if (e.key === "Escape") { e.preventDefault(); close(); } };
  function close() {
    document.removeEventListener("keydown", onkey, true);
    if (ov.parentNode) ov.parentNode.removeChild(ov);
    if (prevFocus && prevFocus.focus) { try { prevFocus.focus(); } catch (e) { /* gone from the DOM */ } }
  }
  document.addEventListener("keydown", onkey, true);
  ov.addEventListener("click", e => { if (e.target === ov) close(); });
  ov.querySelector("[data-x]").onclick = close;
  const sendBtn = ov.querySelector("[data-send]");
  sendBtn.onclick = () => busy(sendBtn, async () => {
    const to = ov.querySelector("[data-to]").value.trim();
    const subject = ov.querySelector("[data-subj]").value.trim();
    if (!to) { ov.querySelector("[data-err]").textContent = "יש למלא נמען"; ov.querySelector("[data-to]").focus(); return; }
    ov.querySelector("[data-err]").textContent = "";
    sendBtn.innerHTML = `${ic("send")} שולח…`;
    try { await jf("api/send", post({ to, subject, body: ov.querySelector("[data-body]").value })); }
    catch (e) { sendBtn.innerHTML = `${ic("send")} שליחה`; ov.querySelector("[data-err]").textContent = e.message; return; }
    close();
    binaTell("ההודעה נשלחה");
    /* show it: the sent view, and the message itself when the mailbox already lists it */
    await goList({ view: "sent" });
    const hit = MSGS.find(x => (x.subject || "") === subject);
    if (hit) openMessage(hit.id);
    else binaTell("ההודעה נשלחה — תופיע ב„נשלח” ברגע שהתיבה תרשום אותה", "ok", { ms: 8000, act: ["רענון", refreshView] });
  });
  const to = ov.querySelector("[data-to]");
  if (to && !pre.to) to.focus(); else ov.querySelector("[data-body]").focus();
}

/* ══ the rules editor (/organizer) ══════════════════════════════════════════════════════════════
   Grid over the organizer defaults singleton (mailapi /organizer/defaults →
   defaults.mail.organizer.rules[]: EVENT/KEY/LABEL/RULE/TYPE/row_number/enabled). Everything is
   edited in place; one save PUTs the whole document, renumbered in grid order, and re-reads. */
const NEVER_MATCH = 'contains(email.text, "__NEVER_MATCH_SYNC_STATE__")';
const RULE_FIELDS = ["EVENT", "KEY", "LABEL", "RULE", "TYPE", "label_id", "row_number", "enabled"];
let ORG = null;
let ORG_UID = 0;
const isSysRule = r => r.EVENT === "SYSTEM" || (r.TYPE && r.TYPE !== "ON_CREATE_EVENT");
const labelName = r => String(r.LABEL || "").replace(/^-/, "");
const labelRemoves = r => String(r.LABEL || "").startsWith("-");
function cleanRule(r) {
  const o = {};
  for (const k of RULE_FIELDS) if (k in r && r[k] !== undefined) o[k] = r[k];
  return o;
}
function orgSnapshot(rules) { return JSON.stringify(rules.map(cleanRule)); }
function orgDirty() { return !!ORG && orgSnapshot(ORG.rules) !== ORG.snapshot; }
function orgNotice(kind, html) {
  const el = $("#orgNotice");
  if (!kind) { el.className = "org-notice hidden"; el.innerHTML = ""; return; }
  el.className = "org-notice " + kind; el.innerHTML = html;
}
async function openOrganizer(push) {
  if (push && !(await leaveGuard())) return;
  showScreen("organizer");
  $("#viewTitle").innerHTML = `${ic("tag")} חוקי תיוג`;
  if (push) nav();
  if (!ORG) await loadOrganizer();
  else drawOrgGrid();
}
async function loadOrganizer() {
  $("#orgGrid").innerHTML = '<div class="empty">טוען…</div>';
  orgNotice(null);
  try {
    const [d, l] = await Promise.all([jf("api/organizer/defaults", { silent: true }),
                                      jf("api/labels", { silent: true }).catch(() => ({ labels: [] }))]);
    const doc = d.defaults || {};
    const org = ((doc.mail || {}).organizer) || {};
    /* `enabled` is a REAL boolean or absent — the engine honours only `=== false`, so a legacy
       string "false" is coerced here and saved back as a boolean, never echoed as text. */
    const rules = (Array.isArray(org.rules) ? org.rules : []).map((r, i) => {
      const o = Object.assign({ _uid: ++ORG_UID, _i: i, _origKey: r.KEY }, r);
      if ("enabled" in o) o.enabled = !(o.enabled === false || String(o.enabled).trim().toLowerCase() === "false" || o.enabled === 0);
      return o;
    });
    rules.sort((a, b) => ((a.row_number || 0) - (b.row_number || 0)) || (a._i - b._i));
    ORG = { doc, org, rules, snapshot: orgSnapshot(rules), problems: {},
            labels: ((l.labels || []).filter(x => !/^\\/.test(x) && !String(x).startsWith("[Gmail]"))).sort() };
    drawOrgGrid();
  } catch (e) {
    ORG = null;
    $("#orgGrid").innerHTML = `<div class="failbox">${ic("alert")}<b>לא ניתן לטעון את חוקי התיוג</b>
      <span class="why"><bdi>${esc(e.message)}</bdi>${e.detail ? ` · <bdi>${esc(e.detail)}</bdi>` : ""}</span>
      <button class="btn" id="orgRetry" type="button">${ic("refresh")} נסה שוב</button></div>`;
    $("#orgRetry").onclick = () => busy($("#orgRetry"), loadOrganizer);
  }
  updateSaveState();
}
function updateSaveState() {
  const dirty = orgDirty();
  $("#orgSave").disabled = !dirty;
  $("#orgSave").textContent = dirty ? "שמירה" : "נשמר";
}
/* ── inList([...]) arrays as chips: found by a small scanner that respects strings and nesting,
   rewritten only when a chip is edited — an untouched RULE string stays byte-identical. ── */
const ARRAY_FNS = /\b(inList|containsAny|containsAll|includesAny|includesAll|isAnyDomain)\s*\(/g;
function parseStringItems(inner) {
  const items = []; let i = 0;
  while (i < inner.length) {
    while (i < inner.length && /[\s,]/.test(inner[i])) i++;
    if (i >= inner.length) break;
    const q = inner[i]; if (q !== '"' && q !== "'") return null;
    let j = i + 1, s = "";
    for (; j < inner.length; j++) {
      const c = inner[j];
      if (c === "\\" && j + 1 < inner.length) { s += inner[j + 1]; j++; continue; }
      if (c === q) break;
      s += c;
    }
    if (inner[j] !== q) return null;
    items.push(s); i = j + 1;
  }
  return items;
}
function findArrays(rule) {
  const out = []; let m;
  ARRAY_FNS.lastIndex = 0;
  while ((m = ARRAY_FNS.exec(rule))) {
    let i = m.index + m[0].length, depth = 0, inStr = null;
    for (; i < rule.length; i++) {
      const c = rule[i];
      if (inStr) { if (c === "\\") { i++; continue; } if (c === inStr) inStr = null; continue; }
      if (c === '"' || c === "'" || c === "`") { inStr = c; continue; }
      if (c === "(" || c === "[" || c === "{") depth++;
      else if (c === ")" || c === "]" || c === "}") { if (depth === 0) break; depth--; }
      else if (c === "," && depth === 0) break;
    }
    if (rule[i] !== ",") continue;
    i++;
    while (i < rule.length && /\s/.test(rule[i])) i++;
    if (rule[i] !== "[") continue;
    const start = i; let j = i + 1; inStr = null; depth = 0;
    for (; j < rule.length; j++) {
      const c = rule[j];
      if (inStr) { if (c === "\\") { j++; continue; } if (c === inStr) inStr = null; continue; }
      if (c === '"' || c === "'" || c === "`") { inStr = c; continue; }
      if (c === "[") depth++;
      else if (c === "]") { if (depth === 0) break; depth--; }
    }
    if (rule[j] !== "]") continue;
    const items = parseStringItems(rule.slice(start + 1, j));
    if (!items) continue;
    out.push({ fn: m[1], start, end: j + 1, items });
  }
  return out;
}
const serializeItems = items => "[" + items.map(s => JSON.stringify(s)).join(", ") + "]";
const replaceArray = (rule, arr, items) => rule.slice(0, arr.start) + serializeItems(items) + rule.slice(arr.end);

const TYPE_HE = { ON_CREATE_EVENT: "בהגעת מייל", SYSTEM: "תווית מערכת" };
function problemsFor(i, field) {
  const p = (ORG.problems[i] || []).filter(x => !field || x.field === field);
  return p.length ? p.map(x => `<div class="org-prob">${ic("alert")}<bdi>${esc(x.message)}</bdi></div>`).join("") : "";
}
function drawOrgGrid() {
  if (!ORG) return;
  const rows = ORG.rules;
  if (!rows.length) {
    $("#orgGrid").innerHTML = `<div class="empty">אין חוקים עדיין · <a class="testline" id="orgFirst">הוספת החוק הראשון</a></div>`;
    $("#orgFirst").onclick = addOrgRow;
    updateSaveState(); return;
  }
  let h = `<table class="org"><thead><tr>
    <th title="סדר ההרצה — חוק מאוחר רואה את התוויות שחוקים מוקדמים הוסיפו">סדר</th>
    <th>אירוע</th><th title="מזהה קבוע של החוק — האוטומציות מתייחסות אליו, לא לשם התווית">מפתח</th>
    <th>תווית</th><th>חוק</th><th>פעיל</th><th></th></tr></thead><tbody>`;
  rows.forEach((r, i) => {
    const sys = isSysRule(r);
    const off = !sys && r.enabled === false;
    const bad = !!(ORG.problems[i] || []).length;
    const rm = labelRemoves(r), name = labelName(r);
    const arrays = sys ? [] : findArrays(String(r.RULE || ""));
    h += `<tr class="${sys ? "sys" : ""} ${off ? "off" : ""} ${bad ? "bad" : ""}" data-i="${i}">
      <td class="org-ord"><span class="ord-n">${i + 1}</span>
        <button class="ord-b" data-move="up" data-i="${i}" type="button" title="העלאה" aria-label="העלאה" ${i === 0 ? "disabled" : ""}>${ic("arrow-up")}</button>
        <button class="ord-b" data-move="down" data-i="${i}" type="button" title="הורדה" aria-label="הורדה" ${i === rows.length - 1 ? "disabled" : ""}>${ic("arrow-down")}</button>
        ${problemsFor(i, "row_number")}</td>
      <td class="org-type">${sys
        ? `<span class="org-ro" title="שורת מערכת: התווית ניתנת על ידי האוטומציה, לא על ידי חוק">${ic("server")} ${TYPE_HE.SYSTEM}</span>`
        : `<select class="org-in" data-f="TYPE" data-i="${i}" aria-label="אירוע">
             <option value="ON_CREATE_EVENT" selected>${TYPE_HE.ON_CREATE_EVENT}</option>
             <option value="SYSTEM">${TYPE_HE.SYSTEM}</option></select>`}
        ${problemsFor(i, "TYPE")}${problemsFor(i, "EVENT")}</td>
      <td class="org-key"><input class="org-in ltr ${bad && (ORG.problems[i] || []).some(x => x.field === "KEY") ? "bad" : ""}" data-f="KEY" data-i="${i}" value="${esc(r.KEY || "")}" placeholder="MY_RULE" aria-label="מפתח" spellcheck="false">
        ${r._origKey === "PROCESSED" ? `<div class="org-ro small" style="margin-top:4px">${ic("shield")} סימון „טופל” של המנוע</div>` : ""}
        ${problemsFor(i, "KEY")}</td>
      <td class="org-label"><div class="org-lbl">
        <button class="pickbtn" data-pick="${i}" type="button" aria-label="בחירת תווית">
          ${name ? `<bdi>${esc(name)}</bdi>` : `<span class="none">בחירת תווית…</span>`}${ic("chevron")}</button>
        ${sys ? "" : `<label class="org-rm ${rm ? "on" : ""}"><input type="checkbox" data-f="REMOVE" data-i="${i}" ${rm ? "checked" : ""}> הסר תווית (במקום להוסיף)</label>`}
        ${problemsFor(i, "LABEL")}</div></td>
      <td class="org-rule">${sys
        ? `<span class="org-ro">— אין חוק: התווית נכתבת על ידי האוטומציה</span>`
        : `<textarea class="org-in ltr org-rule ${(ORG.problems[i] || []).some(x => x.field === "RULE") ? "bad" : ""}" data-f="RULE" data-i="${i}" aria-label="חוק" spellcheck="false" dir="ltr">${esc(r.RULE || "")}</textarea>`
          + arrays.map((a, k) => `<div class="chips" data-arr="${k}" data-i="${i}">
              <span class="chh">${esc(a.fn)}(…, [${a.items.length}])</span>
              ${a.items.map((it, j) => `<span class="chip"><bdi>${esc(it)}</bdi><button class="rm" type="button" data-chip-rm="${j}" aria-label="הסרה">${ic("x")}</button></span>`).join("")}
              <input type="text" data-chip-add placeholder="הוספה… (Enter)" aria-label="הוספת פריט" dir="ltr"></div>`).join("")}
        ${problemsFor(i, "RULE")}</td>
      <td class="org-on">${sys ? `<span class="org-ro">—</span>` : `<label class="org-onl"><input type="checkbox" data-f="enabled" data-i="${i}" ${r.enabled === false ? "" : "checked"} aria-label="פעיל"></label>`}
        ${problemsFor(i, "enabled")}</td>
      <td class="org-acts"><div class="org-rowacts">
        ${sys ? "" : `<button class="btn ghost" data-preview="${i}" type="button" title="להריץ את החוק על ההודעות האחרונות בתצוגה הנוכחית">${ic("play")} תצוגה מקדימה</button>`}
        <button class="btn ghost" data-del="${i}" type="button">${ic("trash")} מחיקה</button></div></td>
    </tr>`;
  });
  h += "</tbody></table>";
  $("#orgGrid").innerHTML = h;
  updateSaveState();
}
function orgSet(i, f, v) { ORG.rules[i][f] = v; updateSaveState(); }
$("#orgGrid").addEventListener("input", e => {
  const el = e.target.closest("[data-f]"); if (!el || !ORG) return;
  const i = +el.dataset.i, f = el.dataset.f;
  if (f === "RULE") orgSet(i, "RULE", el.value);
  if (f === "KEY") orgSet(i, "KEY", el.value.trim());
});
$("#orgGrid").addEventListener("change", async e => {
  const el = e.target.closest("[data-f]"); if (!el || !ORG) return;
  const i = +el.dataset.i, f = el.dataset.f, r = ORG.rules[i];
  if (f === "KEY") {
    const v = el.value.trim();
    if (r._origKey === "PROCESSED" && v !== "PROCESSED") {
      const ok = await binaAsk({ danger: true, ok: "שינוי", title: "לשנות את המפתח PROCESSED?",
        body: "המפתח PROCESSED מסמן את התווית „טופל” של מנוע התיוג; המנוע מחפש אותו בשם הזה." });
      if (!ok) { el.value = "PROCESSED"; orgSet(i, "KEY", "PROCESSED"); return; }
      ORG.processedOk = true;                  // the answer travels with the save — see saveOrganizer
    }
    orgSet(i, "KEY", v);
    if (isSysRule(r)) orgSet(i, "TYPE", v || "SYSTEM");
    return;
  }
  if (f === "TYPE") {
    if (el.value === "SYSTEM") {
      orgSet(i, "EVENT", "SYSTEM"); orgSet(i, "TYPE", r.KEY || "SYSTEM"); orgSet(i, "RULE", NEVER_MATCH);
      if (labelRemoves(r)) orgSet(i, "LABEL", labelName(r));
    } else { orgSet(i, "EVENT", "ON_CREATE"); orgSet(i, "TYPE", "ON_CREATE_EVENT"); }
    drawOrgGrid(); return;
  }
  if (f === "REMOVE") { orgSet(i, "LABEL", (el.checked ? "-" : "") + labelName(r)); drawOrgGrid(); return; }
  if (f === "enabled") { orgSet(i, "enabled", el.checked ? true : false); drawOrgGrid(); return; }
});
$("#orgGrid").addEventListener("keydown", e => {
  const add = e.target.closest("[data-chip-add]");
  if (add && e.key === "Enter") {
    e.preventDefault();
    const box = add.closest(".chips"), i = +box.dataset.i, k = +box.dataset.arr;
    const v = add.value.trim(); if (!v) return;
    const arrays = findArrays(String(ORG.rules[i].RULE || "")); const a = arrays[k]; if (!a) return;
    orgSet(i, "RULE", replaceArray(ORG.rules[i].RULE, a, a.items.concat([v])));
    drawOrgGrid();
    const again = $(`#orgGrid .chips[data-i="${i}"][data-arr="${k}"] [data-chip-add]`); if (again) again.focus();
  }
});
$("#orgGrid").addEventListener("click", async e => {
  if (!ORG) return;
  const rm = e.target.closest("[data-chip-rm]");
  if (rm) {
    const box = rm.closest(".chips"), i = +box.dataset.i, k = +box.dataset.arr;
    const arrays = findArrays(String(ORG.rules[i].RULE || "")); const a = arrays[k]; if (!a) return;
    const items = a.items.slice(); items.splice(+rm.dataset.chipRm, 1);
    orgSet(i, "RULE", replaceArray(ORG.rules[i].RULE, a, items)); drawOrgGrid(); return;
  }
  const mv = e.target.closest("[data-move]");
  if (mv) {
    const i = +mv.dataset.i, j = mv.dataset.move === "up" ? i - 1 : i + 1;
    if (j < 0 || j >= ORG.rules.length) return;
    const t = ORG.rules[i]; ORG.rules[i] = ORG.rules[j]; ORG.rules[j] = t;
    ORG.rules.forEach((r, k) => r.row_number = k + 1);
    ORG.problems = {}; drawOrgGrid(); return;
  }
  const pk = e.target.closest("[data-pick]");
  if (pk) return orgLabelPicker(+pk.dataset.pick);
  const pv = e.target.closest("[data-preview]");
  if (pv) return previewRule(+pv.dataset.preview, pv);
  const del = e.target.closest("[data-del]");
  if (del) {
    const i = +del.dataset.del, r = ORG.rules[i];
    const isProcessed = r._origKey === "PROCESSED" || r.KEY === "PROCESSED";
    const ok = await binaAsk(isProcessed
      ? { danger: true, ok: "מחיקה", title: "למחוק את שורת PROCESSED?",
          body: "זו שורת „טופל” של מנוע התיוג — בלעדיה המנוע לא יסמן הודעות שעבר עליהן, ויעבור עליהן שוב ושוב." }
      : { danger: true, ok: "מחיקה", title: `למחוק את החוק «${r.KEY || labelName(r) || "(ללא שם)"}»?`,
          body: "המחיקה נכנסת לתוקף בשמירה." });
    if (!ok) return;
    if (isProcessed) ORG.processedOk = true;
    ORG.rules.splice(i, 1); ORG.problems = {}; drawOrgGrid();
  }
});
function addOrgRow() {
  if (!ORG) return;
  ORG.rules.push({ _uid: ++ORG_UID, EVENT: "ON_CREATE", KEY: "", LABEL: "", RULE: "", TYPE: "ON_CREATE_EVENT",
                   row_number: ORG.rules.length + 1, enabled: true });
  drawOrgGrid();
  const rows = $("#orgGrid").querySelectorAll("tbody tr");
  const last = rows[rows.length - 1];
  if (last) { last.scrollIntoView({ block: "nearest" }); const k = last.querySelector('[data-f="KEY"]'); if (k) k.focus(); }
}
$("#orgAddRow").onclick = addOrgRow;
/* The way back is DRAWN. The reader's ← gets its arrow each time a message opens (renderReadBar); the
   rules' and the settings' never got one — a round button with nothing in it, beside a title that hid
   the gap. A person had the side menu and nothing else to leave these two screens by. */
$("#orgClose").innerHTML = ic("back");
$("#orgClose").onclick = async () => { if (!(await leaveGuard())) return; ORG_PREVIEW_SEQ++; showList({}); };
$("#orgReload").onclick = async () => {
  if (orgDirty() && !(await binaAsk({ danger: true, ok: "טעינה מחדש", title: "לטעון מחדש מהשרת?", body: "השינויים שלא נשמרו יאבדו." }))) return;
  ORG = null; await loadOrganizer();
};
/* the label picker: every label the mailbox has (system flags and Gmail folders aside), search,
   and "צור תווית" — the leading "-" remove form is the checkbox under the cell, never typed */
function orgLabelPicker(i) {
  const r = ORG.rules[i];
  const cur = labelName(r);
  const draw = q => (ORG.labels.filter(l => !q || l.includes(q)).map(l =>
    `<div class="pick" data-t="${esc(l)}" role="button" tabindex="0"><span class="dot n"></span><bdi>${esc(l)}</bdi>${l === cur ? ic("check") : ""}</div>`).join("")
    || `<div class="empty small">אין תווית כזו</div>`);
  modal("בחירת תווית",
    `<input type="search" id="mSearch" placeholder="חיפוש תווית…" aria-label="חיפוש תווית" value="">
     <div class="pick-list" id="pickList">${draw("")}</div>
     <div class="pick-new"><input type="text" id="mNew" placeholder="שם לתווית חדשה" aria-label="שם לתווית חדשה" dir="auto">
       <button class="btn" id="mCreate" type="button">${ic("plus")} צור תווית</button></div>`,
    [{ label: "ביטול", onclick: closeModal }]);
  const choose = name => { orgSet(i, "LABEL", (labelRemoves(r) ? "-" : "") + name); closeModal(); drawOrgGrid(); };
  $("#mSearch").oninput = () => { $("#pickList").innerHTML = draw($("#mSearch").value.trim()); };
  $("#pickList").onclick = e => { const p = e.target.closest(".pick"); if (p) choose(p.dataset.t); };
  $("#pickList").onkeydown = e => { const p = e.target.closest(".pick"); if (p && e.key === "Enter") choose(p.dataset.t); };
  const create = () => busy($("#mCreate"), async () => {
    const name = $("#mNew").value.trim();
    if (!name) { $("#mNew").focus(); return; }
    try { await jf("api/labels", post({ name })); } catch (e) { return; }
    binaTell("התווית נוצרה");
    if (!ORG.labels.includes(name)) { ORG.labels.push(name); ORG.labels.sort(); }
    loadLabels();
    choose(name);
  });
  $("#mCreate").onclick = create;
  $("#mNew").onkeydown = e => { if (e.key === "Enter") create(); };
  $("#mSearch").focus();
}
/* client-side checks mirror the server's (unique non-empty KEY, non-empty LABEL, a parse of RULE),
   so most problems are caught at the keyboard; the server's 400 still stands behind them */
function orgValidate() {
  const problems = {}, seen = new Map();
  const add = (i, field, message) => { (problems[i] = problems[i] || []).push({ field, message }); };
  ORG.rules.forEach((r, i) => {
    const key = String(r.KEY || "").trim();
    if (!key) add(i, "KEY", "מפתח חסר");
    else if (seen.has(key)) add(i, "KEY", `המפתח ${key} כבר בשימוש בשורה ${seen.get(key) + 1}`);
    else seen.set(key, i);
    if (!labelName(r).trim()) add(i, "LABEL", "תווית חסרה");
    if (!isSysRule(r)) {
      const rule = String(r.RULE || "").trim();
      if (!rule) add(i, "RULE", "חוק חסר");
      else { try { RulesLib.compileRule(rule); } catch (e) { add(i, "RULE", "החוק אינו תקין: " + e.message); } }
    }
  });
  return problems;
}
/* busy() re-enables the button when it is done; the save state (disabled when clean) is re-derived
   right after, so a successful save leaves the button reading "נשמר" and disabled */
$("#orgSave").onclick = async () => { await busy($("#orgSave"), saveOrganizer); updateSaveState(); };
async function saveOrganizer() {
  if (!ORG) return;
  ORG.problems = orgValidate();
  if (Object.keys(ORG.problems).length) {
    drawOrgGrid();
    orgNotice("err", `${ic("alert")} יש לתקן את השורות המסומנות לפני השמירה`);
    return;
  }
  ORG.rules.forEach((r, i) => { r.row_number = i + 1; r.EVENT = isSysRule(r) ? "SYSTEM" : "ON_CREATE"; if (isSysRule(r)) r.TYPE = r.KEY; else r.TYPE = "ON_CREATE_EVENT"; });
  const doc = JSON.parse(JSON.stringify(ORG.doc || {}));
  doc.mail = doc.mail || {};
  doc.mail.organizer = Object.assign({}, ORG.org, { mode: ORG.org.mode || "default", rules: ORG.rules.map(cleanRule) });
  $("#orgSave").textContent = "שומר…";
  /* The service guards the engine's one cursor: a document that drops the PROCESSED row, or renames its
     label, is refused (409) until the request says it is meant (`confirm_processed`). Where the change was
     asked about when it was made, that answer travels with the save — it used to stay here, and the save
     the person had just agreed to was refused, in English. Where it was not asked (a new label picked for
     the row), it is asked now, and the save is sent again. */
  const send = meant => jf("api/organizer/defaults",
    Object.assign(put(meant ? Object.assign({ confirm_processed: true }, doc) : doc), { silent: true }));
  try {
    try { await send(ORG.processedOk); }
    catch (e) {
      if (e.status !== 409 || !(e.body && e.body.confirm_with)) throw e;
      if (!await binaAsk({ danger: true, ok: "שמירה בכל זאת", title: "לשמור שינוי בשורת PROCESSED?",
            body: "זו השורה שמנוע התיוג מסמן בה כל הודעה שסיים. בלי השורה, או תחת תווית אחרת, המנוע יעבור שוב על כל התיבה." })) { updateSaveState(); return; }
      await send(true);
    }
  } catch (e) {
    const probs = e.body && Array.isArray(e.body.problems) ? e.body.problems : null;
    if (probs && probs.length) {
      ORG.problems = {};
      for (const p of probs) {
        let i = Number.isInteger(p.index) ? p.index : Number.isInteger(p.row) ? p.row : -1;
        if ((i < 0 || i >= ORG.rules.length) && p.key) i = ORG.rules.findIndex(r => r.KEY === p.key);
        if (i < 0 || i >= ORG.rules.length) i = 0;
        (ORG.problems[i] = ORG.problems[i] || []).push({ field: p.field || "RULE", message: p.message || String(p) });
      }
      drawOrgGrid();
      orgNotice("err", `${ic("alert")} השרת דחה את השמירה — <bdi>${esc(e.message)}</bdi>. הבעיות מסומנות בשורות.`);
    } else {
      orgNotice("err", `${ic("alert")} השמירה נכשלה — <bdi>${esc(e.message)}</bdi>${e.detail ? ` · <bdi>${esc(e.detail)}</bdi>` : ""}`);
    }
    updateSaveState();
    return;
  }
  binaTell("חוקי התיוג נשמרו");
  ORG = null;
  await loadOrganizer();
  orgNotice("ok", `${ic("check-circle")} נשמר. המנוע מריץ את החוקים המעודכנים מהמחזור הבא.`);
  loadLabelMap();
}
/* ── legend ── */
$("#orgLegendBtn").onclick = () => {
  const el = $("#orgLegend");
  if (!el.innerHTML) {
    const L = RulesLib.LEGEND;
    const block = (title, rows) => `<div><h3>${title}</h3>${rows.map(([c, t]) => `<div class="l"><code>${esc(c)}</code><span>${esc(t)}</span></div>`).join("")}</div>`;
    el.innerHTML = block("פונקציות עזר", L.helpers) + block("email — ההודעה", L.email) + block("thread — השיחה", L.thread) + block("attachments — קבצים מצורפים", L.attachments)
      + `<div><h3>כללי</h3><div class="l"><span>החוק הוא ביטוי JavaScript שמחזיר אמת/שקר. אפשר לשלב: <code dir="ltr">&amp;&amp;</code> וגם, <code dir="ltr">||</code> או, <code dir="ltr">!</code> לא. מחרוזות בגרשיים כפולים; רשימות בסוגריים מרובעים.</span></div></div>`;
  }
  el.classList.toggle("hidden");
};
/* ── preview: the rule over the last N messages of the CURRENT list scope, evaluated in the browser
   with the engine's own helper library (rules-lib.js). Exceptions are shown, never swallowed. ── */
let ORG_PREVIEW_SEQ = 0;
const PREVIEW_N = 50;
async function previewRule(i, btn) {
  const r = ORG.rules[i];
  const rule = String(r.RULE || "").trim();
  const seq = ++ORG_PREVIEW_SEQ;
  const panel = $("#orgPreview");
  panel.classList.remove("hidden");
  const scope = CURLABEL ? `תווית „${CURLABEL}”` : QUERY ? `חיפוש „${QUERY}”` : (SYS_VIEWS.find(v => v.id === (VIEW || "inbox")) || {}).he;
  const winHe = (WINDOWS.find(w => w.id === WIN) || {}).he;
  const head = (sumHtml, running) => `<div class="pv-h"><b>תצוגה מקדימה: <bdi>${esc(labelName(r) || r.KEY || "")}</bdi></b>
      <span class="pv-rule" title="${esc(rule)}">${esc(rule)}</span>
      <span class="pv-sum">${sumHtml}</span>
      ${running ? `<button class="btn ghost" data-pv-cancel type="button">${ic("x")} עצירה</button>` : ""}
      <button class="btn ghost" data-pv-close type="button">${ic("x")} סגירה</button></div>
    <div class="pv-bar"><i style="width:0%"></i></div>
    <div class="pv-empty">${PREVIEW_N} ההודעות האחרונות ב־${esc(scope || "")}${WIN !== "all" ? ` · טווח „${esc(winHe)}”` : ""} — כדי לבדוק תצוגה אחרת, בחר אותה בסרגל וחזור לכאן.</div>
    <div class="pv-list"></div>`;
  panel.innerHTML = head("מכין…", true);
  panel.scrollIntoView({ block: "nearest" });
  const wire = () => {
    const c = panel.querySelector("[data-pv-cancel]"); if (c) c.onclick = () => { ORG_PREVIEW_SEQ++; panel.querySelector(".pv-sum").textContent += " · נעצר"; c.remove(); };
    panel.querySelector("[data-pv-close]").onclick = () => { ORG_PREVIEW_SEQ++; panel.classList.add("hidden"); panel.innerHTML = ""; };
  };
  wire();
  try { RulesLib.compileRule(rule); }
  catch (e) {
    panel.querySelector(".pv-list").innerHTML = `<div class="pv-row exc"><span class="pv-res">${ic("alert")}</span><span class="pv-subj">החוק אינו מתקמפל</span><span class="pv-err">${esc(e.message)}</span></div>`;
    panel.querySelector(".pv-sum").textContent = "לא ניתן להריץ"; const c = panel.querySelector("[data-pv-cancel]"); if (c) c.remove();
    return;
  }
  let list;
  try { list = (await jf(listQuery(PREVIEW_N, 0), { silent: true })).messages || []; }
  catch (e) {
    if (seq !== ORG_PREVIEW_SEQ) return;
    panel.querySelector(".pv-list").innerHTML = `<div class="pv-row exc"><span class="pv-res">${ic("alert")}</span><span class="pv-subj">רשימת ההודעות לא נטענה</span><span class="pv-err">${esc(e.message)}</span></div>`;
    return;
  }
  if (seq !== ORG_PREVIEW_SEQ) return;
  const listEl = panel.querySelector(".pv-list"), sum = panel.querySelector(".pv-sum"), bar = panel.querySelector(".pv-bar i");
  if (!list.length) { listEl.innerHTML = `<div class="pv-empty">אין הודעות בתצוגה הנוכחית</div>`; sum.textContent = "0 הודעות"; const c = panel.querySelector("[data-pv-cancel]"); if (c) c.remove(); return; }
  const needThread = /\bthread\b/.test(rule);
  const name = labelName(r);
  let done = 0, hits = 0, excs = 0;
  const row = (m, res, err, already) => {
    const cls = err ? "exc" : res ? "hit" : "miss";
    listEl.insertAdjacentHTML("beforeend", `<div class="pv-row ${cls}">
      <span class="pv-res">${err ? ic("alert") : res ? ic("check") : ic("x")}</span>
      <span class="pv-from"><bdi>${esc(fromName(m.from))}</bdi></span>
      <span class="pv-subj"><bdi>${esc(m.subject || "(ללא נושא)")}</bdi>${already ? ` <span class="chip info">כבר מתויג</span>` : ""}</span>
      <span class="pv-when">${esc(fmtDate(m.date))}</span>
      ${err ? `<span class="pv-err">${esc(err)}</span>` : ""}</div>`);
  };
  /* (named `tryOne`, not `one`: the page's `one(n, single, many)` is what words the count of errors below — a
     local of that name took its place, and one error asked the trial of a number, which failed and asked again) */
  const tryOne = async m => {
    let meta, threadJson = null, res = false, err = null, already = false;
    try {
      meta = await fetchMessage(m.id, true);
      if (needThread) {
        const tid = meta.threadId || meta.id;
        threadJson = MSGCACHE.get("thread:" + tid);
        if (!threadJson) { threadJson = await jf("api/thread/" + enc(tid), { silent: true }); cacheSet("thread:" + tid, threadJson); }
      }
    } catch (e) { err = "ההודעה לא נטענה: " + e.message; }
    if (!err) {
      try {
        const ctx = RulesLib.contextFor(meta, threadJson);
        already = !!name && ctx.email.labels.includes(name);
        res = RulesLib.evaluateRuleStrict(rule, ctx.email, ctx.thread, ctx.attachments);
      } catch (e) { err = (e && e.name ? e.name + ": " : "") + (e && e.message ? e.message : String(e)); }
    }
    if (seq !== ORG_PREVIEW_SEQ) return;
    done++; if (err) excs++; else if (res) hits++;
    row(m, res, err, already);
    bar.style.width = Math.round(done / list.length * 100) + "%";
    sum.innerHTML = `יתאימו <b>${num(hits)}</b> מתוך ${num(done)}/${num(list.length)}${excs ? ` · <span style="color:var(--red)">${one(excs, "שגיאה אחת", "שגיאות")}</span>` : ""}`;
  };
  /* two at a time: enough to overlap, not enough to queue the whole preview on the mailbox lock */
  const queue = list.slice();
  const worker = async () => { while (queue.length && seq === ORG_PREVIEW_SEQ) await tryOne(queue.shift()); };
  await Promise.all([worker(), worker()]);
  if (seq !== ORG_PREVIEW_SEQ) return;
  const c = panel.querySelector("[data-pv-cancel]"); if (c) c.remove();
  sum.innerHTML = `יתאימו <b>${num(hits)}</b> מתוך ${num(list.length)}${excs ? ` · <span style="color:var(--red)">${one(excs, "שגיאה אחת", "שגיאות")}</span>` : ""}`;
}

/* ══ mailbox settings (/settings) ═══════════════════════════════════════════════════════════════
   Three sections, one pane: the company's addresses (mailboxes), the private-mail readiness
   checklist (setup), and connecting an existing account (connect). Ported from the mail
   service's own UI so there is ONE client. */
const SET_SECTIONS = [
  { id: "mailboxes", he: "כתובות בחברה" },
  { id: "setup",     he: "דואר פרטי — בדיקת הגדרות" },
  { id: "connect",   he: "חיבור חשבון" },
];
let CONN = { active: null, list: [] };
let SET_SEQ = 0;
async function openSettings(section, push) {
  if (push && !(await leaveGuard())) return;
  SETTINGS_SECTION = SET_SECTIONS.some(s => s.id === section) ? section : "mailboxes";
  showScreen("settings");
  $("#viewTitle").innerHTML = `${ic("server")} הגדרות תיבה`;
  nav(!push);
  $("#setTabs").innerHTML = SET_SECTIONS.map(s =>
    `<a href="${esc(href('/settings/' + s.id))}" data-sec="${s.id}" class="${s.id === SETTINGS_SECTION ? "active" : ""}">${s.he}</a>`).join("");
  $("#setTabs").querySelectorAll("[data-sec]").forEach(a => a.onclick = e => { e.preventDefault(); openSettings(a.dataset.sec, true); });
  const seq = ++SET_SEQ;
  $("#setBody").innerHTML = `<div class="empty">טוען…</div>`;
  try { await loadConnections(); } catch (e) { /* each section says what it could not load */ }
  if (seq !== SET_SEQ) return;
  if (SETTINGS_SECTION === "mailboxes") return renderMailboxes(seq);
  if (SETTINGS_SECTION === "setup") return renderSetup(seq);
  return renderConnect(seq);
}
$("#setClose").innerHTML = ic("back");
$("#setClose").onclick = () => goList({});
async function loadConnections() {
  const d = await jf("api/connections", { silent: true });
  CONN = { active: d.active || null, list: d.connections || [], reason: d.reason || "" };
}
const isLocalConn = c => (c && c.protocol) === "mail_imap_local";
const connName = c => !c ? "לא נבחר חשבון" : (c.label || c.account_hint || c.id);
const activeConn = () => CONN.list.find(c => c.id === CONN.active) || null;
function copyBtn(text) {
  const b = document.createElement("button");
  b.type = "button"; b.className = "st-copy"; b.title = "העתקה"; b.setAttribute("aria-label", "העתקה"); b.innerHTML = ic("copy");
  b.onclick = async () => {
    try { await navigator.clipboard.writeText(text); binaTell("הועתק"); }
    catch (e) { fail("ההעתקה נכשלה — העתק ידנית מהשדה"); }
  };
  return b;
}
const failBox = (title, e, retryId) => `<div class="failbox">${ic("alert")}<b>${esc(title)}</b>
  <span class="why"><bdi>${esc(e.message)}</bdi>${e.detail ? ` · <bdi>${esc(e.detail)}</bdi>` : ""}</span>
  <button class="btn" id="${retryId}" type="button">${ic("refresh")} נסה שוב</button></div>`;

/* ── mailboxes at this domain: adding a person is one row on the server and ZERO DNS work ── */
const genPw = () => {
  // Ambiguity-free alphabet: no O/0, no l/1/I — these get read off a screen and typed into a phone.
  const A = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from(crypto.getRandomValues(new Uint32Array(16)), n => A[n % A.length]).join("");
};
async function renderMailboxes(seq) {
  const body = $("#setBody");
  let d;
  try { d = await jf("api/mailboxes", { silent: true }); }
  catch (e) {
    if (seq !== SET_SEQ) return;
    body.innerHTML = `<div class="set-h">כתובות הדואר של החברה</div>` + failBox("שירות ניהול התיבות אינו זמין", e, "mbRetry")
      + `<div class="cw-msg soft">${ic("info")}<div>קריאת הדואר אינה מושפעת. השירות mailboxd הוא זה שיוצר ומוחק תיבות.</div></div>`;
    $("#mbRetry").onclick = () => busy($("#mbRetry"), () => renderMailboxes(seq));
    return;
  }
  if (seq !== SET_SEQ) return;
  if (d.available === false) {
    body.innerHTML = `<div class="set-h">כתובות הדואר של החברה</div>
      <div class="cw-msg err">${ic("alert")}<div><b>שירות ניהול התיבות אינו זמין</b><span class="sub"><bdi>${esc(d.error || "")}</bdi> · קריאת הדואר אינה מושפעת.</span></div></div>
      <div class="set-acts"><button class="btn ghost" id="mbRetry" type="button">${ic("refresh")} נסה שוב</button></div>`;
    $("#mbRetry").onclick = () => busy($("#mbRetry"), () => renderMailboxes(seq));
    return;
  }
  const list = d.mailboxes || [];
  const act = activeConn();
  body.innerHTML = `<div class="set-h">כתובות הדואר של החברה</div>
    <div class="set-sub">הרשומות של <bdi class="ltr">${esc(d.domain || "")}</bdi> — MX, SPF, DKIM ו-DMARC — חלות על <b>כל</b> כתובת בדומיין, ולכן תיבה חדשה היא רק שורה בשרת: בלי רשומת DNS, בלי תעודה ובלי הפעלה מחדש.</div>
    ${act && !isLocalConn(act) ? `<div class="cw-msg soft">${ic("info")}<div>יצירה ומחיקה של תיבות נעשות כפרופיל מנהל של שרת הדואר המקומי. החשבון הפעיל כרגע הוא <bdi>${esc(connName(act))}</bdi> — השרת ידחה שינוי עד שייבחר חשבון מקומי (בלשונית „חיבור חשבון”).</div></div>` : ""}
    <div class="set-acts"><button class="btn" id="mbAdd" type="button">${ic("plus")} הוספת כתובת</button>
      <button class="btn ghost" id="mbRefresh" type="button">${ic("refresh")} רענון</button></div>
    <div id="mbForm"></div>
    <div class="st-list" id="mbList"></div>`;
  const box = $("#mbList");
  if (!list.length) box.innerHTML = `<div class="cw-msg">${ic("alert")}<div>לא הוגדרה אף תיבה.</div></div>`;
  for (const m of list) {
    const row = document.createElement("div");
    row.className = "st-row";
    const head = document.createElement("div");
    head.className = "mb-row";
    head.innerHTML = `<span class="dot ${m.maildir_exists ? "healthy" : "muted"}" title="${m.maildir_exists ? "התיבה קיימת על הדיסק" : "עדיין לא התקבל דואר"}"></span>
      <span class="mb-a">${esc(m.address)}</span>
      ${m.primary ? `<span class="st-badge ok">ראשית</span>` : ""}
      <span class="mb-meta">${m.size_bytes ? esc(attSize(m.size_bytes)) : "ריקה"}</span>`;
    row.appendChild(head);
    if (!m.primary) {
      const del = document.createElement("button");
      del.type = "button"; del.className = "mb-del"; del.title = "מחיקת התיבה"; del.setAttribute("aria-label", "מחיקת התיבה " + m.address); del.innerHTML = ic("trash");
      del.onclick = async () => {
        if (!await binaAsk({
          danger: true, ok: "מחיקה", title: "למחוק את התיבה?",
          body: "הדואר עצמו לא נמחק.\nהכתובת תפסיק לקבל דואר ולא יהיה ניתן להתחבר אליה, אך ההודעות נשארות על השרת וניתן להחזיר גישה ביצירת התיבה מחדש.",
          facts: [["תיבה", m.address]].concat(m.size_bytes ? [["דואר שנשאר", attSize(m.size_bytes)]] : []),
          run: () => jf("api/mailboxes/" + enc(m.address), { method: "DELETE", silent: true }),
        })) return;
        binaTell("התיבה נמחקה — הדואר נשמר");
        try { await loadConnections(); } catch (e) { /* the list below still refreshes */ }
        renderMailboxes(seq);
      };
      head.appendChild(del);
    }
    box.appendChild(row);
  }
  $("#mbRefresh").onclick = () => busy($("#mbRefresh"), () => renderMailboxes(seq));
  $("#mbAdd").onclick = () => {
    const pw = genPw();
    $("#mbForm").innerHTML = `<div class="set-form">
      <div class="field"><label for="mbLocal">שם המשתמש בתיבה</label>
        <input id="mbLocal" type="text" dir="ltr" autocomplete="off" placeholder="user2">
        <span class="h">הכתובת שתיווצר: <bdi class="ltr" id="mbPrev">user2@${esc(d.domain || "")}</bdi> · אותיות לטיניות קטנות, ספרות, נקודה, מקף.</span></div>
      <div class="field"><label for="mbPw">סיסמה</label>
        <input id="mbPw" type="text" dir="ltr" autocomplete="off" value="${esc(pw)}">
        <span class="h">הסיסמה נשמרת מוצפנת ולא ניתן יהיה להציג אותה שוב — העתק אותה לפני הסגירה.</span></div>
      <div class="row"><button class="btn" id="mbCreate" type="button">${ic("plus")} יצירה</button>
        <button class="btn ghost" id="mbCancel" type="button">ביטול</button></div></div>`;
    const li = $("#mbLocal"), pv = $("#mbPrev");
    li.oninput = () => { pv.textContent = (li.value.trim().toLowerCase() || "user2") + "@" + (d.domain || ""); };
    li.focus();
    $("#mbCancel").onclick = () => { $("#mbForm").innerHTML = ""; };
    $("#mbCreate").onclick = () => busy($("#mbCreate"), async () => {
      const local = (li.value || "").trim().toLowerCase();
      const password = ($("#mbPw").value || "").trim();
      if (!local) { li.focus(); binaTell("יש להזין שם תיבה", "warn"); return; }
      let r;
      try { r = await jf("api/mailboxes", post({ local, password })); }
      catch (e) { return; }
      binaTell("התיבה נוצרה");
      try { await loadConnections(); } catch (e) { /* shown on the next open */ }
      $("#mbForm").innerHTML = `<div class="set-form">
        <div class="cw-msg ok">${ic("check-circle")}<div><b><bdi class="ltr">${esc(r.address || local + "@" + (d.domain || ""))}</bdi></b>
          <span class="sub">מקבלת דואר כבר עכשיו, והחיבור אליה נוצר באותה פעולה. לא נדרשה שום פעולה בדומיין.</span></div></div>
        <div class="field"><label>סיסמה — מוצגת פעם אחת בלבד</label><div class="mb-pw"><code id="mbNewPw">${esc(password)}</code></div></div>
        <div class="row"><button class="btn ghost" id="mbDone" type="button">סגירה</button></div></div>`;
      $(".mb-pw").appendChild(copyBtn(password));
      $("#mbDone").onclick = () => renderMailboxes(seq);
      renderMailboxList(seq);
    });
  };
}
/* the list half only — used after a create so the password panel above it stays on screen */
async function renderMailboxList(seq) {
  try {
    const d = await jf("api/mailboxes", { silent: true });
    if (seq !== SET_SEQ) return;
    const box = $("#mbList"); if (!box) return;
    box.innerHTML = (d.mailboxes || []).map(m => `<div class="st-row"><div class="mb-row">
      <span class="dot ${m.maildir_exists ? "healthy" : "muted"}"></span><span class="mb-a">${esc(m.address)}</span>
      ${m.primary ? `<span class="st-badge ok">ראשית</span>` : ""}<span class="mb-meta">${m.size_bytes ? esc(attSize(m.size_bytes)) : "ריקה"}</span></div></div>`).join("");
  } catch (e) { /* the full render on סגירה retries */ }
}

/* ── private-mail setup: every red line is ACTIONABLE — the record to publish, with a copy button ── */
const SETUP_DOT = { ok: "healthy", propagating: "checking", missing: "needs_action", bad: "degraded", unknown: "muted" };
const SETUP_WORD = { ok: "תקין", propagating: "מתעדכן", missing: "חסר", bad: "שגוי", unknown: "לא ידוע" };
function setupRow(c) {
  const row = document.createElement("div");
  row.className = "st-row " + (c.status || "");
  const head = document.createElement("div");
  head.className = "st-head";
  head.innerHTML = `<span class="dot ${SETUP_DOT[c.status] || "muted"}"></span>
    <span class="st-t">${esc(c.title)}</span>
    <span class="st-badge ${esc(c.status || "")}">${SETUP_WORD[c.status] || esc(c.status || "")}</span>`;
  row.appendChild(head);
  const d = document.createElement("div");
  d.className = "st-d"; d.textContent = c.detail || "";
  row.appendChild(d);
  if (c.status !== "ok" && (c.expected || c.observed)) {
    const kv = document.createElement("div");
    kv.className = "st-kv";
    kv.innerHTML = `<div><span>נדרש</span><code><bdi>${esc(c.expected || "—")}</bdi></code></div>
                    <div><span>נמצא</span><code><bdi>${esc(c.observed || "—")}</bdi></code></div>`;
    row.appendChild(kv);
  }
  /* a `propagating` record is ALREADY published — no copy button, re-publishing resets its TTL */
  if (c.status !== "ok" && c.status !== "propagating" && c.record) {
    const rec = document.createElement("div");
    rec.className = "st-rec";
    rec.innerHTML = `<div class="st-rec-h">${ic("info")} רשומת DNS להוספה אצל רשם הדומיין</div>
      <div class="st-rec-g">
        <div><span>סוג</span><code>${esc(c.record.type)}</code></div>
        <div><span>שם</span><code><bdi>${esc(c.record.name)}</bdi></code></div>
      </div>
      <div class="st-rec-v"><span>ערך</span><code class="st-val"><bdi>${esc(c.record.value)}</bdi></code></div>`;
    rec.querySelector(".st-rec-v").appendChild(copyBtn(c.record.value));
    row.appendChild(rec);
  }
  if (c.fix) {
    const f = document.createElement("div");
    f.className = "st-fix"; f.innerHTML = ic("alert") + `<span>${esc(c.fix)}</span>`;
    row.appendChild(f);
  }
  return row;
}
async function renderSetup(seq) {
  const body = $("#setBody");
  body.innerHTML = `<div class="set-h">דואר פרטי — בדיקת הגדרות</div><div class="cw-msg wait"><span class="spin">${ic("clock")}</span><div>בודק את הדומיין, רשומות ה-DNS וחתימת השולח…</div></div>`;
  let s;
  try { s = await jf("api/setup/status", { silent: true }); }
  catch (e) {
    if (seq !== SET_SEQ) return;
    body.innerHTML = `<div class="set-h">דואר פרטי — בדיקת הגדרות</div>` + failBox("לא ניתן לבדוק את ההגדרות כרגע", e, "stRetry");
    $("#stRetry").onclick = () => busy($("#stRetry"), () => renderSetup(seq));
    return;
  }
  if (seq !== SET_SEQ) return;
  const checks = s.checks || [];
  const bad = checks.filter(c => c.status === "missing" || c.status === "bad").length;
  const prop = checks.filter(c => c.status === "propagating").length;
  const propNote = !prop ? "" : " · " + (prop === 1
    ? "רשומה אחת עדיין מתעדכנת אצל חלק משרתי ה-DNS בעולם"
    : `${prop} רשומות עדיין מתעדכנות אצל חלק משרתי ה-DNS בעולם`);
  const head = s.mode === "local"
    ? `<div class="cw-msg soft">${ic("info")}<div><b>התקנה מקומית</b><span class="sub">הדואר עובד במלואו בתוך המערכת. כדי לקבל ולשלוח דואר מהאינטרנט נדרש דומיין אמיתי.</span></div></div>`
    : bad === 0
      ? `<div class="cw-msg ok">${ic("check-circle")}<div><b>הדואר הפרטי מוגדר במלואו</b><span class="sub"><bdi class="ltr">${esc(s.domain)}</bdi> · מזהה חתימה <bdi class="ltr">${esc(s.selector)}</bdi>${propNote}</span></div></div>`
      : `<div class="cw-msg err">${ic("alert")}<div><b>נותרו ${bad} דברים להשלמה</b><span class="sub"><bdi class="ltr">${esc(s.domain)}</bdi> · מזהה חתימה <bdi class="ltr">${esc(s.selector)}</bdi>${s.public_ip ? " · " + esc(s.public_ip) : ""}${propNote}</span></div></div>`;
  body.innerHTML = `<div class="set-h">דואר פרטי — בדיקת הגדרות</div>
    <div class="set-sub">האם שרת הדואר הפרטי באמת יכול לשלוח ולקבל דואר מהאינטרנט — ואם לא, מה חסר. כל שורה אדומה מציינת את הרשומה שיש לפרסם.</div>
    ${head}
    <div class="set-acts"><button class="btn ghost" id="stAgain" type="button">${ic("refresh")} בדיקה מחדש</button>
      <button class="btn ghost" id="stMb" type="button">${ic("plus")} הוספת כתובת בחברה</button></div>
    <div class="st-list" id="stList"></div>`;
  const list = $("#stList");
  for (const c of checks) list.appendChild(setupRow(c));
  if (!checks.length) list.innerHTML = `<div class="cw-msg soft">${ic("info")}<div>לא הוחזרו בדיקות.</div></div>`;
  $("#stAgain").onclick = () => busy($("#stAgain"), () => renderSetup(seq));
  $("#stMb").onclick = () => openSettings("mailboxes", true);
}

/* ── guided connect: provider → method → provide → VERIFY → activate. A connection is never
   "added", it is verified; every step is a visible state with a way back. ── */
const STEPS = ["ספק", "אופן החיבור", "פרטי גישה", "בדיקה", "הפעלה"];
const stepsHtml = n => `<div class="cw-steps">` + STEPS.map((l, i) =>
  `<span class="cw-step ${i + 1 === n ? "cur" : i + 1 < n ? "done" : ""}">${i + 1 < n ? ic("check") : ""} ${esc(l)}</span>`).join("") + `</div>`;
const NEEDLBL = { username: "כתובת המייל", password: "סיסמת האפליקציה" };
let CW_TIMER = 0;
function cwStop() { if (CW_TIMER) { clearInterval(CW_TIMER); CW_TIMER = 0; } }
function connectFrame(inner) {
  cwStop();
  $("#setBody").innerHTML = `<div class="set-h">חיבור חשבון דואר</div>
    <div class="set-sub">מסך זה מחבר תיבה שכבר קיימת (Gmail, או תיבה מקומית) כמקור לקריאה — הוא אינו יוצר כתובת. יצירת כתובת חדשה בחברה נעשית בלשונית „כתובות בחברה”.</div>
    <div id="cwConns"></div><h3 class="set-cap">חיבור חשבון חדש</h3><div id="cwBody">${inner}</div>`;
  renderConnList();
}
function renderConnList() {
  const box = $("#cwConns"); if (!box) return;
  if (!CONN.list.length) { box.innerHTML = `<div class="cw-msg soft">${ic("info")}<div>עדיין אין חשבונות מחוברים.</div></div>`; return; }
  box.innerHTML = `<h3 class="set-cap">חשבונות מחוברים</h3>` + (CONN.reason ? `<div class="cw-msg err">${ic("alert")}<div><bdi>${esc(CONN.reason)}</bdi></div></div>` : "")
    + `<div class="acct-list">` + CONN.list.map(c => `<div class="acct-row" data-cid="${esc(c.id)}">
        <span class="dot ${c.id === CONN.active ? "healthy" : "muted"}"></span>
        <span class="nm"><bdi>${esc(connName(c))}</bdi></span>
        ${c.account_hint ? `<span class="hint"><bdi class="ltr">${esc(c.account_hint)}</bdi></span>` : ""}
        ${c.id === CONN.active ? `<span class="chip healthy">פעיל</span>` : ""}
        <span class="sp">
          ${c.id !== CONN.active ? `<button class="btn ghost" data-sel="${esc(c.id)}" type="button">הפעלה</button>` : ""}
          <button class="btn ghost" data-probe="${esc(c.id)}" type="button">בדיקה</button>
          ${!/-env$/.test(c.id) && !isLocalConn(c) ? `<button class="btn ghost" data-rm="${esc(c.id)}" type="button">${ic("trash")} הסרה</button>` : ""}
        </span></div>`).join("") + `</div>`;
  box.querySelectorAll("[data-sel]").forEach(b => b.onclick = () => busy(b, () => selectConn(b.dataset.sel)));
  box.querySelectorAll("[data-probe]").forEach(b => b.onclick = () => busy(b, async () => {
    let r; try { r = await jf("api/connections/" + enc(b.dataset.probe) + "/probe"); } catch (e) { return; }
    if (r.ok) binaTell("החיבור תקין" + (r.account_hint ? " · " + r.account_hint : ""));
    else fail("החיבור אינו עובד", r.reason || "");
  }));
  box.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => {
    const c = CONN.list.find(x => x.id === b.dataset.rm);
    if (!await binaAsk({
      danger: true, ok: "הסרה", title: `להסיר את החיבור «${connName(c)}»?`,
      body: "הדואר בחשבון עצמו לא נמחק — רק החיבור אליו מוסר.",
      facts: c.account_hint && c.account_hint !== connName(c) && [["חשבון", c.account_hint]],
      run: () => jf("api/connections/" + enc(c.id), { method: "DELETE", silent: true }),
    })) return;
    binaTell("החיבור הוסר");
    try { await loadConnections(); } catch (e) { /* the list re-renders with what it has */ }
    renderConnList();
    if (c.id === CONN.active) rebootData();
  });
}
async function selectConn(id) {
  try { await jf("api/connections/select", post({ id })); } catch (e) { return false; }
  binaTell("החשבון הוחלף");
  try { await loadConnections(); } catch (e) { /* shown on the next open */ }
  renderConnList();
  rebootData();
  return true;
}
async function renderConnect(seq) {
  connectFrame(stepsHtml(1) + `<div class="cw-msg soft">טוען ספקים…</div>`);
  let provs = [];
  try { provs = (await jf("api/providers", { silent: true })).providers || []; }
  catch (e) {
    if (seq !== SET_SEQ) return;
    $("#cwBody").innerHTML = failBox("רשימת הספקים לא נטענה", e, "cwRetry");
    $("#cwRetry").onclick = () => busy($("#cwRetry"), () => renderConnect(seq));
    return;
  }
  if (seq !== SET_SEQ) return;
  if (!provs.length) { $("#cwBody").innerHTML = `<div class="cw-msg err">${ic("alert")}<div>לא נמצאו ספקים.</div></div>`; return; }
  stepProvider(provs);
}
function stepProvider(provs) {
  cwStop();
  $("#cwBody").innerHTML = stepsHtml(1) + `<div class="cw-msg soft">בחר את הספק שבו נמצא הדואר.</div><div class="cw-grid">` + provs.map((p, i) =>
    `<button class="cw-card" data-i="${i}" type="button">
       <span class="cw-ic">${ic(ICONS[p.icon] ? p.icon : "mail")}</span>
       <span class="cw-t">${esc(p.name)}${p.builtin ? `<span class="chip healthy">מובנה</span>` : ""}</span>
       <span class="cw-d">${esc(p.description || "")}</span></button>`).join("") + `</div>`;
  $("#cwBody").querySelectorAll(".cw-card").forEach(b => b.onclick = () => stepMethod(provs, provs[+b.dataset.i]));
}
function stepMethod(provs, prov) {
  cwStop();
  const ms = prov.auth_methods || [];
  $("#cwBody").innerHTML = stepsHtml(2) + `<div class="cw-msg soft">חיבור ${esc(prov.name)} — כל אפשרות מסבירה מה היא דורשת ומה היא תאפשר.</div>` +
    ms.map((m, i) => `<button class="cw-m" data-i="${i}" type="button">
       <span class="cw-m-h">${ic(m.start_url ? "external" : "key")} ${esc(m.label)}${m.recommended ? `<span class="chip healthy">מומלץ</span>` : ""}</span>
       <span class="cw-m-d">${esc(m.can || "")}</span>
       ${m.needs && m.needs.length ? `<span class="cw-m-need">${m.needs.map(n => `<span>${esc(NEEDLBL[n] || n)}</span>`).join("")}</span>` : ""}</button>`).join("")
    + `<div class="set-acts"><button class="btn ghost" data-back type="button">חזרה</button></div>`;
  $("#cwBody").querySelector("[data-back]").onclick = () => stepProvider(provs);
  $("#cwBody").querySelectorAll(".cw-m").forEach(b => b.onclick = () => {
    const m = ms[+b.dataset.i];
    if (m.protocol === "mail_imap_local") return stepBuiltin(provs, prov);
    if (m.start_url) return stepOauth(provs, prov, m);
    return stepForm(provs, prov, m);
  });
}
function stepBuiltin(provs, prov) {
  const locals = CONN.list.filter(isLocalConn);
  $("#cwBody").innerHTML = stepsHtml(5) +
    `<div class="cw-msg ok">${ic("check-circle")}<div>תיבות שרת הדואר המקומי מובנות במערכת ואינן דורשות חיבור.<span class="sub">אין מה למלא כאן: השרת נמצא בתוך המערכת, וכל תיבה שנוצרת בו מקבלת את החיבור שלה באותה פעולה.</span></div></div>` +
    (locals.length
      ? `<div class="st-list">` + locals.map((c, i) => `<button class="cw-m" data-i="${i}" type="button"><span class="cw-m-h">${esc(connName(c))}${c.id === CONN.active ? `<span class="chip healthy">פעיל</span>` : ""}</span>
             <span class="cw-m-d ltr"><bdi>${esc(c.account_hint || c.id)}</bdi></span></button>`).join("") + `</div>`
      : `<div class="cw-msg">${ic("alert")}<div>עדיין אין תיבה מקומית.</div></div>`)
    + `<div class="set-acts"><button class="btn ghost" data-mb type="button">${ic("plus")} הוספת כתובת בחברה</button><button class="btn ghost" data-back type="button">חזרה</button></div>`;
  $("#cwBody").querySelectorAll(".cw-m").forEach(b => b.onclick = () => busy(b, () => selectConn(locals[+b.dataset.i].id)));
  $("#cwBody").querySelector("[data-back]").onclick = () => stepMethod(provs, prov);
  $("#cwBody").querySelector("[data-mb]").onclick = () => openSettings("mailboxes", true);
}
function stepOauth(provs, prov, m) {
  cwStop();
  const before = new Set(CONN.list.map(c => c.id));
  $("#cwBody").innerHTML = stepsHtml(3) +
    `<div class="cw-msg">${ic("info")}<div>${esc(m.explain || "")}</div></div>
     <div class="cw-msg soft">החלון נפתח אצל ספק הזהות, לא כאן — הסיסמה שלך לעולם אינה עוברת דרך המערכת הזו.</div>
     <div class="set-acts"><button class="btn" data-open type="button">${ic("external")} פתיחת חלון האישור</button><button class="btn ghost" data-back type="button">חזרה</button></div>`;
  $("#cwBody").querySelector("[data-back]").onclick = () => stepMethod(provs, prov);
  $("#cwBody").querySelector("[data-open]").onclick = () => {
    window.open(m.start_url, "_blank", "noopener,width=560,height=720");
    waitOauth(provs, prov, m, before);
  };
}
function waitOauth(provs, prov, m, before) {
  cwStop();
  let tries = 0;
  $("#cwBody").innerHTML = stepsHtml(3) +
    `<div class="cw-msg wait"><span class="spin">${ic("clock")}</span><div><b>ממתין לאישור בחלון של ${esc(prov.name)}…</b><span class="sub">אם סגרת את החלון או ביטלת — לא נוצר חיבור, אפשר לנסות שוב.</span></div></div>
     <div class="set-acts"><button class="btn ghost" data-again type="button">${ic("external")} פתיחה מחדש</button><button class="btn ghost" data-cancel type="button">ביטול</button></div>`;
  $("#cwBody").querySelector("[data-again]").onclick = () => window.open(m.start_url, "_blank", "noopener,width=560,height=720");
  $("#cwBody").querySelector("[data-cancel]").onclick = () => stepMethod(provs, prov);
  CW_TIMER = setInterval(async () => {
    tries++;
    let d; try { d = await jf("api/connections", { silent: true }); } catch (e) { return; }
    const list = d.connections || [];
    const fresh = list.find(c => !before.has(c.id) && c.protocol === m.protocol);
    if (fresh) { cwStop(); CONN.list = list; CONN.active = d.active || CONN.active; renderConnList(); return stepVerify(provs, prov, m, fresh); }
    if (tries > 60) {          // ~3 minutes
      cwStop();
      $("#cwBody").innerHTML = stepsHtml(3) + `<div class="cw-msg err">${ic("alert")}<div><b>לא התקבל אישור</b><span class="sub">החלון נסגר, האישור בוטל, או שהחיבור לספק נכשל. אפשר לנסות שוב.</span></div></div>
        <div class="set-acts"><button class="btn" data-retry type="button">ניסיון נוסף</button><button class="btn ghost" data-back type="button">חזרה</button></div>`;
      $("#cwBody").querySelector("[data-retry]").onclick = () => stepOauth(provs, prov, m);
      $("#cwBody").querySelector("[data-back]").onclick = () => stepMethod(provs, prov);
    }
  }, 3000);
}
function stepForm(provs, prov, m) {
  cwStop();
  $("#cwBody").innerHTML = stepsHtml(3) +
    (m.explain ? `<div class="cw-msg">${ic("info")}<div>${esc(m.explain)}</div></div>` : "") +
    `<div class="set-form">` + (m.needs || []).map(n => `<div class="field"><label for="cw_${esc(n)}">${esc(NEEDLBL[n] || n)}</label>
      <input id="cw_${esc(n)}" type="${n === "password" ? "password" : "text"}" data-need="${esc(n)}" dir="ltr" autocomplete="off"></div>`).join("") +
    (m.help_url ? `<a class="link" href="${esc(m.help_url)}" target="_blank" rel="noopener">${ic("external")} מהיכן משיגים את הערך הזה?</a>` : "") +
    `<div class="row"><button class="btn" data-go type="button">המשך לבדיקה</button><button class="btn ghost" data-back type="button">חזרה</button></div></div>`;
  $("#cwBody").querySelector("[data-back]").onclick = () => stepMethod(provs, prov);
  const go = $("#cwBody").querySelector("[data-go]");
  go.onclick = () => busy(go, async () => {
    const secret = {};
    for (const i of $("#cwBody").querySelectorAll("[data-need]")) secret[i.dataset.need] = i.value.trim();
    if (Object.values(secret).some(v => !v)) return binaTell("יש למלא את כל השדות", "warn");
    let r;
    try { r = await jf("api/connections", post({ protocol: m.protocol, label: prov.name, secret, account_hint: secret.username || "" })); }
    catch (e) { return; }
    if (!r || !r.id) return fail("יצירת החיבור נכשלה — השירות לא החזיר מזהה");
    try { await loadConnections(); } catch (e) { /* verify still runs on the id we have */ }
    renderConnList();
    stepVerify(provs, prov, m, CONN.list.find(c => c.id === r.id) || { id: r.id });
  });
}
async function stepVerify(provs, prov, m, conn) {
  cwStop();
  $("#cwBody").innerHTML = stepsHtml(4) + `<div class="cw-msg wait"><span class="spin">${ic("clock")}</span><div>בודק את החיבור מול ${esc(prov.name)}…</div></div>`;
  let r;
  try { r = await jf("api/connections/" + enc(conn.id) + "/probe", { silent: true }); }
  catch (e) { r = { ok: false, reason: e.message }; }
  const ok = !!(r && r.ok);
  const hint = (r && r.account_hint) || conn.account_hint;
  if (!ok) {
    $("#cwBody").innerHTML = stepsHtml(4) + `<div class="cw-msg err">${ic("alert")}<div><b>החיבור נוצר אך אינו עובד</b><span class="sub"><bdi>${esc((r && r.reason) || "הבדיקה נכשלה")}</bdi></span></div></div>
      <div class="set-acts"><button class="btn" data-again type="button">${ic("refresh")} בדיקה חוזרת</button><button class="btn danger" data-rm type="button">${ic("trash")} הסרת החיבור</button></div>`;
    $("#cwBody").querySelector("[data-again]").onclick = () => stepVerify(provs, prov, m, conn);
    const rm = $("#cwBody").querySelector("[data-rm]");
    rm.onclick = () => busy(rm, async () => {
      try { await jf("api/connections/" + enc(conn.id), { method: "DELETE" }); } catch (e) { return; }
      binaTell("החיבור הוסר");
      try { await loadConnections(); } catch (e) { /* list re-renders with what it has */ }
      renderConnList(); stepProvider(provs);
    });
    return;
  }
  $("#cwBody").innerHTML = stepsHtml(5) + `<div class="cw-msg ok">${ic("check-circle")}<div><b>הבדיקה עברה</b><span class="sub">${esc(conn.label || prov.name)}${hint ? " · " : ""}${hint ? `<bdi class="ltr">${esc(hint)}</bdi>` : ""}</span></div></div>
    <div class="cw-msg soft">אפשר להפעיל את החשבון עכשיו — כל הפעולות (כולל האוטומציות) יעברו לעבוד מולו.</div>
    <div class="set-acts"><button class="btn" data-act type="button">הפעלה כחשבון פעיל</button><button class="btn ghost" data-keep type="button">שמירה בלי להפעיל</button></div>`;
  const act = $("#cwBody").querySelector("[data-act]");
  act.onclick = () => busy(act, async () => { if (await selectConn(conn.id)) stepProvider(provs); });
  $("#cwBody").querySelector("[data-keep]").onclick = () => stepProvider(provs);
}

/* ── boot ─────────────────────────────────────────────────────────────────────────────────────── */
function bootFailed(e) {
  ACCOUNT_LINE = "לא מחובר"; renderSide();
  $("#viewTitle").innerHTML = `${ic("mail")} מייל`;
  showScreen("list");
  $("#msgTable").innerHTML = `<div class="failbox">${ic("alert")}<b>לא ניתן להתחבר לתיבה</b>
    <span class="why"><bdi>${esc(e.message)}</bdi>${e.detail ? ` · <bdi>${esc(e.detail)}</bdi>` : ""}</span>
    <button class="btn" id="bootRetry" type="button">${ic("refresh")} נסה שוב</button></div>`;
  $("#statusbar").textContent = "";
  $("#bootRetry").onclick = () => busy($("#bootRetry"), boot);
}
async function loadAccount() {
  const acct = await jf("api/account", { silent: true });
  MODE = acct.mode === "local" ? "local" : "gmail";
  ACCOUNT_LINE = acct.user + (MODE === "local" ? " · מקומי" : " · Gmail");
  renderSide();
}
/* re-read the whole world for the (possibly new) active connection, keeping the screen */
async function rebootData() {
  MSGCACHE.clear(); HIDDEN.clear(); SELECTED.clear(); BUSY_IDS.clear(); ORG = null;
  try { await loadAccount(); } catch (e) { bootFailed(e); return; }
  await Promise.all([loadLabels(), loadLabelMap()]);
  await applyUrl();
}
async function boot() {
  renderGear();
  document.body.dataset.density = DENSITY;
  try { await loadAccount(); } catch (e) { bootFailed(e); return; }
  await Promise.all([loadLabels(), loadLabelMap()]);
  await applyUrl();
}
/* THE CONTRACT with the console shell (platform-base/console/static/app.js reloadEmbeddedApp):
     in   { type: 'platform:connection-changed' | 'platform:reload', service?: 'mail' }
     out  { type: 'platform:reload-ack', service: 'mail' }
   An app that answers is re-read in place; one that does not is reloaded by the shell. No
   connection id is taken from the message — the service owns the pointer and is re-asked. */
window.addEventListener("message", ev => {
  if (ev.origin !== location.origin) return;
  const d = ev.data;
  if (!d || typeof d !== "object") return;
  if (d.type !== "platform:connection-changed" && d.type !== "platform:reload") return;
  if (d.service && d.service !== "mail" && d.service !== "mailview") return;
  try { if (ev.source && ev.source.postMessage) ev.source.postMessage({ type: "platform:reload-ack", service: "mail" }, location.origin); } catch (e) { /* opaque */ }
  rebootData();
});
boot();
