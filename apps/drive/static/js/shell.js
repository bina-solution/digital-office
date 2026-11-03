/* shell.js — the frame and the start. The side (places, media, folders, storage) is a column on a
   wide box and a drawer on a narrow one — the SAME rows with their words, never an icon rail. The
   top bar is the path, the search and the view; while something is selected it becomes the
   selection's own bar. A phone gets bottom tabs (icon AND word) and one round add button. The
   size classes are measured on the app's own box (a console tile, a desktop window, a phone), so
   the layout answers the space it really has. */
(function () {
  "use strict";
  const { html, hooks, state, set, L, ic, fmtSize, render } = F;
  const D = F.data, U = F.ui;

  /* ── words for each place ─────────────────────────────────────────────── */
  const PLACES = [
    { view: "home", icon: "home", he: "בית", en: "Home" },
    { view: "folder", id: "", icon: "drive", he: "הקבצים שלי", en: "My files", tab: ["קבצים", "Files"] },
    { view: "recent", icon: "clock", he: "נפתחו לאחרונה", en: "Recent" },
    { view: "starred", icon: "star", he: "מסומנים בכוכב", en: "Starred" },
  ];
  const MEDIA = [
    { view: "photos", icon: "image", he: "תמונות", en: "Photos" },
    { view: "music", icon: "music", he: "מוזיקה ואודיו", en: "Music & audio", tab: ["אודיו", "Audio"] },
    { view: "videos", icon: "film", he: "סרטונים", en: "Videos" },
  ];
  const TITLES = { home: ["בית", "Home"], recent: ["נפתחו לאחרונה", "Recent"], starred: ["מסומנים בכוכב", "Starred"], photos: ["תמונות", "Photos"],
    music: ["מוזיקה ואודיו", "Music & audio"], videos: ["סרטונים", "Videos"], trash: ["אשפה", "Trash"] };
  const placeOf = (p) => (p.view === "folder" ? "files" : p.view);
  const isOn = (p, r) => p.view === r.view && (p.view !== "folder" || (r.id || "") === (p.id || ""));

  function addMenu(e, parent) {
    U.openMenu([
      { icon: "upload", label: L("העלאת קבצים", "Upload files"), run: () => F.upload.pick({ dest: parent != null ? { folder: parent } : undefined }) },
      { icon: "folder-up", label: L("העלאת תיקייה", "Upload a folder"), run: () => F.upload.pick({ folder: true, dest: parent != null ? { folder: parent } : undefined }) },
      { sep: true },
      { icon: "folder-plus", label: L("תיקייה חדשה", "New folder"), run: () => D.newFolder(parent != null ? parent : (state.route.view === "folder" ? state.route.id : "")) },
    ], e, L("הוספה", "Add"));
  }

  function Side() {
    const route = F.useStore((s) => s.route);
    const folders = F.useStore((s) => s.folders);
    const store = F.useStore((s) => s.storage);
    const open = F.useStore((s) => s.drawer);
    const top = folders.filter((f) => !f.parent).sort((a, b) => (b.system ? 1 : 0) - (a.system ? 1 : 0) || a.name.localeCompare(b.name, "he"));
    // data-place: a stable handle for whatever drives this page (the simulation's map, an agent's browser)
    const item = (p) => html`<a class=${"nav-i place" + (isOn(p, route) ? " on" : "")} data-place=${placeOf(p)} href=${F.BASE + F.pathOf(p)} aria-current=${isOn(p, route) ? "page" : null}
      onClick=${(e) => { e.preventDefault(); F.go(p); }} ...${p.view === "folder" ? F.views.dropTarget(p.id || "") : {}}>
      ${ic(p.icon)}<span class="lbl">${L(p.he, p.en)}</span></a>`;
    const pct = store && store.limit ? Math.min(100, store.percent) : null;
    return html`<aside class=${"fx-side" + (open ? " open" : "")} aria-label=${L("ניווט", "Navigation")}>
      <div class="side-brand"><span class="mark">${ic("folder", "sm")}</span><b>${L("קבצים", "Files")}</b>
        <span class="spacer"></span>
        <button class="icbtn only-n" title=${L("סגירה", "Close")} onClick=${() => set({ drawer: false })}>${ic("x")}</button></div>
      <button class="side-new" onClick=${(e) => { set({ drawer: false }); addMenu(e); }}>${ic("plus")}${L("חדש", "New")}</button>
      <nav class="side-scroll">
        ${PLACES.map(item)}
        <div class="nav-h">${L("מדיה", "Media")}</div>
        ${MEDIA.map(item)}
        <div class="nav-h">${L("תיקיות", "Folders")}
          <button title=${L("תיקייה חדשה", "New folder")} onClick=${() => D.newFolder("")}>${ic("plus", "sm")}</button></div>
        ${top.map((f) => html`<a key=${f.id} class=${"nav-i" + (route.view === "folder" && route.id === f.id ? " on" : "")} href=${F.BASE + F.pathOf({ view: "folder", id: f.id })}
          onClick=${(e) => { e.preventDefault(); F.go({ view: "folder", id: f.id }); }} ...${F.views.dropTarget(f.id)} title=${f.name}>
          ${ic(f.system ? "folder-input" : "folder")}<span class="lbl"><bdi>${f.name}</bdi></span>${f.count ? html`<span class="cnt num">${f.count}</span>` : ""}</a>`)}
        ${!top.length && html`<div class="nav-i muted static">${ic("folder", "sm")}<span class="lbl">${L("עוד אין תיקיות", "No folders yet")}</span></div>`}
        <div class="nav-h"></div>
        ${item({ view: "trash", icon: "trash", he: "אשפה", en: "Trash" })}
      </nav>
      ${store && html`<div class="side-store" title=${F.count(store.files, ["קובץ אחד", "1 file"], ["קבצים", "files"])}>
        <div class="t"><span>${L("אחסון", "Storage")}</span><span class="num">${fmtSize(store.used)}${store.limit ? " / " + fmtSize(store.limit) : ""}</span></div>
        ${pct != null && html`<div class="bar"><i style=${"width:" + pct + "%"}></i></div>`}
        <div class="t"><span>${F.count(store.files, ["קובץ אחד", "1 file"], ["קבצים", "files"])}</span>${store.trash_used ? html`<span>${L("באשפה ", "Trash ")}${fmtSize(store.trash_used)}</span>` : ""}</div>
      </div>`}
    </aside>`;
  }

  /* ── the top bar ──────────────────────────────────────────────────────── */
  /* the path, as much of it as the bar has room for: the folder itself on a phone (with a step up),
     its parent too on a tablet, up to four on a desktop — the rest behind «…», never squeezed */
  function Crumbs({ route, w }) {
    if (route.view === "folder") {
      const trail = D.folderPath(route.id);
      const parts = [{ id: "", name: L("הקבצים שלי", "My files") }, ...trail];
      const keep = w === "w" ? 4 : 1;
      const hidden = parts.slice(0, Math.max(0, parts.length - keep));
      const shown = parts.slice(-keep);
      const up = parts.length > 1 ? parts[parts.length - 2] : null;
      return html`<nav class="crumbs" aria-label=${L("מיקום", "Location")}>
        ${w !== "w" && up && html`<button class="icbtn" title=${L("לתיקייה ", "Up to ") + up.name} onClick=${() => F.go({ view: "folder", id: up.id })}>${ic("back", "flip")}</button>`}
        ${hidden.length > 0 && w === "w" && html`<button class="crumb more" title=${hidden.map((x) => x.name).join(" › ")}
          onClick=${(e) => U.openMenu(hidden.map((x) => ({ icon: "folder", label: x.name, run: () => F.go({ view: "folder", id: x.id }) })), e)}>…</button>
          <span class="crumb-sep">${ic("chevron")}</span>`}
        ${shown.map((p, i) => html`
        ${i > 0 && html`<span class="crumb-sep">${ic("chevron")}</span>`}
        ${i === shown.length - 1
          ? html`<span class="crumb" title=${p.name} aria-current="page"><bdi>${p.name}</bdi></span>`
          : html`<button class="crumb" title=${p.name} onClick=${() => F.go({ view: "folder", id: p.id })} ...${F.views.dropTarget(p.id)}><bdi>${p.name}</bdi></button>`}`)}</nav>`;
    }
    const t = route.view === "search" ? [L("חיפוש", "Search")] : TITLES[route.view] || TITLES.home;
    return html`<nav class="crumbs"><span class="crumb" aria-current="page">${route.view === "search" ? L("תוצאות חיפוש", "Search results") : L(t[0], t[1])}</span></nav>`;
  }
  function SearchBox() {
    const route = F.useStore((s) => s.route);
    const [q, setQ] = hooks.useState(route.view === "search" ? route.q : "");
    const t = hooks.useRef();
    hooks.useEffect(() => { if (route.view !== "search") setQ(""); }, [route.view]);
    const onInput = (e) => {
      const v = e.target.value; setQ(v);
      clearTimeout(t.current);
      t.current = setTimeout(() => F.go({ view: "search", q: v }, { replace: state.route.view === "search" }), 260);
    };
    const clear = () => { setQ(""); set({ searching: false }); if (state.route.view === "search") history.back(); };
    return html`<label class="top-search" role="search">
      <span class="sr">${L("חיפוש בקבצים", "Search files")}</span>${ic("search")}
      <input type="search" value=${q} onInput=${onInput} placeholder=${L("חיפוש בכל הקבצים", "Search all files")} autocomplete="off"
        onKeyDown=${(e) => e.key === "Escape" && clear()} autofocus=${state.searching} />
      ${q && html`<button class="x" type="button" title=${L("ניקוי", "Clear")} onClick=${clear}>${ic("x", "sm")}</button>`}
    </label>`;
  }
  function SelBar() {
    const sel = F.views.selected();
    const n = sel.length, trash = state.route.view === "trash", sys = sel.some((x) => x.system);
    const clear = () => set({ sel: [] });
    return html`<div class="selbar" role="toolbar" aria-label=${L("פעולות על הבחירה", "Selection actions")}>
      <button class="icbtn" title=${L("ביטול הבחירה", "Clear selection")} onClick=${clear}>${ic("x")}</button>
      <b>${F.count(n, ["פריט אחד נבחר", "1 selected"], ["נבחרו", "selected"])}</b>
      ${trash ? html`
        <button class="icbtn" title=${L("שחזור", "Restore")} onClick=${() => D.restore(sel)}>${ic("restore")}</button>
        <button class="icbtn" title=${L("מחיקה לצמיתות", "Delete forever")} onClick=${() => D.destroy(sel)}>${ic("trash")}</button>` : html`
        ${!sel.some((x) => x.kind === "folder") && html`<button class="icbtn hide-n" title=${L("הורדה", "Download")} onClick=${() => sel.forEach(D.download)}>${ic("download")}</button>`}
        <button class="icbtn" title=${L("העברה אל…", "Move to…")} disabled=${sys} onClick=${() => set({ dialog: { type: "move", items: sel } })}>${ic("folder-input")}</button>
        <button class="icbtn hide-n" title=${L("כוכב", "Star")} onClick=${() => D.star(sel, !sel.every((x) => x.starred))}>${ic("star")}</button>
        <button class="icbtn" title=${L("העברה לאשפה", "Move to trash")} disabled=${sys} onClick=${() => D.trash(sel)}>${ic("trash")}</button>`}
      <button class="icbtn" title=${L("עוד", "More")} onClick=${(e) => U.openMenu(U.actionsFor(sel), e)}>${ic("more")}</button>
    </div>`;
  }
  function Top() {
    const route = F.useStore((s) => s.route);
    const w = F.useStore((s) => s.size.w);
    const sel = F.useStore((s) => s.sel.length);
    const layout = F.useStore((s) => s.layout);
    const details = F.useStore((s) => s.details);
    const searching = F.useStore((s) => s.searching);
    const narrow = w === "n";
    const setLayout = (l) => { F.localSet("layout", l); set({ layout: l }); };
    const listy = !["photos", "music", "videos"].includes(route.view);
    if (sel) return html`<header class="fx-top"><${SelBar} /></header>`;
    if (narrow && searching) return html`<header class="fx-top searching">
      <button class="icbtn" title=${L("חזרה", "Back")} onClick=${() => { set({ searching: false }); if (state.route.view === "search") history.back(); }}>${ic("back", "flip")}</button>
      <${SearchBox} /></header>`;
    return html`<header class="fx-top">
      <div class="top-title"><${Crumbs} route=${route} w=${w} /></div>
      ${narrow ? html`<button class="icbtn" title=${L("חיפוש", "Search")} onClick=${() => set({ searching: true })}>${ic("search")}</button>`
        : html`<${SearchBox} />`}
      ${narrow && html`<button class="icbtn add" title=${L("הוספה: העלאה, תיקייה חדשה", "Add: upload, new folder")} aria-label=${L("הוספה", "Add")} onClick=${(e) => addMenu(e)}>${ic("plus")}</button>`}
      <div class="top-acts">
        ${listy && w === "w" && html`<div class="seg" role="group" aria-label=${L("תצוגה", "View")}>
          <button class=${layout === "list" ? "on" : ""} title=${L("רשימה", "List")} aria-pressed=${layout === "list"} onClick=${() => setLayout("list")}>${ic("list", "sm")}</button>
          <button class=${layout === "grid" ? "on" : ""} title=${L("רשת", "Grid")} aria-pressed=${layout === "grid"} onClick=${() => setLayout("grid")}>${ic("grid", "sm")}</button></div>`}
        ${listy && w === "m" && html`<button class="icbtn" title=${layout === "list" ? L("תצוגת רשת", "Grid view") : L("תצוגת רשימה", "List view")}
          onClick=${() => setLayout(layout === "list" ? "grid" : "list")}>${ic(layout === "list" ? "grid" : "list")}</button>`}
        ${!narrow && html`<button class=${"icbtn" + (details ? " on" : "")} title=${L("פרטים (I)", "Details (I)")} aria-pressed=${details} onClick=${() => set({ details: !details })}>${ic("info")}</button>`}
        ${narrow && html`<button class="icbtn" title=${L("עוד", "More")} onClick=${(e) => U.openMenu([
          ...(listy ? [{ icon: layout === "list" ? "grid" : "list", label: layout === "list" ? L("תצוגת רשת", "Grid view") : L("תצוגת רשימה", "List view"), run: () => setLayout(layout === "list" ? "grid" : "list") }] : []),
          { icon: "sort", label: L("מיון לפי שם", "Sort by name"), run: () => F.views.setSort("name") },
          { icon: "sort", label: L("מיון לפי תאריך", "Sort by date"), run: () => F.views.setSort("date") },
          { icon: "sort", label: L("מיון לפי גודל", "Sort by size"), run: () => F.views.setSort("size") },
          { sep: true },
          { icon: "refresh", label: L("רענון", "Refresh"), run: () => D.refresh() },
        ], e)}>${ic("more")}</button>`}
      </div>
    </header>`;
  }

  /* ── bottom tabs and the add button (phone) ───────────────────────────── */
  function Tabs() {
    const route = F.useStore((s) => s.route);
    const tabs = [PLACES[0], PLACES[1], MEDIA[0], MEDIA[1]];
    return html`<nav class="fx-tabs" aria-label=${L("ניווט ראשי", "Main navigation")}>
      ${tabs.map((p) => html`<a class=${"tab" + (isOn(p, route) ? " on" : "")} data-place=${placeOf(p)} title=${L(p.he, p.en)} href=${F.BASE + F.pathOf(p)} onClick=${(e) => { e.preventDefault(); F.go(p); }}>
        <span class="pill">${ic(p.icon)}</span><span>${p.tab ? L(p.tab[0], p.tab[1]) : L(p.he, p.en)}</span></a>`)}
      <button class="tab" data-place="more" onClick=${() => set({ drawer: true })}><span class="pill">${ic("menu")}</span><span>${L("עוד", "More")}</span></button>
    </nav>`;
  }

  /* ── the frame ────────────────────────────────────────────────────────── */
  function Frame() {
    const root = hooks.useRef(), content = hooks.useRef();
    const size = F.useStore((s) => s.size);
    const route = F.useStore((s) => s.route);
    const drawer = F.useStore((s) => s.drawer);
    const hasPlayer = F.useStore((s) => s.player.index >= 0 && s.player.queue.length > 0);
    const upH = F.useStore((s) => s.upH || 0);
    const selecting = F.useStore((s) => s.sel.length > 0);
    const [veil, setVeil] = hooks.useState(false);

    /* a box too small for the app — under 300 tall, or under 560×440 — is a widget (widget.js): the
       phone (taller) and the console's own window (628×567) stay the whole app */
    hooks.useLayoutEffect(() => {
      const touch = matchMedia("(pointer: coarse)").matches;
      const ro = new ResizeObserver(() => {
        const r = root.current.getBoundingClientRect();
        const w = r.width < 760 ? "n" : r.width < 1100 ? "m" : "w", h = r.height < 560 ? "s" : "t";
        const tiny = r.height < 300 || (r.width < 560 && r.height < 440);
        const s = state.size;
        if (w === s.w && h === s.h && touch === s.touch && tiny === !!s.tiny) return;
        // what the widget cannot show must not act unseen: a selection (Delete), the drawer
        set({ size: { w, h, touch, tiny }, ...(tiny && !s.tiny ? { sel: [], drawer: false, searching: false } : {}) });
      });
      ro.observe(root.current);
      return () => ro.disconnect();
    }, []);
    hooks.useLayoutEffect(() => {
      const el = content.current;
      if (!el) return;
      const co = new ResizeObserver(() => {
        const cw = el.clientWidth;
        el.dataset.cw = cw < 420 ? "xs" : cw < 640 ? "s" : cw < 900 ? "m" : "l";
      });
      co.observe(el);
      return () => co.disconnect();
    }, [size.tiny]);
    hooks.useEffect(() => { D.loadList(); }, [route.view, route.id, route.q]);
    /* the office's notices sit above what is at the bottom of this app (tabs, player, the queue) — in a
       widget they come from the top (files.css body[data-tiny]): the bottom is the widget's buttons */
    hooks.useEffect(() => {
      const narrow = size.w === "n";
      const lift = (narrow ? (size.h === "s" ? 52 : 64) : 0) + (hasPlayer ? (narrow ? 66 : 72) : 0) + (upH && narrow ? upH + 8 : 0);
      document.body.style.setProperty("--tell-lift", lift + "px");
      document.body.dataset.w = size.w;
      if (size.tiny) document.body.dataset.tiny = ""; else delete document.body.dataset.tiny;
    }, [size.w, size.h, size.tiny, hasPlayer, upH]);
    /* a file dropped in from the computer — anywhere on the app */
    hooks.useEffect(() => {
      let depth = 0;
      const isFiles = (e) => [...(e.dataTransfer && e.dataTransfer.types || [])].includes("Files");
      const enter = (e) => { if (!isFiles(e)) return; e.preventDefault(); depth++; setVeil(true); };
      const over = (e) => { if (isFiles(e)) e.preventDefault(); };
      const leave = (e) => { if (!isFiles(e)) return; if (--depth <= 0) { depth = 0; setVeil(false); } };
      const drop = async (e) => { if (!isFiles(e)) return; e.preventDefault(); depth = 0; setVeil(false); F.upload.enqueue(await F.upload.fromDrop(e.dataTransfer)); };
      const paste = (e) => { const f = [...(e.clipboardData && e.clipboardData.files || [])]; if (f.length && !e.target.closest("input,textarea")) { e.preventDefault(); F.upload.enqueue(f); } };
      addEventListener("dragenter", enter); addEventListener("dragover", over); addEventListener("dragleave", leave); addEventListener("drop", drop);
      document.addEventListener("paste", paste); document.addEventListener("keydown", F.views.onKey);
      return () => { removeEventListener("dragenter", enter); removeEventListener("dragover", over); removeEventListener("dragleave", leave);
        removeEventListener("drop", drop); document.removeEventListener("paste", paste); document.removeEventListener("keydown", F.views.onKey); };
    }, []);
    const narrow = size.w === "n";
    const where = state.route.view === "folder" ? (D.folderPath(state.route.id).slice(-1)[0] || {}).name || L("הקבצים שלי", "My files") : L("הקבצים שלי", "My files");
    return html`<div class=${"fx" + (hasPlayer ? " has-player" : "")} ref=${root} data-w=${size.w} data-h=${size.h}
      data-touch=${size.touch ? "" : null} data-selecting=${selecting ? "" : null} data-tiny=${size.tiny ? "" : null}>
      ${size.tiny ? html`<${F.widget.Widget} />` : html`
      <${Side} />
      ${narrow && html`<div class=${"fx-scrim" + (drawer ? " on" : "")} onClick=${() => set({ drawer: false })}></div>`}
      <main class="fx-main">
        <${Top} />
        <div class="fx-body">
          <section class="fx-content" ref=${content} tabIndex="-1" aria-live="polite"
            onClick=${(e) => { if (e.target === e.currentTarget && state.sel.length) set({ sel: [] }); }}
            onContextMenu=${(e) => { if (e.target === e.currentTarget && state.route.view === "folder") { e.preventDefault(); addMenu(e, state.route.id || ""); } }}>
            <${F.NewVersion} />
            <${F.views.Content} />
          </section>
          <${U.Details} />
        </div>
      </main>
      <${F.player.PlayerBar} />
      ${narrow && html`<${Tabs} />`}`}
      <${F.upload.UploadPanel} />
      <${F.widget.Publish} />
      <${F.upload.Pickers} />
      <${U.Menu} />
      <${U.MoveDialog} />
      <${F.viewer.Viewer} />
      ${veil && html`<div class="drop-veil"><div>${ic("upload")}${L("שחררו כדי להעלות אל ", "Drop to upload to ")}«${where}»</div></div>`}
    </div>`;
  }

  /* ── start ────────────────────────────────────────────────────────────── */
  async function boot() {
    // the same page opened under /rec is «הקלטות» (its own tile; the server marks the surface)
    if (document.documentElement.dataset.surface === "recorder" && F.recorder) return F.recorder.boot();
    set({ route: F.parse() });
    addEventListener("popstate", () => set({ route: F.parse(), viewer: null, menu: null }));
    render(html`<${Frame} />`, document.getElementById("app"));
    document.getElementById("app").removeAttribute("aria-busy");
    try { await D.loadFolders(); } catch (e) { /* the list says why */ }
    D.loadList(true); D.loadStorage(); D.loadOpenWith(); D.watch();
    const r = state.route;
    if (r.view === "folder" && r.file) {
      const wait = setInterval(() => {
        if (state.list.loading) return;
        clearInterval(wait);
        const i = state.list.files.findIndex((x) => x.id === r.file);
        if (i >= 0) F.viewer.open(state.list.files, i);
      }, 120);
    }
  }
  F.boot = boot;
  F.shell = { PLACES, MEDIA, TITLES, addMenu };
})();
