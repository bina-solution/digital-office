/* views.js — what fills the content area. Files as a list or a grid (Drive, Finder), photos as a
   timeline of justified rows (Google Photos), music as a library with a play-all (Spotify),
   videos as a wall of posters (YouTube), and home as quick access. One selection model for all,
   mouse or finger (Google Photos, OneDrive, every phone): a click or a tap OPENS; the circle on an
   item, ctrl / shift, or a long press SELECTS; once something is selected a click adds or removes;
   right-click is the item's own menu; the keyboard everywhere (arrows, Enter, Space, Delete, F2,
   ctrl+A). */
(function () {
  "use strict";
  const { html, hooks, state, set, L, ic, fmtSize, fmtWhen, fmtMonth, fmtDur, asDate, contentUrl } = F;
  const T = F.types, U = F.ui;

  /* ── open, select ──────────────────────────────────────────────────────── */
  function open(it, list) {
    if (it.kind === "folder") return F.go({ view: "folder", id: it.id });
    const items = (list || state.list.files).filter((x) => x.kind !== "folder");
    F.viewer.open(items.length ? items : [it], Math.max(0, items.findIndex((x) => x.id === it.id)));
  }
  const allItems = () => [...state.list.folders, ...sorted(state.list.files)];
  function pick(it, e) {
    const all = allItems().map((x) => x.id);
    if (e && (e.ctrlKey || e.metaKey)) {
      const sel = state.sel.includes(it.id) ? state.sel.filter((x) => x !== it.id) : [...state.sel, it.id];
      return set({ sel, anchor: it.id });
    }
    if (e && e.shiftKey && state.anchor) {
      const a = all.indexOf(state.anchor), b = all.indexOf(it.id);
      if (a >= 0 && b >= 0) return set({ sel: all.slice(Math.min(a, b), Math.max(a, b) + 1) });
    }
    set({ sel: [it.id], anchor: it.id });
  }
  const selected = () => allItems().filter((x) => state.sel.includes(x.id));

  /* a double-click is a click and then a second one on whatever the first opened — the second is dropped */
  let lastOpen = 0;
  function once(fn) { const t = Date.now(); if (t - lastOpen < 450) return; lastOpen = t; fn(); }
  const openOnce = (it, list) => once(() => open(it, list));
  /* a finger's long press also fires the browser's contextmenu: that press is already a selection */
  let touchAt = 0;
  /* a click: modifiers select, an open selection takes it, otherwise it opens */
  function clickItem(it, list, e) {
    if (e.ctrlKey || e.metaKey || e.shiftKey) return pick(it, e);
    if (state.sel.length) return pick(it, { ctrlKey: true });
    openOnce(it, list);
  }
  /* the menu of one item: the selection's when the item is part of it, otherwise its own — the
     selection stays as it was, and the item is marked while its menu is open */
  function itemMenu(it, e, title) {
    const many = state.sel.length > 1 && state.sel.includes(it.id);
    U.openMenu(U.actionsFor(many ? selected() : [it]), e, many ? undefined : title, it.id);
  }
  /* the circle that selects — on a card, a photo, a row's picture */
  function Check({ it, on }) {
    return html`<span class="check" role="checkbox" aria-checked=${!!on} aria-label=${L("בחירה", "Select")} title=${L("בחירה", "Select")}
      onClick=${(e) => { e.stopPropagation(); pick(it, { ctrlKey: true }); }}
      onPointerDown=${(e) => e.stopPropagation()} onDblClick=${(e) => e.stopPropagation()}>${ic("check", "sm")}</span>`;
  }

  /* one handler set per item: mouse, touch (long-press), keyboard, right-click, drag to move */
  function useItem(it, list) {
    const timer = hooks.useRef(), longed = hooks.useRef(false);
    return {
      onClick: (e) => {
        if (longed.current) { longed.current = false; return; }
        clickItem(it, list, e);
      },
      onContextMenu: (e) => { e.preventDefault(); if (Date.now() - touchAt > 1500) itemMenu(it, e); },
      onPointerDown: (e) => {
        if (e.pointerType !== "touch") return;
        touchAt = Date.now();
        clearTimeout(timer.current);
        timer.current = setTimeout(() => { longed.current = true; navigator.vibrate && navigator.vibrate(12); pick(it, { ctrlKey: true }); }, 480);
      },
      onPointerUp: () => clearTimeout(timer.current), onPointerCancel: () => clearTimeout(timer.current),
      onPointerMove: (e) => { if (e.pointerType === "touch" && Math.abs(e.movementY) + Math.abs(e.movementX) > 6) clearTimeout(timer.current); },
      draggable: !state.size.touch && state.route.view !== "trash",
      onDragStart: (e) => {
        const ids = state.sel.includes(it.id) ? state.sel : [it.id];
        if (!state.sel.includes(it.id)) set({ sel: [it.id] });
        e.dataTransfer.setData("application/x-files", JSON.stringify(ids));
        e.dataTransfer.effectAllowed = "move";
      },
      ...(it.kind === "folder" ? dropTarget(it.id) : {}),
      tabIndex: 0, "data-id": it.id,
    };
  }
  /* a folder (row, card, crumb, side entry) takes items dragged onto it */
  function dropTarget(folderId) {
    return {
      onDragOver: (e) => { if ([...e.dataTransfer.types].includes("application/x-files")) { e.preventDefault(); e.currentTarget.classList.add("drop"); } },
      onDragLeave: (e) => e.currentTarget.classList.remove("drop"),
      onDrop: (e) => {
        e.currentTarget.classList.remove("drop");
        const raw = e.dataTransfer.getData("application/x-files"); if (!raw) return;
        e.preventDefault(); e.stopPropagation();
        const ids = JSON.parse(raw).filter((x) => x !== folderId);
        const items = allItems().filter((x) => ids.includes(x.id));
        if (items.length) F.data.move(items, folderId);
      },
    };
  }

  /* ── sorting: folders first, then by what the person chose ──────────────── */
  function sorted(files) {
    const { key, dir } = state.sort || { key: "date", dir: -1 };
    const cmp = key === "name" ? (a, b) => a.name.localeCompare(b.name, "he", { numeric: true })
      : key === "size" ? (a, b) => (Number(a.size) || 0) - (Number(b.size) || 0)
      : (a, b) => String(a.created || a.last || "").localeCompare(String(b.created || b.last || ""));
    return [...files].sort((a, b) => cmp(a, b) * dir);
  }
  function setSort(key) {
    const s = state.sort || {};
    const sort = { key, dir: s.key === key ? -s.dir : key === "name" ? 1 : -1 };
    F.localSet("sort", sort); set({ sort });
  }

  /* ── rows and cards ────────────────────────────────────────────────────── */
  function Row({ it, list }) {
    const sel = F.useStore((s) => s.sel.includes(it.id));
    const ctx = F.useStore((s) => !!(s.menu && s.menu.for === it.id));
    const playing = F.useStore((s) => { const c = s.player.queue[s.player.index]; return !!(c && c.id === it.id && s.player.playing); });
    const h = useItem(it, list);
    const folder = it.kind === "folder";
    const meta = folder ? (it.count ? F.count(it.count, ["קובץ אחד", "1 file"], ["קבצים", "files"]) : "") : [fmtSize(it.size), fmtWhen(it.created)].filter(Boolean).join(" · ");
    return html`<div class=${"lr" + (sel ? " sel" : "") + (ctx ? " ctx" : "") + (playing ? " playing" : "")} role="row" aria-selected=${sel} ...${h}>
      <div class=${"th" + (folder ? " folder" : "")} title=${it.system ? L("האפליקציה «" + it.system + "» שומרת לכאן", "The «" + it.system + "» app saves here") : null}><${U.Thumb} it=${it} size=${96} />
        ${T.isMedia(it) === "audio" && html`<span class="play">${ic(playing ? "pause" : "play", "sm")}</span>`}
        <${Check} it=${it} on=${sel} /></div>
      <div class="name">
        <div class="fname"><${U.Name} name=${it.name} />${it.starred && html`<span class="star" title=${L("מסומן בכוכב", "Starred")}>${ic("star", "sm")}</span>`}
</div>
        <div class="meta">${meta}</div>
      </div>
      <div class="c-date">${fmtWhen(it.created || it.last)}</div>
      <div class="c-size num">${folder ? "" : fmtSize(it.size)}</div>
      <button class="rowact" title=${L("פעולות", "Actions")} aria-label=${L("פעולות", "Actions")}
        onClick=${(e) => { e.stopPropagation(); itemMenu(it, e, it.name); }}>${ic("more", "sm")}</button>
    </div>`;
  }
  function Card({ it, list }) {
    const sel = F.useStore((s) => s.sel.includes(it.id));
    const ctx = F.useStore((s) => !!(s.menu && s.menu.for === it.id));
    const h = useItem(it, list);
    const folder = it.kind === "folder", k = T.kindOf(it);
    const doc = T.info(it).doc;
    const dur = (it.meta || {}).duration;
    return html`<div class=${"card" + (sel ? " sel" : "") + (ctx ? " ctx" : "")} role="gridcell" aria-selected=${sel} ...${h}>
      <div class=${"pic" + (folder ? " folder" : doc ? " doc" : "")}><${U.Thumb} it=${it} size=${384} big />
        ${dur ? html`<span class="badge">${k === "video" ? ic("play", "sm") : ic("music", "sm")}${fmtDur(dur)}</span>` : ""}
        <${Check} it=${it} on=${sel} /></div>
      <div class="body"><div class="fname"><${U.Name} name=${it.name} /></div>
        <button class="rowact" title=${L("פעולות", "Actions")} onClick=${(e) => { e.stopPropagation(); itemMenu(it, e, it.name); }}>${ic("more", "sm")}</button></div>
      <div class="sub">${folder ? (it.count ? F.count(it.count, ["קובץ אחד", "1 file"], ["קבצים", "files"]) : L("תיקייה", "Folder")) : [fmtSize(it.size), fmtWhen(it.created)].join(" · ")}</div>
    </div>`;
  }

  /* render a long folder in steps — the first 240 at once, the rest as the person scrolls */
  function useWindow(n) {
    const [count, setCount] = hooks.useState(240), end = hooks.useRef();
    hooks.useEffect(() => setCount(240), [n === 0]);
    hooks.useEffect(() => {
      if (!end.current || count >= n) return;
      const io = new IntersectionObserver((e) => e[0].isIntersecting && setCount((c) => c + 240), { rootMargin: "600px" });
      io.observe(end.current);
      return () => io.disconnect();
    }, [count, n]);
    return [count, html`<div ref=${end} aria-hidden="true"></div>`];
  }

  function Items({ folders, files }) {
    const layout = F.useStore((s) => s.layout);
    const sort = F.useStore((s) => s.sort);
    const items = [...folders, ...sorted(files)];
    const [count, sentinel] = useWindow(items.length);
    const shown = items.slice(0, count);
    const arrow = (k) => sort && sort.key === k ? ic(sort.dir > 0 ? "arrow-up" : "arrow-down", "sm") : null;
    if (layout === "grid") return html`<div class="grid" role="grid">${shown.map((it) => html`<${Card} key=${it.id} it=${it} list=${files} />`)}</div>${sentinel}`;
    return html`<div class="list" role="grid" aria-rowcount=${items.length}>
      <div class="lh" role="row">
        <span></span>
        <button onClick=${() => setSort("name")}>${L("שם", "Name")}${arrow("name")}</button>
        <button class="c-date" onClick=${() => setSort("date")}>${L("נוצר", "Created")}${arrow("date")}</button>
        <button class="c-size" onClick=${() => setSort("size")}>${L("גודל", "Size")}${arrow("size")}</button>
        <span></span>
      </div>
      ${shown.map((it) => html`<${Row} key=${it.id} it=${it} list=${files} />`)}
    </div>${sentinel}`;
  }

  /* ── the views ─────────────────────────────────────────────────────────── */
  function Loading() { return html`<${U.Skeleton} rows=${9} />`; }
  function Failed({ error }) {
    return html`<${U.Empty} icon="alert" bad title=${L("לא הצלחנו לטעון", "Could not load")} text=${error}>
      <button class="btn" onClick=${() => F.data.loadList(true)}>${ic("refresh", "sm")}${L("נסו שוב", "Try again")}</button></${U.Empty}>`;
  }
  function FolderView() {
    const list = F.useStore((s) => s.list);
    const route = F.useStore((s) => s.route);
    if (list.loading && !list.files.length && !list.folders.length) return html`<${Loading} />`;
    if (list.error && !list.files.length) return html`<${Failed} error=${list.error} />`;
    if (!list.files.length && !list.folders.length) {
      if (route.view === "trash") return html`<${U.Empty} icon="trash" title=${L("האשפה ריקה", "Trash is empty")} text=${L("מה שמועבר לאשפה מחכה כאן עד שמוחקים אותו לצמיתות.", "What you move to trash waits here until it is deleted forever.")} />`;
      if (route.view === "starred") return html`<${U.Empty} icon="star" title=${L("עוד אין כאן כוכבים", "No starred items yet")} text=${L("סמנו קובץ או תיקייה בכוכב כדי למצוא אותם מהר.", "Star a file or folder to find it fast.")} />`;
      if (route.view === "recent") return html`<${U.Empty} icon="clock" title=${L("עוד לא נפתח כלום", "Nothing opened yet")} text=${L("קבצים שתפתחו יופיעו כאן.", "Files you open appear here.")} />`;
      if (route.view === "search") return html`<${U.Empty} icon="search" title=${(route.q || "").trim().length < 2 ? L("מה לחפש?", "What to look for?") : L("לא נמצא כלום", "Nothing found")}
        text=${(route.q || "").trim().length < 2 ? L("הקלידו לפחות שני תווים.", "Type at least two characters.") : L("נסו מילה אחרת או חלק מהשם.", "Try another word or part of the name.")} />`;
      return html`<${U.Empty} icon="upload" title=${L("התיקייה ריקה", "This folder is empty")} text=${L("גררו לכאן קבצים או תיקיות, או העלו מהמכשיר.", "Drag files or folders here, or upload from your device.")}>
        <button class="btn primary" onClick=${() => F.upload.pick()}>${ic("upload", "sm")}${L("העלאת קבצים", "Upload files")}</button>
        <button class="btn" onClick=${() => F.data.newFolder(route.id || "")}>${ic("folder-plus", "sm")}${L("תיקייה חדשה", "New folder")}</button>
      </${U.Empty}>`;
    }
    return html`${route.view === "trash" && html`<div class="vbar"><span class="vcount">${L("פריטים באשפה נמחקים רק כשמוחקים אותם לצמיתות", "Items in trash are kept until deleted forever")}</span>
      <span class="grow"></span><button class="btn sm danger" onClick=${F.data.emptyTrash}>${ic("trash", "sm")}${L("ריקון האשפה", "Empty trash")}</button></div>`}
      <${Items} folders=${list.folders} files=${list.files} />`;
  }

  function HomeView() {
    const list = F.useStore((s) => s.list);
    const store = F.useStore((s) => s.storage);
    if (list.loading && !list.files.length && !list.folders.length) return html`<${Loading} />`;
    if (list.error && !list.files.length) return html`<${Failed} error=${list.error} />`;
    const recent = list.files.slice(0, 12);
    if (!recent.length && !list.folders.length) return html`<${U.Empty} icon="cloud" title=${L("ברוכים הבאים לקבצים", "Welcome to Files")}
      text=${L("כל הקבצים של העסק במקום אחד — מסמכים, תמונות, הקלטות, פגישות וסרטונים. גררו לכאן קבצים או העלו מהמכשיר.", "All the business's files in one place — documents, photos, recordings, meetings and videos. Drag files here or upload from your device.")}>
      <button class="btn primary" onClick=${() => F.upload.pick()}>${ic("upload", "sm")}${L("העלאת קבצים", "Upload files")}</button>
      <button class="btn" onClick=${() => F.upload.pick({ folder: true })}>${ic("folder-up", "sm")}${L("העלאת תיקייה", "Upload a folder")}</button></${U.Empty}>`;
    return html`
      ${recent.length > 0 && html`<div class="sect"><h2>${L("נוספו לאחרונה", "Recently added")}</h2>
        <button class="more" onClick=${() => F.go({ view: "recent" })}>${L("נפתחו לאחרונה", "Recently opened")}</button></div>
        <div class="strip">${recent.map((it) => html`<${Card} key=${it.id} it=${it} list=${recent} />`)}</div>`}
      ${list.folders.length > 0 && html`<div class="sect"><h2>${L("תיקיות", "Folders")}</h2>
        <button class="more" onClick=${() => F.go({ view: "folder", id: "" })}>${L("כל הקבצים", "All files")}</button></div>
        <div class="folders">${list.folders.map((f) => html`<${FolderCard} key=${f.id} it=${f} />`)}</div>`}
      ${store && html`<div class="sect"><h2>${L("אחסון", "Storage")}</h2></div>
        <div class="vcount">${F.count(store.files, ["קובץ אחד", "1 file"], ["קבצים", "files"])} · ${fmtSize(store.used)}${store.trash_files ? L(` · ${fmtSize(store.trash_used)} באשפה`, ` · ${fmtSize(store.trash_used)} in trash`) : ""}</div>`}`;
  }
  function FolderCard({ it }) {
    const sel = F.useStore((s) => s.sel.includes(it.id));
    const ctx = F.useStore((s) => !!(s.menu && s.menu.for === it.id));
    const h = useItem(it);
    return html`<div class=${"fcard" + (sel ? " sel" : "") + (ctx ? " ctx" : "")} ...${h}>
      <div class="th folder">${ic(it.system ? "folder-input" : "folder", "sm")}</div>
      <div class="t"><b><bdi>${it.name}</bdi></b><span>${it.count ? F.count(it.count, ["קובץ אחד", "1 file"], ["קבצים", "files"]) : L("ריקה", "Empty")}</span></div>
      <button class="rowact show" title=${L("פעולות", "Actions")} onClick=${(e) => { e.stopPropagation(); itemMenu(it, e, it.name); }}>${ic("more", "sm")}</button>
    </div>`;
  }

  /* photos and videos, by month, each in its own shape */
  function PhotosView() {
    const list = F.useStore((s) => s.list);
    const sel = F.useStore((s) => s.sel);
    if (list.loading && !list.files.length) return html`<${Loading} />`;
    if (list.error && !list.files.length) return html`<${Failed} error=${list.error} />`;
    if (!list.files.length) return html`<${U.Empty} icon="image" title=${L("עוד אין כאן תמונות", "No photos yet")}
      text=${L("תמונות וסרטונים מכל התיקיות יופיעו כאן לפי תאריך.", "Photos and videos from every folder appear here by date.")}>
      <button class="btn primary" onClick=${() => F.upload.pick()}>${ic("upload", "sm")}${L("העלאת תמונות", "Upload photos")}</button></${U.Empty}>`;
    const files = [...list.files].sort((a, b) => String(b.taken || b.created).localeCompare(String(a.taken || a.created)));
    const groups = [];
    files.forEach((it) => { const m = fmtMonth(it.taken || it.created); if (!groups.length || groups[groups.length - 1].m !== m) groups.push({ m, items: [] }); groups[groups.length - 1].items.push(it); });
    return html`${groups.map((g) => html`<div key=${g.m}><div class="month">${g.m}</div><div class="just">${g.items.map((it) => {
      const m = it.meta || {}, r = m.w && m.h ? Math.max(0.4, Math.min(3, m.w / m.h)) : T.kindOf(it) === "video" ? 16 / 9 : 4 / 3;
      const h = tileHandlers(it, files);
      return html`<div key=${it.id} class=${"tile" + (sel.includes(it.id) ? " sel" : "")} style=${"--r:" + r.toFixed(3)} ...${h}>
        <${U.Thumb} it=${it} size=${512} />
        ${T.kindOf(it) === "video" && html`<span class="badge">${ic("play", "sm")}${m.duration ? fmtDur(m.duration) : ""}</span>`}
        <${Check} it=${it} on=${sel.includes(it.id)} /></div>`;
    })}</div></div>`)}`;
  }
  /* the tiles are drawn in a loop, not as components, so they take their handlers through a plain
     helper — and keep their long press here, one finger at a time */
  let pressTimer = 0, pressed = null;
  function tileHandlers(it, list) {
    const stop = () => clearTimeout(pressTimer);
    return {
      onClick: (e) => { if (pressed === it.id) { pressed = null; return; } clickItem(it, list, e); },
      onContextMenu: (e) => { e.preventDefault(); if (Date.now() - touchAt > 1500) itemMenu(it, e); },
      onPointerDown: (e) => {
        if (e.pointerType !== "touch") return;
        touchAt = Date.now(); stop();
        pressTimer = setTimeout(() => { pressed = it.id; navigator.vibrate && navigator.vibrate(12); pick(it, { ctrlKey: true }); }, 480);
      },
      onPointerUp: stop, onPointerCancel: stop,
      onPointerMove: (e) => { if (e.pointerType === "touch" && Math.abs(e.movementY) + Math.abs(e.movementX) > 6) stop(); },
      tabIndex: 0, "data-id": it.id, onKeyDown: (e) => e.key === "Enter" && open(it, list),
    };
  }

  function MusicView() {
    const list = F.useStore((s) => s.list);
    const p = F.useStore((s) => s.player);
    const menuFor = F.useStore((s) => s.menu && s.menu.for);
    if (list.loading && !list.files.length) return html`<${Loading} />`;
    if (list.error && !list.files.length) return html`<${Failed} error=${list.error} />`;
    if (!list.files.length) return html`<${U.Empty} icon="music" title=${L("עוד אין כאן אודיו", "No audio yet")}
      text=${L("הקלטות, שירים ופודקאסטים מכל התיקיות יופיעו כאן.", "Recordings, songs and podcasts from every folder appear here.")} />`;
    const tracks = [...list.files].sort((a, b) => String(b.created).localeCompare(String(a.created)));
    const total = tracks.reduce((s, t) => s + ((t.meta || {}).duration || 0), 0);
    const cur = p.queue[p.index];
    return html`<div class="hero"><div class="art">${ic("music", "xl")}</div>
      <div><h1>${L("כל האודיו", "All audio")}</h1>
        <div class="vcount">${F.count(tracks.length, ["פריט אחד", "1 item"], ["פריטים", "items"])}${total ? " · " + fmtDur(total) : ""}</div>
        <div class="acts">
          <button class="play-fab" title=${L("ניגון הכל", "Play all")} onClick=${() => F.player.play(tracks, 0)}>${ic("play")}</button>
          <button class="btn" onClick=${() => { const q = [...tracks].sort(() => Math.random() - 0.5); F.player.play(q, 0); }}>${ic("shuffle", "sm")}${L("ערבוב", "Shuffle")}</button>
        </div></div></div>
      <div class="tracks">${tracks.map((t, i) => {
        const m = t.meta || {}, on = cur && cur.id === t.id;
        return html`<div key=${t.id} class=${"tr" + (on ? " playing" : "") + (menuFor === t.id ? " ctx" : "")}
          onClick=${() => once(() => (on ? F.player.toggle() : F.player.play(tracks, i)))}
          onContextMenu=${(e) => { e.preventDefault(); U.openMenu(U.actionsFor([t]), e, t.name, t.id); }}>
          <span class="n num">${on ? html`<span class=${"eq" + (p.playing ? "" : " paused")}><i></i><i></i><i></i></span>` : i + 1}</span>
          <div class="cover"><${F.player.Cover} it=${t} /></div>
          <div class="t"><b><bdi>${F.player.titleOf(t)}</bdi></b><span>${m.artist || fmtWhen(t.created)}</span></div>
          <div class="alb">${m.album || fmtSize(t.size)}</div>
          <div class="dur num">${m.duration ? fmtDur(m.duration) : ""}</div>
          <button class="rowact show" title=${on && p.playing ? L("השהיה", "Pause") : L("ניגון", "Play")}
            onClick=${(e) => { e.stopPropagation(); on ? F.player.toggle() : F.player.play(tracks, i); }}>${ic(on && p.playing ? "pause" : "play", "sm")}</button>
        </div>`;
      })}</div>`;
  }

  function VideosView() {
    const list = F.useStore((s) => s.list);
    const menuFor = F.useStore((s) => s.menu && s.menu.for);
    if (list.loading && !list.files.length) return html`<${Loading} />`;
    if (list.error && !list.files.length) return html`<${Failed} error=${list.error} />`;
    if (!list.files.length) return html`<${U.Empty} icon="film" title=${L("עוד אין כאן סרטונים", "No videos yet")}
      text=${L("סרטונים והקלטות פגישות מכל התיקיות יופיעו כאן.", "Videos and meeting recordings from every folder appear here.")} />`;
    const vids = [...list.files].sort((a, b) => String(b.created).localeCompare(String(a.created)));
    return html`<div class="vids">${vids.map((v) => html`<div key=${v.id} class=${"vcard" + (menuFor === v.id ? " ctx" : "")} tabIndex="0" onClick=${() => openOnce(v, vids)}
        onKeyDown=${(e) => e.key === "Enter" && open(v, vids)} onContextMenu=${(e) => { e.preventDefault(); U.openMenu(U.actionsFor([v]), e, v.name, v.id); }}>
      <div class="pic"><${U.Thumb} it=${v} size=${640} big />${(v.meta || {}).duration ? html`<span class="badge">${fmtDur(v.meta.duration)}</span>` : ""}</div>
      <b title=${v.name}>${F.splitName(v.name)[0]}</b><span>${[fmtSize(v.size), fmtWhen(v.created)].join(" · ")}</span>
    </div>`)}</div>`;
  }

  function OpenView() {
    const route = F.useStore((s) => s.route);
    hooks.useEffect(() => {
      F.api("api/file/" + encodeURIComponent(route.file)).then((d) => F.viewer.open([d.file], 0))
        .catch((e) => F.tell(e.message, "bad"));
    }, [route.file]);
    return html`<${Loading} />`;
  }

  const BY_VIEW = { home: HomeView, folder: FolderView, recent: FolderView, starred: FolderView, trash: FolderView, search: FolderView,
    photos: PhotosView, music: MusicView, videos: VideosView, open: OpenView };
  function Content() {
    const route = F.useStore((s) => s.route);
    const View = BY_VIEW[route.view] || HomeView;
    return html`<${View} />`;
  }

  /* the keyboard, for whatever is shown */
  function onKey(e) {
    // a widget (widget.js) has no selection to act on — its frame keeps its own keys
    if (state.size.tiny || state.viewer || state.menu || state.dialog || document.querySelector(".bask")) return;
    if (e.target.closest("input,textarea,select,[contenteditable]")) return;
    const all = allItems(), sel = selected(), D = F.data;
    const idx = all.findIndex((x) => x.id === (state.anchor || state.sel[0]));
    const move = (d) => { const n = all[Math.max(0, Math.min(all.length - 1, (idx < 0 ? -1 : idx) + d))]; if (n) { set({ sel: [n.id], anchor: n.id }); const el = document.querySelector(`[data-id="${CSS.escape(n.id)}"]`); el && el.focus(); } };
    if (e.key === "ArrowDown") { e.preventDefault(); move(state.layout === "grid" ? gridCols() : 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(state.layout === "grid" ? -gridCols() : -1); }
    else if (e.key === "ArrowLeft" && state.layout === "grid") { e.preventDefault(); move(document.dir === "rtl" ? 1 : -1); }
    else if (e.key === "ArrowRight" && state.layout === "grid") { e.preventDefault(); move(document.dir === "rtl" ? -1 : 1); }
    else if (e.key === "Enter" && sel.length === 1) { e.preventDefault(); open(sel[0]); }
    else if (e.key === " " && sel.length === 1 && sel[0].kind !== "folder") { e.preventDefault(); open(sel[0]); }
    else if ((e.key === "Delete" || e.key === "Backspace") && sel.length && !sel.some((x) => x.system)) { e.preventDefault(); state.route.view === "trash" ? D.destroy(sel) : D.trash(sel); }
    else if (e.key === "F2" && sel.length === 1 && !sel[0].system) { e.preventDefault(); D.rename(sel[0]); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") { e.preventDefault(); set({ sel: all.map((x) => x.id) }); }
    else if (e.key === "Escape" && state.sel.length) set({ sel: [] });
    else if (e.key.toLowerCase() === "i" && !e.ctrlKey && !e.metaKey) set({ details: !state.details });
  }
  function gridCols() {
    const g = document.querySelector(".grid"); if (!g) return 1;
    return getComputedStyle(g).gridTemplateColumns.split(" ").length || 1;
  }

  F.views = { open, pick, selected, Content, onKey, dropTarget, sorted, setSort };
})();
