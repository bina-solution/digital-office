/* upload.js — the upload queue. Each file is a resumable session (tus, /api/uploads): pieces of
   8 MB, two files at a time, a dropped network resumes from what the server already has, and a
   session outlives a reload (its id is kept per file). Every row says where it is: sending (speed,
   time left), saving (the server is storing it), done, or failed — with the reason and a retry.
   A whole folder dropped in keeps its shape: its sub-folders are created on the way. */
(function () {
  "use strict";
  const { html, hooks, state, set, api, L, tell, ic, fmtSize, BASE, localGet, localSet } = F;
  const CHUNK = 8 * 1024 * 1024, PARALLEL = 2, RETRIES = 8;
  let seq = 0, active = 0;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const fp = (f, dest) => [f.name, f.size, f.lastModified, dest.folder || "", dest.path || ""].join("|");
  const sessions = () => localGet("up", {});
  const remember = (k, sid) => { const s = sessions(); s[k] = sid; localSet("up", s); };
  const forget = (k) => { const s = sessions(); delete s[k]; localSet("up", s); };
  const patch = (key, p) => set({ uploads: state.uploads.map((u) => (u.key === key ? { ...u, ...p } : u)) });
  // a row no longer in the queue (cleared away) stops its upload, as a canceled one does
  const row = (key) => state.uploads.find((u) => u.key === key) || { key, state: "canceled", size: 0 };

  /* where an upload goes: the open folder, else the root of «הקבצים שלי» */
  function here() {
    const r = state.route;
    return r.view === "folder" ? { folder: r.id || "" } : { folder: "" };
  }
  function enqueue(files, dest) {
    dest = dest || here();
    const list = [...files].filter((f) => f && f.size >= 0);
    if (!list.length) return;
    const rows = list.map((f) => ({ key: ++seq, file: f, name: f.name, rel: f._rel || "", size: f.size, sent: 0,
      state: "queued", error: "", dest: f._rel ? relDest(dest, f._rel) : dest, speed: 0, t0: 0 }));
    set({ uploads: [...state.uploads, ...rows], upOpen: !dest.quiet });
    pump();
    return rows.map((r) => r.key);      // an app that queued a file follows it by its key (the recorder)
  }
  /* a file inside a dropped folder lands in the same folder under the destination (made on demand) */
  function relDest(dest, rel) {
    const dir = rel.split("/").slice(0, -1).join("/");
    if (!dir) return dest;
    const base = dest.folder ? F.data.folderPath(dest.folder).map((f) => f.name).join("/") : "";
    return { path: "/" + [base, dir].filter(Boolean).join("/") };
  }
  function pump() {
    while (active < PARALLEL) {
      const u = state.uploads.find((x) => x.state === "queued");
      if (!u) break;
      active++;
      patch(u.key, { state: "sending", t0: performance.now(), error: "" });
      send(u.key).finally(() => { active--; pump(); });
    }
  }

  async function send(key) {
    const u = row(key), k = fp(u.file, u.dest);
    try {
      let sid = sessions()[k], offset = 0;
      if (sid) {
        try { const s = await api("api/uploads/" + sid); offset = s.offset || 0; if (s.state === "done") return finished(key, k, s.file); }
        catch (e) { sid = null; }
      }
      if (!sid) {
        const s = await api("api/uploads", { body: { size: u.size, name: u.file.name, mime: u.file.type || "",
          folder: u.dest.folder || "", path: u.dest.path || "", mode: u.dest.path ? "new" : "",
          system: u.dest.system || "", remux: u.dest.remux || "" } });
        sid = s.id; remember(k, sid);
      }
      patch(key, { sid, sent: offset });
      let tries = 0, mark = { t: performance.now(), b: offset };
      while (offset < u.size) {
        if (row(key).state === "canceled") return;
        const end = Math.min(offset + CHUNK, u.size);
        let r;
        try {
          r = await fetch(BASE + "api/uploads/" + sid, { method: "PATCH", body: u.file.slice(offset, end),
            headers: { "Upload-Offset": String(offset), "Content-Type": "application/offset+octet-stream", "Tus-Resumable": "1.0.0" } });
        } catch (e) {                                   // the network dropped: wait, ask where we are, go on
          if (++tries > RETRIES) throw new Error(L("החיבור לשרת נקטע — לחצו «נסה שוב» כדי להמשיך מאותה נקודה", "The connection dropped — press Retry to continue where it stopped"));
          patch(key, { error: L("החיבור נקטע — מנסה שוב…", "Connection lost — retrying…") });
          await sleep(Math.min(30000, 1000 * 2 ** tries));
          try { offset = (await api("api/uploads/" + sid)).offset || offset; } catch (e2) { /* still offline */ }
          continue;
        }
        if (r.status === 409) { offset = Number(r.headers.get("Upload-Offset")) || offset; continue; }
        if (!r.ok) { let b = {}; try { b = await r.json(); } catch (e) { /* none */ } throw new Error(b.error || window.binaSaid(r.status)); }
        tries = 0;
        offset = Number(r.headers.get("Upload-Offset")) || end;
        const now = performance.now();
        if (now - mark.t > 700) {
          const speed = ((offset - mark.b) / (now - mark.t)) * 1000;
          mark = { t: now, b: offset };
          patch(key, { sent: offset, speed, error: "" });
        } else patch(key, { sent: offset, error: "" });
      }
      patch(key, { state: "finishing", sent: u.size, error: "" });
      for (let i = 0; ; i++) {
        const s = await api("api/uploads/" + sid);
        if (s.state === "done") return finished(key, k, s.file);
        if (s.state === "failed") throw new Error(s.error || L("השמירה נכשלה", "Saving failed"));
        await sleep(i < 10 ? 600 : 1500);
      }
    } catch (e) {
      if (row(key).state !== "canceled") patch(key, { state: "failed", error: e.message });
    }
  }
  function finished(key, k, item) {
    forget(k);
    patch(key, { state: "done", item, sent: row(key).size, error: "" });
    clearTimeout(finished.t);
    finished.t = setTimeout(() => F.data.refresh(), 250);
  }
  async function cancel(key) {
    const u = row(key);
    patch(key, { state: "canceled" });
    if (u.sid) { try { await api("api/uploads/" + u.sid, { method: "DELETE" }); } catch (e) { /* gone already */ } forget(fp(u.file, u.dest)); }
  }
  function retry(key) { patch(key, { state: "queued", error: "" }); pump(); }
  function clearDone() { set({ uploads: state.uploads.filter((u) => !["done", "canceled"].includes(u.state)) }); }
  const busy = () => state.uploads.some((u) => ["queued", "sending", "finishing"].includes(u.state));
  window.addEventListener("beforeunload", (e) => { if (busy()) { e.preventDefault(); e.returnValue = ""; } });

  /* files out of a drop — folders included, walked to the bottom */
  async function fromDrop(dt) {
    const items = [...(dt.items || [])].filter((i) => i.kind === "file");
    const entries = items.map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null));
    if (!entries.some((e) => e && e.isDirectory)) return [...dt.files];
    const out = [];
    const readAll = (dir) => new Promise((res) => { const r = dir.createReader(), all = []; (function more() {
      r.readEntries((batch) => { if (!batch.length) return res(all); all.push(...batch); more(); }, () => res(all)); })(); });
    async function walk(e, prefix) {
      if (!e) return;
      if (e.isFile) await new Promise((res) => e.file((f) => { f._rel = prefix + f.name; out.push(f); res(); }, res));
      else if (e.isDirectory) for (const c of await readAll(e)) await walk(c, prefix + e.name + "/");
    }
    for (const e of entries) await walk(e, "");
    return out;
  }
  /* the page's two pickers are real inputs that stay in the page (Pickers, below): «choose files»
     and «choose a folder». A pick remembers where its files go until the person has chosen. */
  let pickDest = null;
  function pick(opts) {
    pickDest = (opts && opts.dest) || null;
    const inp = document.getElementById(opts && opts.folder ? "files-pick-folder" : "files-pick");
    if (inp) { inp.value = ""; inp.click(); }
  }
  function picked(e, folder) {
    const files = [...e.target.files];
    if (folder) files.forEach((f) => (f._rel = f.webkitRelativePath || f.name));
    enqueue(files, pickDest || undefined);
    pickDest = null;
    e.target.value = "";
  }
  const Pickers = () => html`<input type="file" id="files-pick" multiple hidden onChange=${(e) => picked(e, false)} />
    <input type="file" id="files-pick-folder" multiple hidden webkitdirectory onChange=${(e) => picked(e, true)} />`;

  /* ── the panel ─────────────────────────────────────────────────────────── */
  function UploadPanel() {
    const ups = F.useStore((s) => s.uploads);
    const open = F.useStore((s) => s.upOpen);
    const ref = hooks.useRef();
    /* how tall the queue is, for what has to stand above it (the add button, the notices) */
    hooks.useLayoutEffect(() => {
      const el = ref.current;
      if (!el) { if (state.upH) set({ upH: 0 }); return; }
      const ro = new ResizeObserver(() => { if (el.offsetHeight !== state.upH) set({ upH: el.offsetHeight }); });
      ro.observe(el);
      return () => { ro.disconnect(); set({ upH: 0 }); };
    }, [ups.length > 0]);
    if (!ups.length) return null;
    const live = ups.filter((u) => ["queued", "sending", "finishing"].includes(u.state));
    const bad = ups.filter((u) => u.state === "failed").length;
    const total = ups.reduce((s, u) => s + u.size, 0), sent = ups.reduce((s, u) => s + Math.min(u.sent, u.size), 0);
    const pct = total ? Math.round((sent / total) * 100) : 100;
    const title = live.length ? L("מעלה ", "Uploading ") + F.count(live.length, ["קובץ אחד", "1 file"], ["קבצים", "files"]) + ` · ${pct}%`
      : bad ? F.count(bad, ["העלאה אחת נכשלה", "1 upload failed"], ["העלאות נכשלו", "uploads failed"]) : L("כל הקבצים הועלו", "All files uploaded");
    return html`<section class="up" ref=${ref} role="region" aria-label=${L("העלאות", "Uploads")}>
      <div class="up-h">
        ${live.length ? html`<span class="spin-sm"></span>` : bad ? ic("alert") : ic("ok")}
        <b>${title}</b>
        <button class="icbtn up-more" title=${open ? L("כיווץ", "Collapse") : L("הרחבה", "Expand")} onClick=${() => set({ upOpen: !open })}>${ic(open ? "chevron-down" : "arrow-up")}</button>
        ${!live.length && html`<button class="icbtn" title=${L("סגירה", "Close")} onClick=${clearAll}>${ic("x")}</button>`}
      </div>
      ${open && html`<div class="up-l">${ups.map((u) => html`<${Row} key=${u.key} u=${u} />`)}</div>`}
    </section>`;
  }
  function clearAll() { set({ uploads: state.uploads.filter((u) => ["queued", "sending", "finishing"].includes(u.state)) }); }
  function Row({ u }) {
    const pct = u.size ? Math.min(100, Math.round((u.sent / u.size) * 100)) : 100;
    const left = u.speed > 0 ? Math.max(0, (u.size - u.sent) / u.speed) : 0;
    const status = u.state === "sending" ? (u.error || L(`${fmtSize(u.sent)} מתוך ${fmtSize(u.size)}`, `${fmtSize(u.sent)} of ${fmtSize(u.size)}`) + (u.speed ? ` · ${fmtSize(u.speed, "/s")}` + (left > 2 ? " · " + L("נותרו ", "") + F.fmtDur(left) + L("", " left") : "") : ""))
      : u.state === "finishing" ? L("שומר בשרת…", "Saving on the server…")
      : u.state === "done" ? L("הועלה · ", "Uploaded · ") + fmtSize(u.size)
      : u.state === "failed" ? u.error
      : u.state === "canceled" ? L("בוטל", "Canceled") : L("ממתין…", "Waiting…");
    const cls = "ur " + (u.state === "done" ? "ok" : u.state === "failed" ? "bad" : u.state === "finishing" ? "finishing" : "");
    const it = { name: u.name, size: u.size };
    return html`<div class=${cls}>
      <div class="th">${ic(F.types.icon(it), "sm")}</div>
      <div class="t">
        <div class="fname"><${F.Name} name=${u.rel || u.name} /></div>
        <div class="s" title=${status}>${status}</div>
        ${u.state !== "done" && u.state !== "canceled" && html`<div class="prog" role="progressbar" aria-valuenow=${pct} aria-valuemin="0" aria-valuemax="100"><i style=${"width:" + pct + "%"}></i></div>`}
      </div>
      <div>
        ${u.state === "failed" && html`<button class="icbtn" title=${L("נסה שוב", "Retry")} onClick=${() => retry(u.key)}>${ic("refresh")}</button>`}
        ${["queued", "sending"].includes(u.state) && html`<button class="icbtn" title=${L("ביטול", "Cancel")} onClick=${() => cancel(u.key)}>${ic("x")}</button>`}
        ${u.state === "done" && u.item && html`<button class="icbtn" title=${L("פתיחה", "Open")} onClick=${() => F.viewer.open([u.item], 0)}>${ic("eye")}</button>`}
      </div>
    </div>`;
  }

  F.upload = { enqueue, pick, fromDrop, cancel, retry, clearDone, busy, UploadPanel, Pickers, here };
})();
