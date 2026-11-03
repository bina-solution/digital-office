/* «פגישות» — core.js: the app's root and its server calls, Hebrew formatting, glyphs, the direction of a piece of
   text, people's colours, and the router (the centre at …/flow/, a meeting at …/flow/<room>/). Every other file
   hangs its part on window.MF. */
(() => {
  "use strict";
  const MF = (window.MF = window.MF || {});
  const readCfg = () => { try { MF.cfg = JSON.parse((document.body && document.body.dataset.config) || "{}") || {}; } catch (e) { MF.cfg = {}; } };
  readCfg();
  // the app's root from the address: «/a/meet/» inside the console, «/» on the app's own host. The console gives
  // the page a <base> of its own; nothing here leans on it — every address is written from this root.
  MF.root = window.MF_ROOT || location.pathname.replace(/flow(\/.*)?$/, "");
  MF.url = (p) => MF.root + String(p || "").replace(/^\/+/, "");
  MF.roomUrl = (room, rest) => MF.url("flow/" + encodeURIComponent(room) + "/" + (rest || ""));

  /* ---------- text ---------- */
  MF.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // a clock on the meeting's own axis: 0:12:34 (an hour or more) or 12:34
  MF.fmt = (t, long) => {
    t = Math.max(0, Math.floor(+t || 0));
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return h || long ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
  };
  MF.fmtLen = (sec) => {
    const m = Math.round((+sec || 0) / 60);
    if (m < 60) return `${m} דק׳`;
    const h = Math.floor(m / 60), r = m % 60;
    return r ? `${h}:${String(r).padStart(2, "0")} שע׳` : `${h} שע׳`;
  };
  const OFFICE_TZ = "Asia/Jerusalem";
  const dayKey = (d) => new Intl.DateTimeFormat("en-CA", { timeZone: OFFICE_TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  // «2026-10-28 08:28» (the office's local time, as the recorder writes it) or epoch seconds
  MF.toDate = (v) => {
    if (v == null || v === "") return null;
    if (typeof v === "number") return new Date(v * 1000);
    const m = String(v).match(/^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/);
    if (!m) return null;
    // the string is the office's wall clock: find the instant whose office time it is
    const guess = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    const off = (d) => { const p = new Intl.DateTimeFormat("en-US", { timeZone: OFFICE_TZ, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(d);
      const g = (k) => +p.find((x) => x.type === k).value; return Date.UTC(g("year"), g("month") - 1, g("day"), g("hour"), g("minute")) - d.getTime(); };
    return new Date(guess - off(new Date(guess)));
  };
  MF.day = (v, now) => {
    const d = MF.toDate(v); if (!d) return "";
    const today = dayKey(now ? new Date(now * 1000) : new Date()), k = dayKey(d);
    const y = new Date((now ? now * 1000 : Date.now()) - 86400000);
    if (k === today) return "היום";
    if (k === dayKey(y)) return "אתמול";
    return new Intl.DateTimeFormat("he-IL", { timeZone: OFFICE_TZ, weekday: "long", day: "numeric", month: "long" }).format(d);
  };
  MF.dayShort = (v) => { const d = MF.toDate(v); return d ? new Intl.DateTimeFormat("he-IL", { timeZone: OFFICE_TZ, day: "numeric", month: "short" }).format(d) : ""; };
  MF.clock = (v) => { const d = MF.toDate(v); return d ? new Intl.DateTimeFormat("he-IL", { timeZone: OFFICE_TZ, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(d) : ""; };
  MF.ago = (sec) => {
    const s = Math.max(0, Date.now() / 1000 - (+sec || 0));
    if (s < 60) return "עכשיו";
    if (s < 3600) return `לפני ${Math.round(s / 60)} דק׳`;
    if (s < 86400) return `לפני ${Math.round(s / 3600)} שע׳`;
    return `לפני ${Math.round(s / 86400)} ימים`;
  };
  MF.num = (n) => new Intl.NumberFormat("he-IL").format(+n || 0);

  // Which way a piece of text runs, by its letters (not by its first one: «Zoom עובד» starts Latin and is Hebrew)
  MF.dirOf = (s) => {
    const t = String(s || "").slice(0, 240);
    const he = (t.match(/[֐-׿]/g) || []).length, la = (t.match(/[A-Za-z]/g) || []).length;
    return la > 3 && la > he * 1.5 ? "ltr" : "rtl";
  };
  // the attributes of a block of content: its own direction; a long English paragraph reads from the left
  MF.dirAttr = (s) => (MF.dirOf(s) === "ltr" ? ` dir="ltr"${String(s || "").length > 160 ? " data-long" : ""}` : "");
  // search: case, niqqud and final letters do not matter
  MF.norm = (s) => String(s || "").toLowerCase().replace(/[֑-ׇ]/g, "")
    .replace(/[ךםןףץ]/g, (c) => ({ "ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ" }[c]));

  /* ---------- people ---------- */
  const HUES = ["sky", "lime", "plum", "olive"];
  MF.people = (colors) => {
    const map = Object.assign({}, colors || {});
    const used = new Set(Object.values(map));
    return (who) => {
      who = String(who || "?");
      if (!map[who]) { const free = HUES.find((h) => !used.has(h)) || HUES[Object.keys(map).length % HUES.length]; map[who] = free; used.add(free); }
      return map[who];
    };
  };
  MF.initial = (who) => { const s = String(who || "?").trim(); return (s.match(/[\p{L}\p{N}]/u) || ["?"])[0].toUpperCase(); };
  MF.avatar = (who, hue) => `<span class="mf-av" data-hue="${MF.esc(hue)}" title="${MF.esc(who)}" aria-hidden="true">${MF.esc(MF.initial(who))}</span>`;

  /* ---------- glyphs: the office's set (bina-icons.js), and the media/work ones it has no name for (Feather) ---------- */
  MF.ICONS = {
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    edit: '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
    users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>',
    bookmark: '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    task: '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    done: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>',
    volume: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>',
    mute: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>',
    back10: '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
    fwd10: '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
    expand: '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>',
    video: '<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
    headphones: '<path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/>',
    list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    radio: '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14"/>',
    target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    chevronL: '<polyline points="15 18 9 12 15 6"/>',
    chevronR: '<polyline points="9 18 15 12 9 6"/>',
    chevronD: '<polyline points="6 9 12 15 18 9"/>',
    arrowR: '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    zoomIn: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>',
    zoomOut: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/>',
    star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    type: '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/>',
    film: '<rect x="2" y="2" width="20" height="20" rx="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/>',
  };
  MF.ic = (name, cls) => {
    const p = MF.ICONS[name] || (window.BINA_ICONS || {})[name] || (window.BINA_ICONS || {}).app || "";
    return `<svg class="ic${cls ? " " + cls : ""}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${p}</svg>`;
  };

  /* ---------- the server ---------- */
  class MFError extends Error { constructor(code, he, doc) { super(he); this.code = code; this.doc = doc; } }
  MF.Error = MFError;
  MF.errorHe = (code, doc) => {
    const e = (doc && (doc.error || doc.detail)) || "";
    if (code === "net") return "אין חיבור לשרת הפגישות — בדקו את הרשת ונסו שוב";
    if (code === 401) return "צריך להיות מחוברים למשרד כדי לשנות פגישה";
    if (code === 403) return "השרת סירב לבקשה";
    if (code === 404) return "לא נמצא";
    if (code === 409) return "הקובץ השתנה בינתיים — ממשיכים מהנקודה שהשרת שמר";
    if (code === 413) return "הקובץ גדול מדי לשרת הזה";
    if (code === 502 && e === "plane") return "Plane לא ענה — המשימה לא נשלחה, אפשר לנסות שוב";
    if (code === 503 && e === "no store") return "האחסון של הפגישות עוד לא הוגדר בשרת — אי אפשר לשמור";
    if (code === 503) return "השירות לא זמין כרגע";
    return `השרת ענה בשגיאה (${code})`;
  };
  MF.api = async (path, opt = {}) => {
    const init = { method: opt.method || "GET", headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store" };
    if (opt.body !== undefined) { init.body = JSON.stringify(opt.body); init.headers["Content-Type"] = "application/json"; }
    if (init.method !== "GET") init.headers["X-Meet-Flow"] = "1";
    if (opt.signal) init.signal = opt.signal;
    let r;
    try { r = await fetch(MF.url(path), init); } catch (e) { if (e && e.name === "AbortError") throw e; throw new MFError("net", MF.errorHe("net")); }
    const txt = await r.text();
    let doc = null;
    try { doc = txt ? JSON.parse(txt) : null; } catch (e) { doc = null; }
    if (!r.ok) throw new MFError(r.status, MF.errorHe(r.status, doc), doc);
    return doc;
  };
  // a meeting's full data (data.js sets window.MEETING): read as a script, once per address
  MF.loadData = (src) => new Promise((ok, bad) => {
    delete window.MEETING;
    const s = document.createElement("script");
    s.src = MF.url(src) + (src.includes("?") ? "&" : "?") + "at=" + Date.now();
    s.onload = () => { const M = window.MEETING; s.remove(); M ? ok(M) : bad(new MFError(404, "הנתונים של הפגישה ריקים")); };
    s.onerror = () => { s.remove(); bad(new MFError(404, "הנתונים של הפגישה לא נטענו")); };
    document.head.appendChild(s);
  });
  MF.tell = (text, kind, o) => (window.binaTell ? window.binaTell(text, kind || "ok", o) : console.log(text));
  MF.ask = (o) => (window.binaAsk ? window.binaAsk(o) : Promise.resolve(window.confirm(o.title)));
  MF.copy = async (text, said) => {
    try { await navigator.clipboard.writeText(text); MF.tell(said || "הקישור הועתק", "ok"); }
    catch (e) { MF.ask({ title: "הקישור", body: "העתיקו מכאן:", input: { label: "קישור", value: text }, ok: "סגירה" }); }
  };
  MF.store = {
    get(k, d) { try { const v = localStorage.getItem("mf:" + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("mf:" + k, JSON.stringify(v)); } catch (e) { /* private window */ } },
  };

  /* ---------- Hebrew names of states ---------- */
  MF.STATE = {
    before: { he: "לפני הפגישה", tone: "muted", hint: "הפגישה עוד לא התחילה" },
    live: { he: "בשידור", tone: "live", hint: "הפגישה מתקיימת עכשיו" },
    first: { he: "עיבוד ראשון", tone: "run", hint: "ההקלטה והכתוביות החיות, לפני העיבוד המלא" },
    ready: { he: "מעובדת", tone: "ok", hint: "התמלול, הנושאים, ההחלטות והמשימות מוכנים" },
    reviewed: { he: "נבדקה", tone: "ok", hint: "אדם עבר על התמלול" },
  };
  MF.STAGE = {
    record: "הקלטה", captions: "כתוביות חיות", first: "עיבוד ראשון", best: "תמלול מלא",
    speakers: "זיהוי דוברים", summary: "נושאים · החלטות · משימות", review: "בדיקה של אדם",
  };
  MF.STAGE_STATE = { done: "הושלם", running: "רץ עכשיו", waiting: "ממתין", off: "לא פעיל", failed: "נכשל" };
  MF.statePill = (state) => {
    const s = MF.STATE[state] || { he: state, tone: "muted" };
    return `<span class="mf-state" data-tone="${s.tone}" title="${MF.esc(s.hint || "")}">${s.tone === "live" ? '<i class="mf-pulse" aria-hidden="true"></i>' : ""}${MF.esc(s.he)}</span>`;
  };

  /* ---------- the router ---------- */
  MF.where = () => {
    const rest = location.pathname.slice(MF.root.length);
    const m = rest.match(/^flow\/([^/]+)\/?/);
    const q = new URLSearchParams(location.search);
    const h = location.hash.match(/^#t=?(\d+(?:\.\d+)?)/);
    return { room: m ? decodeURIComponent(m[1]).toLowerCase() : null, view: q.get("v") || "", q: q.get("q") || "", t: h ? +h[1] : null };
  };
  // the address of the page as it is, with one thing changed (the page's own path: a <base> must not move it)
  MF.setQuery = (k, v, replace = true) => {
    const q = new URLSearchParams(location.search);
    if (v == null || v === "") q.delete(k); else q.set(k, v);
    const s = q.toString();
    const href = location.pathname + (s ? "?" + s : "") + location.hash;
    try { history[replace ? "replaceState" : "pushState"](null, "", href); } catch (e) { /* a sandboxed page */ }
  };
  MF.setHash = (h) => { try { history.replaceState(null, "", location.pathname + location.search + (h ? "#" + h : "")); } catch (e) { /* */ } };
  let current = null;
  MF.go = (href, opt = {}) => {
    try { history[opt.replace ? "replaceState" : "pushState"](null, "", href); } catch (e) { location.href = href; return; }
    MF.render();
  };
  MF.render = () => {
    const w = MF.where(), app = document.getElementById("app");
    if (current && current.destroy) { try { current.destroy(); } catch (e) { console.error(e); } }
    current = null;
    window.scrollTo(0, 0);
    app.className = "mf " + (w.room ? "mf-is-meeting" : "mf-is-home");
    current = w.room ? MF.Meeting(app, w) : MF.Home(app, w);
  };
  // links inside the app move without reloading it (a click with a modifier still opens a new tab)
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[data-go]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    MF.go(a.getAttribute("href"));
  });
  window.addEventListener("popstate", () => MF.render());
  // the page is drawn once the document is parsed (the scripts may run before the body exists) and its styles are in
  MF.start = () => {
    if (!(MF.Home && MF.Meeting)) return;
    const dom = document.readyState === "loading" ? new Promise((ok) => document.addEventListener("DOMContentLoaded", ok, { once: true })) : Promise.resolve();
    Promise.all([dom, window.MF_STYLES || Promise.resolve()]).then(() => { readCfg(); MF.render(); });
  };
})();
