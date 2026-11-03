/* «פגישות» — screens.js: the moments a screen was pointed at (M5-T44, fireplace 2026-10-29). Shlomo, call 5 [1:41:39]:
   whenever someone says «here», the shared screen's frame from that second belongs with the meeting; C1 [35:53]: every
   «צילום מסך», automatically. The transcript knows when each word was said, so the moments are found in it («צילום
   מסך» / screenshot: asked for; «פה», «הנה», «כאן»: pointed at), one per 15 s — the server's rule (screen_moments),
   the same list it writes to the meeting's Drive folder. Each moment's frame is drawn here from the recording itself
   (nothing leaves the office), and a person keeps a frame with one tap: it is stored in the meeting's folder in
   «קבצים» as «מסך HH-MM-SS.jpg», beside the recording, where every agent reads it. A frame is kept only by a person:
   a shared screen can show what must stay private (C1's password message, CHAT-106). */
(() => {
  "use strict";
  const MF = window.MF;
  Object.assign(MF.ICONS, {
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    history: '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/>',
    user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  });
  const key = (w) => MF.norm(w).replace(/[^\p{L}\p{N}]/gu, "");
  const HERE = new Set(["פה", "הנה", "כאן", "מפה", "לפה", "מכאן", "לכאן", "here"].map(key));
  const SHOT_W = new Set(["screenshot", "screenshots"].map(key));
  const SHOT_P = new Set([["צילום", "מסך"], ["צלם", "מסך"], ["תצלם", "מסך"], ["צילומי", "מסך"], ["צילום", "המסך"]].map(([a, b]) => key(a) + " " + key(b)));

  /* the moments of a meeting's lines: [{t, kind: shot|here, words, line, text}], one per 15 s */
  MF.moments = (turns) => {
    const found = [];
    for (const x of turns || []) {
      const toks = String(x.text || "").split(/\s+/).filter(Boolean);
      if (!toks.length) continue;
      const keys = toks.map(key);
      const wt = Array.isArray(x.w) && x.w.length === toks.length ? x.w : null;
      keys.forEach((k, i) => {
        const kind = SHOT_W.has(k) || (i + 1 < keys.length && SHOT_P.has(k + " " + keys[i + 1])) ? "shot" : HERE.has(k) ? "here" : null;
        if (kind) found.push({ t: Math.round(((+x.s || 0) + (wt ? wt[i] / 10 : 0)) * 10) / 10, kind, word: toks[i].replace(/[.,!?;:"'״׳()]/g, ""), line: x.id, text: String(x.text).slice(0, 160) });
      });
    }
    found.sort((a, b) => a.t - b.t);
    const out = [];
    for (const f of found) {
      const last = out[out.length - 1];
      if (last && f.t - last.t < 15) { if (f.kind === "shot") last.kind = "shot"; if (!last.words.includes(f.word)) last.words.push(f.word); continue; }
      out.push({ t: f.t, kind: f.kind, words: [f.word], line: f.line, text: f.text });
    }
    return out;
  };
  const hms = (t) => { const s = Math.max(0, Math.floor(t)); return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map((n) => String(n).padStart(2, "0")).join("-"); };
  MF.frameName = (t) => `מסך ${hms(t)}.jpg`;

  MF.Screens = function Screens(el, ctx) {
    const { esc, ic, fmt } = MF;
    const { M, room } = ctx;
    const list = Array.isArray(M.moments) ? M.moments : MF.moments(M.turns);
    const src = M.video && M.video.src ? String(M.video.src) : "";
    const vsrc = !src ? "" : src.startsWith("../../") ? MF.url(src.slice(6)) : /^([a-z][a-z0-9+.-]*:|\/)/i.test(src) ? src : MF.roomUrl(room, src);
    const vdur = M.video ? (+M.video.duration || +(M.meeting || {}).duration || 0) : 0;
    const savedNames = () => new Set((ctx.uploads() || []).filter((u) => u.done !== false).map((u) => u.name));
    let saved = savedNames();
    const shots = list.filter((m) => m.kind === "shot");
    const card = (m, i) => {
      const has = saved.has(MF.frameName(m.t));
      const what = m.kind === "shot" ? "צילום מסך" : "«" + m.words.join("», «") + "»";
      return `<li class="mf-sc" data-i="${i}" data-kind="${m.kind}">
        <button class="mf-sc-shot" type="button" data-sc-seek="${m.t}" aria-label="לנגן מ-${fmt(m.t)}"><canvas width="320" height="180" aria-hidden="true"></canvas><span class="mf-sc-ph" aria-hidden="true">${ic("image")}</span><time dir="ltr">${fmt(m.t)}</time></button>
        <div class="mf-sc-b">
          <div class="mf-sc-h"><span class="mf-tag" data-tone="${m.kind === "shot" ? "warn" : ""}">${esc(what)}</span>${has ? `<span class="mf-tag mf-sc-kept" data-tone="ok">${ic("tick")}<span>נשמר בקבצים</span></span>` : ""}</div>
          <p class="mf-sc-tx" dir="auto">${esc(m.text)}</p>
          ${vsrc ? `<div class="mf-sc-acts"><button class="btn sm ghost" type="button" data-sc-save="${i}"${has ? " disabled" : ""}>${ic("camera")}<span>${has ? "נשמר" : "שמירה בקבצים"}</span></button></div>` : ""}
        </div></li>`;
    };
    let open = [];                                      // the «צילום מסך» moments whose frame nobody kept yet
    function render() {
      saved = savedNames();
      open = shots.filter((m) => !saved.has(MF.frameName(m.t)));
      el.innerHTML = list.length ? `
        <div class="mf-sc-head"><p class="muted small">${MF.num(list.length)} רגעים שבהם נאמר «פה», «כאן» או «צילום מסך» — כל אחד עם המסך מאותה שנייה בהקלטה. ${vsrc ? "מסך שנשמר נכנס לתיקיית הפגישה ב«קבצים»." : "לפגישה הזו אין הקלטת וידאו, אז אין מסכים לשמור."}</p>
          ${vsrc && open.length ? `<button class="btn sm" type="button" data-sc-all>${ic("camera")}<span>${open.length === 1 ? "שמירת צילום המסך" : `שמירת ${MF.num(open.length)} צילומי המסך`}</span></button>` : ""}</div>
        <ol class="mf-sc-list">${list.map(card).join("")}</ol>`
        : `<div class="mf-empty">${ic("image")}<p>בפגישה הזו לא נאמר «פה», «כאן» או «צילום מסך».</p><p class="muted small">כשמישהו מצביע על המסך המשותף במילים, הרגע והמסך שלו מופיעים כאן.</p></div>`;
      observe();
    }

    /* ---------- the frames, drawn from the recording itself: one hidden player, one moment at a time ---------- */
    let video = null, queue = [], busy = false, io = null;
    const want = new Set();
    function player() {
      if (video || !vsrc) return video;
      video = document.createElement("video");
      video.muted = true; video.preload = "auto"; video.playsInline = true; video.src = vsrc;
      return video;
    }
    const seekTo = (t) => new Promise((ok, bad) => {
      const v = player(); if (!v) { bad(new Error("no video")); return; }
      let done = false;
      const fin = (f) => { if (done) return; done = true; v.removeEventListener("seeked", on); clearTimeout(tm); f(); };
      const on = () => fin(ok);
      const tm = setTimeout(() => fin(() => bad(new Error("the recording did not answer"))), 12000);
      v.addEventListener("seeked", on);
      const go = () => { try { v.currentTime = Math.min(Math.max(0, t), (v.duration || vdur || t + 1) - 0.05); } catch (e) { fin(() => bad(e)); } };
      if (v.readyState >= 1) go(); else v.addEventListener("loadedmetadata", go, { once: true });
    });
    async function pump() {
      if (busy) return;
      busy = true;
      while (queue.length) {
        const i = queue.shift(), m = list[i], li = el.querySelector(`.mf-sc[data-i="${i}"]`);
        if (!li || li.dataset.drawn) continue;
        if (vdur && m.t > vdur) { li.dataset.drawn = "past"; continue; }
        try {
          await seekTo(m.t);
          const c = li.querySelector("canvas"), v = video;
          c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
          li.dataset.drawn = "1";
        } catch (e) { li.dataset.drawn = "failed"; }
      }
      busy = false;
    }
    function observe() {
      if (!vsrc) return;
      if (io) io.disconnect();
      io = "IntersectionObserver" in window ? new IntersectionObserver((es) => {
        for (const e of es) if (e.isIntersecting) { const i = +e.target.dataset.i; if (!want.has(i)) { want.add(i); queue.push(i); } io.unobserve(e.target); }
        pump();
      }, { root: null, rootMargin: "200px" }) : null;
      for (const li of el.querySelectorAll(".mf-sc")) { if (io) io.observe(li); else queue.push(+li.dataset.i); }
      if (!io) pump();
    }

    /* ---------- keeping a frame: the full picture, into the meeting's folder in «קבצים» ---------- */
    async function keep(i) {
      const m = list[i], name = MF.frameName(m.t);
      await seekTo(m.t);
      const v = video, w = Math.min(1280, v.videoWidth || 1280), h = Math.round(w * ((v.videoHeight || 720) / (v.videoWidth || 1280)));
      const c = document.createElement("canvas"); c.width = w; c.height = h;
      c.getContext("2d").drawImage(v, 0, 0, w, h);
      const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.86));
      if (!blob) throw new Error("לא הצלחנו לצייר את המסך");
      const url = `flow/${encodeURIComponent(room)}/uploads/${encodeURIComponent(name)}`;
      const r = await fetch(MF.url(url), { method: "PUT", credentials: "same-origin", body: blob,
        headers: { "X-Meet-Flow": "1", "Content-Range": `bytes 0-${blob.size - 1}/${blob.size}`, "Content-Type": "application/octet-stream" } });
      const doc = await r.json().catch(() => null);
      if (!r.ok && !(r.status === 409 && doc && +doc.received === blob.size)) throw new MF.Error(r.status, MF.errorHe(r.status, doc), doc);
      try { await MF.api(`${url}/meta`, { method: "POST", body: { label: `המסך ב-${fmt(m.t)} — ${m.kind === "shot" ? "צילום מסך" : "«" + m.words.join("», «") + "»"}` } }); } catch (e) { /* the name says it already */ }
      return name;
    }
    async function keepMany(idx, btn) {
      btn.disabled = true; btn.classList.add("busy");
      let ok = 0;
      for (const i of idx) {
        try { await keep(i); ok++; } catch (e) { MF.tell(e.message || "השמירה נכשלה", "bad"); break; }
      }
      if (ctx.onSaved) await ctx.onSaved();
      render();
      if (ok) MF.tell(ok === 1 ? "המסך נשמר בתיקיית הפגישה ב«קבצים»" : `${MF.num(ok)} מסכים נשמרו בתיקיית הפגישה ב«קבצים»`, "ok");
    }
    el.addEventListener("click", (e) => {
      const s = e.target.closest("[data-sc-seek]");
      if (s) { if (ctx.stage) { ctx.stage.seek(+s.dataset.scSeek); if (ctx.onSeek) ctx.onSeek(); } return; }
      const b = e.target.closest("[data-sc-save]");
      if (b) { keepMany([+b.dataset.scSave], b); return; }
      const all = e.target.closest("[data-sc-all]");
      if (all) keepMany(list.map((m, i) => (m.kind === "shot" && !saved.has(MF.frameName(m.t)) ? i : -1)).filter((i) => i >= 0), all);
    });
    render();
    return { count: list.length, refresh: render, destroy() { if (io) io.disconnect(); if (video) { video.removeAttribute("src"); video.load(); } } };
  };
})();
