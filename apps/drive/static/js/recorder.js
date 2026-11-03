/* recorder.js — «הקלטות», the office's voice recorder (Voice Memos, made for an office). It is the
   «קבצים» page opened under /rec (its own tile): it records in the browser (MediaRecorder), keeps
   every second of a take on this device while it is recorded (IndexedDB — a crash, a reload or a
   closed lid loses nothing; an unsaved take is offered back on the next visit), and saves the
   finished take into «קבצים» → /הקלטות through the same resumable upload as every other file. The
   server copies the take into a fresh container on arrival (a browser recording has no length in
   its header and seeks badly), measures its waveform, and every agent reads it from that path.
   The list IS that folder: play in place on the waveform, ±15 s, speed, rename, open in «קבצים»,
   copy the path for an agent, move to the trash. */
(function () {
  "use strict";
  const { html, hooks, state, set, L, ic, fmtWhen, fmtDur, api, tell, ask } = F;
  const U = F.ui;
  const FOLDER = "/הקלטות", SYSTEM = "הקלטות";

  /* ── the takes kept on this device while they are recorded ────────────────── */
  let dbp = null;
  const db = () => dbp || (dbp = new Promise((res, rej) => {
    const r = indexedDB.open("files-recorder", 1);
    r.onupgradeneeded = () => { const d = r.result; d.createObjectStore("takes", { keyPath: "id" }); d.createObjectStore("pieces", { keyPath: ["take", "n"] }); };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  }));
  const done = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  const span = (take) => IDBKeyRange.bound([take, 0], [take, Number.MAX_SAFE_INTEGER]);
  const keep = {
    take: async (t) => done((await db()).transaction("takes", "readwrite").objectStore("takes").put(t)),
    piece: async (take, n, blob) => done((await db()).transaction("pieces", "readwrite").objectStore("pieces").put({ take, n, blob })),
    takes: async () => done((await db()).transaction("takes").objectStore("takes").getAll()),
    pieces: async (take) => done((await db()).transaction("pieces").objectStore("pieces").getAll(span(take))),
    drop: async (take) => {
      const t = (await db()).transaction(["takes", "pieces"], "readwrite");
      t.objectStore("takes").delete(take);
      t.objectStore("pieces").delete(span(take));
      return new Promise((res, rej) => { t.oncomplete = res; t.onerror = () => rej(t.error); });
    },
  };

  /* ── the recording engine (one take at a time) ─────────────────────────────── */
  // the container the browser can record, and what the server makes of it on arrival
  const KINDS = [["audio/webm;codecs=opus", "webm", "webm"], ["audio/mp4", "m4a", "mp4"], ["audio/webm", "webm", "webm"], ["audio/ogg;codecs=opus", "ogg", ""]];
  const eng = { stream: null, rec: null, ctx: null, an: null, take: null, n: 0, mem: [], acc: 0, since: 0, levels: [], wake: null, persist: false, raf: 0 };
  const elapsed = () => eng.acc + (eng.rec && eng.rec.state === "recording" ? performance.now() - eng.since : 0);
  const two = (n) => String(n).padStart(2, "0");
  function takeName(ext, at) {
    const d = new Date(at);
    return `${L("הקלטה", "Recording")} ${d.getDate()}.${d.getMonth() + 1}.${d.getFullYear()} ${two(d.getHours())}.${two(d.getMinutes())}.${ext}`;
  }
  const rset = (p) => set({ rec: { ...state.rec, ...p } });

  async function start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) return rset({ phase: "unsupported" });
    rset({ phase: "asking", error: "" });
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      const name = e && e.name;
      return rset({ phase: name === "NotFoundError" || name === "OverconstrainedError" ? "nomic" : name === "NotAllowedError" || name === "SecurityError" ? "denied" : "failed",
        error: String((e && e.message) || e) });
    }
    const [mime, ext, remux] = KINDS.find(([m]) => MediaRecorder.isTypeSupported(m)) || ["", "webm", "webm"];
    let rec;
    try { rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 96000 } : undefined); }
    catch (e) { stream.getTracks().forEach((t) => t.stop()); return rset({ phase: "failed", error: String(e.message || e) }); }
    const at = Date.now();
    const take = { id: "t" + at.toString(36), name: takeName(ext, at), mime: (rec.mimeType || mime || "audio/webm").split(";")[0], remux, at, duration: 0 };
    Object.assign(eng, { stream, rec, take, n: 0, mem: [], acc: 0, since: performance.now(), levels: [] });
    try { await keep.take(take); eng.persist = true; } catch (e) { eng.persist = false; }
    rec.ondataavailable = (e) => {
      if (!e.data || !e.data.size) return;
      const n = eng.n++;
      eng.mem.push(e.data);
      if (eng.persist) keep.piece(take.id, n, e.data).catch(() => { eng.persist = false; });
    };
    rec.onerror = (e) => rset({ phase: "failed", error: String((e.error && e.error.message) || e.type) });
    stream.getAudioTracks().forEach((t) => (t.onended = () => { if (eng.rec === rec && rec.state !== "inactive") stop(); }));
    rec.start(1000);
    meter(stream);
    awake(true);
    rset({ phase: "recording", take, persist: eng.persist });
  }
  function pause() {
    if (!eng.rec || eng.rec.state !== "recording") return;
    eng.acc += performance.now() - eng.since;
    eng.rec.pause();
    rset({ phase: "paused" });
  }
  function resume() {
    if (!eng.rec || eng.rec.state !== "paused") return;
    eng.since = performance.now();
    eng.rec.resume();
    rset({ phase: "recording" });
  }
  function release() {
    cancelAnimationFrame(eng.raf);
    try { eng.ctx && eng.ctx.close(); } catch (e) { /* closed */ }
    if (eng.stream) eng.stream.getTracks().forEach((t) => t.stop());
    awake(false);
    Object.assign(eng, { stream: null, ctx: null, an: null });
  }
  async function stop() {
    const r = eng.rec;
    if (!r || r.state === "inactive") return;
    const ms = elapsed();
    rset({ phase: "saving" });
    await new Promise((res) => { r.onstop = res; try { r.stop(); } catch (e) { res(); } });
    release();
    const take = { ...eng.take, duration: ms / 1000 };
    eng.rec = null;
    try { await keep.take(take); } catch (e) { /* kept in memory below */ }
    save(take, new Blob(eng.mem, { type: take.mime }));
  }
  async function discard() {
    const ok = await ask({ title: L("למחוק את ההקלטה?", "Discard this recording?"), danger: true, ok: L("מחיקה", "Discard"),
      body: L("ההקלטה לא תישמר ב«קבצים» ולא תהיה אפשרות לשחזר אותה.", "It will not be saved and cannot be recovered."),
      facts: [[L("אורך", "Length"), fmtDur(elapsed() / 1000)]] });
    if (!ok) return;
    const r = eng.rec, take = eng.take;
    eng.rec = null;
    try { r && r.state !== "inactive" && r.stop(); } catch (e) { /* stopped */ }
    release();
    if (take) keep.drop(take.id).catch(() => {});
    rset({ phase: "idle" });
  }
  /* the saved take goes the way every file goes — resumable, retried, followed by its key */
  function save(take, blob) {
    const file = new File([blob], take.name, { type: take.mime, lastModified: take.at });
    const [key] = F.upload.enqueue([file], { path: FOLDER, system: SYSTEM, remux: take.remux, quiet: true }) || [];
    set({ rec: { phase: "idle" }, recSaving: { ...state.recSaving, [take.id]: { key, take } } });
  }

  /* the level meter: what the microphone hears, 12 times a second, drawn by LiveWave */
  function meter(stream) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      eng.ctx = new Ctx();
      const src = eng.ctx.createMediaStreamSource(stream);
      eng.an = eng.ctx.createAnalyser();
      eng.an.fftSize = 2048;
      src.connect(eng.an);
    } catch (e) { eng.an = null; }
    const buf = new Float32Array(2048);
    let last = 0;
    const loop = (t) => {
      eng.raf = requestAnimationFrame(loop);
      if (!eng.an || t - last < 80) return;
      last = t;
      if (eng.rec && eng.rec.state === "paused") return;
      eng.an.getFloatTimeDomainData(buf);
      let s = 0;
      for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
      eng.levels.push(Math.min(1, Math.sqrt(s / buf.length) * 4.5));
      if (eng.levels.length > 600) eng.levels.splice(0, eng.levels.length - 600);
    };
    eng.raf = requestAnimationFrame(loop);
  }
  /* a phone keeps its screen on while it records (a sleeping phone may stop the microphone) */
  async function awake(on) {
    try {
      if (on && navigator.wakeLock && !eng.wake) { eng.wake = await navigator.wakeLock.request("screen"); eng.wake.addEventListener("release", () => (eng.wake = null)); }
      if (!on && eng.wake) { await eng.wake.release(); eng.wake = null; }
    } catch (e) { /* not offered here */ }
  }
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && eng.rec && eng.rec.state !== "inactive") awake(true); });
  addEventListener("beforeunload", (e) => { if (eng.rec && eng.rec.state !== "inactive") { e.preventDefault(); e.returnValue = ""; } });

  /* ── the list: the /הקלטות folder of «קבצים» ─────────────────────────────── */
  async function load(quiet) {
    if (!quiet) set({ recList: { ...state.recList, loading: true, error: "" } });
    try {
      const r = await api("api/fs?path=" + encodeURIComponent(FOLDER));
      const files = (r.files || []).filter((f) => (f.mime || "").startsWith("audio") || /\.(webm|m4a|mp3|wav|ogg|opus|aac|flac)$/i.test(f.name))
        .sort((a, b) => String(b.created).localeCompare(String(a.created)));
      set({ recList: { loading: false, error: "", files, folder: r.folder || null } });
    } catch (e) {
      // no folder yet is the empty state, not a failure — the first saved take makes it
      if (e.status === 404) set({ recList: { loading: false, error: "", files: [], folder: null } });
      else set({ recList: { ...state.recList, loading: false, error: e.message || String(e) } });
    }
  }
  /* takes on this device that never reached the server: offered back */
  async function recover() {
    try {
      const saving = new Set(Object.keys(state.recSaving || {}));
      const left = (await keep.takes()).filter((t) => !saving.has(t.id) && (!eng.take || eng.take.id !== t.id || !eng.rec));
      set({ recLeft: left });
    } catch (e) { set({ recLeft: [] }); }
  }
  async function saveLeft(t) {
    const parts = (await keep.pieces(t.id)).sort((a, b) => a.n - b.n).map((p) => p.blob);
    if (!parts.length) { await keep.drop(t.id); return recover(); }
    set({ recLeft: (state.recLeft || []).filter((x) => x.id !== t.id) });
    save(t, new Blob(parts, { type: t.mime }));
  }
  async function dropLeft(t) {
    const ok = await ask({ title: L("למחוק את ההקלטה שלא נשמרה?", "Delete the unsaved recording?"), danger: true, ok: L("מחיקה", "Delete"),
      facts: [[L("הוקלטה", "Recorded"), fmtWhen(new Date(t.at).toISOString().slice(0, 16).replace("T", " "))], [L("אורך", "Length"), t.duration ? fmtDur(t.duration) : L("לא ידוע", "unknown")]] });
    if (!ok) return;
    await keep.drop(t.id);
    recover();
  }

  /* ── what follows a saved take: done → off this device, into the list ─────── */
  function useSaves() {
    const ups = F.useStore((s) => s.uploads);
    const saving = F.useStore((s) => s.recSaving);
    hooks.useEffect(() => {
      Object.entries(saving || {}).forEach(([id, sv]) => {
        const u = ups.find((x) => x.key === sv.key);
        if (u && u.state === "done" && !sv.done) {
          set({ recSaving: { ...state.recSaving, [id]: { ...sv, done: true } } });
          keep.drop(id).catch(() => {});
          tell(L("ההקלטה נשמרה ב«קבצים» → הקלטות", "Saved to Files → Recordings"), "ok");
          setTimeout(() => load(true), 400);
          setTimeout(() => { const n = { ...state.recSaving }; delete n[id]; set({ recSaving: n }); }, 1500);
        }
      });
    }, [ups, saving]);
  }

  /* ── the screens ─────────────────────────────────────────────────────────── */
  function Clock() {
    const [, tick] = hooks.useState(0);
    hooks.useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 250); return () => clearInterval(t); }, []);
    const s = elapsed() / 1000;
    return html`<div class="rc-clock num" aria-live="off">${fmtDur(s)}<small>.${Math.floor((s % 1) * 10)}</small></div>`;
  }
  /* what the microphone hears, newest at the start of the line (the right in Hebrew), drawn in the
     sky — the palette's «in motion» — read off the page's own tokens */
  function LiveWave() {
    const ref = hooks.useRef();
    hooks.useEffect(() => {
      let raf = 0;
      const draw = () => {
        raf = requestAnimationFrame(draw);
        const c = ref.current;
        if (!c) return;
        const w = c.clientWidth, h = c.clientHeight, dpr = Math.min(2, devicePixelRatio || 1);
        if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
        const g = c.getContext("2d");
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        g.clearRect(0, 0, w, h);
        const cs = getComputedStyle(c);
        g.fillStyle = cs.getPropertyValue("--sky-d").trim() || cs.color;
        const bar = 3, gap = 2, n = Math.floor(w / (bar + gap)), lv = eng.levels.slice(-n), rtl = document.dir === "rtl";
        for (let i = 0; i < lv.length; i++) {
          const v = Math.max(0.04, lv[lv.length - 1 - i]), bh = Math.max(2, v * (h - 6));
          const x = rtl ? w - (i + 1) * (bar + gap) : i * (bar + gap);
          g.fillRect(x, (h - bh) / 2, bar, bh);
        }
      };
      raf = requestAnimationFrame(draw);
      return () => cancelAnimationFrame(raf);
    }, []);
    return html`<canvas class="rc-live" ref=${ref} aria-hidden="true"></canvas>`;
  }

  function Sheet() {
    const r = F.useStore((s) => s.rec);
    const paused = r.phase === "paused", saving = r.phase === "saving";
    return html`<section class="rc-sheet" role="region" aria-label=${L("הקלטה פעילה", "Recording")}>
      <div class="rc-sheet-h"><span class=${"rc-dot" + (paused ? " paused" : "")}></span>
        <b>${saving ? L("שומר…", "Saving…") : paused ? L("מושהה", "Paused") : L("מקליט", "Recording")}</b>
        <span class="rc-name" dir="auto">${r.take && r.take.name.replace(/\.[^.]+$/, "")}</span></div>
      <${Clock} />
      <${LiveWave} />
      ${!r.persist && html`<div class="rc-note">${ic("alert", "sm")}${L("הדפדפן לא מאפשר לשמור את ההקלטה במכשיר תוך כדי — אל תסגרו את החלון עד הסיום", "This browser cannot keep the take on the device while recording — keep this window open until you stop")}</div>`}
      <div class="rc-ctl">
        <button class="btn ghost" title=${L("מחיקת ההקלטה", "Discard the recording")} disabled=${saving} onClick=${discard}>${ic("trash", "sm")}${L("מחיקה", "Discard")}</button>
        <button class="rc-stop" title=${L("סיום ושמירה ב«קבצים»", "Stop and save to Files")} aria-label=${L("סיום ושמירה", "Stop and save")} disabled=${saving} onClick=${stop}><span></span></button>
        <button class="btn ghost" title=${paused ? L("המשך הקלטה", "Resume") : L("השהיה", "Pause")} disabled=${saving} onClick=${paused ? resume : pause}>
          ${ic(paused ? "mic" : "pause", "sm")}${paused ? L("המשך", "Resume") : L("השהיה", "Pause")}</button>
      </div>
    </section>`;
  }

  function Dock() {
    const r = F.useStore((s) => s.rec);
    if (r.phase === "recording" || r.phase === "paused" || r.phase === "saving") return html`<${Sheet} />`;
    const msg = {
      denied: L("אין גישה למיקרופון. אפשר לאשר אותה מהסמל שבשורת הכתובת של הדפדפן, ואז ללחוץ שוב.", "No access to the microphone. Allow it from the icon in the browser's address bar, then press again."),
      nomic: L("לא נמצא מיקרופון במכשיר הזה.", "No microphone was found on this device."),
      unsupported: L("הדפדפן הזה לא יודע להקליט. אפשר להקליט ב-Chrome, Edge או Safari עדכניים.", "This browser cannot record. Use a current Chrome, Edge or Safari."),
      failed: L("ההקלטה לא התחילה: ", "The recording did not start: ") + (r.error || ""),
    }[r.phase];
    return html`<footer class="rc-dock">
      ${msg && html`<div class="rc-msg" role="alert">${ic("alert", "sm")}<span>${msg}</span></div>`}
      <button class=${"rc-rec" + (r.phase === "asking" ? " busy" : "")} onClick=${start} disabled=${r.phase === "asking"}
        title=${L("הקלטה חדשה", "New recording")} aria-label=${L("הקלטה חדשה", "New recording")}><span></span></button>
      <div class="rc-hint">${r.phase === "asking" ? L("מבקש גישה למיקרופון…", "Asking for the microphone…") : L("הקלטה חדשה", "New recording")}</div>
    </footer>`;
  }

  const SPEEDS = [1, 1.25, 1.5, 2];
  function Row({ it, list }) {
    const open = F.useStore((s) => s.recOpen === it.id);
    const tiny = F.useStore((s) => !!s.recTiny);
    const p = F.useStore((s) => s.player);
    const cur = p.queue[p.index], mine = !!(cur && cur.id === it.id);
    const dur = (it.meta || {}).duration;
    const play = (e) => { e && e.stopPropagation(); if (mine) F.player.toggle(); else F.player.play(list, list.findIndex((x) => x.id === it.id)); };
    // a widget window has no room to open a take in its row: the take plays, and the player's face takes the window
    const toggleOpen = () => { if (tiny) { if (!mine) play(); set({ recFace: true }); return; } set({ recOpen: open ? null : it.id }); };
    const [rate, setRate] = hooks.useState(1);
    const speed = () => { const r = SPEEDS[(SPEEDS.indexOf(rate) + 1) % SPEEDS.length]; setRate(r); F.player.audio.playbackRate = r; };
    const inFiles = () => {
      const route = "folder/" + encodeURIComponent(it.folder || "") + "/file/" + encodeURIComponent(it.id);
      try { if (window.top !== window && top.location.hash.startsWith("#/m/")) { top.location.hash = "#/m/drive/" + route; return; } } catch (e) { /* not the console */ }
      location.href = F.BASE.replace(/[^/]+\/$/, "drive/") + route;
    };
    const after = (fn) => async () => { await fn(); load(true); };
    return html`<div class=${"rc-row" + (open ? " open" : "") + (mine && p.playing ? " playing" : "")}>
      <div class="rc-line" role="button" tabIndex="0" aria-expanded=${open} onClick=${toggleOpen}
        onKeyDown=${(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggleOpen())}>
        <button class="rc-play" title=${mine && p.playing ? L("השהיה", "Pause") : L("ניגון", "Play")} onClick=${play}>${ic(mine && p.playing ? "pause" : "play", "sm")}</button>
        <div class="rc-t"><b><${U.Name} name=${it.name} /></b><span>${fmtWhen(it.created)}${dur ? " · " + fmtDur(dur) : ""}</span></div>
        <div class="rc-mini"><${U.WaveThumb} it=${it} /></div>
      </div>
      ${open && !tiny && html`<div class="rc-open">
        <${F.player.Wave} it=${it} time=${mine ? p.time : 0} duration=${mine ? p.duration || dur : dur || 0} tall />
        <div class="times"><span class="num">${fmtDur(mine ? p.time : 0)}</span><span class="num">${fmtDur(mine ? p.duration || dur : dur || 0)}</span></div>
        <div class="rc-pctl">
          <button class="btn sm ghost rc-speed" title=${L("מהירות ניגון", "Playback speed")} onClick=${speed}><span class="num">${rate}×</span></button>
          <button class="icbtn" title=${L("15 שניות אחורה", "Back 15 seconds")} onClick=${() => (mine ? F.player.skip(-15) : play())}>${ic("back15")}</button>
          <button class="rc-big" title=${mine && p.playing ? L("השהיה", "Pause") : L("ניגון", "Play")} onClick=${play}>${ic(mine && p.playing ? "pause" : "play", "lg")}</button>
          <button class="icbtn" title=${L("15 שניות קדימה", "Forward 15 seconds")} onClick=${() => (mine ? F.player.skip(15) : play())}>${ic("fwd15")}</button>
          <span class="rc-speed-pad"></span>
        </div>
        <div class="rc-acts">
          <button class="btn sm ghost" title=${L("שינוי השם", "Rename")} onClick=${after(() => F.data.rename(it))}>${ic("edit", "sm")}${L("שינוי שם", "Rename")}</button>
          <button class="btn sm ghost" title=${L("פתיחה ב«קבצים»", "Open in Files")} onClick=${inFiles}>${ic("folder", "sm")}${L("ב«קבצים»", "In Files")}</button>
          <button class="btn sm ghost" title=${L("העתקת הנתיב — כך סוכן מוצא את ההקלטה", "Copy the path — how an agent finds it")} onClick=${() => F.data.copyPath(it)}>${ic("bot", "sm")}${L("נתיב לסוכנים", "Path for agents")}</button>
          <button class="btn sm ghost danger" title=${L("העברה לאשפה של «קבצים»", "Move to the trash in Files")} onClick=${after(() => F.data.trash([it]))}>${ic("trash", "sm")}${L("לאשפה", "Trash")}</button>
        </div>
      </div>`}
    </div>`;
  }

  function Pending() {
    const saving = F.useStore((s) => s.recSaving) || {};
    const ups = F.useStore((s) => s.uploads);
    const rows = Object.entries(saving).filter(([, v]) => !v.done);
    if (!rows.length) return null;
    return html`${rows.map(([id, v]) => {
      const u = ups.find((x) => x.key === v.key) || {};
      const pct = u.size ? Math.round((Math.min(u.sent || 0, u.size) / u.size) * 100) : 0;
      const bad = u.state === "failed";
      return html`<div class=${"rc-row pending" + (bad ? " bad" : "")} key=${id}>
        <div class="rc-line"><span class="rc-play">${bad ? ic("alert", "sm") : html`<span class="spin-sm"></span>`}</span>
          <div class="rc-t"><b dir="auto">${v.take.name}</b><span>${bad ? L("השמירה נכשלה — ההקלטה שמורה במכשיר. ", "Saving failed — the take is kept on this device. ") + (u.error || "")
            : u.state === "finishing" ? L("מסיים לשמור…", "Finishing…") : L(`נשמרת ב«קבצים»… ${pct}%`, `Saving to Files… ${pct}%`)}</span></div>
          ${bad && html`<button class="btn sm" onClick=${() => F.upload.retry(v.key)}>${ic("refresh", "sm")}${L("נסה שוב", "Retry")}</button>`}
        </div></div>`;
    })}`;
  }

  function Left() {
    const left = F.useStore((s) => s.recLeft) || [];
    if (!left.length) return null;
    return html`${left.map((t) => html`<div class="rc-left" key=${t.id} role="status">
      ${ic("alert", "sm")}<div class="rc-t"><b>${L("הקלטה שלא נשמרה", "A recording that was not saved")}</b>
        <span dir="auto">${t.name}${t.duration ? " · " + fmtDur(t.duration) : ""}</span></div>
      <button class="btn sm primary" onClick=${() => saveLeft(t)}>${ic("upload", "sm")}${L("שמירה", "Save")}</button>
      <button class="btn sm ghost danger" onClick=${() => dropLeft(t)}>${L("מחיקה", "Delete")}</button>
    </div>`)}`;
  }

  function Recorder() {
    const list = F.useStore((s) => s.recList);
    const files = list.files || [];
    const total = files.reduce((s, f) => s + ((f.meta || {}).duration || 0), 0);
    useSaves();
    hooks.useEffect(() => {
      load(); recover();
      const build = () => api("api/changes").then((d) => F.sawBuild(d.build)).catch(() => {});
      build();
      // a take saved from another device appears; a deploy since this window opened is offered
      const t = setInterval(() => { if (document.visibilityState === "visible") { load(true); build(); } }, 20000);
      return () => clearInterval(t);
    }, []);
    const r = F.useStore((s) => s.rec);
    /* a window too small for the whole page (as in «קבצים»: under 300 tall, or under 560×440) is a
       widget: the newest takes that fit and the button — while recording, the recording alone; while a
       take plays from it, the player's face */
    const root = hooks.useRef(), listEl = hooks.useRef();
    const tiny = F.useStore((s) => !!s.recTiny);
    const fit = F.useStore((s) => (s.recFit == null ? 1 : s.recFit));      // 0 is an answer: no take fits whole
    const faceOn = F.useStore((s) => !!s.recFace && s.player.index >= 0 && s.player.queue.length > 0);
    F.useStore((s) => (s.recLeft || []).length + Object.values(s.recSaving || {}).filter((v) => !v.done).length);   // measured again when these come and go
    hooks.useLayoutEffect(() => {
      const ro = new ResizeObserver(() => {
        const b = root.current.getBoundingClientRect();
        const t = b.height < 300 || (b.width < 560 && b.height < 440);
        if (t !== !!state.recTiny) set({ recTiny: t });
        if (t) document.body.dataset.tiny = ""; else delete document.body.dataset.tiny;
      });
      ro.observe(root.current);
      return () => ro.disconnect();
    }, []);
    /* the office's notices («saved to Files → Recordings») sit above the dock — the big button, or the
       recording's sheet — never over it (files.css: #bina-tell is lifted by --tell-lift); in a widget they
       come from the top (body[data-tiny]) */
    hooks.useLayoutEffect(() => {
      const dock = root.current && root.current.querySelector(":scope > .rc-dock, :scope > .rc-sheet");
      const put = () => document.body.style.setProperty("--tell-lift",
        (dock && !state.recTiny ? Math.max(0, Math.round(innerHeight - dock.getBoundingClientRect().top)) : 0) + "px");
      put();
      if (!dock) return;
      const ro = new ResizeObserver(put);
      ro.observe(dock);
      addEventListener("resize", put);
      return () => { ro.disconnect(); removeEventListener("resize", put); };
    }, [tiny, r.phase, faceOn]);     // the dock is another element when the phase, the size class or the face changes
    const live = ["recording", "paused", "saving"].includes(r.phase);
    const face = tiny && faceOn && !live;
    // how many takes the list holds whole (a row measured: 62 + 6) under what must stay in it — an unsaved
    // take, a take being saved: the rest wait for a larger window
    hooks.useLayoutEffect(() => {
      const l = listEl.current;
      if (!l || !tiny) return;
      const measure = () => {
        let room = l.clientHeight - 8;
        l.querySelectorAll(":scope > .rc-left, :scope > .rc-row.pending").forEach((el) => { room -= el.offsetHeight + parseFloat(getComputedStyle(el).marginBottom || 0); });
        const one = l.querySelector(":scope > .rc-row:not(.pending)");
        const n = Math.max(0, Math.floor(room / (one ? one.offsetHeight + parseFloat(getComputedStyle(one).marginBottom || 0) : 68)));
        if (n !== state.recFit) set({ recFit: n });
      };
      measure();
      const ro = new ResizeObserver(measure);
      ro.observe(l);
      return () => ro.disconnect();
    });
    const shown = tiny ? files.slice(0, fit) : files;
    const toFiles = () => {
      try { if (window.top !== window && top.location.hash.startsWith("#/m/")) { top.location.hash = "#/m/drive/" + (list.folder ? "folder/" + encodeURIComponent(list.folder.id) : "files"); return; } } catch (e) { /* not the console */ }
      location.href = F.BASE.replace(/[^/]+\/$/, "drive/") + (list.folder ? "folder/" + encodeURIComponent(list.folder.id) : "files");
    };
    if (face) return html`<div class="rc" ref=${root} data-tiny="" data-face="">
      <div class="wg"><${F.widget.PlayerFace} onMin=${() => set({ recFace: false })} /></div><${F.widget.Publish} /></div>`;
    return html`<div class="rc" ref=${root} data-tiny=${tiny ? "" : null} data-live=${tiny && live ? "" : null}>
      <header class="rc-top">
        <div class="rc-title"><b>${L("הקלטות", "Recordings")}</b>
          <span>${files.length ? F.count(files.length, ["הקלטה אחת", "1 recording"], ["הקלטות", "recordings"]) + (total ? " · " + fmtDur(total) : "") : L("נשמרות ב«קבצים» → הקלטות", "Saved to Files → Recordings")}</span></div>
        <button class="icbtn" title=${L("התיקייה ב«קבצים»", "The folder in Files")} onClick=${toFiles}>${ic("folder")}</button>
      </header>
      <main class="rc-list" ref=${listEl} aria-busy=${list.loading ? "true" : "false"}>
        <${F.NewVersion} busy=${["asking", "recording", "paused", "saving"].includes(r.phase) || Object.values(F.state.recSaving || {}).some((v) => !v.done)} />
        <${Left} />
        <${Pending} />
        ${list.error ? html`<${U.Empty} bad icon="alert" title=${L("לא הצלחתי לטעון את ההקלטות", "Could not load the recordings")} text=${list.error}>
            <button class="btn" onClick=${() => load()}>${ic("refresh", "sm")}${L("נסה שוב", "Try again")}</button></${U.Empty}>`
          : list.loading && !files.length ? html`<${U.Skeleton} rows=${4} />`
          : !files.length && tiny ? html`<div class="rc-none">${ic("mic")}<span>${L("עוד אין הקלטות — הכפתור למטה מתחיל אחת", "No recordings yet — the button below starts one")}</span></div>`
          : !files.length ? html`<${U.Empty} icon="mic" title=${L("עוד אין הקלטות", "No recordings yet")}
              text=${L("לחיצה על הכפתור למטה מתחילה הקלטה. כל הקלטה נשמרת ב«קבצים», בתיקייה «הקלטות», וכל סוכן יכול לעבוד איתה.", "Press the button below to record. Every recording is saved in Files, in «Recordings», where every agent can work with it.")} />`
          : shown.map((it) => html`<${Row} key=${it.id} it=${it} list=${files} />`)}
      </main>
      <${Dock} />
      <${F.widget.Publish} />
    </div>`;
  }

  function boot() {
    set({ rec: { phase: "idle" }, recList: { loading: true, files: [], error: "", folder: null }, recSaving: {}, recLeft: [], recOpen: null });
    F.render(html`<${Recorder} />`, document.getElementById("app"));
    document.getElementById("app").removeAttribute("aria-busy");
    document.title = L("הקלטות", "Recordings");
  }
  F.recorder = { boot, start, stop, pause, resume, discard, load, eng };
})();
