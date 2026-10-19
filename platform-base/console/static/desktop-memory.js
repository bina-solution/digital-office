/* desktop-memory.js — working memory for desktop mode (desktop.js).
 *
 * Associative memory (ai/context/console-desktop-working-memory.md §3.A): every window's PLACE — the
 * module and the route it shows — owns a collection, a panel attached to the window that takes
 * whatever is dragged, pasted or picked into it, keeps it (IndexedDB, this browser), and remembers
 * where each item came from. With "מקור" on, hovering an item marks its source window and the exact
 * passage in it (E7). Items can be grouped into folders, and a folder or a selection turned into a
 * derived item — a table, a summary — that keeps its parents (A6–A7, done locally, without AI).
 *
 * Episodic memory (§3.E): content-free attention signals per place — how long it held focus, how far
 * it was scrolled, how many keystrokes, copies, pastes and submissions, never WHAT they were — kept in
 * this browser for 30 days (Q1–Q5), and condensed without AI into anchors, a story, and a timeline
 * that lays "you" over the system lanes any-concurrency already records. A snapshot of the open
 * windows is kept with it, so any moment on the timeline can be restored as a workspace.
 *
 * Written clean-room: the reference prototypes carry no licence, so no code or data is taken.
 */
(function () {
  "use strict";
  const D = window.BinaDesktop;
  if (!D || !D.wm) return;
  const wm = D.wm;

  const DAY = 86400000, KEEP_MS = 30 * DAY, IDLE_MS = 5 * 60000, GAP_MS = 20 * 60000;
  const h = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const hm = t => new Date(t).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
  const dur = ms => { const m = Math.round(ms / 60000); return m < 1 ? "פחות מדקה" : m < 60 ? m + " דק׳" : Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0") + " שע׳"; };
  const placeOf = w => (w && !w.native ? w.mid + (w.route || "") : null);
  const nameOf = mid => { const m = wm.modById(mid); return m ? m.name : mid; };
  const iconOf = mid => { const m = wm.modById(mid); return wm.icon(m ? m.icon : "app"); };

  // ── storage ──────────────────────────────────────────────────────────────────────────────
  let dbp = null, dbFailed = false;
  function db() {
    if (dbp) return dbp;
    dbp = new Promise((res, rej) => {
      let r;
      try { r = indexedDB.open("bina-desktop", 1); } catch (e) { rej(e); return; }
      r.onupgradeneeded = () => {
        const d = r.result;
        if (!d.objectStoreNames.contains("items")) d.createObjectStore("items", { keyPath: "id" }).createIndex("owner", "owner");
        if (!d.objectStoreNames.contains("blobs")) d.createObjectStore("blobs", { keyPath: "id" });
        if (!d.objectStoreNames.contains("visits")) d.createObjectStore("visits", { keyPath: "id" }).createIndex("t0", "t0");
        if (!d.objectStoreNames.contains("snaps")) d.createObjectStore("snaps", { keyPath: "t" });
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    dbp.catch(() => { if (!dbFailed) { dbFailed = true; wm.toast("אחסון הדפדפן אינו זמין · האוסף וההיסטוריה לא יישמרו"); } });
    return dbp;
  }
  const req = r => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  const os = async (name, mode) => (await db()).transaction(name, mode || "readonly").objectStore(name);
  const put = async (name, v) => req((await os(name, "readwrite")).put(v));
  const del = async (name, k) => req((await os(name, "readwrite")).delete(k));
  const get = async (name, k) => req((await os(name)).get(k));
  const byOwner = async owner => req((await os("items")).index("owner").getAll(owner));
  const visitsSince = async t => req((await os("visits")).index("t0").getAll(IDBKeyRange.lowerBound(t)));
  const allSnaps = async () => req((await os("snaps")).getAll());
  async function purgeOld() {
    const cut = Date.now() - KEEP_MS;
    try {
      const s = await os("visits", "readwrite");
      const cur = s.index("t0").openCursor(IDBKeyRange.upperBound(cut));
      cur.onsuccess = () => { const c = cur.result; if (c) { c.delete(); c.continue(); } };
      const ss = await os("snaps", "readwrite");
      ss.delete(IDBKeyRange.upperBound(cut));
    } catch (e) { /* storage unavailable: nothing to purge */ }
  }

  // ══ ASSOCIATIVE: the collection attached to a window ═════════════════════════════════════
  const panels = new Map();   // window id -> panel state
  let lastDrag = null;        // what a page started dragging: {mid, route, place, title, text, url, t}

  function addTitleButton(w) {
    const slot = w.el.querySelector(".dk-end");
    if (!slot || slot.querySelector(".dk-tbtn")) return;
    const b = h("button", "dk-tbtn", wm.icon("box") + '<span class="n"></span>');
    b.type = "button";
    b.title = "אוסף: פריטים שנאספו למקום הזה";
    b.setAttribute("aria-label", "אוסף");
    b.addEventListener("pointerdown", e => e.stopPropagation());   // not a title-bar drag
    b.addEventListener("dblclick", e => e.stopPropagation());
    b.addEventListener("click", e => { e.stopPropagation(); togglePanel(w); });
    slot.appendChild(b);
    refreshCount(w);
  }
  async function refreshCount(w) {
    const b = w.el.querySelector(".dk-tbtn .n");
    if (!b) return;
    let n = 0;
    try { n = (await byOwner(placeOf(w))).filter(it => !it.parent).length; } catch (e) { /* storage unavailable */ }
    b.textContent = n ? String(n) : "";
    w.el.querySelector(".dk-tbtn").classList.toggle("has", n > 0);
  }

  function togglePanel(w, force) {
    let p = panels.get(w.id);
    const open = force != null ? force : !(p && p.open);
    if (!p) p = makePanel(w);
    p.open = open;
    p.el.classList.toggle("open", open);
    w.el.classList.toggle("with-col", open);
    if (open) { placePanel(w); loadPanel(w); setTimeout(() => p.list.focus({ preventScroll: true }), 50); }
    else unreveal();
  }

  function makePanel(w) {
    const el = h("aside", "dk-col");
    el.setAttribute("aria-label", "אוסף");
    el.innerHTML =
      '<header><b>אוסף</b><span class="place"></span><span class="grow"></span>' +
      '<button type="button" data-a="grab" title="הוספת הטקסט המסומן בחלון הזה">' + wm.icon("plus") + "</button>" +
      '<button type="button" data-a="trace" title="מקור: ריחוף על פריט מסמן מאיפה הגיע">מקור</button>' +
      '<button type="button" data-a="acts" title="פעולות על הפריטים המסומנים">פעולות</button>' +
      '<button type="button" data-a="close" title="סגירת האוסף">' + wm.icon("x") + "</button></header>" +
      '<nav class="crumbs"></nav><div class="list" tabindex="0" role="listbox" aria-multiselectable="true"></div>' +
      '<div class="hint">גררו לכאן טקסט, קישור, תמונה או קובץ, או הדביקו (Ctrl V)</div>' +
      '<section class="view"></section>';
    const p = { el, w, open: false, owner: placeOf(w), items: [], sel: new Set(), folder: null, trace: false, viewing: null,
      list: el.querySelector(".list"), crumbs: el.querySelector(".crumbs"), view: el.querySelector(".view") };
    panels.set(w.id, p);
    el.addEventListener("pointerdown", e => e.stopPropagation());   // the panel is not the window's drag handle
    el.querySelector("header").addEventListener("click", e => {
      const b = e.target.closest("button[data-a]");
      if (!b) return;
      const a = b.dataset.a;
      if (a === "close") togglePanel(w, false);
      else if (a === "grab") grabSelection(w);
      else if (a === "trace") { p.trace = !p.trace; b.classList.toggle("on", p.trace); if (!p.trace) unreveal(); wm.toast(p.trace ? "מקור פעיל · רחפו על פריט" : "מקור כבוי"); }
      else if (a === "acts") actionsMenu(w, b);
    });
    // drop anything here: page selections and links, images, files from the computer
    el.addEventListener("dragover", e => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; el.classList.add("over"); });
    el.addEventListener("dragleave", e => { if (!el.contains(e.relatedTarget)) el.classList.remove("over"); });
    el.addEventListener("drop", e => { el.classList.remove("over"); onDrop(e, w); });
    p.list.addEventListener("paste", e => onPaste(e, w));
    p.list.addEventListener("keydown", e => {
      if ((e.key === "Delete" || e.key === "Backspace") && p.sel.size) { e.preventDefault(); removeItems(w, [...p.sel]); }
      else if (e.key === "Enter" && p.sel.size === 1) { e.preventDefault(); openItem(w, [...p.sel][0]); }
      else if (e.key === "Escape") togglePanel(w, false);
    });
    p.list.addEventListener("pointerleave", () => unreveal());
    w.el.appendChild(el);
    return p;
  }

  // the panel sits on the side of its window that faces the middle of the screen, and moves with it
  function placePanel(w) {
    const p = panels.get(w.id);
    if (!p || !p.open) return;
    const G = wm.geom();
    const right = w.cx < G.W / 2 - 40;
    p.el.classList.toggle("side-r", right);
    p.el.classList.toggle("side-l", !right);
  }

  async function loadPanel(w) {
    const p = panels.get(w.id);
    if (!p) return;
    p.owner = placeOf(w);
    p.el.querySelector(".place").textContent = w.titleFull || nameOf(w.mid);
    try { p.items = (await byOwner(p.owner)).sort((a, b) => b.created - a.created); } catch (e) { p.items = []; }
    if (p.folder && !p.items.some(it => it.id === p.folder)) p.folder = null;
    p.sel.forEach(id => { if (!p.items.some(it => it.id === id)) p.sel.delete(id); });
    renderList(w);
    refreshCount(w);
  }

  const KIND_ICON = { text: "file-text", link: "link", image: "palette", file: "box", folder: "folder", table: "grid", note: "sparkles" };
  const KIND_HE = { text: "קטע", link: "קישור", image: "תמונה", file: "קובץ", folder: "תיקייה", table: "טבלה", note: "סיכום" };

  function renderList(w) {
    const p = panels.get(w.id);
    const shown = p.items.filter(it => (it.parent || null) === p.folder);
    const folder = p.folder && p.items.find(it => it.id === p.folder);
    p.crumbs.innerHTML = folder ? '<button type="button" data-up="1">' + wm.icon("back") + " כל האוסף</button><b>" + esc(folder.title) + "</b>" : "";
    const up = p.crumbs.querySelector("[data-up]");
    if (up) up.onclick = () => { p.folder = null; renderList(w); };
    p.list.innerHTML = shown.length ? "" : '<div class="empty">' + (folder ? "התיקייה ריקה" : "האוסף ריק · אספו לכאן חומר שאינכם מטפלים בו עכשיו") + "</div>";
    shown.forEach(it => {
      const row = h("div", "it" + (p.sel.has(it.id) ? " sel" : ""));
      row.dataset.id = it.id;
      row.draggable = true;
      row.setAttribute("role", "option");
      const kids = it.kind === "folder" ? p.items.filter(x => x.parent === it.id).length : 0;
      const src = it.src && it.src.mid ? '<button type="button" class="src" data-src="1" title="פתיחת המקור">' + iconOf(it.src.mid) + esc(nameOf(it.src.mid)) + "</button>"
        : it.src && it.src.kind === "os" ? '<span class="src">מהמחשב</span>' : it.src && it.src.kind === "clip" ? '<span class="src">מההדבקה</span>' : "";
      row.innerHTML = '<span class="ic">' + wm.icon(KIND_ICON[it.kind] || "app") + "</span>" +
        '<div class="tx"><b></b><small>' + esc(KIND_HE[it.kind] || "") + (kids ? " · " + kids + " פריטים" : "") + " · " + hm(it.created) + " " + src + "</small></div>";
      row.querySelector("b").textContent = it.title || "";
      row.addEventListener("click", e => {
        if (e.target.closest("[data-src]")) { openSource(it); return; }
        if (e.metaKey || e.ctrlKey) { if (p.sel.has(it.id)) p.sel.delete(it.id); else p.sel.add(it.id); }
        else if (e.shiftKey && p.sel.size) {
          const ids = shown.map(x => x.id), a = ids.indexOf([...p.sel].pop()), b = ids.indexOf(it.id);
          ids.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(id => p.sel.add(id));
        } else { p.sel.clear(); p.sel.add(it.id); }
        p.list.querySelectorAll(".it").forEach(r => r.classList.toggle("sel", p.sel.has(r.dataset.id)));
      });
      row.addEventListener("dblclick", () => openItem(w, it.id));
      row.addEventListener("pointerenter", () => { if (p.trace) reveal(it); });
      row.addEventListener("dragstart", e => dragOut(e, it));
      p.list.appendChild(row);
    });
    if (p.viewing && !p.items.some(it => it.id === p.viewing)) closeView(w);
  }

  // ── getting things in ──
  function takeDrag() {
    const d = lastDrag;
    lastDrag = null;
    return d && Date.now() - d.t < 30000 ? d : null;
  }
  const srcOf = d => (d ? { mid: d.mid, route: d.route, place: d.place, title: d.title, text: (d.text || "").slice(0, 600) } : null);
  const firstLine = s => { const l = String(s || "").trim().split(/\n/).find(x => x.trim()) || ""; return l.length > 90 ? l.slice(0, 88) + "…" : l; };

  async function onDrop(e, w) {
    e.preventDefault();
    const dt = e.dataTransfer, drag = takeDrag(), src = srcOf(drag);
    const files = Array.from(dt.files || []);
    if (files.length) { for (const f of files) await addFile(w, f, src || { kind: "os" }); return; }
    const uri = (dt.getData("text/uri-list") || "").split(/\r?\n/).find(l => l && l[0] !== "#") || "";
    const text = dt.getData("text/plain") || "";
    const html = dt.getData("text/html") || "";
    if (uri && (!text.trim() || text.trim() === uri.trim() || (drag && drag.url === uri && !drag.text))) {
      const img = /^<img\b/i.test(html.trim()) || /\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(uri);
      await addItem(w, { kind: img ? "image" : "link", url: uri, title: (drag && drag.text && drag.text.trim()) || uri, src });
    } else if (text.trim()) {
      await addItem(w, { kind: "text", text, title: firstLine(text), src });
    }
  }
  async function onPaste(e, w) {
    const cd = e.clipboardData;
    if (!cd) return;
    e.preventDefault();
    const files = Array.from(cd.files || []);
    if (files.length) { for (const f of files) await addFile(w, f, { kind: "clip" }); return; }
    const text = cd.getData("text/plain");
    if (!text.trim()) return;
    if (/^https?:\/\/\S+$/.test(text.trim())) await addItem(w, { kind: "link", url: text.trim(), title: text.trim(), src: { kind: "clip" } });
    else await addItem(w, { kind: "text", text, title: firstLine(text), src: { kind: "clip" } });
  }
  // A2 "park it, don't process it": the passage selected in this window's own page
  async function grabSelection(w) {
    let text = "";
    try { const d = w.frame && w.frame.contentDocument; text = d && d.getSelection ? d.getSelection().toString() : ""; } catch (e) { /* not ours */ }
    if (!text.trim()) { wm.toast("סמנו טקסט בחלון, ואז לחצו על הפלוס"); return; }
    await addItem(w, { kind: "text", text, title: firstLine(text), src: { mid: w.mid, route: w.route || "", place: placeOf(w), title: w.titleFull, text: text.slice(0, 600) } });
  }
  async function addFile(w, f, src) {
    if (f.size > 25 * 1024 * 1024) { wm.toast("הקובץ " + f.name + " גדול מ-25MB ולא נשמר"); return; }
    const blob = uid();
    try { await put("blobs", { id: blob, data: f }); } catch (e) { return; }
    await addItem(w, { kind: /^image\//.test(f.type) ? "image" : "file", title: f.name, mime: f.type, size: f.size, blob, src });
  }
  async function addItem(w, it) {
    const p = panels.get(w.id) || makePanel(w);
    const item = Object.assign({ id: uid(), owner: placeOf(w), parent: p.folder || null, created: Date.now() }, it);
    try { await put("items", item); } catch (e) { return null; }
    if (item.src && item.src.place) countClip(item.src.place);
    await loadPanel(w);
    p.sel.clear();
    p.sel.add(item.id);
    renderList(w);
    return item;
  }

  // ── getting things out: an item drags into any page like text does ──
  function dragOut(e, it) {
    const dt = e.dataTransfer;
    dt.effectAllowed = "copy";
    if (it.kind === "link" || it.kind === "image") { dt.setData("text/uri-list", it.url || ""); dt.setData("text/plain", it.url || ""); }
    else if (it.kind === "table") { dt.setData("text/plain", tableText(it)); dt.setData("text/html", tableHtml(it)); }
    else dt.setData("text/plain", it.text || it.title || "");
  }
  const tableText = it => (it.rows || []).map(r => r.join("\t")).join("\n");
  const tableHtml = it => "<table>" + (it.rows || []).map((r, i) => "<tr>" + r.map(c => (i ? "<td>" : "<th>") + esc(c) + (i ? "</td>" : "</th>")).join("") + "</tr>").join("") + "</table>";

  // ── two-up: an item beside the list, viewable and (for text) editable (A8) ──
  async function openItem(w, id) {
    const p = panels.get(w.id);
    const it = p && p.items.find(x => x.id === id);
    if (!it) return;
    if (it.kind === "folder") { p.folder = it.id; p.sel.clear(); renderList(w); return; }
    p.viewing = id;
    p.el.classList.add("two-up");
    const v = p.view;
    v.innerHTML = '<header><b></b><span class="grow"></span><button type="button" data-a="closeview" title="סגירה">' + wm.icon("x") + "</button></header><div class=\"vb\"></div>";
    v.querySelector("b").textContent = it.title || KIND_HE[it.kind];
    v.querySelector("[data-a=closeview]").onclick = () => closeView(w);
    const vb = v.querySelector(".vb");
    if (it.kind === "text" || it.kind === "note") {
      const ta = h("textarea");
      ta.value = it.text || "";
      let t = 0;
      ta.addEventListener("input", () => { clearTimeout(t); t = setTimeout(async () => { it.text = ta.value; it.title = firstLine(ta.value) || it.title; await put("items", it); loadPanel(w); }, 500); });
      vb.appendChild(ta);
    } else if (it.kind === "link") {
      vb.innerHTML = '<p class="url"></p><div class="row"><button type="button" class="btn sm">פתיחה</button></div>';
      vb.querySelector(".url").textContent = it.url;
      vb.querySelector("button").onclick = () => openUrl(it.url);
    } else if (it.kind === "image" || it.kind === "file") {
      const url = it.blob ? await blobUrl(it.blob) : it.url;
      if (it.kind === "image" && url) { const img = h("img"); img.src = url; img.alt = it.title || ""; vb.appendChild(img); }
      const meta = h("p", "meta");
      meta.textContent = (it.mime || "") + (it.size ? " · " + Math.round(it.size / 1024) + " KB" : "");
      vb.appendChild(meta);
      if (url && it.blob) { const a = h("a", "btn sm ghost", "שמירה במחשב"); a.href = url; a.download = it.title || "file"; vb.appendChild(a); }
    } else if (it.kind === "table") {
      vb.innerHTML = tableHtml(it);
    }
  }
  function closeView(w) {
    const p = panels.get(w.id);
    if (!p) return;
    p.viewing = null;
    p.el.classList.remove("two-up");
    p.view.innerHTML = "";
  }
  const blobUrls = new Map();
  async function blobUrl(id) {
    if (blobUrls.has(id)) return blobUrls.get(id);
    const b = await get("blobs", id).catch(() => null);
    if (!b || !b.data) return "";
    const u = URL.createObjectURL(b.data);
    blobUrls.set(id, u);
    return u;
  }
  // an app address opens as a window on this desktop; anything else in a new browser tab
  function openUrl(url) {
    try {
      const u = new URL(url, location.href);
      if (u.origin === location.origin) {
        const hm2 = /^#\/m\/([^/?#]+)([/?].*)?$/.exec(u.hash);
        if (hm2 && wm.modById(hm2[1])) { wm.openModule(wm.modById(hm2[1]), hm2[2] || ""); return; }
        const am = /^\/a\/([^/]+)\/?(.*)$/.exec(u.pathname);
        if (am) {
          const m = (typeof MODULES !== "undefined" ? MODULES : []).find(x => x.embed === "/a/" + am[1] + "/");
          if (m) { wm.openModule(m, (am[2] ? "/" + am[2] : "") + u.search); return; }
        }
      }
      window.open(u.href, "_blank", "noopener");
    } catch (e) { /* not a URL */ }
  }
  function openSource(it) {
    const m = it.src && it.src.mid && wm.modById(it.src.mid);
    if (m) wm.openModule(m, it.src.route || "");
  }

  // ── actions on a selection (A6–A7, local: no model is called) ──
  function actionsMenu(w, btn) {
    const p = panels.get(w.id);
    const old = p.el.querySelector(".acts");
    if (old) { old.remove(); return; }
    const sel = p.items.filter(it => p.sel.has(it.id));
    const pool = sel.length ? sel : p.items.filter(it => (it.parent || null) === p.folder && it.kind !== "folder");
    const m = h("div", "acts");
    const add = (label, fn, dis) => { const b = h("button", "", ""); b.type = "button"; b.textContent = label; b.disabled = !!dis; b.onclick = () => { m.remove(); fn(); }; m.appendChild(b); };
    add("קיבוץ לתיקייה" + (sel.length ? " (" + sel.length + ")" : ""), () => groupFolder(w, sel), !sel.length);
    add("טבלה מהפריטים", () => deriveTable(w, pool), !pool.length);
    add("סיכום הפריטים", () => deriveNote(w, pool), !pool.length);
    add("ארגון לפי מקור", () => organizeBySource(w), p.items.length < 2);
    add("העתקה כטקסט", () => copyText(pool), !pool.length);
    add("פתיחת הקישורים", () => pool.filter(it => it.kind === "link").forEach(it => openUrl(it.url)), !pool.some(it => it.kind === "link"));
    add("מחיקה" + (sel.length ? " (" + sel.length + ")" : ""), () => removeItems(w, [...p.sel]), !sel.length);
    p.el.appendChild(m);
    const r = btn.getBoundingClientRect(), pr = p.el.getBoundingClientRect(), k = pr.width / p.el.offsetWidth || 1;
    m.style.top = ((r.bottom - pr.top) / k + 4) + "px";
  }
  async function groupFolder(w, sel) {
    const p = panels.get(w.id);
    const n = p.items.filter(it => it.kind === "folder").length + 1;
    const f = await addItem(w, { kind: "folder", title: "תיקייה " + n });
    if (!f) return;
    for (const it of sel) { it.parent = f.id; await put("items", it); }
    await loadPanel(w);
  }
  async function deriveTable(w, pool) {
    const rows = [["כותרת", "סוג", "מקור", "נאסף"]].concat(pool.map(it => [it.title || it.url || "", KIND_HE[it.kind] || "", it.src && it.src.mid ? nameOf(it.src.mid) : "", hm(it.created)]));
    await addItem(w, { kind: "table", title: "טבלה · " + pool.length + " פריטים", rows, parents: pool.map(it => it.id) });
  }
  async function deriveNote(w, pool) {
    const byKind = {}, bySrc = {};
    pool.forEach(it => { byKind[KIND_HE[it.kind]] = (byKind[KIND_HE[it.kind]] || 0) + 1; const s = it.src && it.src.mid ? nameOf(it.src.mid) : "ללא מקור"; bySrc[s] = (bySrc[s] || 0) + 1; });
    const text = "סיכום של " + pool.length + " פריטים\n\n" +
      "לפי סוג: " + Object.entries(byKind).map(([k, v]) => k + " " + v).join(", ") + "\n" +
      "לפי מקור: " + Object.entries(bySrc).map(([k, v]) => k + " " + v).join(", ") + "\n\n" +
      pool.map(it => "• " + (it.title || it.url || "")).join("\n");
    await addItem(w, { kind: "note", text, title: "סיכום · " + pool.length + " פריטים", parents: pool.map(it => it.id) });
  }
  async function organizeBySource(w) {
    const p = panels.get(w.id);
    const loose = p.items.filter(it => !it.parent && it.kind !== "folder");
    const groups = {};
    loose.forEach(it => { const k = it.src && it.src.mid ? nameOf(it.src.mid) : it.src && it.src.kind === "os" ? "מהמחשב" : "אחר"; (groups[k] = groups[k] || []).push(it); });
    for (const k of Object.keys(groups)) {
      if (groups[k].length < 2) continue;
      const f = await addItem(w, { kind: "folder", title: k });
      if (!f) continue;
      for (const it of groups[k]) { it.parent = f.id; await put("items", it); }
    }
    p.folder = null;
    await loadPanel(w);
  }
  function copyText(pool) {
    const text = pool.map(it => it.kind === "table" ? tableText(it) : (it.text || it.url || it.title || "")).join("\n\n");
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => wm.toast("הועתק"), () => wm.toast("ההעתקה נחסמה בדפדפן"));
  }
  async function removeItems(w, ids) {
    const p = panels.get(w.id);
    for (const id of ids) {
      const it = p.items.find(x => x.id === id);
      if (!it) continue;
      if (it.kind === "folder") for (const k of p.items.filter(x => x.parent === id)) { k.parent = null; await put("items", k); }
      if (it.blob) await del("blobs", it.blob).catch(() => {});
      await del("items", id).catch(() => {});
    }
    p.sel.clear();
    await loadPanel(w);
  }

  // ── provenance on hover (E7): the source window is marked, and the passage in it ──
  let revealed = null;
  function reveal(it) {
    unreveal();
    if (!it.src || !it.src.mid) return;
    const wins = wm.wins();
    const sw = wins.find(x => x.mid === it.src.mid && (x.route || "") === (it.src.route || "")) || wins.find(x => x.mid === it.src.mid);
    if (!sw) { wm.toast("המקור (" + nameOf(it.src.mid) + ") סגור · לחיצה על שם המקור פותחת אותו"); return; }
    sw.el.classList.add("dk-origin");
    revealed = { w: sw, doc: null };
    if (!it.src.text || !sw.frame) return;
    let d;
    try { d = sw.frame.contentDocument; } catch (e) { return; }
    const range = d && findText(d, it.src.text);
    if (!range) return;
    revealed.doc = d;
    const win = d.defaultView;
    if (win && win.CSS && win.CSS.highlights && win.Highlight) {
      if (!d.getElementById("dk-origin-style")) {
        const st = d.createElement("style");
        st.id = "dk-origin-style";
        // «look here» — the palette's lime where the page in the window carries it, the system's own
        // highlight where it is somebody else's page
        st.textContent = "::highlight(dk-origin){background:var(--lime-line,Highlight);color:inherit}";
        (d.head || d.documentElement).appendChild(st);
      }
      win.CSS.highlights.set("dk-origin", new win.Highlight(range));
    }
    const el = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  function unreveal() {
    if (!revealed) return;
    revealed.w.el.classList.remove("dk-origin");
    try { if (revealed.doc && revealed.doc.defaultView.CSS.highlights) revealed.doc.defaultView.CSS.highlights.delete("dk-origin"); } catch (e) { /* gone */ }
    revealed = null;
  }
  // the first place the passage's opening words occur in the page's text, as a Range
  function findText(d, text) {
    const needle = String(text).replace(/\s+/g, " ").trim().slice(0, 60);
    if (needle.length < 3 || !d.body) return null;
    const walker = d.createTreeWalker(d.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let flat = "", n;
    while ((n = walker.nextNode())) {
      const t = n.nodeValue.replace(/\s+/g, " ");
      nodes.push({ n, at: flat.length, len: t.length, raw: n.nodeValue });
      flat += t;
    }
    const i = flat.indexOf(needle);
    if (i < 0) return null;
    const pos = k => {
      const e = nodes.find(x => k >= x.at && k <= x.at + x.len) || nodes[nodes.length - 1];
      // map the collapsed offset back into the raw node text
      let raw = 0, col = 0;
      while (raw < e.raw.length && col < k - e.at) { const ws = /\s/.test(e.raw[raw]); raw++; if (!ws || !/\s/.test(e.raw[raw] || "")) col++; }
      return { node: e.n, off: Math.min(raw, e.raw.length) };
    };
    const a = pos(i), b = pos(i + needle.length);
    const r = d.createRange();
    try { r.setStart(a.node, a.off); r.setEnd(b.node, b.off); } catch (e) { return null; }
    return r;
  }

  // ══ EPISODIC: attention signals per place ══════════════════════════════════════════════
  let cur = null, lastActive = Date.now(), idleT = 0, snapT = 0, lastSnapKey = "";
  const recording = () => wm.prefs().history !== false;

  function startVisit(w, how) {
    if (!recording() || !w || w.native || document.hidden) return;
    cur = { id: uid(), wid: w.id, place: placeOf(w), mid: w.mid, route: w.route || "", title: w.titleFull || nameOf(w.mid),
      t0: Date.now(), t1: 0, focus: 0, scroll: 0, typing: 0, copy: 0, cut: 0, paste: 0, submit: 0, clip: 0, how: how || "switch", from: lastPlace };
  }
  let lastPlace = null;
  function endVisit() {
    if (!cur) return;
    const v = cur;
    cur = null;
    v.t1 = Date.now();
    v.focus = v.t1 - v.t0;
    lastPlace = v.place;
    if (v.focus >= 1500) put("visits", v).catch(() => {});
  }
  function countClip(place) {
    if (cur && cur.place === place) cur.clip++;
    else pendingClips[place] = (pendingClips[place] || 0) + 1;
  }
  const pendingClips = {};
  function touch() {
    const was = Date.now() - lastActive > IDLE_MS;
    lastActive = Date.now();
    if (was && !cur) { const f = wm.focused(); if (f) startVisit(f, "return"); }
  }

  function instrumentPage(w, d) {
    const mine = () => cur && cur.wid === w.id;
    let st = 0;
    d.addEventListener("scroll", () => {
      touch();
      if (!mine() || st) return;
      st = setTimeout(() => {
        st = 0;
        try {
          const se = d.scrollingElement || d.documentElement;
          const max = se.scrollHeight - se.clientHeight;
          if (max > 40 && cur) cur.scroll = Math.max(cur.scroll, Math.round(100 * se.scrollTop / max));
        } catch (e) { /* ignore */ }
      }, 400);
    }, true);
    d.addEventListener("keydown", e => { touch(); if (mine() && !e.ctrlKey && !e.metaKey && !e.altKey && e.key && e.key.length === 1) cur.typing++; }, true);
    d.addEventListener("pointerdown", touch, true);
    d.addEventListener("copy", () => { if (mine()) cur.copy++; }, true);
    d.addEventListener("cut", () => { if (mine()) cur.cut++; }, true);
    d.addEventListener("paste", () => { if (mine()) cur.paste++; }, true);
    d.addEventListener("submit", () => { if (mine()) cur.submit++; }, true);
    d.addEventListener("dragstart", e => {
      let text = "", url = "";
      try { text = d.getSelection ? d.getSelection().toString() : ""; } catch (x) { /* ignore */ }
      const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
      if (a) { url = a.href; if (!text) text = a.textContent || ""; }
      const img = e.target && e.target.tagName === "IMG" ? e.target : null;
      if (img) url = img.src;
      lastDrag = { mid: w.mid, route: w.route || "", place: placeOf(w), title: w.titleFull, text, url, t: Date.now() };
    }, true);
  }

  // a record of which windows were open where, so a moment can be restored as a workspace
  function snapSoon() {
    clearTimeout(snapT);
    snapT = setTimeout(async () => {
      if (!recording() || !wm.root()) return;
      const wins = wm.wins().map(w => ({ mid: w.mid, native: w.native || null, route: w.route || "", cx: Math.round(w.cx), cy: Math.round(w.cy), w: w.w, h: w.h }));
      const key = JSON.stringify(wins.map(x => [x.mid, x.route, Math.round(x.cx / 40), Math.round(x.cy / 40)]));
      if (key === lastSnapKey || !wins.length) return;
      lastSnapKey = key;
      put("snaps", { t: Date.now(), W: wm.geom().W, wins }).catch(() => {});
    }, 6000);
  }

  // ── wiring to the window manager ──
  wm.on("mount", () => {
    purgeOld();
    lastActive = Date.now();
    clearInterval(idleT);
    idleT = setInterval(() => { if (cur && Date.now() - lastActive > IDLE_MS) endVisit(); }, 30000);
  });
  wm.on("unmount", () => { endVisit(); clearInterval(idleT); panels.clear(); unreveal(); });
  wm.on("open", w => { w.justOpened = true; if (!w.native) addTitleButton(w); snapSoon(); });
  wm.on("close", w => { if (cur && cur.wid === w.id) endVisit(); panels.delete(w.id); snapSoon(); });
  wm.on("focus", w => {
    endVisit();
    startVisit(w, w.justOpened ? "open" : "switch");
    w.justOpened = false;
    if (cur && pendingClips[cur.place]) { cur.clip += pendingClips[cur.place]; delete pendingClips[cur.place]; }
    snapSoon();
  });
  wm.on("route", w => {
    if (cur && cur.wid === w.id) { endVisit(); startVisit(w, "navigate"); }
    const p = panels.get(w.id);
    if (p) { p.folder = null; p.sel.clear(); closeView(w); if (p.open) loadPanel(w); }
    refreshCount(w);
    snapSoon();
  });
  wm.on("load", (w, d) => { instrumentPage(w, d); refreshCount(w); });
  wm.on("pos", w => { placePanel(w); snapSoon(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) endVisit(); else { const f = wm.focused(); if (f && !cur) startVisit(f, "return"); } });
  window.addEventListener("pointerdown", touch, true);
  window.addEventListener("keydown", touch, true);
  window.addEventListener("pagehide", endVisit);

  // ══ THE MEMORY WINDOW ═════════════════════════════════════════════════════════════════
  const MV = { tab: "story", hours: 6 };

  // one score per place: attention that was actually paid (focus, gated by how far the page was
  // read), what was taken from it and put into it, and how many other places lead through it
  function aggregate(visits) {
    const P = new Map();
    const seq = visits.slice().sort((a, b) => a.t0 - b.t0);
    seq.forEach(v => {
      let p = P.get(v.place);
      if (!p) { p = { place: v.place, mid: v.mid, route: v.route, title: v.title, n: 0, focus: 0, scroll: 0, typing: 0, copy: 0, cut: 0, paste: 0, submit: 0, clip: 0, first: v.t0, last: v.t1 || v.t0, nb: new Set() }; P.set(v.place, p); }
      p.n++;
      p.focus += v.focus || ((v.t1 || Date.now()) - v.t0);
      p.scroll = Math.max(p.scroll, v.scroll || 0);
      ["typing", "copy", "cut", "paste", "submit", "clip"].forEach(k => { p[k] += v[k] || 0; });
      p.last = Math.max(p.last, v.t1 || Date.now());
      if (v.title) p.title = v.title;
    });
    for (let i = 1; i < seq.length; i++) {
      const a = P.get(seq[i - 1].place), b = P.get(seq[i].place);
      if (a && b && a !== b) { a.nb.add(b.place); b.nb.add(a.place); }
    }
    P.forEach(p => {
      const read = 0.35 + 0.65 * Math.min(1, (p.scroll || 0) / 100);
      p.score = (p.focus / 60000) * read + 2.5 * (p.copy + p.cut) + 2 * p.paste + 4 * p.submit + 3 * p.clip + p.typing / 40 + 1.5 * Math.min(p.nb.size, 5) + 0.4 * (p.n - 1);
    });
    const list = [...P.values()].sort((a, b) => b.score - a.score);
    const k = clamp(Math.round(Math.sqrt(list.length) * 2), Math.min(3, list.length), 9);
    list.forEach((p, i) => { p.anchor = i < k; p.tier = i < Math.max(1, Math.round(k / 3)) ? 3 : i < k ? 2 : 1; });
    return list;
  }
  function sessions(visits) {
    const seq = visits.slice().sort((a, b) => a.t0 - b.t0), out = [];
    seq.forEach(v => {
      const s = out[out.length - 1];
      if (!s || v.t0 - s.t1 > GAP_MS) out.push({ t0: v.t0, t1: v.t1 || Date.now(), visits: [v] });
      else { s.visits.push(v); s.t1 = Math.max(s.t1, v.t1 || Date.now()); }
    });
    return out;
  }
  async function loadVisits(hours) {
    let vs = [];
    try { vs = await visitsSince(Date.now() - hours * 3600000); } catch (e) { /* storage unavailable */ }
    if (cur) vs.push(Object.assign({}, cur, { t1: Date.now(), focus: Date.now() - cur.t0 }));
    return vs;
  }
  function openPlace(p) {
    const m = wm.modById(p.mid);
    if (m) wm.openModule(m, p.route || "");
  }

  function renderMemory(body) {
    body.innerHTML =
      '<div class="dk-mem"><header class="mh">' +
      '<nav class="tabs" role="tablist">' + [["story", "סיפור"], ["anchors", "עוגנים"], ["timeline", "ציר זמן"], ["records", "רשומות"]]
        .map(([k, l]) => '<button type="button" role="tab" data-t="' + k + '">' + l + "</button>").join("") + "</nav>" +
      '<span class="grow"></span><nav class="range">' + [[1, "שעה"], [6, "6 שעות"], [24, "יממה"], [168, "שבוע"]]
        .map(([k, l]) => '<button type="button" data-r="' + k + '">' + l + "</button>").join("") + "</nav></header>" +
      '<div class="mb"></div></div>';
    const root = body.querySelector(".dk-mem"), mb = root.querySelector(".mb");
    const paint = () => {
      root.querySelectorAll("[data-t]").forEach(b => { b.classList.toggle("on", b.dataset.t === MV.tab); b.setAttribute("aria-selected", String(b.dataset.t === MV.tab)); });
      root.querySelectorAll("[data-r]").forEach(b => b.classList.toggle("on", +b.dataset.r === MV.hours));
      const f = { story: viewStory, anchors: viewAnchors, timeline: viewTimeline, records: viewRecords }[MV.tab];
      f(mb).catch(e => { mb.innerHTML = '<div class="empty">לא ניתן להציג · ' + esc(e && e.message) + "</div>"; });
    };
    root.addEventListener("click", e => {
      const t = e.target.closest("[data-t]"), r = e.target.closest("[data-r]");
      if (t) { MV.tab = t.dataset.t; paint(); }
      if (r) { MV.hours = +r.dataset.r; paint(); }
    });
    paint();
    const iv = setInterval(() => { if (!body.isConnected) { clearInterval(iv); return; } if (MV.tab !== "records") paint(); }, 30000);
  }

  // E6: where the time went, one sentence per stretch of work
  async function viewStory(mb) {
    const vs = await loadVisits(MV.hours);
    if (!vs.length) { mb.innerHTML = '<div class="empty">' + (recording() ? "עדיין אין היסטוריה בטווח הזה. עבדו בחלונות, והסיפור ייבנה כאן." : "רישום ההיסטוריה כבוי (לשונית רשומות).") + "</div>"; return; }
    const ss = sessions(vs).reverse();
    mb.innerHTML = '<p class="lead">המסלול של העבודה, מקובץ לרצפים. רצף נחתך אחרי ' + GAP_MS / 60000 + " דקות בלי פעילות. בכל רצף מוצגים המקומות שקיבלו את רוב תשומת הלב.</p>";
    ss.forEach(s => {
      const places = aggregate(s.visits);
      const main = places.filter(p => p.anchor).sort((a, b) => a.first - b.first);
      const card = h("section", "story");
      const flows = [];
      const seq = s.visits.slice().sort((a, b) => a.t0 - b.t0);
      seq.forEach((v, i) => { if (v.copy || v.cut) { const to = seq.slice(i + 1).find(x => x.paste && x.place !== v.place); if (to) flows.push([v, to]); } });
      card.innerHTML = '<header><b>' + hm(s.t0) + " – " + hm(s.t1) + "</b><small>" + dur(s.t1 - s.t0) + " · " + places.length + " מקומות · " + s.visits.length + " מעברים</small></header>";
      const chain = h("div", "chain");
      main.forEach((p, i) => {
        if (i) chain.appendChild(h("span", "arrow", "←"));
        const c = h("button", "chip " + wm.colorFor(p.mid), iconOf(p.mid) + "<b></b><small></small>");
        c.type = "button";
        c.querySelector("b").textContent = nameOf(p.mid);
        c.querySelector("small").textContent = (p.title && p.title !== nameOf(p.mid) ? p.title.replace(nameOf(p.mid) + " · ", "") + " · " : "") + dur(p.focus);
        c.title = p.title || "";
        c.onclick = () => openPlace(p);
        chain.appendChild(c);
      });
      card.appendChild(chain);
      if (flows.length) {
        const fl = h("p", "flows");
        fl.textContent = "הועבר חומר: " + flows.slice(0, 4).map(([a, b]) => "מ" + nameOf(a.mid) + " אל " + nameOf(b.mid)).join(" · ");
        card.appendChild(fl);
      }
      mb.appendChild(card);
    });
  }

  // E4: fifty stops condensed to a handful of anchors, with the rest as satellites
  async function viewAnchors(mb) {
    const vs = await loadVisits(MV.hours);
    const P = aggregate(vs);
    if (!P.length) { mb.innerHTML = '<div class="empty">אין עדיין מקומות בטווח הזה.</div>'; return; }
    const W = Math.max(640, mb.clientWidth - 24), H = Math.max(420, mb.clientHeight - 90);
    const anchors = P.filter(p => p.anchor).sort((a, b) => a.first - b.first);
    const sats = P.filter(p => !p.anchor);
    // anchors along the time they first mattered, right to left like the page
    anchors.forEach((p, i) => { p.x = W - 90 - (anchors.length > 1 ? i * (W - 180) / (anchors.length - 1) : (W - 180) / 2); p.y = H / 2 + (i % 2 ? -1 : 1) * Math.min(90, H / 6); });
    sats.forEach(s => {
      const home = anchors.find(a => a.nb.has(s.place)) || anchors.reduce((b, a) => Math.abs(a.first - s.first) < Math.abs(b.first - s.first) ? a : b, anchors[0]);
      s.home = home;
    });
    const around = new Map();
    sats.forEach(s => { const l = around.get(s.home) || []; l.push(s); around.set(s.home, l); });
    around.forEach((l, a) => l.forEach((s, i) => { const ang = (i / l.length) * Math.PI * 2 - Math.PI / 2, r = 78 + (i % 2) * 18; s.x = a.x + Math.cos(ang) * r; s.y = a.y + Math.sin(ang) * r; }));
    const maxS = Math.max.apply(null, anchors.map(a => a.score)) || 1;
    let svg = '<svg class="anchors" viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="עוגנים">';
    // how work moved between anchors
    const seq = vs.slice().sort((a, b) => a.t0 - b.t0), of = pl => { const p = P.find(x => x.place === pl); return p && (p.anchor ? p : p.home); };
    const edges = new Map();
    for (let i = 1; i < seq.length; i++) {
      const a = of(seq[i - 1].place), b = of(seq[i].place);
      if (!a || !b || a === b) continue;
      const k = [a.place, b.place].sort().join("|");
      edges.set(k, { a, b, n: ((edges.get(k) || {}).n || 0) + 1 });
    }
    edges.forEach(e => { svg += '<line class="edge" x1="' + e.a.x + '" y1="' + e.a.y + '" x2="' + e.b.x + '" y2="' + e.b.y + '" stroke-width="' + Math.min(6, 1 + e.n) + '"/>'; });
    // where value was carried: a copy in one place, a paste in the next place that took one
    seq.forEach((v, i) => {
      if (!v.copy && !v.cut) return;
      const to = seq.slice(i + 1).find(x => x.paste && x.place !== v.place);
      const a = of(v.place), b = to && of(to.place);
      if (a && b && a !== b) svg += '<path class="flow" d="M' + a.x + " " + a.y + " Q " + (a.x + b.x) / 2 + " " + (Math.min(a.y, b.y) - 70) + " " + b.x + " " + b.y + '"/>';
    });
    sats.forEach(s => { svg += '<line class="tether" x1="' + s.home.x + '" y1="' + s.home.y + '" x2="' + s.x + '" y2="' + s.y + '"/><circle class="sat" cx="' + s.x + '" cy="' + s.y + '" r="7" data-p="' + esc(s.place) + '"><title>' + esc((s.title || nameOf(s.mid)) + " · " + dur(s.focus)) + "</title></circle>"; });
    anchors.forEach(a => {
      const k = 0.55 + 0.45 * a.score / maxS, w = 150 * k + 40, hh = 44 * k + 18;
      svg += '<g class="anchor t' + a.tier + '" data-p="' + esc(a.place) + '" transform="translate(' + (a.x - w / 2) + " " + (a.y - hh / 2) + ')">' +
        '<rect width="' + w + '" height="' + hh + '" rx="12"/><text x="' + w / 2 + '" y="' + (hh / 2 - 2) + '" text-anchor="middle">' + esc(nameOf(a.mid)) + "</text>" +
        '<text class="sub" x="' + w / 2 + '" y="' + (hh / 2 + 14) + '" text-anchor="middle">' + esc(dur(a.focus) + (a.copy + a.paste ? " · " + (a.copy + a.cut) + "↑ " + a.paste + "↓" : "")) + "</text>" +
        "<title>" + esc((a.title || "") + "\nמיקוד " + dur(a.focus) + " · גלילה " + a.scroll + "% · הקלדות " + a.typing + " · העתקות " + (a.copy + a.cut) + " · הדבקות " + a.paste + " · שליחות " + a.submit + " · נאסף " + a.clip) + "</title></g>";
    });
    svg += "</svg>";
    mb.innerHTML = '<p class="lead">' + P.length + " מקומות צומצמו ל-" + anchors.length + " עוגנים, בחשבון פשוט ובלי בינה מלאכותית: זמן מיקוד כפול עומק הגלילה, העתקות, הדבקות, שליחות, פריטים שנאספו ומספר המקומות שעוברים דרכם. קו מקווקו מסמן חומר שהועתק ממקום אחד והודבק במקום אחר.</p>" + svg;
    mb.querySelectorAll("[data-p]").forEach(n => n.addEventListener("click", () => { const p = P.find(x => x.place === n.getAttribute("data-p")); if (p) openPlace(p); }));
  }

  // "you" over the system: the lanes of this desktop on the same ruler as any-concurrency's
  async function viewTimeline(mb) {
    const hours = MV.hours, now = Date.now(), t0 = now - hours * 3600000;
    const vs = (await loadVisits(hours)).filter(v => (v.t1 || now) >= t0);
    const places = aggregate(vs), tierOf = pl => { const p = places.find(x => x.place === pl); return p ? p.tier : 1; };
    let spans = [], sysNote = "";
    const hasAC = (typeof MODULES !== "undefined" ? MODULES : []).some(m => m.embed === "/a/any-concurrency/");
    if (hasAC) {
      try {
        const r = await fetch("/a/any-concurrency/api/spans?hours=" + hours);
        if (r.ok) spans = await r.json(); else sysNote = "כל מקביל לא ענה (" + r.status + ")";
      } catch (e) { sysNote = "כל מקביל אינו זמין"; }
    } else sysNote = "כל מקביל אינו מותקן, ולכן אין נתיבי מערכת";
    const W = Math.max(700, mb.clientWidth - 24), LBL = 150, X0 = 12, X1 = W - LBL - 8, LANE = 26;
    const x = t => X0 + (X1 - X0) * (t - t0) / (now - t0);
    const mids = [...new Set(vs.map(v => v.mid))];
    const srcs = {};
    (Array.isArray(spans) ? spans : []).forEach(s => { if (!s || !(s.s > 0)) return; const e = s.e || s.s; if (e < t0) return; (srcs[s.src] = srcs[s.src] || []).push(s); });
    const srcNames = Object.keys(srcs).sort((a, b) => srcs[b].length - srcs[a].length);
    const H = 40 + (mids.length + 1) * LANE + 30 + (srcNames.length + 1) * LANE + 20;
    let svg = '<svg class="tl" viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '">';
    // ruler
    const stepMin = hours <= 1 ? 10 : hours <= 6 ? 60 : hours <= 24 ? 180 : 1440;
    const first = Math.ceil(t0 / (stepMin * 60000)) * stepMin * 60000;
    for (let t = first; t <= now; t += stepMin * 60000) {
      const lbl = stepMin >= 1440 ? new Date(t).toLocaleDateString("he-IL", { weekday: "short", day: "numeric" }) : hm(t);
      svg += '<line class="tick" x1="' + x(t) + '" y1="22" x2="' + x(t) + '" y2="' + H + '"/><text class="tickl" x="' + x(t) + '" y="16" text-anchor="middle">' + lbl + "</text>";
    }
    let y = 34;
    svg += '<text class="grp" x="' + (W - 8) + '" y="' + (y + 14) + '" text-anchor="end">אתה</text>';
    y += LANE;
    mids.forEach(mid => {
      svg += '<text class="lane" x="' + (W - 8) + '" y="' + (y + 17) + '" text-anchor="end">' + esc(nameOf(mid)) + '</text><line class="lanel" x1="' + X0 + '" y1="' + (y + LANE - 2) + '" x2="' + X1 + '" y2="' + (y + LANE - 2) + '"/>';
      vs.filter(v => v.mid === mid).forEach(v => {
        const a = x(Math.max(v.t0, t0)), b = Math.max(a + 2, x(v.t1 || now)), tier = tierOf(v.place), hh = (LANE - 6) * (tier === 3 ? 1 : tier === 2 ? 0.72 : 0.45);
        svg += '<rect class="blk ' + wm.colorFor(mid) + '" data-v="' + esc(v.id) + '" x="' + a + '" y="' + (y + LANE - 3 - hh) + '" width="' + (b - a) + '" height="' + hh + '" rx="3"><title>' +
          esc((v.title || nameOf(mid)) + "\n" + hm(v.t0) + " · " + dur((v.t1 || now) - v.t0) + " · גלילה " + (v.scroll || 0) + "% · הקלדות " + (v.typing || 0) + " · העתקות " + ((v.copy || 0) + (v.cut || 0)) + " · הדבקות " + (v.paste || 0)) + "</title></rect>";
      });
      y += LANE;
    });
    y += 30;
    svg += '<text class="grp" x="' + (W - 8) + '" y="' + (y - 8) + '" text-anchor="end">מערכת' + (sysNote ? " · " + esc(sysNote) : " · כל מקביל") + "</text>";
    const bins = Math.max(60, Math.floor((X1 - X0) / 4)), bw = (X1 - X0) / bins;
    srcNames.forEach(src => {
      const cnt = new Array(bins).fill(0), err = new Array(bins).fill(0);
      srcs[src].forEach(s => { const i = clamp(Math.floor((Math.max(s.s, t0) - t0) / (now - t0) * bins), 0, bins - 1); cnt[i]++; if (s.status === "error") err[i]++; });
      const mx = Math.max.apply(null, cnt) || 1;
      svg += '<text class="lane sys" x="' + (W - 8) + '" y="' + (y + 17) + '" text-anchor="end">' + esc(src) + " · " + srcs[src].length + "</text>";
      cnt.forEach((c, i) => {
        if (!c) return;
        const hh = 3 + (LANE - 8) * Math.log(1 + c) / Math.log(1 + mx);
        svg += '<rect class="bin' + (err[i] ? " err" : "") + '" x="' + (X0 + i * bw) + '" y="' + (y + LANE - 3 - hh) + '" width="' + Math.max(1, bw - 0.6) + '" height="' + hh + '"><title>' +
          esc(src + " · " + c + " אירועים" + (err[i] ? " · " + err[i] + " שגיאות" : "") + " · " + hm(t0 + i * (now - t0) / bins)) + "</title></rect>";
      });
      y += LANE;
    });
    svg += '<line class="cursor" x1="-10" y1="22" x2="-10" y2="' + H + '"/></svg>';
    mb.innerHTML = '<p class="lead">הנתיבים העליונים הם העבודה שלך בשולחן העבודה; התחתונים הם מה שהמערכת עשתה באותו זמן, כפי שכל מקביל רושם. לחיצה על הסרגל בוחרת רגע; לחיצה על קטע פותחת את המקום.</p>' +
      '<div class="tlbar"><span class="at">בחרו רגע על ציר הזמן</span><button type="button" class="btn sm" data-restore disabled>שחזור החלונות מהרגע הזה</button></div>' + svg;
    const sv = mb.querySelector("svg.tl"), cursor = sv.querySelector(".cursor"), at = mb.querySelector(".at"), rb = mb.querySelector("[data-restore]");
    let pick = 0;
    sv.addEventListener("click", e => {
      const blk = e.target.closest("[data-v]");
      if (blk) { const v = vs.find(z => z.id === blk.getAttribute("data-v")); if (v) openPlace(v); return; }
      const r = sv.getBoundingClientRect(), px = (e.clientX - r.left) * (W / r.width);
      if (px < X0 || px > X1) return;
      pick = t0 + (px - X0) / (X1 - X0) * (now - t0);
      cursor.setAttribute("x1", px);
      cursor.setAttribute("x2", px);
      at.textContent = "נבחר: " + new Date(pick).toLocaleString("he-IL", { weekday: "short", hour: "2-digit", minute: "2-digit" });
      rb.disabled = false;
    });
    rb.addEventListener("click", () => restoreAt(pick));
  }

  // episodic → spatial: the windows that were open at a moment, back where they were
  async function restoreAt(t) {
    let snaps = [];
    try { snaps = await allSnaps(); } catch (e) { /* storage unavailable */ }
    const s = snaps.filter(x => x.t <= t).sort((a, b) => b.t - a.t)[0];
    if (!s) { wm.toast("אין תמונת מצב של החלונות מלפני הרגע הזה"); return; }
    const kx = s.W ? wm.geom().W / s.W : 1;
    let n = 0;
    s.wins.forEach(x => {
      const o = { cx: x.cx * kx, cy: x.cy, w: x.w, h: x.h };
      if (x.native) { if (!wm.wins().some(w => w.native === x.native)) { wm.openNative(x.native, o); n++; } return; }
      const m = wm.modById(x.mid);
      if (!m || wm.wins().some(w => w.mid === x.mid && (w.route || "") === (x.route || ""))) return;
      wm.openModule(m, x.route || "");
      n++;
    });
    wm.toast(n ? "שוחזרו " + n + " חלונות מ-" + hm(s.t) : "כל החלונות של " + hm(s.t) + " כבר פתוחים");
  }

  // what is recorded, in the open, with the switch and the eraser
  async function viewRecords(mb) {
    const vs = (await loadVisits(MV.hours)).sort((a, b) => b.t0 - a.t0);
    mb.innerHTML =
      '<div class="rec-h"><label class="sw"><input type="checkbox" data-hist' + (recording() ? " checked" : "") + "> רישום ההיסטוריה פעיל</label>" +
      '<button type="button" class="btn sm ghost" data-export>ייצוא לקובץ</button><button type="button" class="btn sm ghost" data-wipe>מחיקת כל ההיסטוריה</button></div>' +
      '<p class="lead">נרשם בדפדפן הזה בלבד, ל-30 יום: איזה מקום היה בחזית ולכמה זמן, עד כמה הדף נגלל, וכמה הקלדות, העתקות, הדבקות ושליחות היו בו. ' +
      "לא נרשם אף פעם: מה הוקלד, מה הועתק, תוכן הדפים או צילומי מסך.</p>" +
      '<table class="rec"><thead><tr><th>זמן</th><th>מקום</th><th>משך</th><th>גלילה</th><th>הקלדות</th><th>העתקות</th><th>הדבקות</th><th>שליחות</th><th>נאסף</th><th>הגעה</th></tr></thead><tbody></tbody></table>';
    const tb = mb.querySelector("tbody");
    const HOW = { open: "פתיחה", "switch": "מעבר", navigate: "ניווט", "return": "חזרה" };
    vs.slice(0, 400).forEach(v => {
      const tr = h("tr");
      [hm(v.t0), (v.title || nameOf(v.mid)), dur((v.t1 || Date.now()) - v.t0), (v.scroll || 0) + "%", v.typing || 0, (v.copy || 0) + (v.cut || 0), v.paste || 0, v.submit || 0, v.clip || 0, HOW[v.how] || ""]
        .forEach(c => { const td = h("td"); td.textContent = String(c); tr.appendChild(td); });
      tb.appendChild(tr);
    });
    if (!vs.length) tb.innerHTML = '<tr><td colspan="10" class="empty">אין רשומות בטווח הזה</td></tr>';
    mb.querySelector("[data-hist]").addEventListener("change", e => {
      wm.setPref("history", e.target.checked);
      if (!e.target.checked) endVisit(); else { const f = wm.focused(); if (f) startVisit(f, "return"); }
      wm.toast(e.target.checked ? "רישום ההיסטוריה הופעל" : "רישום ההיסטוריה הושהה");
    });
    const wipe = mb.querySelector("[data-wipe]");
    wipe.addEventListener("click", async () => {
      if (!wipe.dataset.sure) { wipe.dataset.sure = "1"; wipe.textContent = "לחצו שוב כדי למחוק הכל"; setTimeout(() => { delete wipe.dataset.sure; wipe.textContent = "מחיקת כל ההיסטוריה"; }, 4000); return; }
      try { (await os("visits", "readwrite")).clear(); (await os("snaps", "readwrite")).clear(); } catch (e) { /* storage unavailable */ }
      cur = null;
      wm.toast("ההיסטוריה נמחקה");
      viewRecords(mb);
    });
    mb.querySelector("[data-export]").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(vs, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "desktop-history-" + new Date().toISOString().slice(0, 10) + ".json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    });
  }

  wm.registerNative({ key: "memory", name: "זיכרון", icon: "brain", color: "dk-c2", render: body => renderMemory(body) });
})();
