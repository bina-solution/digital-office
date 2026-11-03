/* «פגישות» — upload.js: a meeting's files. The recordings it already has (the bridge's video, the side recordings),
   its documents, and what people add to it: another recording of the same meeting (a phone, an iPad), a text, a
   document. A file goes up in 4 MB pieces (the console's proxy drops a long request), each piece confirmed by the
   server, so a dropped connection resumes where the server says it stopped. A recording is placed on the meeting's
   axis by saying when it started. */
(() => {
  "use strict";
  const MF = window.MF;
  const PIECE = 4 * 1024 * 1024;
  const KIND = (name) => {
    const x = (String(name).match(/\.([a-z0-9]+)$/i) || [, ""])[1].toLowerCase();
    if (["m4a", "mp3", "ogg", "opus", "wav", "webm", "aac", "flac"].includes(x)) return "audio";
    if (["mp4", "mov", "mkv"].includes(x)) return "video";
    if (["txt", "md", "vtt", "srt", "json"].includes(x)) return "text";
    if (["pdf", "docx", "xlsx", "pptx", "png", "jpg"].includes(x)) return "doc";
    return "";
  };
  const KIND_HE = { audio: "הקלטת קול", video: "וידאו", text: "טקסט", doc: "מסמך" };
  const KIND_IC = { audio: "headphones", video: "video", text: "type", doc: "file-text" };
  const size = (b) => (b >= 1 << 30 ? (b / (1 << 30)).toFixed(1) + " GB" : b >= 1 << 20 ? Math.round(b / (1 << 20)) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
  const parseClock = (s) => {
    const p = String(s || "").trim().split(":").map((x) => +x);
    if (!p.length || p.some((x) => isNaN(x))) return null;
    return p.reduce((a, x) => a * 60 + x, 0);
  };

  MF.Files = function Files(el, ctx) {
    const { esc, ic, fmt } = MF;
    const { M, room } = ctx;
    let uploads = [];
    const busy = new Map();                      // name → {sent, total, abort}
    const base = MF.roomUrl(room);
    async function load() {
      try { const r = await MF.api(`flow/${encodeURIComponent(room)}/uploads`); uploads = (r && r.uploads) || []; }
      catch (e) { uploads = []; if (e.code !== 404) MF.tell(e.message, "warn"); }
      render();
    }
    function trackRow(icon, title, meta, href) {
      return `<div class="mf-file"><span class="mf-file-ic">${ic(icon)}</span><div class="mf-file-b"><b dir="auto">${esc(title)}</b><span class="muted small">${meta}</span></div>${href ? `<a class="btn sm ghost" href="${esc(href)}" download>${ic("download")}<span>הורדה</span></a>` : ""}</div>`;
    }
    function render() {
      const own = [];
      if (M && M.video && M.video.src) own.push(trackRow("video", "הקלטת הפגישה (וידאו)", `${fmt(M.video.duration || 0)} · מהגשר של Jitsi`, M.video.src.startsWith("../../") ? MF.url(M.video.src.slice(6)) : base + M.video.src));
      for (const a of (M && M.audio) || []) if (a.id !== "meet") own.push(trackRow("headphones", a.label || a.short || a.id, `${fmt(a.duration || 0)} · מתחילה ב-${fmt(a.offset || 0)} בציר`, a.src ? base + a.src : ""));
      const docs = ((M && M.meeting && M.meeting.docs) || []).map((d) => `<button class="mf-file mf-doc" type="button" data-doc="${esc(d.href)}"><span class="mf-file-ic">${ic("file-text")}</span><div class="mf-file-b"><b dir="auto">${esc(d.title)}</b><span class="muted small">מסמך של הפגישה</span></div>${ic("chevronL", "mf-go")}</button>`);
      const ups = uploads.map((u) => {
        const b = busy.get(u.name), k = u.kind || KIND(u.name);
        const pct = b ? Math.round((b.sent / b.total) * 100) : u.done ? 100 : Math.round(((u.received || 0) / (u.size || 1)) * 100);
        const placed = k === "audio" || k === "video" ? (u.offset != null ? `מתחיל ב-${fmt(u.offset)} בציר` : "עוד לא שובץ בציר") : KIND_HE[k] || "";
        return `<div class="mf-file mf-up" data-name="${esc(u.name)}">
          <span class="mf-file-ic">${ic(KIND_IC[k] || "file-text")}</span>
          <div class="mf-file-b"><b dir="auto">${esc(u.label || u.name)}</b>
            <span class="muted small">${esc(size(u.size || 0))} · ${esc(placed)}${u.by ? ` · ${esc(u.by.name || u.by.username)}` : ""}${u.at ? ` · ${esc(MF.ago(u.at))}` : ""}</span>
            ${!u.done || b ? `<div class="mf-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i style="--p:${pct}%"></i></div>` : ""}</div>
          <span class="mf-file-acts">${b ? `<button class="btn sm ghost" type="button" data-u="stop">עצירה</button>`
            : !u.done ? `<span class="mf-st" data-st="proposed">נעצר ב-${pct}%</span>`
            : (k === "audio" || k === "video") ? `<button class="btn sm ghost" type="button" data-u="place">${ic("clock")}<span>${u.offset != null ? "שינוי המיקום" : "שיבוץ בציר"}</span></button>` : ""}
            ${u.done ? `<a class="btn sm ghost" href="${esc(base + "uploads/" + encodeURIComponent(u.name))}" download>${ic("download")}<span>הורדה</span></a>` : ""}</span>
        </div>`;
      });
      el.innerHTML = `
        <section class="mf-sec"><h3>הקלטות</h3>${own.join("") || '<p class="muted small">ההקלטה של הפגישה תופיע כאן כשהמקליט יסיים.</p>'}</section>
        ${docs.length ? `<section class="mf-sec"><h3>מסמכים</h3>${docs.join("")}</section>` : ""}
        ${(M.turns || []).length ? `<section class="mf-sec mf-export"><h3>התמלול כקובץ</h3><p class="muted small">עם כל התיקונים — השורות והדוברים. הקובץ נכתב גם לתיקיית הפגישה ב«קבצים» מיד כשהעיבוד מוכן.</p>
          <div class="mf-export-acts">${[["txt", "טקסט", "file-text"], ["vtt", "כתוביות VTT", "type"], ["srt", "כתוביות SRT", "type"]].map(([x, h, i]) => `<a class="btn sm ghost" href="${esc(base + "transcript." + x)}" download="${esc(room + "." + x)}">${ic(i)}<span>${h}</span></a>`).join("")}</div></section>` : ""}
        <section class="mf-sec"><h3>קבצים שנוספו</h3>${ups.join("") || '<p class="muted small">עוד לא נוסף קובץ.</p>'}
          <label class="mf-drop" tabindex="0">${ic("upload")}<span><b>הוספת קובץ לפגישה</b><span class="muted small">הקלטה נוספת (טלפון, iPad), טקסט או מסמך · גררו לכאן או לחצו</span></span>
            <input type="file" multiple accept="audio/*,video/*,.txt,.md,.vtt,.srt,.json,.pdf,.docx,.xlsx,.pptx,.png,.jpg" hidden></label>
        </section>`;
    }
    async function send(file) {
      const k = KIND(file.name);
      if (!k) { MF.tell(`סוג הקובץ «${file.name}» לא נתמך`, "warn"); return; }
      const name = file.name.replace(/[\/\\:*?"<>|\x00-\x1f]/g, " ").replace(/\s+/g, " ").trim().slice(-120);
      const ctl = { sent: 0, total: file.size, stop: false };
      busy.set(name, ctl);
      if (!uploads.some((u) => u.name === name)) uploads.push({ name, size: file.size, kind: k, received: 0, done: false });
      render();
      const url = `flow/${encodeURIComponent(room)}/uploads/${encodeURIComponent(name)}`;
      try {
        while (ctl.sent < file.size && !ctl.stop) {
          const end = Math.min(file.size, ctl.sent + PIECE);
          const r = await fetch(MF.url(url), { method: "PUT", credentials: "same-origin", headers: { "X-Meet-Flow": "1", "Content-Range": `bytes ${ctl.sent}-${end - 1}/${file.size}`, "Content-Type": "application/octet-stream" }, body: file.slice(ctl.sent, end) });
          const doc = await r.json().catch(() => null);
          if (r.status === 409 && doc && doc.received != null) { ctl.sent = +doc.received; continue; }     // the server's count wins: resume there
          if (!r.ok) throw new MF.Error(r.status, MF.errorHe(r.status, doc), doc);
          ctl.sent = +(doc && doc.received) || end;
          const row = el.querySelector(`.mf-up[data-name="${CSS.escape(name)}"] .mf-bar i`);
          if (row) row.style.setProperty("--p", Math.round((ctl.sent / file.size) * 100) + "%");
        }
        busy.delete(name);
        if (!ctl.stop) MF.tell(`«${name}» הועלה`, "ok", k === "audio" || k === "video" ? { act: ["שיבוץ בציר", () => place(name)] } : {});
      } catch (e) {
        busy.delete(name);
        MF.tell(e.message || "ההעלאה נכשלה", "bad", { more: e.doc ? JSON.stringify(e.doc) : "" });
      }
      await load();
      if (ctx.onChange) ctx.onChange();
    }
    async function place(name) {
      const u = uploads.find((x) => x.name === name); if (!u) return;
      const now = ctx.stage ? ctx.stage.t : 0;
      const v = await MF.ask({ title: "מתי ההקלטה הזו מתחילה?", body: `השעה בציר של הפגישה שבה מתחיל הקובץ «${u.label || u.name}». אפשר לכתוב 0:00 אם הוא התחיל עם הפגישה, או את הרגע המתנגן עכשיו (${fmt(now)}).`, input: { label: "מתחיל ב- (דק׳:שנ׳ או ש׳:דק׳:שנ׳)", value: fmt(u.offset != null ? u.offset : now) }, ok: "שיבוץ" });
      if (v == null) return;
      const off = parseClock(v);
      if (off == null) { MF.tell("זה לא זמן — כתבו למשל 12:30", "warn"); return; }
      try { await MF.api(`${`flow/${encodeURIComponent(room)}/uploads/${encodeURIComponent(name)}`}/meta`, { method: "POST", body: { offset: off } }); MF.tell("ההקלטה שובצה בציר", "ok"); await load(); if (ctx.onChange) ctx.onChange(); }
      catch (e) { MF.tell(e.message, "bad"); }
    }
    el.addEventListener("change", (e) => { if (e.target.type === "file") { for (const f of e.target.files) send(f); e.target.value = ""; } });
    el.addEventListener("dragover", (e) => { const d = e.target.closest(".mf-drop"); if (d) { e.preventDefault(); d.classList.add("over"); } });
    el.addEventListener("dragleave", (e) => { const d = e.target.closest(".mf-drop"); if (d) d.classList.remove("over"); });
    el.addEventListener("drop", (e) => { const d = e.target.closest(".mf-drop"); if (!d) return; e.preventDefault(); d.classList.remove("over"); for (const f of e.dataTransfer.files) send(f); });
    el.addEventListener("keydown", (e) => { const d = e.target.closest(".mf-drop"); if (d && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); d.querySelector("input").click(); } });
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-u]");
      if (b) { const name = b.closest(".mf-up").dataset.name; if (b.dataset.u === "stop") { const c = busy.get(name); if (c) c.stop = true; } else if (b.dataset.u === "place") place(name); return; }
      const d = e.target.closest("[data-doc]"); if (d && ctx.openDoc) ctx.openDoc(d.dataset.doc);
    });
    load();
    return { reload: load, get uploads() { return uploads; } };
  };
})();
