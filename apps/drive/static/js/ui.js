/* ui.js — the parts every view is made of: a file's name (its extension on the right side in
   Hebrew), its picture, the empty / loading / failed states, the menu (at the pointer on a
   desktop, a sheet from the bottom on a phone), the move-to picker and the details pane. One
   action list for an item serves the row's ⋮, the right click, the viewer's ⋮ and the details. */
(function () {
  "use strict";
  const { html, hooks, state, set, L, ic, fmtSize, fmtWhen, splitName, thumbUrl, contentUrl } = F;
  const T = F.types;

  /* a name takes its direction from its own first letter (dir=auto): a Hebrew name reads
     «שם.pdf» with the dot beside the name, an English one «report.pdf» — and only the stem is cut.
     A Hebrew name whose stem ENDS in Latin («תמלול — fpg106.txt») is one left-to-right run at its
     end: its extension is written inside the stem, so it reads «fpg106.txt — תמלול» as plain text
     does — as a box of its own the dot turned and the line read «txt.fpg106 — תמלול» (FPG-385) */
  const firstStrong = (s, back) => {
    const a = [...String(s)];
    for (const ch of back ? a.reverse() : a) {
      if (/[֐-ࣿיִ-﷿ﹰ-﻿]/.test(ch)) return "rtl";
      if (/[A-Za-zÀ-ɏͰ-ϿЀ-ӿ]/.test(ch)) return "ltr";
    }
    return "";
  };
  function Name({ name }) {
    const [stem, ext] = splitName(name);
    if (ext && firstStrong(stem) === "rtl" && firstStrong(stem, true) === "ltr")
      return html`<span class="nm" dir="auto" title=${name}><span class="stem">${stem}<span class="ext in">${ext}</span></span></span>`;
    return html`<span class="nm" dir="auto" title=${name}><span class="stem">${stem}</span>${ext && html`<span class="ext">${ext}</span>`}</span>`;
  }

  /* a real picture when the server can draw one; for a small image the image itself; else the glyph */
  /* the failures are remembered FOR AN ITEM, not reset by an effect: a cached 404 can arrive before the
     first paint's effects run, and a reset there put the broken picture back for good */
  function Thumb({ it, size, big }) {
    const [failed, setFailed] = hooks.useState({ id: null, n: 0 });
    if (it.kind === "folder") return ic(it.system ? "folder-input" : "folder", big ? "xl" : "");
    const k = T.kindOf(it);
    const srcs = [];
    if (T.hasThumb(it)) srcs.push(thumbUrl(it, size || 256));
    if (k === "image" && Number(it.size) < 4e6) srcs.push(contentUrl(it.id));
    const step = failed.id === it.id ? failed.n : 0;
    if (step < srcs.length) {
      return html`<img key=${srcs[step]} src=${srcs[step]} alt="" loading="lazy" decoding="async" draggable="false"
        onError=${() => setFailed({ id: it.id, n: step + 1 })} />`;
    }
    if (big && k === "audio") return html`<${WaveThumb} it=${it} />`;
    return html`${ic(T.icon(it), big ? "xl" : "")}${!big && T.badge(it) && html`<span class="kind">${T.badge(it)}</span>`}`;
  }

  /* a recording without its own art shows its waveform (SoundCloud) once the server has measured it. A
     list only ASKS (?cached=1) — it never starts the work; the server measures every recording in the
     background when it arrives. Until then, the note; asked again a minute later. Time runs with the
     page: from the right in Hebrew, as in the player. */
  const waves = new Map();          // id → { at, vals }
  const BARS = 48;
  function WaveThumb({ it }) {
    const ref = hooks.useRef();
    const [vals, setVals] = hooks.useState(() => (waves.get(it.id) || {}).vals || null);
    hooks.useEffect(() => {
      const el = ref.current;
      let off = false;
      const known = waves.get(it.id);
      if (known && known.vals) { setVals(known.vals); return; }
      if (!el || (known && Date.now() - known.at < 60e3)) return;
      const io = new IntersectionObserver((ents) => {
        if (!ents[0].isIntersecting) return;
        io.disconnect();
        F.api("api/file/" + encodeURIComponent(it.id) + "/peaks?cached=1").then((r) => r.peaks || null).catch(() => null)
          .then((v) => { waves.set(it.id, { at: Date.now(), vals: v }); if (!off && v) setVals(v); });
      }, { rootMargin: "200px" });
      io.observe(el);
      return () => { off = true; io.disconnect(); };
    }, [it.id]);
    if (!vals || !vals.length) return html`<span class="wthumb" ref=${ref}>${ic(T.icon(it), "xl")}</span>`;
    const step = vals.length / BARS, w = 100 / BARS;
    const bars = Array.from({ length: BARS }, (_, i) => Math.max(...vals.slice(Math.floor(i * step), Math.max(Math.floor((i + 1) * step), Math.floor(i * step) + 1))));
    if (document.dir === "rtl") bars.reverse();
    return html`<span class="wthumb" ref=${ref} aria-hidden="true"><svg class="wv" viewBox="0 0 100 100" preserveAspectRatio="none">
      ${bars.map((v, i) => { const h = Math.max(4, v * 92); return html`<rect x=${(i * w + w * 0.18).toFixed(2)} width=${(w * 0.64).toFixed(2)} y=${(50 - h / 2).toFixed(2)} height=${h.toFixed(2)} rx="0.6" />`; })}
    </svg></span>`;
  }

  function Empty({ icon, title, text, children, bad }) {
    return html`<div class=${"empty" + (bad ? " bad" : "")}>
      <div class="ring">${ic(icon || "folder", "lg")}</div>
      <b>${title}</b>${text && html`<div>${text}</div>`}
      ${children && html`<div class="acts">${children}</div>`}
    </div>`;
  }
  const Skeleton = ({ rows }) => html`<div class="list" aria-busy="true">${Array.from({ length: rows || 8 }, (_, i) =>
    html`<div class="sk-row" key=${i}><div class="sk a"></div><div class="sk b" style=${"max-width:" + (180 + ((i * 53) % 160)) + "px"}></div></div>`)}</div>`;

  /* ── the action list ──────────────────────────────────────────────────── */
  function openWithFor(it) {
    const ext = T.extOf(it.name);
    return (state.openWith || []).filter((x) => {
      const s = x.spec || {};
      return (s.exts || []).includes(ext) || (s.mimes || []).some((m) => (it.mime || "").startsWith(m.replace("*", "")));
    });
  }
  function launch(x, it) {
    const s = x.spec || {};
    const url = String(s.url || "").replace("{id}", encodeURIComponent(it.id)).replace("{name}", encodeURIComponent(it.name));
    if (s.target === "tab") window.open(url, "_blank", "noopener"); else location.assign(url);
  }
  function actionsFor(items, where) {
    const D = F.data, one = items.length === 1 ? items[0] : null;
    if (state.route.view === "trash") return [
      { icon: "restore", label: L("שחזור", "Restore"), run: () => D.restore(items) },
      { sep: true },
      { icon: "trash", label: L("מחיקה לצמיתות", "Delete forever"), danger: true, run: () => D.destroy(items) },
    ];
    const folder = one && one.kind === "folder", sys = items.some((i) => i.system);
    const starred = items.every((i) => i.starred);
    const out = [];
    if (one) out.push({ icon: folder ? "folder" : "eye", label: L("פתיחה", "Open"), kbd: "Enter", run: () => F.views.open(one) });
    if (one && !folder) openWithFor(one).forEach((x) => out.push({ icon: "external", label: L("פתיחה באמצעות ", "Open with ") + (x.spec.label || x.app), run: () => launch(x, one) }));
    if (folder) {
      out.push({ icon: "upload", label: L("העלאה לתיקייה הזאת", "Upload here"), run: () => F.upload.pick({ dest: { folder: one.id } }) });
      out.push({ icon: "folder-plus", label: L("תיקייה חדשה בתוכה", "New folder inside"), run: () => D.newFolder(one.id) });
    }
    if (!folder) out.push({ icon: "download", label: L("הורדה", "Download"), run: () => items.forEach(D.download) });
    if (one && !folder) out.push({ icon: "link", label: L("העתקת קישור לשיתוף", "Copy share link"), run: () => D.copyLink(one) });
    if (one) out.push({ icon: "bot", label: L("העתקת נתיב לסוכנים", "Copy path for agents"), run: () => D.copyPath(one) });
    out.push({ sep: true });
    if (one) out.push({ icon: "edit", label: L("שינוי שם", "Rename"), kbd: "F2", disabled: sys, run: () => D.rename(one) });
    out.push({ icon: "folder-input", label: L("העברה אל…", "Move to…"), disabled: sys, run: () => set({ dialog: { type: "move", items } }) });
    out.push({ icon: "star", label: starred ? L("הסרת כוכב", "Remove star") : L("סימון בכוכב", "Add star"), run: () => D.star(items, !starred) });
    // a widget has no room for the details pane: the entry would do nothing visible
    if (one && where !== "details" && where !== "widget") out.push({ icon: "info", label: L("פרטים", "Details"), kbd: "I", run: () => set({ details: true, sel: [one.id] }) });
    out.push({ sep: true });
    out.push({ icon: "trash", label: L("העברה לאשפה", "Move to trash"), kbd: "Del", danger: true, disabled: sys, run: () => D.trash(items),
      title: sys ? L("אפליקציה כותבת לתיקייה הזאת — היא נשארת", "An app writes into this folder — it stays") : "" });
    return out;
  }

  /* ── the menu ─────────────────────────────────────────────────────────── */
  /* forId: the item the menu belongs to, marked on the page while it is open */
  function openMenu(items, e, title, forId) {
    const sheet = state.size.w === "n" || state.size.touch;
    const r = e && e.currentTarget && e.type === "click" ? e.currentTarget.getBoundingClientRect() : null;
    const x = r ? (document.dir === "rtl" ? r.left : r.right) : e ? e.clientX : innerWidth / 2;
    const y = r ? r.bottom + 4 : e ? e.clientY : innerHeight / 2;
    set({ menu: { items, x, y, sheet, title, for: forId || null } });
  }
  function Menu() {
    const m = F.useStore((s) => s.menu);
    const ref = hooks.useRef();
    hooks.useLayoutEffect(() => {
      const el = ref.current; if (!el || !m || m.sheet) return;
      const r = el.getBoundingClientRect(), rtl = document.dir === "rtl";
      let left = rtl ? m.x - r.width : m.x, top = m.y;
      if (left + r.width > innerWidth - 8) left = innerWidth - r.width - 8;
      if (left < 8) left = 8;
      if (top + r.height > innerHeight - 8) top = Math.max(8, m.y - r.height - 8);
      el.style.left = left + "px"; el.style.top = top + "px";
      const first = el.querySelector(".mi:not(:disabled)"); if (first) first.focus();
    }, [m]);
    if (!m) return null;
    const close = () => set({ menu: null });
    function key(e) {
      const all = [...ref.current.querySelectorAll(".mi:not(:disabled)")], i = all.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); close(); }
      if (e.key === "ArrowDown") { e.preventDefault(); (all[i + 1] || all[0]).focus(); }
      if (e.key === "ArrowUp") { e.preventDefault(); (all[i - 1] || all[all.length - 1]).focus(); }
    }
    return html`<div class=${"menu-scrim" + (m.sheet ? " dim" : "")} onMouseDown=${close} onContextMenu=${(e) => { e.preventDefault(); close(); }}></div>
      <div class=${"menu" + (m.sheet ? " sheet" : "")} ref=${ref} role="menu" onKeyDown=${key}>
        ${m.title && html`<div class="mh"><bdi>${m.title}</bdi></div>`}
        ${m.items.map((a, i) => a.sep ? html`<div class="msep" key=${i}></div>` : html`<button key=${i} role="menuitem"
          class=${"mi" + (a.danger ? " danger" : "")} disabled=${a.disabled} title=${a.title || ""}
          onClick=${() => { close(); a.run(); }}>${ic(a.icon, "sm")}<span class="lbl">${a.label}</span>${a.kbd && !m.sheet && html`<span class="kbd">${a.kbd}</span>`}</button>`)}
      </div>`;
  }

  /* ── move to… : walk the tree, pick, move ─────────────────────────────── */
  function MoveDialog() {
    const d = F.useStore((s) => s.dialog);
    const folders = F.useStore((s) => s.folders);
    const [at, setAt] = hooks.useState("");
    hooks.useEffect(() => setAt(""), [d]);
    if (!d || d.type !== "move") return null;
    const moving = new Set(d.items.filter((i) => i.kind === "folder").map((i) => i.id));
    const kids = folders.filter((f) => (f.parent || "") === at && !moving.has(f.id));
    const trail = F.data.folderPath(at);
    const close = () => set({ dialog: null });
    return html`<div class="dlg-scrim" onMouseDown=${(e) => e.target === e.currentTarget && close()}>
      <div class="dlg" role="dialog" aria-modal="true" aria-label=${L("העברה אל", "Move to")} onKeyDown=${(e) => e.key === "Escape" && close()}>
        <div class="dlg-h"><b>${L("העברה אל…", "Move to…")}</b><button class="icbtn" title=${L("סגירה", "Close")} onClick=${close}>${ic("x")}</button></div>
        <div class="crumbs dlg-crumbs">
          <button class="crumb" onClick=${() => setAt("")}>${L("הקבצים שלי", "My files")}</button>
          ${trail.map((f) => html`<span class="crumb-sep">${ic("chevron", "sm")}</span><button class="crumb" onClick=${() => setAt(f.id)}><bdi>${f.name}</bdi></button>`)}
        </div>
        <div class="dlg-b">
          ${kids.length ? kids.map((f) => html`<button class="mi" key=${f.id} onClick=${() => setAt(f.id)}>${ic("folder", "sm")}<span class="lbl ell"><bdi>${f.name}</bdi></span>${ic("chevron", "sm flip")}</button>`)
            : html`<div class="empty compact"><span>${L("אין כאן תיקיות", "No folders here")}</span></div>`}
        </div>
        <div class="dlg-f">
          <button class="btn ghost" onClick=${() => F.data.newFolder(at)}>${ic("folder-plus", "sm")}${L("תיקייה חדשה", "New folder")}</button>
          <button class="btn primary" onClick=${() => { close(); F.data.move(d.items, at); }}>${L("העברה לכאן", "Move here")}</button>
        </div>
      </div>
    </div>`;
  }

  /* ── details: key over value, the agent's path, the share link ───────── */
  function Details() {
    const show = F.useStore((s) => s.details);
    const sel = F.useStore((s) => s.sel);
    const list = F.useStore((s) => s.list);
    const route = F.useStore((s) => s.route);
    const [extra, setExtra] = hooks.useState(null);
    const all = [...list.folders, ...list.files];
    const it = sel.length === 1 ? all.find((x) => x.id === sel[0]) : null;
    hooks.useEffect(() => {
      setExtra(null);
      if (!show || !it) return;
      const url = it.kind === "folder" ? "api/folder/" + encodeURIComponent(it.id) + "/path" : "api/file/" + encodeURIComponent(it.id);
      F.api(url).then((d) => setExtra(d.file || d)).catch(() => {});
    }, [show, it && it.id]);
    if (!show) return null;
    const close = () => set({ details: false });
    if (!it) {
      const n = sel.length;
      return html`<aside class="fx-details" aria-label=${L("פרטים", "Details")}>
        <div class="det-h"><b>${n ? F.count(n, ["פריט אחד נבחר", "1 item selected"], ["פריטים נבחרו", "items selected"]) : route.view === "folder" ? L("פרטי התיקייה", "Folder details") : L("פרטים", "Details")}</b>
          <button class="icbtn" title=${L("סגירה", "Close")} onClick=${close}>${ic("x")}</button></div>
        <div class="empty compact"><div class="ring">${ic("info", "lg")}</div>
          <span>${n ? fmtSize(all.filter((x) => sel.includes(x.id)).reduce((s, x) => s + (Number(x.size) || 0), 0)) : L("בחרו קובץ או תיקייה כדי לראות את הפרטים שלו", "Select a file or folder to see its details")}</span></div>
      </aside>`;
    }
    const folder = it.kind === "folder";
    const path = extra && (extra.path || "");
    return html`<aside class="fx-details" aria-label=${L("פרטים", "Details")}>
      <div class="det-h"><span class="th">${ic(folder ? "folder" : T.icon(it), "sm")}</span><b><bdi>${it.name}</bdi></b>
        <button class="icbtn" title=${L("סגירה", "Close")} onClick=${close}>${ic("x")}</button></div>
      <div class="det-prev" onClick=${() => F.views.open(it)}><${Thumb} it=${it} size=${512} big /></div>
      <dl class="facts">
        <dt>${L("סוג", "Type")}</dt><dd>${folder ? L("תיקייה", "Folder") : T.label(it)}${T.badge(it) && html` · <span class="num">${T.badge(it)}</span>`}</dd>
        ${!folder && html`<dt>${L("גודל", "Size")}</dt><dd class="num">${fmtSize(it.size)}</dd>`}
        ${folder && html`<dt>${L("קבצים", "Files")}</dt><dd class="num">${it.count || 0}</dd>`}
        <dt>${L("נוצר", "Created")}</dt><dd>${fmtWhen(it.created || it.last)}</dd>
        ${it.opened && html`<dt>${L("נפתח לאחרונה", "Last opened")}</dt><dd>${fmtWhen(it.opened)}</dd>`}
        ${it.system && html`<dt>${L("נכתב על ידי", "Written by")}</dt><dd>${it.system}</dd>`}
      </dl>
      ${path && html`<div><div class="det-label">${L("נתיב לסוכנים", "Path for agents")}</div>
        <div class="copyline"><code title=${path}>${String(path).split("/").map((seg, i) => i ? html`/<bdi>${seg}</bdi>` : seg)}</code><button class="icbtn" title=${L("העתקה", "Copy")} onClick=${() => F.copyText(path)}>${ic("copy", "sm")}</button></div></div>`}
      ${!folder && it.link && html`<div><div class="det-label">${L("קישור לשיתוף", "Share link")}</div>
        <div class="copyline"><code title=${it.link}>${it.link}</code><button class="icbtn" title=${L("העתקה", "Copy")} onClick=${() => F.data.copyLink(it)}>${ic("copy", "sm")}</button></div></div>`}
      <div class="det-acts">
        <button class="btn primary sm" onClick=${() => F.views.open(it)}>${ic(folder ? "folder" : "eye", "sm")}${L("פתיחה", "Open")}</button>
        ${!folder && html`<button class="btn sm" onClick=${() => F.data.download(it)}>${ic("download", "sm")}${L("הורדה", "Download")}</button>`}
        <button class="btn sm" onClick=${(e) => openMenu(actionsFor([it], "details"), e)}>${ic("more", "sm")}${L("עוד", "More")}</button>
      </div>
    </aside>`;
  }

  F.ui = { Name, Thumb, WaveThumb, Empty, Skeleton, Menu, MoveDialog, Details, openMenu, actionsFor, openWithFor, launch };
  F.Name = Name;
})();
