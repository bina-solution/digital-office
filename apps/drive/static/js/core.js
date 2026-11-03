/* core.js — what every part of «קבצים» stands on: the view library (Preact + htm, ~16 KB, no build
   step — the simulator inlines these files as they are), words in the office's language, glyphs,
   formatting, the one store, the router and the API. Each later file adds to `window.F`. */
(function () {
  "use strict";
  const { h, render, Fragment } = window.preact;
  const hooks = window.preactHooks;
  const html = window.htm.bind(h);

  /* words: the office's language (bina-lang.js defines L when the console runs in English) */
  const L = (he, en) => { try { return window.L ? window.L(he, en) : he; } catch (e) { return he; } };

  /* glyphs — Feather/Lucide style, 24×24, stroke = currentColor */
  const P = {
    folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>',
    "folder-plus": '<path d="M12 10v6"/><path d="M9 13h6"/><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "folder-up": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/><path d="M12 10v6"/><path d="m9 13 3-3 3 3"/>',
    "folder-input": '<path d="M2 9V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-1.6"/><path d="M2 13h10"/><path d="m9 16 3-3-3-3"/>',
    file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
    "file-text": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
    pdf: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M8 18v-5h1.5a1.5 1.5 0 0 1 0 3H8"/><path d="M14 13v5"/><path d="M14 13h2"/>',
    sheet: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M8 13h8"/><path d="M8 17h8"/><path d="M12 11v8"/>',
    slides: '<path d="M2 3h20"/><path d="M21 3v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V3"/><path d="m7 21 5-5 5 5"/>',
    code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
    film: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M3 7.5h4"/><path d="M3 12h18"/><path d="M3 16.5h4"/><path d="M17 3v18"/><path d="M17 7.5h4"/><path d="M17 16.5h4"/>',
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>',
    archive: '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
    cube: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    type: '<polyline points="4 7 4 4 20 4 20 7"/><line x1="9" x2="15" y1="20" y2="20"/><line x1="12" x2="12" y1="4" y2="20"/>',
    user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    calendar: '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    mail: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    db: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
    app: '<rect width="16" height="16" x="4" y="4" rx="2"/><path d="M9 9h6v6H9z"/><path d="M9 1v3"/><path d="M15 1v3"/><path d="M9 20v3"/><path d="M15 20v3"/><path d="M20 9h3"/><path d="M20 14h3"/><path d="M1 9h3"/><path d="M1 14h3"/>',
    book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
    magnet: '<path d="m6 15-4-4 6.75-6.77a7.79 7.79 0 0 1 11 11L13 22l-4-4 6.39-6.36a2.14 2.14 0 0 0-3-3L6 15"/><path d="m5 8 4 4"/><path d="m12 15 4 4"/>',
    home: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    drive: '<line x1="22" x2="2" y1="12" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" x2="6.01" y1="16" y2="16"/><line x1="10" x2="10.01" y1="16" y2="16"/>',
    clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    restore: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    menu: '<line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/>',
    more: '<circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/>',
    grid: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    list: '<line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/><line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/><line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/>',
    chevron: '<path d="m9 18 6-6-6-6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    back: '<path d="m15 18-6-6 6-6"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    edit: '<path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/>',
    external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    pause: '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
    next: '<polygon points="5 4 15 12 5 20 5 4"/><line x1="19" x2="19" y1="5" y2="19"/>',
    prev: '<polygon points="19 20 9 12 19 4 19 20"/><line x1="5" x2="5" y1="19" y2="5"/>',
    back15: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M10 9v6"/><path d="M14 9h-1.5a1.5 1.5 0 0 0 0 3h.5a1.5 1.5 0 0 1 0 3H12"/>',
    fwd15: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M10 9v6"/><path d="M14 9h-1.5a1.5 1.5 0 0 0 0 3h.5a1.5 1.5 0 0 1 0 3H12"/>',
    shuffle: '<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/><path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/><path d="m18 14 4 4-4 4"/>',
    repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    volume: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>',
    mute: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
    expand: '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" x2="14" y1="3" y2="10"/><line x1="3" x2="10" y1="21" y2="14"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    ok: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    alert: '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
    cloud: '<path d="M4 14.9A7 7 0 1 1 15.7 8h1.8a4.5 4.5 0 0 1 2.5 8.2"/><path d="M12 12v9"/><path d="m16 16-4-4-4 4"/>',
    eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    "zoom-in": '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/><line x1="11" x2="11" y1="8" y2="14"/><line x1="8" x2="14" y1="11" y2="11"/>',
    "zoom-out": '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/><line x1="8" x2="14" y1="11" y2="11"/>',
    rotate: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    sort: '<path d="m3 16 4 4 4-4"/><path d="M7 20V4"/><path d="m21 8-4-4-4 4"/><path d="M17 4v16"/>',
    refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    wrap: '<line x1="3" x2="21" y1="6" y2="6"/><path d="M3 12h15a3 3 0 1 1 0 6h-4"/><polyline points="16 16 14 18 16 20"/><line x1="3" x2="10" y1="18" y2="18"/>',
    sparkles: '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>',
  };
  const ic = (name, cls) => html`<svg class=${"ic " + (cls || "")} viewBox="0 0 24 24" aria-hidden="true"
    dangerouslySetInnerHTML=${{ __html: P[name] || P.file }}></svg>`;

  /* formatting — numbers stay tabular and left-to-right inside a Hebrew line */
  /* a size is a left-to-right token inside Hebrew text: isolated (U+2066…U+2069), or a Hebrew line
     shows "MB 41.4" — the number and its unit swapped. `per` joins the token ("/s") */
  const LRI = String.fromCharCode(0x2066), PDI = String.fromCharCode(0x2069);
  const fmtSize = (n, per) => {
    n = Number(n) || 0;
    let s;
    if (n < 1024) s = n + " B";
    else {
      const u = ["KB", "MB", "GB", "TB"]; let i = -1;
      do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
      s = (n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2)).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "") + " " + u[i];
    }
    return LRI + s + (per || "") + PDI;
  };
  /* the server writes UTC `YYYY-MM-DD HH:MM`; the page shows the reader's own clock */
  const asDate = (s) => { if (!s) return null; const d = new Date(String(s).replace(" ", "T") + (String(s).length <= 16 ? ":00Z" : "")); return isNaN(d) ? null : d; };
  const fmtWhen = (s) => {
    const d = asDate(s); if (!d) return "";
    const now = new Date(), day = 864e5;
    const t = d.toLocaleTimeString(L("he-IL", "en-US"), { hour: "2-digit", minute: "2-digit" });
    if (d.toDateString() === now.toDateString()) return L("היום ", "Today ") + t;
    if (new Date(now - day).toDateString() === d.toDateString()) return L("אתמול ", "Yesterday ") + t;
    return d.toLocaleDateString(L("he-IL", "en-US"), now.getFullYear() === d.getFullYear()
      ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" });
  };
  const fmtMonth = (s) => { const d = asDate(s); return d ? d.toLocaleDateString(L("he-IL", "en-US"), { month: "long", year: "numeric" }) : ""; };
  /* the build this window was loaded with: when the server reports another one, a deploy happened since
     and the window offers a refresh (NewVersion) — it never reloads by itself */
  let build0 = null;
  function sawBuild(b) { if (!b) return; if (!build0) build0 = b; else if (b !== build0 && !state.newBuild) set({ newBuild: true }); }
  function NewVersion({ busy }) {
    const on = useStore((s) => s.newBuild);
    if (!on) return null;
    return html`<div class="newver" role="status">${ic("refresh", "sm")}<span>${L("יש גרסה חדשה — רענון טוען אותה", "A new version is ready — refresh to load it")}</span>
      <button class="btn sm primary" disabled=${!!busy} title=${busy ? L("אחרי סיום ההקלטה", "After the recording ends") : L("טעינת הגרסה החדשה", "Load the new version")}
        onClick=${() => location.reload()}>${L("רענון", "Refresh")}</button></div>`;
  }
  /* a number with its noun: Hebrew says «קובץ אחד», never «1 קבצים» — one and many are [he, en] pairs */
  const count = (n, one, many) => n === 1 ? L(one[0], one[1]) : L(`${n} ${many[0]}`, `${n} ${many[1]}`);
  const fmtDur = (sec) => {
    sec = Math.max(0, Math.round(Number(sec) || 0));
    const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60;
    return (hh ? hh + ":" + String(mm).padStart(2, "0") : mm) + ":" + String(ss).padStart(2, "0");
  };
  const splitName = (name) => {
    const s = String(name || ""), i = s.lastIndexOf(".");
    return i > 0 && i >= s.length - 12 ? [s.slice(0, i), s.slice(i)] : [s, ""];
  };

  /* one store: state + subscribers; a component reads a slice and re-renders when it changes */
  const listeners = new Set();
  const state = {
    route: { view: "home" }, folders: [], storage: null, connection: null,
    list: { key: "", files: [], folders: [], loading: true, error: "" },
    sel: [], anchor: null, layout: localGet("layout") || "list", sort: localGet("sort", { key: "date", dir: -1 }),
    details: false, viewer: null, menu: null, dialog: null, drawer: false, searching: false,
    uploads: [], player: { queue: [], index: -1, playing: false, time: 0, duration: 0, expanded: false },
    openWith: [], size: { w: "w", h: "t", touch: false }, media: {}, rev: 0,
  };
  function set(patch) {
    Object.assign(state, typeof patch === "function" ? patch(state) : patch);
    listeners.forEach((fn) => fn());
  }
  function useStore(pick) {
    const [, force] = hooks.useReducer((x) => x + 1, 0);
    const last = hooks.useRef();
    last.current = pick(state);
    hooks.useLayoutEffect(() => {
      const fn = () => { const v = pick(state); if (!shallowEq(v, last.current)) force(); };
      listeners.add(fn);
      return () => listeners.delete(fn);
    }, []);
    return last.current;
  }
  function shallowEq(a, b) {
    if (a === b) return true;
    if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => a[k] === b[k]);
  }
  /* what this person chose stays theirs — under a name of this app, never a bare key in the
     console's shared origin */
  function localGet(k, dflt) { try { const v = localStorage.getItem("files." + k); return v ? JSON.parse(v) : dflt; } catch (e) { return dflt; } }
  function localSet(k, v) { try { localStorage.setItem("files." + k, JSON.stringify(v)); } catch (e) { /* private mode */ } }

  /* the router: the app's own URL is the screen (the console mirrors it into #/m/drive/…) */
  /* /a/drive/ under the console, / on the app's own host — and "" where the page has no http base at
     all (the simulator draws it in a srcdoc frame), so every address stays relative there */
  const BASE = (() => { try { const u = new URL(".", document.baseURI); return /^https?:$/.test(u.protocol) ? u.pathname : ""; } catch (e) { return ""; } })();
  function parse() {
    const rest = location.pathname.startsWith(BASE) ? location.pathname.slice(BASE.length) : "";
    const parts = rest.split("/").filter(Boolean).map(decodeURIComponent);
    const q = new URLSearchParams(location.search);
    const r = { view: "home" };
    if (parts[0] === "files") r.view = "folder", r.id = "";
    else if (parts[0] === "folder") { r.view = "folder"; r.id = parts[1] || ""; if (parts[2] === "file") r.file = parts[3]; }
    else if (parts[0] === "open") r.view = "open", r.file = parts[1];
    else if (parts[0] === "trash") r.view = "trash";
    else if (parts[0] === "search") r.view = "search", r.q = q.get("q") || "";
    else if (parts[0] === "p") r.view = parts[1] || "home";
    return r;
  }
  function pathOf(r) {
    switch (r.view) {
      case "folder": return r.id ? "folder/" + encodeURIComponent(r.id) + (r.file ? "/file/" + encodeURIComponent(r.file) : "") : "files";
      case "open": return "open/" + encodeURIComponent(r.file);
      case "trash": return "trash";
      case "search": return "search?q=" + encodeURIComponent(r.q || "");
      case "home": return "";
      default: return "p/" + r.view;
    }
  }
  /* the address bar follows the screen — where a document may not change its address (a srcdoc
     frame), the screen still changes and only the address stays */
  function setUrl(r, replace) {
    const url = BASE + pathOf(r);
    try { if (url !== location.pathname + location.search) history[replace ? "replaceState" : "pushState"]({}, "", url); }
    catch (e) { /* no address to write here */ }
  }
  function go(r, opts) {
    setUrl(r, opts && opts.replace);
    set({ route: r, drawer: false });
  }

  /* the API: relative to the app's own base (works under /a/drive/ and at the app's own host);
     a refusal becomes a sentence in Hebrew, never an engine's English */
  async function api(path, opt) {
    opt = opt || {};
    let r;
    try {
      r = await fetch(BASE + path, {
        method: opt.method || (opt.body !== undefined ? "POST" : "GET"),
        headers: opt.body !== undefined && !(opt.body instanceof Blob) ? { "Content-Type": "application/json" } : (opt.headers || {}),
        body: opt.body === undefined ? undefined : (opt.body instanceof Blob ? opt.body : JSON.stringify(opt.body)),
        signal: opt.signal,
      });
    } catch (e) {
      if (e.name === "AbortError") throw e;
      throw new Error(window.binaSaid ? window.binaSaid(0) : L("אין תשובה מהשירות", "No answer from the service"));
    }
    let body = null;
    try { body = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok) {
      const err = new Error((body && body.error) || window.binaSaid(r.status));
      err.status = r.status; err.body = body;
      throw err;
    }
    return body || {};
  }
  const contentUrl = (id, dl) => BASE + "api/file/" + encodeURIComponent(id) + "/content" + (dl ? "?dl=1" : "");
  const thumbUrl = (it, s) => BASE + "api/file/" + encodeURIComponent(it.id) + "/thumb?s=" + (s || 256) + "&v=" + String(it.md5 || it.size || "").slice(0, 8);

  /* notices and questions are the office's own (bina-ask.js, stamped into app.js): the page's own
     dialog, never the browser's — `confirm()` is not a question this office asks */
  const tell = (text, kind, o) => window.binaTell(text, kind || "ok", o);
  const ask = (q) => window.binaAsk(q);
  async function copyText(text, what) {
    try { await navigator.clipboard.writeText(text); }
    catch (e) {
      const t = document.createElement("textarea"); t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
      document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove();
    }
    tell(what || L("הועתק", "Copied"));
  }

  window.F = {
    h, render, html, Fragment, hooks, L, ic, P,
    fmtSize, fmtWhen, fmtMonth, fmtDur, asDate, splitName,
    state, set, useStore, localGet, localSet,
    BASE, parse, go, setUrl, pathOf, api, contentUrl, thumbUrl, tell, ask, copyText, count, sawBuild, NewVersion,
  };
})();
