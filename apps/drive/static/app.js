/* דרייב — the drive service's own UI. Domain-native by contract (§5): folder tree · file list ·
   preview · upload · move · trash · search, all against the ACTIVE connection. It knows nothing
   about any app above it.

   Everything app-specific on this screen arrives through /extensions (§4c): an app registers a
   spec into a slot, this file renders it and never reads a field of it for meaning. The rail below
   is drawn from `spec.groups[].items[]` — labels, colours and hints are the app's strings; the
   containers are ordinary folders, which is why dropping a file on one is just a move.

   One interaction model throughout: selection (click/ctrl/shift/ctrl+A) · drag rows -> folders to
   move · bulk bar · right-click context menu · sortable columns · global search ·
   URL = state: /folder/<id> · /folder/<id>/file/<fid> · /trash · /search?q= */
const $ = s => document.querySelector(s);
let FOLDERS = [], SHARED_FOLDERS = [], FILES = [], CUR = null, TRASH = false, SEARCHQ = "", PV = null;
let RAIL = [], CONT = {}, CONN = { active: null, list: [], ready: null };
let SEL = new Set(), lastClicked = null;
let SORT = JSON.parse(localStorage.getItem("sort") || '{"key":"created","dir":-1}');
/* ── Drive-grade view state ──────────────────────────────────────────────────────────────────────
   VIEW    — the cross-cutting standing queries. '' means "a folder" (CUR says which).
   LAYOUT  — list or grid. Persisted, because it is a preference about how this person reads, not
             about this folder; making it per-folder would force the same choice over and over.
   DETAILS — whether the info pane is pinned open. Also persisted, same reasoning.
   FILT    — the active filter chips. Cleared on every navigation: a filter that survives a move to
             another folder silently hides files and reads as "the folder is empty". */
let VIEW = "", LAYOUT = localStorage.getItem("layout") || "list";
let DETAILS = localStorage.getItem("details") === "1";
let FILT = { type: "", modified: "", people: "" };
let STORAGE = null;
/* Windowing. A ten-year archive has folders with thousands of files; painting 3,000 rows (or 3,000
   grid cards, each with an SVG) is where a file manager stops feeling instant. So the VIEW is
   windowed — sorting, filtering, counting and select-all still run over the whole list, only the
   DOM is capped, and the window grows as you scroll. */
const PAGE = 180;
let SHOWN = PAGE;

/* ── icons (Lucide paths; never emoji) ── */
const ICONS = {
  folder:   '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  'folder-input': '<path d="M2 9V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-1"/><path d="M2 13h10"/><path d="m9 16 3-3-3-3"/>',
  file:     '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
  'file-text': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
  image:    '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
  table:    '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/>',
  presentation: '<path d="M2 3h20"/><path d="M21 3v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V3"/><path d="m7 21 5-5 5 5"/>',
  archive:  '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
  upload:'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  trash:    '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
  search:   '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  pencil:   '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/>',
  link:     '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  eye:      '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  restore:  '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  more:     '<circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>',
  'x-circle': '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
  x:        '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  plus:     '<path d="M5 12h14"/><path d="M12 5v14"/>',
  chevron:  '<path d="m6 9 6 6 6-6"/>',
  check:    '<path d="M20 6 9 17l-5-5"/>',
  'check-circle': '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  alert:    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  'hard-drive': '<line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" y1="16" x2="6.01" y2="16"/><line x1="10" y1="16" x2="10.01" y2="16"/>',
  cloud:    '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  clock:    '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  menu:     '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>',
  users:    '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/>',
  'list-view': '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
  'grid-view': '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
  info:     '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  star:     '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>',
  home:     '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
  share:    '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.6" y1="10.5" x2="15.4" y2="6.5"/><line x1="8.6" y1="13.5" x2="15.4" y2="17.5"/>',
  globe:    '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20a15 15 0 0 1 0-20z"/>',
  lock:     '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  filter:   '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
  'chevron-start': '<path d="m15 18-6-6 6-6"/>',
  'chevron-end':   '<path d="m9 18 6-6-6-6"/>',
};
const ic = n => ICONS[n]
  ? `<svg class="ic-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`
  : "";
/* static markup declares its icon: <span data-ic="upload"></span> */
const paintIcons = root => (root || document).querySelectorAll("[data-ic]").forEach(e => {
  if (!e.firstChild) e.innerHTML = ic(e.dataset.ic);
});

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
/* ── plumbing ── */
const jf = async (u, opt) => {
  let r;
  try { r = await fetch(u, opt); }
  catch (e) { tellBad(binaSaid(0)); throw e; }              // the office's one name for no answer (it said «שגיאת רשת — נסה שוב»)
  if (!r.ok) {
    const d = await r.json().catch(() => null);
    tellBad((d && d.error) || binaSaid(r.status));          // (it said «שגיאה (502)»: a number, where the office has words)
    throw new Error(r.status);
  }
  return r.json();
};
const jsoft = async (u, opt) => {          // never toasts — for background/probe reads
  try { const r = await fetch(u, opt); return { ok: r.ok, d: await r.json().catch(() => null) }; }
  catch (e) { return { ok: false, d: null }; }
};
const post = body => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
// BANK-STANDARD re-entrancy guard: disable a button while its request is in flight so a double-click /
// slow response can't fire the same mutation twice. (What cannot be taken back is not behind this guard but
// asked through the office's question, which holds its own action while it runs — see `must`.)
// Always re-enables in finally; jf() already surfaces its own Hebrew error toast on failure.
async function guard(btn, fn) {
  if (!btn || btn.disabled) return;
  btn.disabled = true; btn.setAttribute("aria-busy", "true");
  try { return await fn(); }
  catch (e) { /* jf already toasted; leave button re-enabled so the user can retry */ }
  finally { btn.disabled = false; btn.removeAttribute("aria-busy"); }
}
let _uploading = false, _moveBusy = false;   // in-flight guards for the create (upload) and move paths
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
// The office's notice (binaTell) is this screen's too. A failure is said as one and a missing step as a
// warning - the screen's own toast had one look for «הועלו 3 קבצים» and for «שגיאת רשת». A notice with a way
// back is the office's as well: eight seconds, with «ביטול» in it (the block's `act`).
const tellBad = m => binaTell(m, "bad"), tellWarn = m => binaTell(m, "warn");
const tellUndo = (m, undo) => binaTell(m, "ok", { ms: 8000, act: ["ביטול", undo] });
// A count is said the way it is read - «קובץ אחד», «3 קבצים», never «1 קבצים» - and a notice of one file is
// about «הקובץ»: «הקובץ הועבר», «3 קבצים הועברו».
const counted = (n, one, many) => n === 1 ? one : `${n} ${many}`;
const filesSaid = (n, one, many) => n > 1 ? `${n} קבצים ${many}` : `הקובץ ${one}`;
// What cannot be taken back - a permanent delete, a removed account or profile, a replaced key - is asked
// through the office's question (binaAsk), and the question does it (`run`): its action is busy while the
// request is out, and a refusal is said IN the question, in the service's words, with the action offered
// again. `must` is that request: its answer, or the refusal thrown for the question to say.
const must = async (p, say) => { const r = await p; if (!r.ok) throw new Error((r.d && r.d.error) || say); return r.d; };
/* Sizes read at the scale a human would say them out loud. A storage meter that reports
   "238418.6 MB" is technically right and useless — nobody holds six digits in their head. */
// A size is ONE left-to-right token wherever it lands (U+2066 … U+2069 isolate it): bare "3.5 MB"
// in a Hebrew line is drawn "MB 3.5" — the status bar and the storage line both read that way.
const fmtKB = n => !n ? "" : "\u2066" + (
  n >= 1099511627776 ? (n / 1099511627776).toFixed(2) + " TB" :
  n >= 1073741824 ? (n / 1073741824).toFixed(1) + " GB" :
  n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" :
  Math.max(1, Math.round(n / 1024)) + " kB") + "\u2069";
const icon = m => m.includes("pdf") ? ["pdf", "file-text"] : m.startsWith("image") ? ["img", "image"] :
  (m.includes("sheet") || m.includes("excel")) ? ["xls", "table"] :
  m.includes("presentation") ? ["ppt", "presentation"] :
  (m.includes("document") || m.includes("wordprocessingml") || m.startsWith("text/")) ? ["doc", "file-text"] :
  /zip|rar|tar|gzip/.test(m) ? ["zip", "archive"] : ["", "file"];
/* Human words for a mime type. The details pane says "גיליון Google", never the mime string —
   a mime type is a fact about the system, not an answer to "what is this?". */
const typeName = m => {
  m = String(m || "");
  if (m.includes("google-apps.document")) return "מסמך Google";
  if (m.includes("google-apps.spreadsheet")) return "גיליון Google";
  if (m.includes("google-apps.presentation")) return "מצגת Google";
  if (m === "application/pdf") return "PDF";
  if (m.startsWith("image/")) return "תמונה " + m.slice(6).toUpperCase();
  if (m.includes("wordprocessingml")) return "מסמך Word";
  if (m.includes("spreadsheetml")) return "גיליון Excel";
  if (m.includes("presentationml")) return "מצגת PowerPoint";
  if (m.startsWith("text/")) return "טקסט";
  if (/zip|rar|tar|gzip/.test(m)) return "ארכיון";
  return "קובץ";
};
const previewable = m => !m || m.includes("pdf") || m.startsWith("image") || m.startsWith("text");
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/* a colour arrives from a registered spec — treat it as untrusted input, never interpolate raw */
const safeColor = c => /^#[0-9a-f]{3,8}$/i.test(String(c || "")) ? c : "var(--muted)";
/* bytes for preview/download go through the ACTIVE connection (a remote account has no public link) */
const contentPath = id => `api/file/${encodeURIComponent(id)}/content`;
/* the shareable link the connection itself publishes (local: /file/d/<id>/view) */
const shareLink = f => (f && f.link) || new URL(contentPath(f.id), document.baseURI).href;
const copyText = async (txt, msg) => {
  try { await navigator.clipboard.writeText(txt); }
  catch (e) { const i = document.createElement("input"); i.value = txt; document.body.appendChild(i);
    i.select(); document.execCommand("copy"); i.remove(); }
  binaTell(msg || "הקישור הועתק");
};
/* WHEN, as an instant. The server hands a time as "YYYY-MM-DD HH:MM" in UTC — both adapters cut the
   instant down to that and drop its offset — and read as written a browser takes it for LOCAL time.
   Measured 2026-10-05: a file uploaded at 14:28 in Israel was listed as "היום 11:28", and one that
   arrived from another office at 16:35 as "13:35". A time that carries its own offset (or Z) is read
   as it is; one that carries none is UTC. */
const instant = s => {
  const t = String(s || "").trim().replace(" ", "T");
  return new Date(/(?:[zZ]|[+-]\d\d:?\d\d)$/.test(t) ? t : t + "Z");
};
const fmtDate = s => {
  if (!s) return "";
  const d = instant(s);
  if (isNaN(d)) return s;
  const today = new Date(), y = new Date(); y.setDate(today.getDate() - 1);
  const hm = d.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return "היום " + hm;
  if (d.toDateString() === y.toDateString()) return "אתמול " + hm;
  // a ten-year archive needs the year, or "27 באוג׳" means ten different days
  if (d.getFullYear() !== today.getFullYear())
    return d.toLocaleDateString("he-IL", { day: "numeric", month: "short", year: "numeric" });
  return d.toLocaleDateString("he-IL", { day: "numeric", month: "short" }) + " " + hm;
};
const fileById = id => FILES.find(f => f.id === id) || { id, name: id, mime: "" };
const folderById = id => FOLDERS.find(f => f.id === id) || null;

/* Display name for a container: an app that registered it names it; otherwise the connection does;
   otherwise it is its own id. Three fallbacks, no knowledge of what any of them mean. */
const contName = fid => {
  const c = CONT[fid];
  if (c) return `${c.group} · ${c.label}`;
  const f = folderById(fid);
  return (f && f.name) || fid;
};

/* ── modal system ── */
function modal(title, bodyHtml, footBtns) {
  $("#mTitle").textContent = title;
  $("#mBody").innerHTML = bodyHtml;
  const foot = $("#mFoot"); foot.innerHTML = "";
  for (const b of footBtns || []) {
    const el = document.createElement("button");
    el.className = b.cls || "ghost"; el.innerHTML = (b.icon ? ic(b.icon) + " " : "") + esc(b.label);
    el.onclick = b.onclick;
    foot.appendChild(el);
  }
  paintIcons($("#mBody"));
  $("#modal").classList.remove("hidden"); $("#overlay").classList.remove("hidden");
}
function closeModal() {
  $("#modal").classList.add("hidden");
  if ($("#preview").classList.contains("hidden")) $("#overlay").classList.add("hidden");
}
$("#mClose").onclick = closeModal;

/* ── URL routing ──
   The app's own paths (/folder/<id>, /trash, …) hang off its MOUNT POINT: the root when it runs on
   its own host, and /a/<alias>/ when a console frames it — the console injects that as the
   document base, which is where it is read from (never assumed to be the root).
   Assumed, it was wrong in both directions under a console (measured 2026-10-05 from the MacBook
   office, on the HP office's drive): a deep link to a folder opened Home, because the path began
   with /a/drive.hp-laptop/ and nothing matched; and a step taken inside the app pushed /folder/<id>
   onto the CONSOLE's root, so reloading the frame asked the console for a page it does not have. */
const MOUNT = new URL(document.baseURI).pathname.replace(/\/+$/, "");       // "" or "/a/<alias>"
const appPath = () => {
  const p = location.pathname;
  return MOUNT && (p === MOUNT || p.startsWith(MOUNT + "/")) ? (p.slice(MOUNT.length) || "/") : p;
};
const pathFor = (folder, file) => TRASH ? "/trash" : SEARCHQ ? "/search?q=" + encodeURIComponent(SEARCHQ) :
  folder ? "/folder/" + encodeURIComponent(folder) + (file ? "/file/" + encodeURIComponent(file) : "") :
  VIEW && VIEW !== "mydrive" ? "/p/" + encodeURIComponent(VIEW) : "/";
const nav = (folder, file, replace) => {
  const p = pathFor(folder, file);
  if (appPath() + location.search !== p) history[replace ? "replaceState" : "pushState"]({}, "", MOUNT + p);
};
function parseUrl() {
  const path = appPath();
  const m = path.match(/^\/folder\/([^/]+)(?:\/file\/([^/]+))?$/);
  if (m) return { folder: decodeURIComponent(m[1]), file: m[2] ? decodeURIComponent(m[2]) : null };
  if (path === "/trash") return { trash: true };
  if (path === "/search")
    return { search: new URLSearchParams(location.search).get("q") || "" };
  const pm = path.match(/^\/p\/([^/]+)$/);
  if (pm && SYS_PLACES.some(p => p.id === pm[1])) return { place: pm[1] };
  return {};
}
window.addEventListener("popstate", () => applyUrl());
async function applyUrl() {
  const st = parseUrl();
  closePv(true); closeModal(); clearSel();
  if (st.trash) return openTrash(false);
  if (st.place) return openPlace(st.place, false);
  if (st.search) { $("#search").value = st.search; return runGlobalSearch(st.search, false); }
  if (st.folder) {
    await openFolder(st.folder, false);
    if (st.file) {
      const f = FILES.find(x => x.id === st.file);
      preview(f || { id: st.file, name: st.file, mime: "" }, false);
    }
    return;
  }
  /* No route = the drive's front door. A drive that opens on "בחר תיקייה מהצד" wastes the most
     valuable screen it will ever show; Home opens on what you touched last. */
  return openPlace("home", false);
}

/* ── sidebar: extension rail (§4c) + the connection's own folder tree ── */
const grpState = key => localStorage.getItem("grp:" + key) !== "0";
const setGrp = (key, open) => localStorage.setItem("grp:" + key, open ? "1" : "0");
const countOf = fid => { const f = folderById(fid); return f && f.count ? f.count : 0; };

/* An app's rail, rendered from its registered spec. Every string here (title, group label, item
   label, colour, hint) is the app's; this function does not know what any of it is for, and the
   drive still works — identically — when nothing is registered. */
function renderRail() {
  const mount = $("#railMount");
  mount.innerHTML = "";
  CONT = {};
  for (const ext of RAIL) {
    const spec = (ext && ext.spec) || {};
    const groups = Array.isArray(spec.groups) ? spec.groups : [];
    if (!groups.length) continue;
    if (spec.title) {
      const h = document.createElement("div");
      h.className = "navhead";
      h.innerHTML = `<span>${esc(spec.title)}</span>`;
      mount.appendChild(h);
    }
    for (const g of groups) {
      const key = String(g.id || g.label || "");
      const items = (Array.isArray(g.items) ? g.items : []).filter(it => it && it.container);
      if (!items.length) continue;
      const el = document.createElement("div");
      el.className = "grp" + (grpState(key) ? "" : " closed");
      const total = items.reduce((n, it) => n + countOf(it.container), 0);
      el.innerHTML = `<div class="grp-h"><span class="car" data-ic="chevron"></span>
        <span class="gi" data-ic="${esc(g.icon && ICONS[g.icon] ? g.icon : "folder")}"></span>
        <span class="lbl">${esc(g.label || key)}</span>
        <span class="gcnt">${total || ""}</span></div><div class="grp-body"></div>`;
      el.querySelector(".grp-h").onclick = () => {
        el.classList.toggle("closed"); setGrp(key, !el.classList.contains("closed"));
      };
      const body = el.querySelector(".grp-body");
      for (const it of items) {
        CONT[it.container] = { group: g.label || key, label: it.label || it.container,
                               color: it.color, hint: it.hint };
        body.appendChild(navLink(it.container,
          `<span class="dot" style="background:${safeColor(it.color)}"></span>
           <span class="lbl">${esc(it.label || it.container)}</span>`, countOf(it.container)));
      }
      mount.appendChild(el);
    }
  }
  paintIcons(mount);
}

/* ── system places ───────────────────────────────────────────────────────────────────────────────
   Three of these are folders-in-spirit only. "אחרונים / מסומן בכוכב / משותף איתי" are standing
   QUERIES over the same files — which is why a file appears in several at once and why moving it
   changes none of them. Keeping them above the tree, visually separated, is what teaches that. */
const SYS_PLACES = [
  { id: "home",    he: "דף הבית",      icon: "home" },
  { id: "mydrive", he: "הדרייב שלי",   icon: "hard-drive" },
  { id: "shared",  he: "שיתפו איתי",   icon: "users" },
  { id: "recent",  he: "לאחרונה",      icon: "clock" },
  { id: "starred", he: "מסומן בכוכב",  icon: "star" },
  { id: "trash",   he: "אשפה",         icon: "trash" },
];
function renderSysRail() {
  const box = $("#sysRail");
  box.innerHTML = SYS_PLACES.map(p => `
    <a class="bnv-item ${(p.id === "trash" ? TRASH : !TRASH && !SEARCHQ && VIEW === p.id) ? "is-active" : ""}"
       href="#" data-place="${p.id}">
      <span class="bnv-ic" data-ic="${p.icon}"></span><span class="bnv-label">${p.he}</span></a>`).join("");
  box.querySelectorAll("[data-place]").forEach(a => {
    a.onclick = e => {
      e.preventDefault(); sideOpen(false);
      const id = a.dataset.place;
      if (id === "trash") { history.pushState({}, "", MOUNT + "/trash"); openTrash(false); }
      else openPlace(id);
    };
    /* the system places that ARE places accept drops; the query views cannot (there is no folder
       to move into), so they simply never register as targets */
    if (a.dataset.place === "mydrive") {
      a.addEventListener("dragover", e => { if (dragIds) { e.preventDefault(); a.classList.add("droptgt"); } });
      a.addEventListener("dragleave", () => a.classList.remove("droptgt"));
      a.addEventListener("drop", async e => {
        a.classList.remove("droptgt");
        if (!dragIds) return;
        e.preventDefault(); e.stopPropagation();
        const ids = dragIds; dragIds = null;
        await jf("api/move", post({ ids, to: "" }));
        binaTell(`${filesSaid(ids.length, "הועבר", "הועברו")} אל הדרייב שלי`);
        clearSel(); refresh();
      });
    }
  });
  paintIcons(box);
}

/* ── storage meter ── */
async function loadStorage() {
  const r = await jsoft("api/storage");
  STORAGE = r.ok ? r.d : null;
  renderStorage();
}
/* The meter reads the field the backend actually sends. It used to gate on `STORAGE.total`, which
   no adapter has ever emitted — so the whole box was dead code: it rendered "" on every load, on
   every deployment, and looked like a feature nobody had asked about yet. The backend sends
   `{files, used, limit?}`, and `limit` is ABSENT unless DRIVE_STORAGE_LIMIT is configured, because
   a meter showing an invented ceiling is worse than one showing none. So: a bar when there is a
   real ceiling, the bytes used either way. The number is per-PROFILE now, like every other read. */
function renderStorage() {
  const box = $("#storeBox");
  if (!box) return;
  if (!STORAGE || typeof STORAGE.used !== "number") { box.innerHTML = ""; return; }
  const limit = STORAGE.limit;
  const head = `<div class="sl"><span data-ic="hard-drive"></span> אחסון</div>`;
  if (!limit) {
    box.innerHTML = head + `<div class="sn">${fmtKB(STORAGE.used) || "\u20660 kB\u2069"}
      ${STORAGE.files ? `· ${counted(STORAGE.files, "קובץ אחד", "קבצים")}` : ""}</div>`;
  } else {
    const pct = Math.min(100, Math.round((STORAGE.used / limit) * 100));
    const cls = pct >= 90 ? "full" : pct >= 75 ? "warn" : "";
    box.innerHTML = head +
      `<div class="storebar ${cls}"><i style="width:${pct}%"></i></div>
       <div class="sn">${fmtKB(STORAGE.used)} מתוך ${fmtKB(limit)} · ${pct}%</div>`;
  }
  paintIcons(box);
}

/* The domain-native tree: whatever folders the ACTIVE connection has. Flat when the connection is
   flat (the local drive), nested when it is not (Google Drive) — same renderer either way. */
/* The domain-native tree: whatever folders the ACTIVE connection has. Flat when the connection is
   flat, nested when it is not — same renderer either way.

   Nodes with children COLLAPSE. A ten-year archive is ~130 folders; drawing them all flat turns the
   rail into a wall of identical month names and makes the one folder you want unfindable. Open
   state is per-folder and persisted, and the path to the folder you are IN is force-opened, so the
   tree always shows where you are without you having to re-open it. */
function renderTree() {
  const box = $("#treeList");
  box.innerHTML = "";
  const known = new Set(FOLDERS.map(f => f.id));
  const kids = {};
  for (const f of FOLDERS) {
    const p = f.parent && known.has(f.parent) ? f.parent : "";
    (kids[p] = kids[p] || []).push(f);
  }
  const roots = (kids[""] || []).sort((a, b) => String(a.name).localeCompare(String(b.name), "he"));
  if (!roots.length) {
    box.innerHTML = '<div class="navempty">אין תיקיות עדיין</div>';
    return;
  }
  // force the ancestors of the current folder open
  const onPath = new Set();
  let cur = CUR ? folderById(CUR) : null, guard = 0;
  while (cur && guard++ < 12) { onPath.add(cur.id); cur = cur.parent ? folderById(cur.parent) : null; }

  const isOpen = id => onPath.has(id) || localStorage.getItem("tree:" + id) === "1";
  const draw = (list, depth, into) => {
    for (const f of list.sort((a, b) => String(a.name).localeCompare(String(b.name), "he"))) {
      const children = kids[f.id] || [];
      const open = children.length && isOpen(f.id);
      const row = navLink(f.id,
        `<span class="tw ${children.length ? (open ? "open" : "shut") : "leaf"}" data-tw="${esc(f.id)}"></span>
         <span class="bnv-ic" data-ic="folder"></span><span class="bnv-label" dir="auto">${esc(f.name || f.id)}</span>`,
        f.count);
      row.style.paddingInlineStart = 8 + depth * 13 + "px";
      into.appendChild(row);
      const tw = row.querySelector(".tw");
      if (children.length) {
        tw.innerHTML = ic("chevron");
        tw.onclick = e => {
          e.preventDefault(); e.stopPropagation();
          localStorage.setItem("tree:" + f.id, isOpen(f.id) ? "0" : "1");
          renderTree();
        };
      }
      if (open && depth < 6) draw(children, depth + 1, into);
    }
  };
  draw(roots, 0, box);
  paintIcons(box);
}

function navLink(fid, inner, count) {
  const a = document.createElement("a");
  a.className = "bnv-item"; a.href = "/folder/" + encodeURIComponent(fid); a.dataset.fid = fid;
  // the count rides in the component's TRAILING slot: the label keeps the width, the badge never
  // pushes it out — and the tree's own indent is a padding the component never overrides.
  a.innerHTML = inner + (count ? `<span class="bnv-tail"><span class="cnt">${count}</span></span>` : "");
  a.onclick = e => { e.preventDefault(); sideOpen(false); SEARCHQ = ""; nav(fid); openFolder(fid, false); };
  /* drop target: a container is a folder, so dropping on it is a move — nothing more */
  a.addEventListener("dragover", e => {
    if (dragIds) { e.preventDefault(); a.classList.add("droptgt"); }
  });
  a.addEventListener("dragleave", () => a.classList.remove("droptgt"));
  a.addEventListener("drop", async e => {
    a.classList.remove("droptgt");
    if (!dragIds) return;
    e.preventDefault(); e.stopPropagation();
    const ids = dragIds; dragIds = null;
    if (fid === CUR) return;
    await jf("api/move", post({ ids, to: fid }));
    binaTell(`${filesSaid(ids.length, "הועבר", "הועברו")} אל ${contName(fid)}`);
    clearSel(); refresh();
  });
  return a;
}
$("#treeHead").onclick = () => {
  $("#treeList").classList.toggle("hidden"); $("#treeHead").classList.toggle("closed");
};

/* On a narrow screen the sidebar is a drawer: opening a folder must close it, or the file list the
   click just asked for stays hidden behind it. */
const sideOpen = on => {
  document.querySelector(".side").classList.toggle("open", on);
  let veil = $("#sideveil");
  if (on && !veil) {
    veil = document.createElement("div");
    veil.id = "sideveil"; veil.className = "sideveil";
    veil.onclick = () => sideOpen(false);
    document.body.appendChild(veil);
  } else if (!on && veil) veil.remove();
};
$("#sideToggle").onclick = e => { e.stopPropagation(); sideOpen(!document.querySelector(".side").classList.contains("open")); };

function markActive() {
  /* folder links only — the system rail paints its own active row (renderSysRail), and exactly one
     row in the whole sidebar is ever active */
  document.querySelectorAll(".side a.nl[data-fid]").forEach(a =>
    a.classList.toggle("is-active", !TRASH && !SEARCHQ && !VIEW && a.dataset.fid === CUR));
}

/* ── views ── */
async function openFolder(fid, push = true) {
  const c = CONT[fid], f = folderById(fid);
  if (!c && !f) {
    tellBad("התיקייה אינה קיימת או שאין אליה גישה");
    return openPlace("mydrive", false);
  }
  CUR = fid; TRASH = false; SEARCHQ = ""; VIEW = "";
  resetWindow();
  clearFilters(); renderSysRail();
  if (push) nav(fid);
  /* the name is the only part allowed to shrink; the chip and the action keep their size, so a long
     name ellipses instead of pushing the button off-screen */
  $("#viewTitle").innerHTML = `<span class="th-ic" data-ic="folder"></span>` + (c
    ? `<span class="tname">${esc(c.group)}</span>
       <span class="chip" style="background:${safeColor(c.color)}22;color:${safeColor(c.color)}">${esc(c.label)}</span>`
    : `<span class="tname"><bdi>${esc((f && f.name) || fid)}</bdi></span>`)
    + ` <button class="linkbtn" id="copyFolder" title="העתק קישור לתיקייה" data-ic="link"></button>`;
  paintIcons($("#viewTitle"));
  $("#copyFolder").onclick = () => copyText(location.origin + MOUNT + pathFor(fid), "קישור התיקייה הועתק");
  /* the hint is the registering app's copy, echoed verbatim */
  $("#folderHint").textContent = (c && c.hint) || "";
  $("#dropstrip").classList.remove("hidden");
  $("#search").value = "";
  clearSel(); markActive(); await loadFiles();
}
function openTrash(push = true) {
  TRASH = true; CUR = null; SEARCHQ = ""; VIEW = "";
  resetWindow();
  clearFilters(); renderSysRail();
  if (push) nav();
  $("#viewTitle").innerHTML = `<span class="th-ic" data-ic="trash"></span> אשפה`;
  paintIcons($("#viewTitle"));
  $("#folderHint").textContent = "מחיקה סופית מסירה את הקובץ לצמיתות";
  $("#dropstrip").classList.add("hidden");
  $("#search").value = "";
  clearSel(); markActive(); loadFiles();
}
async function runGlobalSearch(q, push = true) {
  SEARCHQ = q; TRASH = false; CUR = null; VIEW = "";
  resetWindow();
  renderSysRail();
  if (push) nav();
  $("#viewTitle").innerHTML = `<span class="th-ic" data-ic="search"></span>
    <span class="tname">חיפוש: <bdi>${esc(q)}</bdi></span>`;
  paintIcons($("#viewTitle"));
  $("#folderHint").textContent = "תוצאות מכל התיקיות";
  $("#dropstrip").classList.add("hidden");
  clearSel(); markActive();
  FILES = (await jf("api/search?q=" + encodeURIComponent(q))).files;
  renderFiles();
}

/* ── the standing-query places ───────────────────────────────────────────────────────────────────
   openPlace is deliberately the same shape as openFolder: same clear-selection, same title, same
   render. The user should not be able to feel that one of these is a folder and the other is a
   query — that distinction is ours, not theirs. */
const PLACE_TITLE = {
  home:    ["home",       "דף הבית",     "הקבצים שנגעת בהם לאחרונה, במקום אחד"],
  mydrive: ["hard-drive", "הדרייב שלי",  "כל התיקיות והקבצים בחשבון הפעיל"],
  shared:  ["users",      "שיתפו איתי",  "קבצים שאחרים שיתפו איתך — הבעלות נשארת אצלם"],
  recent:  ["clock",      "לאחרונה",     "לפי מועד הפתיחה האחרון, לא לפי מועד היצירה"],
  starred: ["star",       "מסומן בכוכב", "הסימון שלך — לא משנה איפה הקובץ יושב"],
};
async function openPlace(id, push = true) {
  VIEW = id; TRASH = false; SEARCHQ = "";
  resetWindow();
  CUR = id === "mydrive" || id === "home" ? "" : null;
  if (push) nav();
  const [icon, title, hint] = PLACE_TITLE[id] || PLACE_TITLE.mydrive;
  $("#viewTitle").innerHTML = `<span class="th-ic" data-ic="${icon}"></span><span class="tname">${title}</span>`;
  paintIcons($("#viewTitle"));
  $("#folderHint").textContent = hint;
  $("#dropstrip").classList.toggle("hidden", id !== "mydrive" && id !== "home");
  $("#search").value = "";
  clearFilters(); clearSel(); markActive(); renderSysRail();
  await loadFiles();
}

/* ── breadcrumb ──────────────────────────────────────────────────────────────────────────────────
   A path, not a label. Every crumb is clickable and every crumb but the last one is muted, so the
   eye lands on "where am I" first and "how do I get back" second. */
function crumbTrail() {
  const trail = [];
  let f = CUR ? folderById(CUR) : null, guard = 0;
  while (f && guard++ < 12) { trail.unshift(f); f = f.parent ? folderById(f.parent) : null; }
  return trail;
}
function renderCrumbs() {
  const box = $("#crumbs");
  if (TRASH) { box.innerHTML = `<button class="cb last">אשפה</button>`; return; }
  if (SEARCHQ) { box.innerHTML = `<button class="cb last">תוצאות חיפוש</button>`; return; }
  if (VIEW && VIEW !== "mydrive" && VIEW !== "home") {
    box.innerHTML = `<button class="cb last">${esc((PLACE_TITLE[VIEW] || [])[1] || VIEW)}</button>`;
    return;
  }
  const trail = crumbTrail();
  const parts = [{ id: "", name: "הדרייב שלי" }].concat(trail);
  box.innerHTML = parts.map((p, i) => {
    const last = i === parts.length - 1;
    return `<button class="cb ${last ? "last" : ""}" data-crumb="${esc(p.id)}"><bdi>${esc(p.name)}</bdi></button>`
      + (last ? "" : `<span class="csep">${ic("chevron-start")}</span>`);
  }).join("");
  box.querySelectorAll("[data-crumb]").forEach(b => {
    b.onclick = () => {
      const fid = b.dataset.crumb;
      if (fid) { nav(fid); openFolder(fid, false); } else openPlace("mydrive");
    };
    /* a crumb is a folder, so it is also a drop target — "move this up two levels" without
       hunting for the folder in the tree */
    b.addEventListener("dragover", e => { if (dragIds) { e.preventDefault(); b.classList.add("droptgt"); } });
    b.addEventListener("dragleave", () => b.classList.remove("droptgt"));
    b.addEventListener("drop", async e => {
      b.classList.remove("droptgt");
      if (!dragIds) return;
      e.preventDefault(); e.stopPropagation();
      const ids = dragIds; dragIds = null;
      const to = b.dataset.crumb;
      if (to === CUR) return;
      await jf("api/move", post({ ids, to }));
      binaTell(filesSaid(ids.length, "הועבר", "הועברו"));
      clearSel(); refresh();
    });
  });
}

/* ── filter chips ────────────────────────────────────────────────────────────────────────────────
   Filters answer "narrow this down" without making the user learn a query language. Three axes
   cover almost every real ask: what KIND of file, WHEN it changed, and WHOSE it is. A chip that is
   on shows its value and its own ✕ — the way out is never somewhere else. */
const TYPE_FILTERS = [
  { id: "doc",    he: "מסמכים",  test: m => /document|wordprocessingml|text\/plain/.test(m) },
  { id: "sheet",  he: "גיליונות", test: m => /spreadsheet|sheet/.test(m) },
  { id: "slide",  he: "מצגות",   test: m => /presentation/.test(m) },
  { id: "pdf",    he: "PDF",     test: m => m === "application/pdf" },
  { id: "image",  he: "תמונות",  test: m => /^image\//.test(m) },
  { id: "arch",   he: "ארכיונים", test: m => /zip|rar|tar|gzip/.test(m) },
];
const MOD_FILTERS = [
  { id: "today", he: "היום",           days: 1 },
  { id: "week",  he: "7 הימים האחרונים", days: 7 },
  { id: "month", he: "30 הימים האחרונים", days: 30 },
  { id: "year",  he: "השנה האחרונה",   days: 365 },
];
const peopleOptions = () => [...new Set(FILES.map(f => f.owner).filter(Boolean))];
const filterLabel = {
  type: v => (TYPE_FILTERS.find(t => t.id === v) || {}).he,
  modified: v => (MOD_FILTERS.find(t => t.id === v) || {}).he,
  people: v => v,
};
function clearFilters() { FILT = { type: "", modified: "", people: "" }; }
function renderChips() {
  const box = $("#chips");
  const chip = (key, dflt) => {
    const v = FILT[key];
    const label = v ? filterLabel[key](v) || v : dflt;
    return `<button class="fchip ${v ? "on" : ""}" data-chip="${key}">
      <bdi>${esc(label)}</bdi>
      ${v ? `<span class="cx" data-chipx="${key}">${ic("x")}</span>` : `<span data-ic="chevron"></span>`}</button>`;
  };
  const any = FILT.type || FILT.modified || FILT.people;
  box.innerHTML = chip("type", "סוג") + chip("modified", "שונה") + chip("people", "אנשים")
    + (any ? `<button class="fchip clearall" data-chipclear="1">ניקוי הכל</button>` : "");
  paintIcons(box);
  box.querySelectorAll("[data-chip]").forEach(b => {
    b.onclick = e => {
      if (e.target.closest("[data-chipx]")) { FILT[b.dataset.chip] = ""; renderChips(); renderFiles(); return; }
      openFilterMenu(b, b.dataset.chip);
    };
  });
  const ca = box.querySelector("[data-chipclear]");
  if (ca) ca.onclick = () => { clearFilters(); resetWindow(); renderChips(); renderFiles(); };
}
let FMENU = null;
function closeFilterMenu() { if (FMENU) { FMENU.remove(); FMENU = null; } }
function openFilterMenu(anchor, key) {
  const wasFor = FMENU && FMENU.dataset.for === key;
  closeFilterMenu();
  if (wasFor) return;
  const opts = key === "type" ? TYPE_FILTERS.map(t => [t.id, t.he])
    : key === "modified" ? MOD_FILTERS.map(t => [t.id, t.he])
    : peopleOptions().map(p => [p, p]);
  const el = document.createElement("div");
  el.className = "fmenu"; el.dataset.for = key;
  el.innerHTML = `<div class="fm-h">${key === "type" ? "סוג קובץ" : key === "modified" ? "שונה לאחרונה" : "בעלות"}</div>`
    + (opts.length ? opts.map(([id, he]) =>
        `<button data-opt="${esc(id)}" class="${FILT[key] === id ? "on" : ""}"><bdi>${esc(he)}</bdi></button>`).join("")
      : `<div class="fm-h">אין ערכים בתיקייה זו</div>`);
  document.body.appendChild(el);
  const r = anchor.getBoundingClientRect();
  el.style.top = Math.min(r.bottom + 6, innerHeight - el.offsetHeight - 10) + "px";
  el.style.insetInlineStart = "auto";
  // Under its chip, starting where the chip starts — the RIGHT edge on this page. Hung from the
  // left edge it opened away from the chip, over the list's first column and across the side panel.
  el.style.left = Math.max(8, Math.min(r.right - el.offsetWidth, innerWidth - el.offsetWidth - 8)) + "px";
  FMENU = el;
  el.querySelectorAll("[data-opt]").forEach(b => {
    b.onclick = () => {
      FILT[key] = FILT[key] === b.dataset.opt ? "" : b.dataset.opt;
      resetWindow(); closeFilterMenu(); renderChips(); renderFiles();
    };
  });
}
document.addEventListener("pointerdown", e => {
  if (FMENU && !e.target.closest(".fmenu") && !e.target.closest("[data-chip]")) closeFilterMenu();
}, true);

function applyFilters(list) {
  let out = list;
  if (FILT.type) {
    const t = TYPE_FILTERS.find(x => x.id === FILT.type);
    if (t) out = out.filter(f => t.test(String(f.mime || "")));
  }
  if (FILT.modified) {
    const m = MOD_FILTERS.find(x => x.id === FILT.modified);
    if (m) {
      const cut = Date.now() - m.days * 86400000;
      out = out.filter(f => instant(f.created).getTime() >= cut);
    }
  }
  if (FILT.people) out = out.filter(f => f.owner === FILT.people);
  return out;
}

async function loadFiles() {
  const u = TRASH ? "api/files?trash=1"
    : VIEW && VIEW !== "mydrive" && VIEW !== "home" ? "api/files?view=" + encodeURIComponent(VIEW)
    : VIEW === "home" ? "api/files?view=recent"
    : "api/files?folder=" + encodeURIComponent(CUR);
  const result = await jf(u);
  FILES = result.files || [];
  SHARED_FOLDERS = VIEW === "shared" ? (result.folders || []) : [];
  renderFiles();
}

/* ── table render: sort + filter + selection ── */
const sortArrow = k => SORT.key === k ? `<span class="arr ${SORT.dir > 0 ? "up" : ""}">${ic("chevron")}</span>` : "";
function sorted(list) {
  const k = SORT.key, d = SORT.dir;
  return [...list].sort((a, b) => {
    const va = k === "size" ? (a.size || 0) : String(a[k] || "").toLowerCase();
    const vb = k === "size" ? (b.size || 0) : String(b[k] || "").toLowerCase();
    return (va < vb ? -1 : va > vb ? 1 : 0) * d;
  });
}
/* Owner avatars: a colour derived from the name, so the same person is the same colour everywhere
   without anyone having to store a palette. Recognition beats reading a name in a narrow column.
   The colours are the office palette's line steps — the ones that turn with the theme, so the
   initial written on them in the surface's colour reads on a light ground and on a dark one. */
const OW_PALETTE = ["sky-d", "olive-d", "plum-d", "lime-d", "violet", "muted"].map(n => "var(--" + n + ")");
function ownerColor(name) {
  let h = 0; const t = String(name || "");
  for (let i = 0; i < t.length; i++) h = (h * 31 + t.charCodeAt(i)) >>> 0;
  return OW_PALETTE[h % OW_PALETTE.length];
}
const ownerInitial = n => (String(n || "?").trim()[0] || "?").toUpperCase();
/* `owner` used to be fiction: no adapter emitted the field, so this compared against a hardcoded
   Hebrew string and every file read "אני". With profiles the backend sends a REAL owner — the
   display name of the profile that owns the row — plus `mine`, which is authoritative because the
   adapter already knows whose drive it just queried. The name comparison stays only as the
   fallback for an adapter that sends an owner without the flag. */
const isMine = f => !!(f && f.mine);
const ownerLabel = () => (CONN.acting && CONN.acting.display_name) || "אני";

/* Which folders belong in THIS view's body? A folder view shows its subfolders above its files —
   the same rule every file manager has used for forty years, and the reason "where do I click to
   go deeper" never needs explaining. Query views (recent/starred/shared) have no subfolders. */
function subfolders() {
  if (TRASH || SEARCHQ) return [];
  if (VIEW === "shared") return SHARED_FOLDERS;
  if (VIEW && VIEW !== "mydrive" && VIEW !== "home") return [];
  const parent = CUR || "";
  return FOLDERS.filter(f => (f.parent || "") === parent)
                .sort((a, b) => String(a.name).localeCompare(String(b.name), "he"));
}

function visibleFiles() {
  const q = SEARCHQ ? "" : $("#search").value.trim().toLowerCase();
  const base = q ? FILES.filter(f => f.name.toLowerCase().includes(q)) : FILES;
  return { list: sorted(applyFilters(base)), q };
}
/* Any change to what is being shown resets the window — otherwise switching folders would inherit
   the previous folder's scroll depth and paint 2,000 rows for a folder with 12. */
function resetWindow() { SHOWN = PAGE; }

function renderFiles() {
  renderCrumbs(); renderChips();
  $("#btnList").classList.toggle("on", LAYOUT === "list");
  $("#btnGrid").classList.toggle("on", LAYOUT === "grid");
  $("#btnInfo").classList.toggle("on", DETAILS);

  const { list: full, q } = visibleFiles();
  const folders = subfolders();
  const list = full.slice(0, SHOWN);
  const empty = !full.length && !folders.length;

  if (empty) {
    // An empty place is a STATE with a face — its own icon, what is (not) here, and what would put
    // something here — in the middle of the list's space. It was one grey line at the top of a
    // blank card as tall as the screen.
    const [mark, what, how] =
      q || SEARCHQ ? ["search", "אין תוצאות", "נסו מילה אחרת, או חפשו בכל הדרייב עם Enter"]
      : FILT.type || FILT.modified || FILT.people ? ["search", "אין קבצים שעונים על הסינון", "ניקוי המסננים יחזיר את הרשימה"]
      : TRASH ? ["trash", "האשפה ריקה", "קובץ שנמחק מחכה כאן עד שמשחזרים אותו או מוחקים אותו סופית"]
      : VIEW === "starred" ? ["star", "אין קבצים מסומנים בכוכב", "כוכב על קובץ שומר אותו כאן, בהישג יד"]
      : VIEW === "shared" ? ["users", "עוד לא שיתפו איתך קבצים", "קובץ שמישהו ישתף איתך יופיע כאן"]
      : ["upload", "התיקייה ריקה", "גררו קבצים לכאן, או השתמשו בכפתור ההעלאה"];
    $("#filesTable").innerHTML = `<div class="empty"><span class="empty-ic">${ic(mark) || ic("folder") || ""}</span>
      <b>${what}</b><span>${how}</span></div>`;
  } else if (LAYOUT === "grid") {
    renderGrid(list, folders);
  } else {
    renderList(list, folders);
  }

  paintIcons($("#filesTable"));
  const bytes = full.reduce((n, f) => n + (f.size || 0), 0);
  const filtered = full.length !== FILES.length;
  $("#statusbar").innerHTML =
    `<span>${full.length > list.length ? `מציג ${list.length} מתוך ${full.length} קבצים`
                                       : counted(full.length, "קובץ אחד", "קבצים")}${
      folders.length ? ` · ${counted(folders.length, "תיקייה אחת", "תיקיות")}` : ""}${
      filtered ? ` (מסונן מתוך ${FILES.length})` : ""}</span>` +
    (bytes ? `<span>${fmtKB(bytes)}</span>` : "") +
    (full.length > list.length ? `<a class="morelink" id="moreFiles">הצג עוד ${ic("chevron")}</a>` : "");
  const more = $("#moreFiles");
  if (more) more.onclick = () => { SHOWN += PAGE; renderFiles(); };
  updateBulkbar();
  renderDetails();
}

/* grow the window as the user reaches the bottom — the same gesture as scrolling a real list */
$("#filesTable").addEventListener("scroll", () => {
  const el = $("#filesTable");
  if (el.scrollTop + el.clientHeight < el.scrollHeight - 400) return;
  const total = visibleFiles().list.length;
  if (SHOWN >= total) return;
  SHOWN += PAGE;
  renderFiles();
});

function rowActs() {
  return TRASH ? `<button title="שחזור" data-act="restore" data-ic="restore"></button>
                  <button title="מחיקה סופית" data-act="delete" data-ic="x-circle"></button>`
               : `<button title="שיתוף" data-act="share" data-ic="share"></button>
                  <button title="הורדה" data-act="dl" data-ic="download"></button>
                  <button title="שינוי שם" data-act="rename" data-ic="pencil"></button>
                  <button title="אשפה" data-act="trash" data-ic="trash"></button>`;
}

function renderList(list, folders) {
  const showFolderCol = !!SEARCHQ || (VIEW && VIEW !== "mydrive");
  /* A folder's item count is NOT its owner and NOT its size — putting it in either column teaches
     the wrong thing about that column. It belongs beside the name, where it describes the folder. */
  const frows = folders.map(fo => `
    <tr class="frow" data-folder="${esc(fo.id)}">
      <td class="starcell"></td>
      <td><span class="ficon">${ic("folder")}</span><span class="name-open fname"><bdi>${esc(fo.name)}</bdi></span>
        ${fo.count ? `<span class="fcount">${counted(fo.count, "פריט אחד", "פריטים")}</span>` : ""}</td>
      <td class="owner"><span class="ow"><span class="owav" style="background:${ownerColor(fo.owner)}">${esc(ownerInitial(fo.owner))}</span>
        ${isMine(fo) ? "אני" : `<bdi>${esc(fo.owner || "לא ידוע")}</bdi>`}</span></td>
      <td class="num muted">—</td><td class="muted created">—</td><td class="acts"></td><td class="more"></td></tr>`).join("");
  const rows = list.map(f => {
    const [cls, ico] = icon(f.mime);
    const shared = (f.shared || []).length;
    return `<tr draggable="true" data-id="${esc(f.id)}" class="${SEL.has(f.id) ? "sel" : ""}">
      <td class="starcell"><span class="rstar ${f.starred ? "on" : ""}" data-star="${esc(f.id)}"
            role="button" title="סימון בכוכב">${ic("star")}</span></td>
      <td><span class="ficon ${cls}">${ic(ico)}</span><span class="name-open"><bdi>${esc(f.name)}</bdi></span>
        ${shared ? `<span class="shmark" title="משותף עם ${esc((f.shared || []).join(", "))}">${ic("users")}</span>` : ""}
        ${showFolderCol ? `<span class="chip subtle"><bdi>${esc(contName(f.folder))}</bdi></span>` : ""}</td>
      <td class="owner"><span class="ow"><span class="owav" style="background:${ownerColor(f.owner)}">${esc(ownerInitial(f.owner))}</span>
        ${isMine(f) ? "אני" : `<bdi>${esc(f.owner)}</bdi>`}</span></td>
      <td class="num">${fmtKB(f.size)}</td>
      <td class="muted created">${fmtDate(f.created)}</td>
      <td class="acts"><div class="rowact">${rowActs()}</div></td>
      <td class="more"><button class="morebtn" data-more title="פעולות על הקובץ" aria-label="פעולות על הקובץ">${ic("more")}</button></td></tr>`;
  }).join("");
  $("#filesTable").innerHTML = `<table class="data"><thead><tr>
      <th class="starcell"></th>
      <th class="sortable" data-sort="name">שם${sortArrow("name")}</th>
      <th class="sortable owner" data-sort="owner">בעלים${sortArrow("owner")}</th>
      <th class="sortable num" data-sort="size">גודל${sortArrow("size")}</th>
      <th class="sortable created" data-sort="created">נוצר${sortArrow("created")}</th>
      <th class="acts"></th><th class="more"></th></tr></thead><tbody>${frows}${rows}</tbody></table>`;
}

/* Grid: the thumbnail band carries the file's TYPE as colour + glyph. This is the whole point —
   scanning thirty files becomes one glance instead of thirty reads, which is why image-heavy and
   deck-heavy folders are unusable as a list and fine as a grid. */
function renderGrid(list, folders) {
  const cards = list.map(f => {
    const [cls, ico] = icon(f.mime);
    return `<div class="gcard ${SEL.has(f.id) ? "sel" : ""}" draggable="true" data-id="${esc(f.id)}">
      <div class="gt ${cls}">${ic(ico)}</div>
      <div class="gm">
        <span class="ficon ${cls}">${ic(ico)}</span>
        <span class="gn"><bdi>${esc(f.name)}</bdi></span>
        <span class="gstar ${f.starred ? "on" : ""}" data-star="${esc(f.id)}" title="סימון בכוכב">${ic("star")}</span>
      </div></div>`;
  }).join("");
  const fold = folders.map(fo => `<div class="gfold" data-folder="${esc(fo.id)}">
      ${ic("folder")}<b><bdi>${esc(fo.name)}</bdi></b>
      ${fo.count ? `<span class="n">${fo.count}</span>` : ""}</div>`).join("");
  $("#filesTable").innerHTML = `<div class="grid">
      ${fold ? `<div class="gsec">תיקיות</div>${fold}` : ""}
      ${cards ? `<div class="gsec">קבצים</div>${cards}` : ""}
    </div>`;
}

/* ── details pane ────────────────────────────────────────────────────────────────────────────────
   The pane answers the questions a row cannot fit: what exactly is this, where does it live, who
   owns it, who else can see it, when was it last opened. It reflects the SELECTION — with nothing
   selected it describes the folder, because a pane that goes blank reads as broken. */
function closeDetails() {
  DETAILS = false; localStorage.setItem("details", "0");
  $("#btnInfo").classList.remove("on");
  $("#details").classList.add("hidden");
  document.body.classList.remove("det-open");
}
function renderDetails() {
  const box = $("#details");
  box.classList.toggle("hidden", !DETAILS);
  /* Below 1120px the pane is a fixed overlay that covers the toolbar — including the ⓘ that opened
     it. Without its own way out it is a trap, exactly like a drawer that only closes by its ✕. */
  document.body.classList.toggle("det-open", DETAILS);
  if (!DETAILS) return;
  const closeBtn = `<button class="detx" id="detClose" aria-label="סגירת הפרטים">${ic("x")}</button>`;
  const ids = [...SEL];
  if (ids.length > 1) {
    const files = FILES.filter(f => ids.includes(f.id));
    const bytes = files.reduce((n, f) => n + (f.size || 0), 0);
    box.innerHTML = closeBtn + `<div class="dh"><div class="dname">${ids.length} פריטים נבחרו</div></div>
      <dl><dt>גודל כולל</dt><dd>${fmtKB(bytes)}</dd>
          <dt>סוגים</dt><dd>${[...new Set(files.map(f => typeName(f.mime)))].join(" · ")}</dd></dl>`;
    return;
  }
  const f = ids.length === 1 ? FILES.find(x => x.id === ids[0]) : null;
  if (!f) {
    const fo = CUR ? folderById(CUR) : null;
    box.innerHTML = closeBtn + `<div class="dh"><span class="ficon">${ic("folder")}</span>
        <div class="dname"><bdi>${esc(fo ? fo.name : "הדרייב שלי")}</bdi></div></div>
      <dl><dt>קבצים</dt><dd>${FILES.length}</dd>
          <dt>תיקיות משנה</dt><dd>${subfolders().length}</dd></dl>
      <div class="dempty">בחר קובץ כדי לראות את פרטיו</div>`;
    paintIcons(box);
    return;
  }
  const [cls, ico] = icon(f.mime);
  const shared = f.shared || [];
  box.innerHTML = closeBtn + `
    <div class="dh"><span class="ficon ${cls}">${ic(ico)}</span>
      <div class="dname"><bdi>${esc(f.name)}</bdi></div></div>
    <div class="dthumb ${cls}">${ic(ico)}</div>
    <div class="dacts">
      <button data-d="preview">${ic("eye")} תצוגה מקדימה</button>
      <button data-d="share">${ic("share")} שיתוף</button>
      <button data-d="dl">${ic("download")} הורדה</button>
    </div>
    <div class="dsec">פרטים</div>
    <dl>
      <dt>סוג</dt><dd>${esc(typeName(f.mime))}</dd>
      <dt>גודל</dt><dd>${fmtKB(f.size)}</dd>
      <dt>מיקום</dt><dd><bdi>${esc(contName(f.folder) || "הדרייב שלי")}</bdi></dd>
      <dt>בעלים</dt><dd>${isMine(f) ? "אני" : `<bdi>${esc(f.owner)}</bdi>`}</dd>
      <dt>נוצר</dt><dd>${esc(fmtDate(f.created))}</dd>
      <dt>נפתח</dt><dd>${esc(fmtDate(f.opened || f.created))}</dd>
    </dl>
    <div class="dsec">גישה</div>
    ${shared.length
      ? `<dl><dt>משותף עם</dt><dd>${shared.map(s => `<bdi>${esc(s)}</bdi>`).join("<br>")}</dd></dl>`
      : `<div class="dempty" style="padding:8px 0">פרטי — רק לך יש גישה</div>`}`;
  paintIcons(box);
  box.querySelectorAll("[data-d]").forEach(b => {
    b.onclick = () => {
      if (b.dataset.d === "preview") preview(f);
      else if (b.dataset.d === "share") shareDialog(f);
      else downloadFile(f);
    };
  });
}

/* ── share dialog ────────────────────────────────────────────────────────────────────────────────
   Ordered the way the question is actually asked: who has it now, then who else may, then the
   link. Putting "copy link" first is what trains people to paste links nobody can open. */
function shareDialog(f) {
  const shared = f.shared || [];
  modal(`שיתוף — ${f.name}`, `
    <div class="fld"><span>הוספת אנשים</span>
      <input id="shAdd" placeholder="שם או כתובת מייל"/></div>
    <div class="dsec" style="border:none;padding-top:12px">בעלי גישה</div>
    <div class="shrow">
      <span class="owav" style="background:${ownerColor(f.owner)}">${esc(ownerInitial(f.owner))}</span>
      <span class="who"><b>${isMine(f) ? "אני" : esc(f.owner)}</b><span>${esc(f.owner || "")}</span></span>
      <span class="muted" style="font-size:12px">בעלים</span>
    </div>
    ${shared.map(s => `<div class="shrow">
        <span class="owav" style="background:${ownerColor(s)}">${esc(ownerInitial(s))}</span>
        <span class="who"><b><bdi>${esc(s)}</bdi></b><span>גישה לקובץ</span></span>
        <select><option>עריכה</option><option selected>צפייה</option></select>
      </div>`).join("")}
    <div class="shgen">
      <span class="gi">${ic(shared.length ? "globe" : "lock")}</span>
      <span class="who"><b>${shared.length ? "בעלי הקישור בארגון" : "מוגבל"}</b>
        <span>${shared.length ? "כל מי שיש לו את הקישור בארגון יכול לצפות" : "רק אנשים עם גישה יכולים לפתוח"}</span></span>
    </div>`,
    [{ label: "סיום", cls: "primary", onclick: closeModal },
     { label: "העתקת קישור", cls: "ghost",
       onclick: () => copyText(location.origin + MOUNT + pathFor(f.folder, f.id), "הקישור הועתק") }]);
  paintIcons($("#mBody"));
}
$("#filesTable").addEventListener("click", e => {
  const th = e.target.closest("th.sortable");
  if (th) {
    const k = th.dataset.sort;
    SORT = { key: k, dir: SORT.key === k ? -SORT.dir : (k === "name" ? 1 : -1) };
    localStorage.setItem("sort", JSON.stringify(SORT));
    renderFiles();
  }
});

/* search box: live filter in folder; Enter = global */
$("#search").addEventListener("input", () => { if (!SEARCHQ) { resetWindow(); renderFiles(); } });
$("#search").addEventListener("keydown", e => {
  if (e.key === "Enter") {
    const q = $("#search").value.trim();
    if (q.length >= 2) { SEARCHQ = q; nav(); runGlobalSearch(q, false); }
  }
});

/* ── selection model ── */
function clearSel() { SEL.clear(); lastClicked = null; updateBulkbar(); }
function updateBulkbar() {
  const n = SEL.size, bar = $("#bulkbar");
  bar.classList.toggle("hidden", n === 0);
  if (!n) return;
  $("#bulkCount").textContent = n === 1 ? "נבחר קובץ אחד" : `נבחרו ${n} קבצים`;
  bar.querySelector('[data-bulk="move"]').classList.toggle("hidden", TRASH);
  bar.querySelector('[data-bulk="trash"]').classList.toggle("hidden", TRASH);
  bar.querySelector('[data-bulk="restore"]').classList.toggle("hidden", !TRASH);
  bar.querySelector('[data-bulk="delete"]').classList.toggle("hidden", !TRASH);
  document.querySelectorAll("tr[data-id], .gcard[data-id]").forEach(el =>
    el.classList.toggle("sel", SEL.has(el.dataset.id)));
}
$("#filesTable").addEventListener("click", e => {
  /* the small controls resolve BEFORE the row — a star click must never also select the row,
     because "I marked it" and "I selected it" are two different intentions */
  const st = e.target.closest("[data-star]");
  if (st) { toggleStar(st.dataset.star); return; }
  const fo = e.target.closest("[data-folder]");
  if (fo) { const fid = fo.dataset.folder; nav(fid); openFolder(fid, false); return; }

  const item = e.target.closest("tr[data-id], .gcard[data-id]");
  if (!item || e.target.closest("button")) return;
  const id = item.dataset.id;
  if (e.target.closest(".name-open")) return preview(fileById(id));   // click on the name = open
  const ids = visibleFiles().list.map(f => f.id);
  if (e.shiftKey && lastClicked) {
    const a = ids.indexOf(lastClicked), b = ids.indexOf(id);
    if (a !== -1 && b !== -1) for (let i = Math.min(a, b); i <= Math.max(a, b); i++) SEL.add(ids[i]);
  } else if (e.ctrlKey || e.metaKey) {
    SEL.has(id) ? SEL.delete(id) : SEL.add(id);
  } else {
    SEL.clear(); SEL.add(id);
  }
  lastClicked = id;
  updateBulkbar(); renderDetails();
});
$("#filesTable").addEventListener("dblclick", e => {
  const folder = e.target.closest("[data-folder]");
  if (folder) { const fid = folder.dataset.folder; nav(fid); openFolder(fid, false); return; }
  const item = e.target.closest("tr[data-id], .gcard[data-id]");
  if (item) preview(fileById(item.dataset.id));
});

/* Starring is a mark, not a move: it never changes where the file lives, so it re-renders in place
   and — in the starred view, where un-starring makes the row leave — offers undo. */
async function toggleStar(id) {
  const f = FILES.find(x => x.id === id); if (!f) return;
  f.starred = !f.starred;
  renderFiles();
  await jf("api/star", post({ ids: [id], starred: f.starred }));
  if (VIEW === "starred" && !f.starred) {
    tellUndo("הכוכב הוסר", async () => { await jf("api/star", post({ ids: [id], starred: true })); refresh(); });
    loadFiles();
  }
}

/* ── view tools ── */
$("#btnList").onclick = () => { LAYOUT = "list"; localStorage.setItem("layout", LAYOUT); clearSel(); resetWindow(); renderFiles(); };
$("#btnGrid").onclick = () => { LAYOUT = "grid"; localStorage.setItem("layout", LAYOUT); clearSel(); resetWindow(); renderFiles(); };
$("#btnInfo").onclick = () => {
  DETAILS = !DETAILS; localStorage.setItem("details", DETAILS ? "1" : "0");
  $("#btnInfo").classList.toggle("on", DETAILS); renderDetails();
};
/* delegated so it survives every re-render of the pane's contents */
$("#details").addEventListener("click", e => { if (e.target.closest("#detClose")) closeDetails(); });
/* and the two gestures people try before hunting for a ✕ */
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && DETAILS && document.body.classList.contains("det-narrow")) closeDetails();
});
const detVeil = () => {
  let v = $("#detveil");
  const need = DETAILS && matchMedia("(max-width:1120px)").matches;
  document.body.classList.toggle("det-narrow", matchMedia("(max-width:1120px)").matches);
  if (need && !v) {
    v = document.createElement("div"); v.id = "detveil"; v.className = "detveil";
    v.onclick = closeDetails; document.body.appendChild(v);
  } else if (!need && v) v.remove();
};
new MutationObserver(detVeil).observe(document.body, { attributes: true, attributeFilter: ["class"] });
addEventListener("resize", detVeil);

/* keyboard */
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { closeModal(); closePv(); ctxHide(); clearSel(); return; }
  if (e.target.matches("input,textarea")) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
    /* select what is ON SCREEN, not what was fetched — selecting rows a filter is hiding is how
       bulk actions surprise people */
    e.preventDefault(); visibleFiles().list.forEach(f => SEL.add(f.id)); updateBulkbar(); renderDetails();
  }
  if (e.key === "Delete" && SEL.size && !TRASH) bulk("trash");
});

/* bulk actions */
$("#bulkbar").addEventListener("click", e => {
  const b = e.target.closest("button[data-bulk]");
  if (b) bulk(b.dataset.bulk);
});
async function bulk(act) {
  const ids = [...SEL];
  if (!ids.length) return;
  if (act === "clear") return clearSel(), renderFiles();
  if (act === "move") return moveFiles(ids);
  if (act === "trash") {
    await jf("api/trash", post({ ids }));
    clearSel(); refresh();
    return tellUndo(filesSaid(ids.length, "הועבר", "הועברו") + " לאשפה", async () => {
      await jf("api/trash", post({ ids, restore: true })); binaTell(filesSaid(ids.length, "שוחזר", "שוחזרו")); refresh();
    });
  }
  if (act === "restore") { await jf("api/trash", post({ ids, restore: true })); clearSel(); binaTell(filesSaid(ids.length, "שוחזר", "שוחזרו")); refresh(); }
  if (act === "delete") return confirmDelete(ids);
}
async function confirmDelete(ids) {
  if (!await binaAsk({
    danger: true, ok: "מחיקה סופית", title: `למחוק לצמיתות ${counted(ids.length, "קובץ אחד", "קבצים")}?`,
    body: "פעולה זו אינה הפיכה.", facts: ids.length === 1 && [["קובץ", fileById(ids[0]).name]],
    run: () => must(jsoft("api/delete", post({ ids })), "המחיקה נכשלה"),
  })) return;
  clearSel(); binaTell(filesSaid(ids.length, "נמחק", "נמחקו") + " לצמיתות"); refresh();
}

/* ── drag rows -> sidebar folders ── */
let dragIds = null, ghost = null;
$("#filesTable").addEventListener("dragstart", e => {
  const tr = e.target.closest("tr[data-id], .gcard[data-id]");
  if (!tr || TRASH) { e.preventDefault(); return; }
  if (!SEL.has(tr.dataset.id)) { SEL.clear(); SEL.add(tr.dataset.id); updateBulkbar(); }
  dragIds = [...SEL];
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("application/x-drive-ids", "1");
  ghost = document.createElement("div");
  ghost.className = "dragghost";
  ghost.textContent = dragIds.length === 1 ? fileById(dragIds[0]).name.slice(0, 30) : `${dragIds.length} קבצים`;
  document.body.appendChild(ghost);
  e.dataTransfer.setDragImage(ghost, 20, 14);
});
$("#filesTable").addEventListener("dragend", () => {
  dragIds = null;
  if (ghost) { ghost.remove(); ghost = null; }
  document.querySelectorAll(".droptgt").forEach(x => x.classList.remove("droptgt"));
});

/* ── context menu ── */
const CTX = $("#ctx");
function ctxHide() { CTX.classList.add("hidden"); }
document.addEventListener("click", ctxHide);
$("#filesTable").addEventListener("contextmenu", e => {
  const tr = e.target.closest("tr[data-id], .gcard[data-id]");
  if (!tr) return;
  e.preventDefault();
  openCtx(tr, e.clientX, e.clientY);
});
// …and the one control a row shows where its hover buttons are not (a finger, a narrow list): the
// same menu, opened under the button. Without it the trash had no visible way to restore a file.
$("#filesTable").addEventListener("click", e => {
  const more = e.target.closest("[data-more]");
  if (!more) return;
  e.stopPropagation();
  const r = more.getBoundingClientRect();
  openCtx(more.closest("tr[data-id]"), r.left + r.width / 2, r.bottom + 4);
});
function openCtx(tr, x, y) {
  const f = fileById(tr.dataset.id);
  if (!SEL.has(f.id)) { SEL.clear(); SEL.add(f.id); updateBulkbar(); }
  const many = SEL.size > 1;
  CTX.innerHTML = TRASH
    ? `<button data-c="restore" data-ic="restore">שחזור</button>
       <button data-c="delete" class="danger" data-ic="x-circle">מחיקה סופית</button>`
    : `${many ? "" : `<button data-c="open" data-ic="eye">תצוגה מקדימה</button>
        <button data-c="share" data-ic="share">שיתוף</button>
        <button data-c="star" data-ic="star">${fileById(tr.dataset.id).starred ? "הסרת כוכב" : "סימון בכוכב"}</button>
        <button data-c="dl" data-ic="download">הורדה</button>
        <button data-c="copy" data-ic="link">העתק קישור</button>
        <button data-c="rename" data-ic="pencil">שינוי שם</button><hr>`}
       <button data-c="move" data-ic="folder-input">העברה${many ? ` (${SEL.size})` : ""}</button>
       <button data-c="trash" class="danger" data-ic="trash">לאשפה${many ? ` (${SEL.size})` : ""}</button>`;
  CTX.querySelectorAll("[data-ic]").forEach(b => b.insertAdjacentHTML("afterbegin", ic(b.dataset.ic)));
  CTX.style.top = Math.min(y, innerHeight - 260) + "px";
  const w = 190;
  CTX.style.left = Math.max(8, Math.min(x - w / 2, innerWidth - w - 8)) + "px";
  CTX.classList.remove("hidden");
  CTX.onclick = ev => {
    const b = ev.target.closest("button[data-c]");
    if (!b) return;
    ctxHide();
    const c = b.dataset.c;
    if (c === "open") preview(f);
    if (c === "share") shareDialog(f);
    if (c === "star") toggleStar(f.id);
    if (c === "dl") downloadFile(f);
    if (c === "copy") copyText(shareLink(f), "קישור הקובץ הועתק");
    if (c === "rename") renameFile(f.id, f.name);
    if (c === "move") moveFiles([...SEL]);
    if (c === "trash") bulk("trash");
    if (c === "restore") bulk("restore");
    if (c === "delete") confirmDelete([...SEL]);
  };
}

/* row action buttons */
$("#filesTable").addEventListener("click", async e => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  e.stopPropagation();
  const host = btn.closest("tr[data-id], .gcard[data-id]");
  if (!host) return;
  const f = fileById(host.dataset.id);
  const act = btn.dataset.act;
  if (act === "share") return shareDialog(f);
  if (act === "dl") return downloadFile(f);
  if (act === "copy") return copyText(shareLink(f), "קישור הקובץ הועתק");
  if (act === "rename") return renameFile(f.id, f.name);
  if (act === "trash") return trashFile(f.id, f.name);
  if (act === "restore") { await jf("api/trash", post({ id: f.id, restore: true })); binaTell("שוחזר"); refresh(); }
  if (act === "delete") return confirmDelete([f.id]);
});

function downloadFile(f) {
  const a = document.createElement("a");
  a.href = contentPath(f.id); a.download = f.name || ""; a.target = "_blank";
  document.body.appendChild(a); a.click(); a.remove();
}
window.downloadFile = downloadFile;
async function trashFile(id, name) {
  await jf("api/trash", post({ id }));
  SEL.delete(id); refresh();
  tellUndo(`"${name.slice(0, 30)}" הועבר לאשפה`, async () => {
    await jf("api/trash", post({ id, restore: true })); binaTell("שוחזר"); refresh();
  });
}

/* modal: rename */
function renameFile(id, name) {
  modal("שינוי שם", `<input type="text" id="mInput" value="${esc(name)}" dir="auto">`, [
    { label: "שמירה", cls: "primary", onclick: e => guard(e.currentTarget, async () => {
        const n = $("#mInput").value.trim();
        if (!n || n === name) return closeModal();
        await jf("api/rename", post({ id, name: n }));
        closeModal(); binaTell("השם עודכן"); refresh();
      }) },
    { label: "ביטול", onclick: closeModal },
  ]);
  const i = $("#mInput"); i.focus(); i.select();
  i.onkeydown = e => { if (e.key === "Enter") $("#mFoot .primary").click(); };
}

/* modal: move (bulk-aware searchable picker) — registered containers first, then plain folders */
function moveFiles(ids) {
  const inRail = f => !!CONT[f.id];
  const groups = {};
  for (const f of FOLDERS.filter(inRail)) (groups[CONT[f.id].group] = groups[CONT[f.id].group] || []).push(f);
  for (const fid of Object.keys(CONT))                     // containers with no files yet
    if (!folderById(fid)) (groups[CONT[fid].group] = groups[CONT[fid].group] || []).push({ id: fid });
  const rest = FOLDERS.filter(f => !inRail(f) && f.id !== CUR);
  let html = `<input type="text" id="mSearch" placeholder="חיפוש תיקייה…"><div class="pick-list" id="pickList">`;
  for (const [key, list] of Object.entries(groups)) {
    html += `<div class="pick-group">${esc(key)}</div>`;
    for (const f of list) {
      const c = CONT[f.id];
      html += `<div class="pick" data-to="${esc(f.id)}" data-q="${esc((key + " " + c.label).toLowerCase())}">
        <span class="dot" style="background:${safeColor(c.color)}"></span>${esc(c.label)}</div>`;
    }
  }
  if (rest.length) {
    html += `<div class="pick-group">תיקיות אחרות</div>`;
    for (const f of rest)
      html += `<div class="pick" data-to="${esc(f.id)}" data-q="${esc(String(f.name || f.id).toLowerCase())}"><bdi>${esc(f.name || f.id)}</bdi></div>`;
  }
  html += "</div>";
  modal(ids.length > 1 ? `העברת ${ids.length} קבצים` : "העברה לתיקייה", html,
    [{ label: "ביטול", onclick: closeModal }]);
  $("#mSearch").oninput = () => {
    const q = $("#mSearch").value.trim().toLowerCase();
    document.querySelectorAll("#pickList .pick").forEach(p =>
      p.style.display = !q || p.dataset.q.includes(q) ? "" : "none");
  };
  $("#pickList").onclick = async e => {
    const p = e.target.closest(".pick");
    if (!p || _moveBusy) return;          // guard: a second pick must not fire another move
    _moveBusy = true;
    try {
      await jf("api/move", post({ ids, to: p.dataset.to }));
      closeModal(); clearSel();
      binaTell(filesSaid(ids.length, "הועבר", "הועברו")); refresh();
    } catch (err) { /* jf already surfaced the error toast */ }
    finally { _moveBusy = false; }
  };
  $("#mSearch").focus();
}

/* modal: new folder */
$("#newFolderBtn").onclick = () => {
  modal("תיקייה חדשה",
    `<input type="text" id="mInput" placeholder="שם התיקייה" dir="rtl">`, [
    { label: "יצירה", cls: "primary", onclick: e => guard(e.currentTarget, async () => {
        const n = $("#mInput").value.trim();
        if (!n) return;
        const out = await jf("api/folders", post({ name: n, parent: CUR || "" }));
        closeModal(); SEARCHQ = "";
        await loadSidebar(); nav(out.folder.id); await openFolder(out.folder.id, false);
      }) },
    { label: "ביטול", onclick: closeModal },
  ]);
  const i = $("#mInput"); i.focus();
  i.onkeydown = e => { if (e.key === "Enter") $("#mFoot .primary").click(); };
};

/* ── preview drawer ── */
/* ── full document view ──────────────────────────────────────────────────────────────────────────
   A document gets the WHOLE screen. The chrome goes dark so the page is the brightest thing in the
   room; every control lives in one bar so nothing floats over the content; and ‹ › walk the same
   list you were just looking at, because "preview one, decide, next" is the actual task — closing
   and reopening for each file is the thing that makes a preview feel cheap. */
function pvSiblings() { return visibleFiles().list; }
function preview(f, push = true) {
  const { id, name, mime = "" } = f;
  PV = f;
  if (push && CUR) nav(CUR, id);
  const sibs = pvSiblings(), at = sibs.findIndex(x => x.id === id);
  const canPrev = at > 0, canNext = at !== -1 && at < sibs.length - 1;
  const body = mime && !previewable(mime)
    ? `<div class="pvpaper pvnone">
         <div><div class="pvnone-ic">${ic(icon(mime)[1])}</div>
           <div class="pvnone-n"><bdi>${esc(name)}</bdi></div>
           <div class="muted pvnone-s">${esc(typeName(mime))}${f.size ? " · " + fmtKB(f.size) : ""} — אין תצוגה מקדימה לסוג קובץ זה</div>
           <button class="btn" data-pv="dl" title="הורדת הקובץ למחשב">${ic("download")} הורדה</button>
         </div></div>`
    : `<div class="pvpaper"><iframe id="pvFrameFull" title="preview" src="${esc(contentPath(id))}"></iframe></div>`;
  $("#pvfull").innerHTML = `
    <div class="pvbar">
      <button data-pv="close" title="סגירה">${ic("x")}</button>
      <span class="pvn"><bdi>${esc(name)}</bdi></span>
      <span class="pvsub">${esc(typeName(mime))}${f.size ? " · " + fmtKB(f.size) : ""}${
        at !== -1 ? ` · ${at + 1} מתוך ${sibs.length}` : ""}</span>
      <span class="sp"></span>
      <button data-pv="dl" title="הורדה">${ic("download")} <span>הורדה</span></button>
      <button data-pv="share" title="שיתוף">${ic("share")} <span>שיתוף</span></button>
      <button data-pv="star" title="${f.starred ? "הסרת כוכב" : "סימון בכוכב"}">${ic("star")} <span>${f.starred ? "הסרת כוכב" : "כוכב"}</span></button>
      <button data-pv="rename" title="שינוי שם">${ic("pencil")} <span>שינוי שם</span></button>
      <button data-pv="move" title="העברה לתיקייה אחרת">${ic("folder-input")} <span>העברה</span></button>
      <button data-pv="trash" title="העברה לאשפה">${ic("trash")} <span>אשפה</span></button>
    </div>
    <div class="pvstage">
      ${canPrev ? `<button class="pvnav prev" data-pv="prev" aria-label="הקודם">${ic("chevron-start")}</button>` : ""}
      ${body}
      ${canNext ? `<button class="pvnav next" data-pv="next" aria-label="הבא">${ic("chevron-end")}</button>` : ""}
    </div>`;
  $("#pvfull").classList.remove("hidden");
  $("#pvfull").querySelectorAll("[data-pv]").forEach(b => {
    b.onclick = () => {
      const a = b.dataset.pv, cur = PV;
      if (a === "close") return closePv();
      if (a === "prev") return preview(sibs[at - 1]);
      if (a === "next") return preview(sibs[at + 1]);
      if (a === "star") { toggleStar(cur.id); return preview(fileById(cur.id), false); }
      if (a === "share") return shareDialog(cur);
      if (a === "dl") return downloadFile(cur);
      if (a === "rename") { closePv(); return renameFile(cur.id, cur.name); }
      if (a === "move") { closePv(); return moveFiles([cur.id]); }
      if (a === "trash") { closePv(); return trashFile(cur.id, cur.name); }
    };
  });
}
function closePv(silent) {
  if (!silent && PV && CUR) nav(CUR);
  PV = null;
  $("#pvfull").classList.add("hidden");
  $("#pvfull").innerHTML = "";
  $("#preview").classList.add("hidden");
  if ($("#modal").classList.contains("hidden")) $("#overlay").classList.add("hidden");
}
$("#overlay").onclick = () => { closeModal(); closePv(); };
/* ‹ › walk the preview — the keyboard shortcut everyone tries first */
document.addEventListener("keydown", e => {
  if (!PV || e.target.matches("input,textarea")) return;
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  const sibs = pvSiblings(), at = sibs.findIndex(x => x.id === PV.id);
  if (at === -1) return;
  /* RTL: the LEFT arrow points at the NEXT item, because the list reads right-to-left */
  const to = e.key === "ArrowLeft" ? at + 1 : at - 1;
  if (sibs[to]) { e.preventDefault(); preview(sibs[to]); }
});

/* ── upload: whole-window drag&drop (files only, not internal drags) ── */
let dragDepth = 0;
const isFileDrag = e => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files") && !dragIds;
window.addEventListener("dragenter", e => {
  e.preventDefault();
  if (!CUR || TRASH || !isFileDrag(e)) return;
  if (++dragDepth === 1) $("#dropveil").classList.remove("hidden");
});
window.addEventListener("dragover", e => e.preventDefault());
window.addEventListener("dragleave", e => {
  e.preventDefault();
  if (--dragDepth <= 0) { dragDepth = 0; $("#dropveil").classList.add("hidden"); }
});
window.addEventListener("drop", e => {
  e.preventDefault(); dragDepth = 0; $("#dropveil").classList.add("hidden");
  if (CUR && !TRASH && isFileDrag(e)) upload(e.dataTransfer.files);
});
$("#filePick").addEventListener("change", e => upload(e.target.files));
$("#filePick2").addEventListener("change", e => upload(e.target.files));

function upload(files) {
  if (!CUR) return tellWarn("בחר תיקייה קודם");
  if (!files.length) return;
  if (_uploading) return tellWarn("העלאה כבר מתבצעת…");   // guard: never fire a second upload (would duplicate files)
  _uploading = true;
  const fd = new FormData();
  fd.append("folder", CUR);
  for (const f of files) fd.append("files", f);
  // stable idempotency key for this upload attempt — ready for backend dedup on the create path
  const idem = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : "u" + Date.now() + Math.random().toString(36).slice(2);
  const xhr = new XMLHttpRequest();
  $("#upProgress").classList.remove("hidden");
  const done = () => { _uploading = false; $("#upProgress").classList.add("hidden"); $("#upBar").style.width = "0"; };
  xhr.upload.onprogress = e => {
    const p = e.lengthComputable ? Math.round(e.loaded / e.total * 100) : 50;
    $("#upBar").style.width = p + "%"; $("#upLabel").textContent = p + "%";
  };
  xhr.onload = () => {
    done();
    let result = {};
    try { result = JSON.parse(xhr.responseText); } catch (_) { /* response has no JSON error */ }
    if (xhr.status === 200) { binaTell(filesSaid(files.length, "הועלה", "הועלו")); refresh(); }
    else if (xhr.status === 207) {
      tellBad(result.failed?.[0]?.error || "חלק מהקבצים לא הועלו"); refresh();
    } else tellBad(result.failed?.[0]?.error || result.error || "ההעלאה נכשלה — " + binaSaid(xhr.status));   // (it said «שגיאה בהעלאה (502)»)
  };
  xhr.onerror = () => { done(); tellBad("ההעלאה נכשלה — " + binaSaid(0)); };
  xhr.open("POST", "api/upload");
  xhr.setRequestHeader("Idempotency-Key", idem);
  xhr.send(fd);
}

/* אשפה now lives in the system rail (renderSysRail) alongside the other places — it was never a
   footnote below the tree, it is one of the six answers to "where can a file be?". */

/* ── the account plane (§2/§4b): which connection is this drive working on right now? ──
   The service owns N connections + ONE active pointer, and every op — this UI's and the automation
   layer's — runs against the active one. So this bar is the single honest answer to that question,
   and its dot comes from /readyz (a real probe), never from the list. */
/* PRIVATE vs REMOTE is now an explicit FIELD, not an id suffix. The bar used to test `/-local$/`,
   which worked only because there was exactly one synthetic local row called `drive_local-local`.
   That row is gone: every profile on the private engine is a real vault instance with a real
   credential and an ordinary `<protocol>-<8hex>` id, so parsing the id would now answer "remote"
   for every profile in the deployment. */
const isPrivateConn = c => !!(c && c.is_private);
const connName = c => !c ? "לא נבחר חשבון" : (c.label || c.account_hint || c.id);
/* The second line of an account is what a PERSON recognises it by — an address. A private profile
   has none: what stood there was its id ("admin" under «מנהל»), which is the office's word, not the
   owner's. It is one hover away (`connId`, in the title). */
const connHint = c => isPrivateConn(c) ? "" : (c.account_hint || "");
const connId = c => (isPrivateConn(c) && c.profile_id ? "פרופיל " + c.profile_id : "");

async function loadConnections() {
  const [cl, rd] = await Promise.all([jsoft("connections"), jsoft("readyz")]);
  CONN.list = (cl.d && cl.d.connections) || [];
  CONN.active = (cl.d && cl.d.active) || null;
  CONN.acting = (cl.d && cl.d.acting_profile) || null;
  CONN.ready = rd.d || null;
  renderAcct();
}
function renderAcct() {
  const box = $("#acct");
  const active = CONN.list.find(c => c.id === CONN.active) || null;
  if (!CONN.list.length) {
    box.innerHTML = `<div class="acct-btn"><span class="dot warn"></span>
      <span class="acct-lbl">שירות החשבונות אינו זמין</span></div>`;
    return;
  }
  const ready = !!(CONN.ready && CONN.ready.ready);
  const reason = (CONN.ready && CONN.ready.reason) || "";
  box.innerHTML = `
    <button class="acct-btn" id="acctBtn" title="${esc([ready ? "החשבון מחובר ופעיל" : reason || "השירות אינו מוכן", connId(active)].filter(Boolean).join(" · "))}">
      <span class="dot ${ready ? "ok" : "warn"}"></span>
      <span class="acct-lbl"><bdi>${esc(connName(active))}</bdi></span>
      ${active && connHint(active) ? `<small class="acct-hint"><bdi>${esc(connHint(active))}</bdi></small>` : ""}
      <span class="acct-chev">${ic("chevron")}</span>
    </button>
    <div class="acct-menu hidden" id="acctMenu"></div>`;
  const menu = $("#acctMenu");
  for (const c of CONN.list) {
    const item = document.createElement("div");
    item.className = "acct-item" + (c.id === CONN.active ? " on" : "");
    const pick = document.createElement("button");
    pick.className = "acct-pick";
    pick.innerHTML = `<span class="acct-lbl"><bdi>${esc(connName(c))}</bdi>` +
      (c.is_admin ? `<span class="tag">מנהל</span>` : "") + `</span>` +
      (connHint(c) ? `<small class="acct-hint"><bdi>${esc(connHint(c))}</bdi></small>` : "") +
      (c.id === CONN.active ? `<span class="acct-on">${ic("check")}</span>` : "");
    pick.title = connId(c);
    pick.onclick = () => guard(pick, () => selectConn(c.id));
    item.appendChild(pick);
    /* A private profile is not removed from the connection bar — removing it means removing an
       IDENTITY, with a last-admin rule and files that must survive. That belongs in the profile
       screen, and DELETE /connections/<id> refuses it for exactly this reason. */
    if (!isPrivateConn(c)) {
      const rm = document.createElement("button");
      rm.className = "acct-rm"; rm.title = "הסר חשבון"; rm.innerHTML = ic("trash");
      rm.onclick = () => removeConn(c);
      item.appendChild(rm);
    }
    menu.appendChild(item);
  }
  /* The PROFILE screen — shown only when a private engine is bound AND the acting profile is an
     admin. Deliberately NOT the connect wizard: creating an identity and connecting to one are
     different acts, and merging them is what made "add a user" undiscoverable everywhere it was
     merged. */
  if (isPrivateConn(active) && CONN.acting && CONN.acting.is_admin) {
    const mp = document.createElement("button");
    mp.className = "acct-add"; mp.innerHTML = ic("users") + " ניהול פרופילים";
    mp.onclick = () => { menu.classList.add("hidden"); profilesScreen(); };
    menu.appendChild(mp);
  }
  const add = document.createElement("button");
  add.className = "acct-add"; add.innerHTML = ic("plus") + " חיבור חשבון";
  add.onclick = () => { menu.classList.add("hidden"); connectFlow(); };
  menu.appendChild(add);
  if (!ready && reason) {
    const w = document.createElement("div");
    w.className = "acct-warn"; w.innerHTML = ic("alert") + `<span><bdi>${esc(reason)}</bdi></span>`;
    box.appendChild(w);
  }
  $("#acctBtn").onclick = e => { e.stopPropagation(); menu.classList.toggle("hidden"); };
}
document.addEventListener("click", () => {
  const m = $("#acctMenu"); if (m) m.classList.add("hidden");
});
async function selectConn(id) {
  const r = await jsoft("connections/select", post({ id }));
  if (!r.ok) return tellBad((r.d && r.d.error) ||"החלפת החשבון נכשלה");
  binaTell("החשבון הוחלף");
  CUR = null; SEARCHQ = ""; TRASH = false;
  history.replaceState({}, "", MOUNT + "/");
  await boot();
}
async function removeConn(c) {
  const hint = connHint(c);
  if (!await binaAsk({
    danger: true, ok: "הסרה", title: `להסיר את החיבור «${connName(c)}»?`,
    body: "הקבצים בחשבון עצמו לא נמחקים — רק החיבור אליו מוסר.",
    facts: hint && hint !== connName(c) && [["חשבון", hint]],
    run: () => must(jsoft("connections/" + encodeURIComponent(c.id), { method: "DELETE" }), "ההסרה נכשלה"),
  })) return;
  binaTell("החיבור הוסר"); await boot();
}

/* ── the PROFILE-MANAGEMENT screen (the engine plane) ──────────────────────────────
   Identities on the private drive engine: create, rename, rotate a key, suspend, remove access.
   Every row here is a real vault connection too — creating a profile creates its connection in the
   same operation, which is why "create" here immediately puts a new entry in the bar above with no
   second, decision-free step. */
async function profilesScreen() {
  modal("ניהול פרופילים", `<div class="muted">טוען…</div>`, []);
  const r = await jsoft("engine/profiles");
  if (!r.ok) {
    return modal("ניהול פרופילים", `<div class="errbox">${ic("alert")}<div>
      <b>אין הרשאה</b><div class="muted"><bdi>${esc((r.d && r.d.error) || "")}</bdi></div></div></div>`,
      [{ label: "סגירה", onclick: closeModal }]);
  }
  const list = (r.d && r.d.profiles) || [];
  /* `acting_as` is an ID, not a record — the same field chat returns, so the console and any
     automation read one dialect across the three apps. */
  const meId = (r.d && r.d.acting_as) || null;
  const rows = list.map(p => `
    <tr data-id="${esc(p.id)}">
      <td><b><bdi>${esc(p.display_name)}</bdi></b>
        ${p.is_admin ? `<span class="tag">מנהל</span>` : ""}
        ${p.status !== "active" ? `<span class="tag warn">מושעה</span>` : ""}
        ${p.id === meId ? `<span class="tag">זה אתה</span>` : ""}
        <div class="muted" dir="ltr">${esc(p.id)}</div></td>
      <td dir="ltr"><small>${esc(p.connection_id || "— אין חיבור —")}</small></td>
      <td class="pf-act">
        <button data-act="use" ${p.connection_id ? "" : "disabled"}>מעבר</button>
        <button data-act="rename">שם</button>
        <button data-act="key">מפתח חדש</button>
        <button data-act="suspend">${p.status === "active" ? "השעיה" : "החזרה"}</button>
        <button data-act="rm" class="danger">הסרה</button>
      </td>
    </tr>`).join("");
  modal("ניהול פרופילים",
    `<table class="pftable"><thead><tr><th>פרופיל</th><th>חיבור</th><th></th></tr></thead>
       <tbody>${rows}</tbody></table>
     <div class="muted">הסרת פרופיל מסירה את הגישה בלבד — הקבצים שלו נשמרים ונראים שוב אם ייווצר
       פרופיל באותו מזהה.</div>`,
    [{ label: "פרופיל חדש", cls: "primary", onclick: () => newProfile() },
     { label: "סגירה", onclick: closeModal }]);
  $("#mBody").querySelectorAll("[data-act]").forEach(b => {
    b.onclick = () => profileAction(b.closest("tr").dataset.id, b.dataset.act, b);
  });
}

function newProfile() {
  modal("פרופיל חדש",
    `<label class="fld"><span>מזהה (אנגלית, ללא רווחים)</span>
       <input type="text" id="pfId" dir="ltr" placeholder="user3"></label>
     <label class="fld"><span>שם לתצוגה</span><input type="text" id="pfName"></label>
     <label class="fld"><input type="checkbox" id="pfAdmin"> <span>הרשאות מנהל</span></label>
     <div class="muted">הפרופיל והחיבור שלו נוצרים יחד. המפתח יוצג פעם אחת בלבד — המערכת שומרת
       רק את הטביעה שלו ולא תוכל להציג אותו שוב.</div>`,
    [{ label: "יצירה", cls: "primary", onclick: e => guard(e.currentTarget, async () => {
        const id = ($("#pfId").value || "").trim().toLowerCase();
        const display_name = ($("#pfName").value || "").trim() || id;
        if (!id) return tellWarn("יש למלא מזהה");
        const r = await jsoft("engine/profiles", post({ id, display_name, admin: $("#pfAdmin").checked }));
        if (!r.ok) return tellBad((r.d && r.d.error) ||"היצירה נכשלה");
        showKey(r.d, "הפרופיל נוצר");
      }) },
     { label: "חזרה", onclick: () => profilesScreen() }]);
}

/* A credential is shown exactly once, and the screen says so. Anything else is a lie: this service
   stores only the hash and genuinely cannot produce the key a second time. */
function showKey(d, title) {
  const key = (d && d.key) || "";
  modal(title,
    `${d && d.warning ? `<div class="errbox">${ic("alert")}<div><bdi>${esc(d.warning)}</bdi></div></div>` : ""}
     <div class="okbox">${ic("check-circle")}<div><b>המפתח של הפרופיל</b>
       <div class="muted">מוצג פעם אחת בלבד. שמור אותו עכשיו.</div></div></div>
     <div class="keybox" dir="ltr" id="pfKey">${esc(key)}</div>`,
    [{ label: "העתקה", cls: "primary", onclick: () => copyText(key, "המפתח הועתק") },
     { label: "סיום", onclick: async () => { await boot(); profilesScreen(); } }]);
}

async function profileAction(id, act, btn) {
  const base = "engine/profiles/" + encodeURIComponent(id);
  const patch = body => ({ method: "PATCH", headers: { "Content-Type": "application/json" },
                           body: JSON.stringify(body) });
  if (act === "use") {
    const p = ((await jsoft("engine/profiles")).d || {}).profiles || [];
    const row = p.find(x => x.id === id);
    if (!row || !row.connection_id) return tellWarn("לפרופיל אין חיבור");
    closeModal(); return selectConn(row.connection_id);
  }
  if (act === "rename") {
    const name = await binaAsk({ title: "שם לתצוגה", ok: "שמירה", input: { label: "השם שיוצג לפרופיל", dir: "auto" } });
    if (!name) return;
    const r = await jsoft(base, patch({ display_name: name }));
    if (!r.ok) return tellBad((r.d && r.d.error) ||"השינוי נכשל");
    await boot(); return profilesScreen();
  }
  if (act === "key") {
    let d;                                   // the new key: shown once, by the screen the question was asked over
    if (await binaAsk({
      danger: true, ok: "החלפה", title: `להחליף את המפתח של «${id}»?`,
      body: "כל לקוח שמחזיק את המפתח הישן יפסיק לעבוד מיד.",
      run: async () => { d = await must(jsoft(base + "/key", post({})), "ההחלפה נכשלה"); },
    })) showKey(d, "המפתח הוחלף");
    return;
  }
  if (act === "suspend") {
    const want = btn.textContent.trim() === "השעיה" ? "suspended" : "active";
    const r = await jsoft(base, patch({ status: want }));
    if (!r.ok) return tellBad((r.d && r.d.error) ||"הפעולה נכשלה");
    await boot(); return profilesScreen();
  }
  if (act === "rm") {
    if (!await binaAsk({
      danger: true, ok: "הסרה", title: `להסיר את הגישה של «${id}»?`,
      body: "הקבצים לא נמחקים. הם יישארו שייכים למזהה הזה ויופיעו שוב אם ייווצר פרופיל באותו שם.",
      run: () => must(jsoft(base, { method: "DELETE" }), "ההסרה נכשלה"),
    })) return;
    binaTell("הגישה הוסרה"); await boot(); return profilesScreen();
  }
}

/* ── guided connect (§4b): provider -> how -> provide -> VERIFY -> activate.
   Every step is visible and resolves to a state; a connection is never "added", it is verified. */
const stepsHtml = (n, labels) => `<div class="steps">` + labels.map((l, i) =>
  `<span class="step ${i + 1 === n ? "on" : i + 1 < n ? "done" : ""}">${i + 1 < n ? ic("check") : i + 1}
   <b>${esc(l)}</b></span>`).join("") + `</div>`;
const STEPS = ["ספק", "אופן החיבור", "אישור", "בדיקה", "הפעלה"];

async function connectFlow() {
  modal("חיבור חשבון", stepsHtml(1, STEPS) + `<div class="muted">טוען ספקים…</div>`, []);
  const r = await jsoft("providers");
  const provs = (r.d && r.d.providers) || [];
  if (!provs.length) return modal("חיבור חשבון", `<div>לא נמצאו ספקים.</div>`,
    [{ label: "סגירה", onclick: closeModal }]);
  stepProvider(provs);
}
function stepProvider(provs) {
  const cards = provs.map((p, i) =>
    `<button class="provcard" data-i="${i}">
       <span class="pic">${ic(ICONS[p.icon] ? p.icon : "hard-drive")}</span>
       <span class="pt">${esc(p.name)}${p.builtin ? `<span class="tag">מובנה</span>` : ""}</span>
       <span class="pd">${esc(p.description || "")}</span>
     </button>`).join("");
  modal("חיבור חשבון", stepsHtml(1, STEPS) + `<div class="provgrid">${cards}</div>`,
    [{ label: "ביטול", onclick: closeModal }]);
  $("#mBody").querySelectorAll(".provcard").forEach(b =>
    b.onclick = () => stepMethod(provs, provs[+b.dataset.i]));
}
function stepMethod(provs, prov) {
  const ms = prov.auth_methods || [];
  const rows = ms.map((m, i) =>
    `<button class="methcard" data-i="${i}">
       <span class="mt">${esc(m.label)}${m.recommended ? `<span class="tag">מומלץ</span>` : ""}</span>
       <span class="md">${esc(m.can || "")}</span>
       ${m.needs && m.needs.length ? `<span class="mn">נדרש: ${esc(m.needs.join(", "))}</span>` : ""}
     </button>`).join("");
  modal("חיבור " + prov.name, stepsHtml(2, STEPS) + `<div class="methlist">${rows}</div>`,
    [{ label: "חזרה", onclick: () => stepProvider(provs) }, { label: "ביטול", onclick: closeModal }]);
  $("#mBody").querySelectorAll(".methcard").forEach(b => b.onclick = () => {
    const m = ms[+b.dataset.i];
    if (m.protocol === "drive_local") return stepBuiltin(provs, prov, m);
    if (m.start_url) return stepOauth(provs, prov, m);
    return stepForm(provs, prov, m);
  });
}
/* The private engine is already there, but it is no longer ONE thing to switch to — it holds N
   profiles, each its own drive. So "connect to the local storage" is really "pick which profile",
   and creating a new one is an act of the profile screen, not of this wizard. Saying so here is
   what stops the wizard from becoming the place people look for "add a user". */
function stepBuiltin(provs, prov, m) {
  const locals = CONN.list.filter(isPrivateConn);
  const rows = locals.map(c => `<button class="methcard" data-id="${esc(c.id)}">
      <span class="mt"><bdi>${esc(connName(c))}</bdi>${c.is_admin ? `<span class="tag">מנהל</span>` : ""}
        ${c.id === CONN.active ? `<span class="tag">פעיל</span>` : ""}</span>
      <span class="md" dir="ltr">${esc(c.profile_id || c.id)}</span></button>`).join("");
  modal(prov.name, stepsHtml(5, STEPS) +
    `<div class="okbox">${ic("check-circle")}<div>האחסון המקומי מובנה במערכת.
       לכל פרופיל יש דרייב משלו — בחר באיזה פרופיל לעבוד.</div></div>` +
    (rows ? `<div class="methlist">${rows}</div>`
          : `<div class="muted">עדיין לא נוצר אף פרופיל.</div>`) +
    `<div class="muted">יצירת פרופיל חדש נעשית במסך "ניהול פרופילים" (זמין למנהל).</div>`,
    [{ label: "חזרה", onclick: () => stepMethod(provs, prov) },
     { label: "סגירה", onclick: closeModal }]);
  $("#mBody").querySelectorAll("[data-id]").forEach(b =>
    b.onclick = () => guard(b, async () => { await selectConn(b.dataset.id); closeModal(); }));
}
/* OAuth: explain -> hand off -> an EXPLICIT waiting state (the window may be closed, consent may
   fail — say so) -> verify. We poll the connection list for the instance the broker creates. */
function stepOauth(provs, prov, m) {
  const before = new Set(CONN.list.map(c => c.id));
  modal("חיבור " + prov.name, stepsHtml(3, STEPS) +
    `<div class="explain">${esc(m.explain || "")}</div>
     <div class="muted">החלון נפתח אצל ספק הזהות שלנו, לא כאן — הסיסמה שלך לעולם אינה עוברת דרך המערכת הזו.</div>`,
    [{ label: "פתיחת חלון האישור", cls: "primary", icon: "external", onclick: () => {
        window.open(m.start_url, "_blank", "noopener,width=560,height=720");
        waitOauth(provs, prov, m, before);
      } },
     { label: "חזרה", onclick: () => stepMethod(provs, prov) }]);
}
function waitOauth(provs, prov, m, before) {
  let tries = 0;
  const render = extra => modal("חיבור " + prov.name, stepsHtml(3, STEPS) +
    `<div class="waitbox"><span class="spin">${ic("clock")}</span>
       <div><b>ממתין לאישור בחלון של ${esc(prov.name)}…</b>
       <div class="muted">אם סגרת את החלון או ביטלת — לא נוצר חיבור, אפשר לנסות שוב.</div>${extra || ""}</div></div>`,
    [{ label: "ניסיון נוסף", onclick: () => { window.open(m.start_url, "_blank", "noopener,width=560,height=720"); } },
     { label: "ביטול", onclick: () => { clearInterval(t); closeModal(); } }]);
  render();
  const t = setInterval(async () => {
    tries++;
    const r = await jsoft("connections");
    const list = (r.d && r.d.connections) || [];
    const fresh = list.find(c => !before.has(c.id) && c.protocol === m.protocol);
    if (fresh) {
      clearInterval(t); CONN.list = list; CONN.active = (r.d && r.d.active) || CONN.active;
      return stepVerify(provs, prov, m, fresh);
    }
    if (tries > 60) {          // ~3 minutes
      clearInterval(t);
      modal("חיבור " + prov.name, stepsHtml(3, STEPS) +
        `<div class="errbox">${ic("alert")}<div><b>לא התקבל אישור</b>
         <div class="muted">החלון נסגר, האישור בוטל, או שהחיבור לספק נכשל. אפשר לנסות שוב.</div></div></div>`,
        [{ label: "ניסיון נוסף", cls: "primary", onclick: () => stepOauth(provs, prov, m) },
         { label: "סגירה", onclick: closeModal }]);
    }
  }, 3000);
}
/* key/password methods: a form built from the method's own `needs` list */
function stepForm(provs, prov, m) {
  const fields = m.fields || (m.needs || []).map(name => ({ name, label: name, type: "text" }));
  modal("חיבור " + prov.name, stepsHtml(3, STEPS) +
    (m.explain ? `<div class="explain">${esc(m.explain)}</div>` : "") +
    fields.map(field => {
      const fieldId = "field_" + Math.random().toString(36).slice(2, 9);
      const fileId = "file_" + Math.random().toString(36).slice(2, 9);
      return `<div class="fld-wrapper">
        <div class="fld"><div class="fld-label"><label for="${fieldId}">${esc(field.label || field.name)}</label>
          ${field.type === "textarea" ? `<label class="file-load-btn" for="${fileId}" title="בחירת קובץ JSON"><span data-ic="upload"></span><span>בחירת קובץ JSON</span></label>` : ""}
        </div>
        ${field.type === "textarea"
          ? `<textarea id="${fieldId}" data-need="${esc(field.name)}" dir="ltr" rows="7" style="resize:vertical;font-family:monospace;font-size:11px;width:100%"></textarea><input id="${fileId}" class="file-load-input" type="file" accept=".json,application/json,text/plain" data-textarea="${fieldId}">`
          : `<input type="text" data-need="${esc(field.name)}" dir="ltr">`}
        </div>
      </div>`;
    }).join("") +
    (m.help_url ? `<a class="pvlink" href="${esc(m.help_url)}" target="_blank" rel="noopener">${ic("external")} מהיכן משיגים את הערך הזה?</a>` : ""),
    [{ label: "המשך לבדיקה", cls: "primary", onclick: event => guard(event.currentTarget, async () => {
        const secret = {};
        for (const input of $("#mBody").querySelectorAll("[data-need]")) secret[input.dataset.need] = input.value.trim();
        if (Object.values(secret).some(value => !value)) return tellWarn("יש למלא את כל השדות");
        const result = await jsoft("connections", post({ protocol: m.protocol, label: prov.name, secret }));
        if (!result.ok || !(result.d && result.d.id)) return tellBad((result.d && result.d.error) || "יצירת החיבור נכשלה");
        const connections = await jsoft("connections");
        CONN.list = (connections.d && connections.d.connections) || CONN.list;
        stepVerify(provs, prov, m, CONN.list.find(connection => connection.id === result.d.id) || { id: result.d.id });
      }) },
     { label: "חזרה", onclick: () => stepMethod(provs, prov) }]);

  $("#mBody").querySelectorAll('input[type="file"]').forEach(input => {
    input.addEventListener("change", () => {
      const file = input.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = event => {
        const textarea = $("#" + input.dataset.textarea);
        if (textarea && typeof event.target?.result === "string") {
          textarea.value = event.target.result;
          binaTell("הקובץ נטען בהצלחה");
        }
      };
      reader.onerror = () => tellBad("שגיאה בקריאת הקובץ");
      reader.readAsText(file);
    });
  });
}

/* VERIFY — the probe result, shown. A failure names what to fix; it never leaves a half-added row. */
async function stepVerify(provs, prov, m, conn) {
  modal("בדיקת החיבור", stepsHtml(4, STEPS) +
    `<div class="waitbox"><span class="spin">${ic("clock")}</span><div>בודק את החיבור מול ${esc(prov.name)}…</div></div>`, []);
  const r = await jsoft("connections/" + encodeURIComponent(conn.id) + "/probe");
  const ok = !!(r.d && r.d.ok);
  const hint = (r.d && r.d.account_hint) || conn.account_hint;
  if (!ok) {
    return modal("בדיקת החיבור", stepsHtml(4, STEPS) +
      `<div class="errbox">${ic("alert")}<div><b>החיבור נוצר אך אינו עובד</b>
        <div class="muted"><bdi>${esc((r.d && r.d.reason) || "הבדיקה נכשלה")}</bdi></div></div></div>`,
      [{ label: "בדיקה חוזרת", cls: "primary", onclick: () => stepVerify(provs, prov, m, conn) },
       { label: "הסרת החיבור", cls: "danger", onclick: e => guard(e.currentTarget, async () => {
           await jsoft("connections/" + encodeURIComponent(conn.id), { method: "DELETE" });
           closeModal(); await boot();
         }) }]);
  }
  modal("החשבון מחובר", stepsHtml(5, STEPS) +
    `<div class="okbox">${ic("check-circle")}<div><b>הבדיקה עברה</b>
      <div class="muted">${esc(conn.label || prov.name)}${hint ? " · " : ""}<bdi>${esc(hint || "")}</bdi></div></div></div>
     <div class="muted">אפשר להפעיל את החשבון עכשיו — כל הפעולות (כולל האוטומציות) יעברו לעבוד מולו.</div>`,
    [{ label: "הפעלה כחשבון פעיל", cls: "primary", onclick: e => guard(e.currentTarget, async () => {
        await selectConn(conn.id); closeModal();
      }) },
     { label: "שמירה בלי להפעיל", onclick: () => { closeModal(); boot(); } }]);
}

/* ── boot / refresh ── */
async function loadSidebar() {
  const [f, x] = await Promise.all([jf("api/folders"), jsoft("extensions?slot=rail")]);
  FOLDERS = f.folders || [];
  RAIL = (x.d && x.d.extensions) || [];
  renderSysRail();   // system places first — they are where most sessions start
  renderRail();      // apps' registered rails (§4c) — then the drive's own tree
  renderTree();
  markActive();
  loadStorage();     // fire-and-forget: the meter is context, never a gate on the file list
}
async function refresh() {
  await loadSidebar();
  if (SEARCHQ) return runGlobalSearch(SEARCHQ, false);
  await loadFiles();
}
async function boot() {
  paintIcons();
  await loadConnections();
  try { await loadSidebar(); }
  catch (e) {
    // (it said «בדוק את החיבור למטה» — the account card, which the console does not draw; the cause is the notice's to say)
    $("#filesTable").innerHTML = `<div class="empty"><span class="empty-ic">${ic("alert")}</span>
      <b>הדרייב לא נטען</b><button class="ghost" id="bootRetry" type="button">נסה שוב</button></div>`;
    $("#bootRetry").onclick = boot; return;
  }
  await applyUrl();
}
boot();
