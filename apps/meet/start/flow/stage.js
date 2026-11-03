/* «פגישות» — stage.js: a meeting's one clock and its media (the recording's video, the side recordings), and every
   track of it on one zoomable time axis: screens, sound, who held the floor, every line and every word, topics,
   decisions, tasks, questions, the moments people marked. Media time runs LEFT TO RIGHT inside the right-to-left
   page — Material 3's rule for Hebrew and YouTube's Hebrew player: the screen, its controls and the axis are one
   left-to-right island, and only their words are Hebrew. */
(() => {
  "use strict";
  const MF = window.MF;

  MF.Stage = function Stage(M, mount, opt = {}) {
    const { esc, fmt, ic } = MF;
    const host = mount.host || document.documentElement;
    const cssv = (n) => getComputedStyle(host).getPropertyValue(n).trim() || "transparent";
    const hueOf = opt.hue || MF.people(M.colors);
    const fill = (who) => cssv("--" + hueOf(who));
    const textOf = opt.textOf || ((x) => x.text);
    const stateOf = opt.stateOf || (() => "");
    const DUR = Math.max(1, +M.meeting.duration || 0);
    const VDUR = M.video ? (+M.video.duration || DUR) : 0;
    const offs = [];
    const on = (el, ev, fn, o) => { if (!el) return; el.addEventListener(ev, fn, o); offs.push(() => el.removeEventListener(ev, fn, o)); };
    const subs = new Set();
    const abs = (u) => {
      if (!u) return u;
      if (/^([a-z][a-z0-9+.-]*:|\/|#)/i.test(u)) return u;
      if (u.startsWith("../../")) return MF.url(u.slice(6));          // the recorder's own files: …/recordings/<session>/…
      return (opt.base || "") + u;                                     // the meeting's flow folder: frames/, media/, docs/
    };
    const frameSrc = (f, kind) => (window.FRAMES && window.FRAMES[f]) || abs(`frames/${kind}/${f}`);
    const q = (sel, el) => (el || mount.root || document).querySelector(sel);

    /* ---------- the screen ---------- */
    if (mount.player) {
      mount.player.innerHTML = `
        <div class="mf-screen" dir="ltr">
          <video playsinline preload="metadata"></video>
          <img class="mf-still" alt="" hidden>
          <div class="mf-novideo" hidden>${ic("headphones")}<span dir="rtl">אין וידאו בפגישה הזו — הקול והתמלול</span></div>
          <div class="mf-after" dir="rtl" hidden></div>
          <div class="mf-cap" aria-hidden="true"></div>
          <button class="mf-bigplay" type="button" aria-label="ניגון">${ic("play")}</button>
        </div>`;
    }
    const video = mount.player ? mount.player.querySelector("video") : document.createElement("video");
    const still = mount.player ? mount.player.querySelector(".mf-still") : null;
    if (M.video && M.video.src) video.src = abs(M.video.src);
    else if (mount.player) {
      video.hidden = true;
      if ((M.frames || []).length) still.hidden = false;
      else mount.player.querySelector(".mf-novideo").hidden = false;
    }

    /* ---------- sound tracks: the meeting's own, and the side recordings (an iPad, a phone, an upload) ---------- */
    const audio = (M.audio || []).concat(opt.extraAudio || []).map((a) => {
      const el = a.src ? new Audio() : null;
      if (el) { el.preload = "none"; el.src = abs(a.src); }
      let env = null;
      if (a.env && a.env.b64) { const b = atob(a.env.b64); env = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) env[i] = b.charCodeAt(i); }
      return { ...a, el, env, rate: a.env ? a.env.rate : 10, on: a.id === "meet", offset: +a.offset || 0, duration: +a.duration || DUR };
    });
    const label = (a) => (a.id === "meet" ? "הפגישה" : a.short || a.label || a.id);

    /* ---------- the one clock ---------- */
    let t = 0, playing = false, rate = 1, follow = true, raf = 0, timer = 0, wall = null;
    const covering = (x) => audio.find((a) => a.el && a.on && x >= a.offset && x < a.offset + a.duration)
      || audio.find((a) => a.el && x >= a.offset && x < a.offset + a.duration);
    function masterTime() {
      if (M.video && t < VDUR - 0.05 && !video.ended) { wall = null; return video.currentTime; }
      const a = covering(t);
      if (a && !a.el.paused) { wall = null; return a.offset + a.el.currentTime; }
      if (!playing) return t;
      const now = performance.now();               // no media at this moment (a gap, a transcript-only meeting): a wall clock
      if (!wall) wall = { t0: t, at: now };
      return wall.t0 + ((now - wall.at) / 1000) * rate;
    }
    const videoActive = () => M.video && t < VDUR - 0.05;
    const videoRolling = () => !video.paused && !video.seeking && video.readyState >= 3;
    function syncSide(force) {
      const masterOk = videoActive() ? videoRolling() : true;   // side recordings move only while the master really moves
      for (const a of audio) {
        if (!a.el) continue;
        const inside = t >= a.offset && t < a.offset + a.duration;
        const afterVideo = !M.video || t >= VDUR - 0.05;
        const want = playing && masterOk && inside && (a.on || (afterVideo && a === covering(t)));
        a.el.muted = !(a.on || afterVideo);
        if (want) {
          const local = t - a.offset;
          if (a.el.paused) { a.el.currentTime = local; a.el.playbackRate = rate; a.el.play().catch(() => {}); }
          else if (force || Math.abs(a.el.currentTime - local) > 0.3) a.el.currentTime = local;
        } else if (!a.el.paused) a.el.pause();
      }
      const meet = audio.find((a) => a.id === "meet");
      video.muted = meet ? !meet.on : false;
    }
    function tick() {
      if (!playing) return;
      t = Math.min(DUR, masterTime());
      if (t >= DUR) { pause(); return; }
      syncSide(false);
      paint();
    }
    const frameLoop = () => { tick(); if (playing) raf = requestAnimationFrame(frameLoop); };
    function play() {
      if (playing) return;
      if (t >= DUR - 0.5) t = 0;
      playing = true; setPlayIcon();
      if (M.video && t < VDUR - 0.05) { video.playbackRate = rate; video.play().catch(() => {}); }
      syncSide(true);
      raf = requestAnimationFrame(frameLoop);
      timer = setInterval(tick, 120);              // keeps the clock and the side recordings in step when frames are throttled
      emit("play");
    }
    function pause() {
      if (!playing && video.paused) { paint(); return; }
      playing = false; wall = null; setPlayIcon();
      video.pause(); for (const a of audio) if (a.el) a.el.pause();
      cancelAnimationFrame(raf); clearInterval(timer);
      MF.setHash("t" + Math.floor(t));
      paint();
      emit("pause");
    }
    function seek(x, o = {}) {
      t = Math.max(0, Math.min(DUR, +x || 0)); wall = null;
      if (M.video) { try { video.currentTime = Math.min(t, VDUR - 0.05); } catch (e) { /* metadata not yet */ } }
      if (playing && M.video && t < VDUR - 0.05 && video.paused) video.play().catch(() => {});
      syncSide(true);
      if (!playing && o.hash !== false) MF.setHash("t" + Math.floor(t));
      paint(true);
      emit("seek");
    }
    for (const ev of ["playing", "waiting", "seeked", "stalled"]) on(video, ev, () => { if (playing) syncSide(true); });
    on(video, "ended", () => { if (playing) { t = VDUR; syncSide(true); } });
    on(video, "error", () => emit("mediaerror"));
    function setPlayIcon() {
      for (const b of (mount.root || document).querySelectorAll(".mf-play, .mf-bigplay")) {
        b.innerHTML = ic(playing ? "pause" : "play"); b.setAttribute("aria-label", playing ? "עצירה" : "ניגון");
        b.title = playing ? "עצירה (רווח)" : "ניגון (רווח)";
      }
      if (mount.player) mount.player.classList.toggle("is-playing", playing);
    }

    /* ---------- transport ---------- */
    if (mount.transport) {
      mount.transport.innerHTML = `
        <div class="mf-transport" dir="ltr" role="toolbar" aria-label="ניגון">
          <button class="mf-tb mf-play" type="button">${ic("play")}</button>
          <button class="mf-tb" type="button" data-skip="-10" title="10 שניות אחורה (חץ שמאלה)" aria-label="10 שניות אחורה">${ic("back10")}</button>
          <button class="mf-tb" type="button" data-skip="10" title="10 שניות קדימה (חץ ימינה)" aria-label="10 שניות קדימה">${ic("fwd10")}</button>
          <span class="mf-clock"><time class="mf-now">${fmt(0, DUR >= 3600)}</time><span class="mf-sep">/</span><time class="mf-dur">${fmt(DUR)}</time></span>
          <select class="mf-rate" title="מהירות ניגון" aria-label="מהירות ניגון">${[0.75, 1, 1.25, 1.5, 1.75, 2].map((r) => `<option value="${r}"${r === 1 ? " selected" : ""}>${r}×</option>`).join("")}</select>
          <span class="mf-tracks" role="group" aria-label="ערוצי קול">${audio.filter((a) => a.el || a.id === "meet").map((a, i) => `<button type="button" class="mf-chip${a.on ? " on" : ""}" data-a="${audio.indexOf(a)}" aria-pressed="${a.on}" title="${esc(a.label || label(a))} — להשמיע או להשתיק">${ic(a.on ? "volume" : "mute")}<span dir="auto">${esc(label(a))}</span></button>`).join("")}</span>
          <span class="mf-grow"></span>
          <button class="mf-tb mf-follow on" type="button" aria-pressed="true" title="התמלול וציר הזמן עוקבים אחרי הרגע המתנגן" aria-label="מעקב">${ic("target")}</button>
          <span class="mf-zoombox"><button class="mf-tb" type="button" data-zoom="out" title="להקטין את ציר הזמן (−)" aria-label="להקטין">${ic("zoomOut")}</button><input class="mf-zoom" type="range" min="0" max="1000" value="0" aria-label="זום בציר הזמן"><button class="mf-tb" type="button" data-zoom="in" title="להגדיל את ציר הזמן (+)" aria-label="להגדיל">${ic("zoomIn")}</button><button class="mf-tb" type="button" data-zoom="fit" title="כל הפגישה בציר" aria-label="כל הפגישה">${ic("expand")}</button></span>
        </div>`;
      on(mount.transport, "click", (e) => {
        const b = e.target.closest("button"); if (!b) return;
        if (b.classList.contains("mf-play")) playing ? pause() : play();
        else if (b.dataset.skip) seek(t + +b.dataset.skip);
        else if (b.dataset.a) {
          const a = audio[+b.dataset.a]; a.on = !a.on;
          b.classList.toggle("on", a.on); b.setAttribute("aria-pressed", a.on); b.querySelector("svg").outerHTML = ic(a.on ? "volume" : "mute");
          syncSide(true); drawWaves();
        } else if (b.classList.contains("mf-follow")) setFollow(!follow);
        else if (b.dataset.zoom === "in") zoomTo(pps * 1.6);
        else if (b.dataset.zoom === "out") zoomTo(pps / 1.6);
        else if (b.dataset.zoom === "fit") zoomTo(fitPps(), 0);
      });
      on(q(".mf-rate", mount.transport), "change", (e) => { rate = +e.target.value; video.playbackRate = rate; for (const a of audio) if (a.el) a.el.playbackRate = rate; });
      on(q(".mf-zoom", mount.transport), "input", (e) => zoomTo(fromSlider(+e.target.value)));
    }
    if (mount.player) on(mount.player, "click", (e) => { if (e.target.closest(".mf-bigplay") || e.target === video || e.target === still) playing ? pause() : play(); });
    function setFollow(v) {
      follow = !!v;
      for (const b of (mount.root || document).querySelectorAll(".mf-follow")) { b.classList.toggle("on", follow); b.setAttribute("aria-pressed", follow); }
      emit("follow");
    }

    /* ---------- the lanes ---------- */
    const tl = mount.timeline;
    let pps = 0.2;
    const LANES = [];
    const hidden = new Set(MF.store.get("hiddenLanes", ["captions", "likes", "insights"]));
    let playhead = null, lanes = null, inner = null, box = null, heads = null, ruler = null, tip = null, wordsC = null;
    const allTurns = (M.turns || []).concat((M.tail || []).map((x) => ({ ...x, tail: true })));
    const toks = (x) => String(textOf(x) || "").split(/\s+/).filter(Boolean);
    if (tl) {
      tl.innerHTML = `
        <div class="mf-tl" dir="ltr">
          <div class="mf-heads"><div class="mf-h mf-h-ruler"><button class="mf-tb sm mf-lanesbtn" type="button" title="אילו שורות להציג בציר" aria-expanded="false">${ic("layers")}<span dir="rtl">שורות</span></button></div></div>
          <div class="mf-lanes" tabindex="0" aria-label="ציר הזמן של הפגישה — לחיצה קופצת לרגע"><div class="mf-inner"><canvas class="mf-ruler"></canvas><div class="mf-lanebox"></div><div class="mf-playhead" aria-hidden="true"><i></i></div></div></div>
          <div class="mf-lanemenu" dir="rtl" hidden></div>
        </div>`;
      lanes = q(".mf-lanes", tl); inner = q(".mf-inner", tl); playhead = q(".mf-playhead", tl); box = q(".mf-lanebox", tl); heads = q(".mf-heads", tl); ruler = q(".mf-ruler", tl);
      tip = document.createElement("div"); tip.className = "mf-tip"; tip.hidden = true; document.body.appendChild(tip);
      offs.push(() => tip.remove());
    }
    function lane(id, title, group, cls = "") {
      if (!tl) return document.createElement("div");
      const n = LANES.length;
      heads.insertAdjacentHTML("beforeend", `<div class="mf-h ${cls}" data-lane="${id}" data-g="${group}"${hidden.has(id) ? " hidden" : ""}><span dir="rtl">${esc(title)}</span></div>`);
      const el = document.createElement("div"); el.className = "mf-lane " + cls; el.dataset.lane = id; el.dataset.g = group;
      if (hidden.has(id)) el.hidden = true;
      box.appendChild(el); LANES.push({ id, title, group, el, n }); return el;
    }
    const shown = (id) => !hidden.has(id);
    const item = (cls, s, d, html, tipText, data, style) => `<div class="${cls}" style="--s:${(+s).toFixed(2)};--d:${Math.max(0.2, +d).toFixed(2)}${style ? ";" + style : ""}" data-tip="${esc(tipText)}" ${data || ""}>${html}</div>`;
    function buildLanes() {
      if (!tl) return;
      box.innerHTML = ""; heads.querySelectorAll(".mf-h:not(.mf-h-ruler)").forEach((h) => h.remove()); LANES.length = 0; wordsC = null;
      if ((M.frames || []).length) {
        const L = lane("frames", "וידאו", "media");
        L.innerHTML = M.frames.map((f, i) => {
          const d = (M.frames[i + 1] ? M.frames[i + 1].t : f.t + 20) - f.t;
          return `<div class="mf-fr" style="--s:${f.t};--d:${d}" data-bg="${esc(frameSrc(f.f, "t"))}" data-tip="${fmt(f.t)}" data-k="frame" data-i="${i}"></div>`;
        }).join("");
      }
      if ((M.screens || []).length) {
        const L = lane("screens", "מה על המסך", "media");
        L.innerHTML = M.screens.map((s, i) => item("mf-it scr" + (s.kind === "camera" ? " cam" : ""), s.s, s.e - s.s, `<span dir="auto">${esc(s.label)}</span>`, `${fmt(s.s)}–${fmt(s.e)}\n${s.label}\n${s.detail || ""}`, `data-k="screen" data-i="${i}"`)).join("");
      }
      for (const a of audio) {
        if (!a.env && !a.el) continue;
        const L = lane("a-" + a.id, "קול · " + label(a), "media", "wave");
        if (a.env) { const c = document.createElement("canvas"); c.dataset.audio = a.id; L.appendChild(c); }
        else L.innerHTML = item("mf-it span", a.offset, a.duration, "", `${label(a)}\n${fmt(a.offset)}–${fmt(a.offset + a.duration)}`, "");
      }
      if ((M.presence || []).length) {
        const who = [...new Set(M.presence.map((p) => p.who))];
        for (const w of who) {
          const L = lane("pr-" + who.indexOf(w), "בשיחה · " + w, "speech");
          L.innerHTML = M.presence.filter((p) => p.who === w).map((p) => item("mf-it flr", p.s, p.e - p.s, "", `${w} ${fmt(p.s)}–${fmt(p.e)}`, "", `background:${fill(w)}`)).join("");
        }
      }
      if ((M.floor || []).length) {
        const L = lane("floor", "מי מדבר", "speech");
        L.innerHTML = M.floor.map((f) => item("mf-it flr", f.s, f.e - f.s, "", `${f.who} ${fmt(f.s)}`, "", `background:${fill(f.who)}`)).join("");
      }
      {
        const L = lane("turns", M.meeting.transcript_label || "תמלול", "speech", "tall");
        L.innerHTML = allTurns.map((x, i) => item("mf-it turn", x.s, Math.max(0.5, x.e - x.s), `<span dir="auto">${esc(textOf(x) || "—")}</span>`,
          `${fmt(x.s)} ${x.who}${x.tail ? " · אחרי השיחה" : ""}\n${textOf(x)}`, `data-k="turn" data-i="${i}"`, `--c:${fill(x.who)}`)).join("");
      }
      if (allTurns.some((x) => x.w)) { wordsC = document.createElement("canvas"); lane("words", "מילים", "speech").appendChild(wordsC); }
      if ((M.captions || []).length) {
        const L = lane("captions", "כתוביות חיות", "speech");
        if (shown("captions")) L.innerHTML = M.captions.map((c, i) => item("mf-it cap", c.s, Math.max(1, (c.e || c.s + 8) - c.s), `<span dir="auto">${esc(c.text)}</span>`, `${fmt(c.s)} (כתובית חיה)\n${c.text}`, `data-k="caption" data-i="${i}"`)).join("");
      }
      if ((M.topics || []).length) {
        const L = lane("topics", "נושאים", "content", "tall");
        L.innerHTML = M.topics.map((x, i) => item("mf-it top", x.s, Math.max(5, x.e - x.s), `<span dir="auto">${esc(x.title)}</span>`, `${fmt(x.s)}–${fmt(x.e)}\n${x.title}`, `data-k="topic" data-i="${i}"`)).join("");
      }
      const markers = (id, title, arr, cls, k) => {
        if (!arr || !arr.length) return;
        const L = lane(id, title, "content");
        if (shown(id)) L.innerHTML = arr.map((x, i) => `<div class="mf-mk ${typeof cls === "function" ? cls(x) : cls} st-${stateOf(k, x) || "none"}" style="--s:${+x.t || 0}" data-tip="${esc(fmt(x.t) + "\n" + (x.id ? x.id + " · " : "") + (x.text || x.label || ""))}" data-k="${k}" data-i="${i}"></div>`).join("");
      };
      markers("marks", "סימונים", opt.marks || [], (x) => "mark " + (x.label || ""), "mark");
      markers("decisions", "החלטות", M.decisions, "dec", "decision");
      markers("tasks", "משימות", M.tasks, "task", "task");
      markers("questions", "שאלות פתוחות", M.questions, "q", "question");
      markers("insights", "תובנות", M.insights, "ins", "insight");
      markers("likes", "אהבו / דחו", M.likes, (x) => (x.kind === "rejected" ? "rej" : "like"), "like");
      laneMenu();
    }
    function laneMenu() {
      const menu = tl && q(".mf-lanemenu", tl); if (!menu) return;
      const G = { media: "מדיה", speech: "דיבור", content: "תוכן" };
      menu.innerHTML = `<div class="mf-lm-h">שורות בציר הזמן</div>` + Object.entries(G).map(([g, gh]) => {
        const rows = LANES.filter((l) => l.group === g); if (!rows.length) return "";
        return `<div class="mf-lm-g">${gh}</div>` + rows.map((l) => `<label class="mf-lm-row"><input type="checkbox" data-l="${esc(l.id)}"${hidden.has(l.id) ? "" : " checked"}><span>${esc(l.title)}</span></label>`).join("");
      }).join("");
    }
    if (tl) {
      on(q(".mf-lanesbtn", tl), "click", (e) => {
        const menu = q(".mf-lanemenu", tl), open = menu.hidden;
        menu.hidden = !open; e.currentTarget.setAttribute("aria-expanded", open);
      });
      on(q(".mf-lanemenu", tl), "change", (e) => {
        const id = e.target.dataset.l; if (!id) return;
        if (e.target.checked) hidden.delete(id); else hidden.add(id);
        MF.store.set("hiddenLanes", [...hidden]);
        const box1 = tl.querySelector(`.mf-lane[data-lane="${CSS.escape(id)}"]`);
        if (e.target.checked && box1 && !box1.childElementCount) { buildLanes(); layout(); return; }   // drawn the first time it is shown
        for (const el of tl.querySelectorAll(`[data-lane="${CSS.escape(id)}"]`)) el.hidden = !e.target.checked;
        layout();
      });
      on(document, "click", (e) => {
        const menu = q(".mf-lanemenu", tl);
        if (menu && !menu.hidden && !e.target.closest(".mf-lanemenu, .mf-lanesbtn")) { menu.hidden = true; q(".mf-lanesbtn", tl).setAttribute("aria-expanded", "false"); }
      });
    }

    /* ---------- drawing: the ruler, the sound, the words ---------- */
    let W = 0;                                     // the axis's visible width, kept by the ResizeObserver
    const width = () => W || (W = lanes ? lanes.clientWidth : 800);
    const fitPps = () => Math.max(0.005, (width() - 4) / DUR);
    function layout() {
      if (!tl) return;
      inner.style.width = Math.ceil(DUR * pps) + "px";
      inner.style.setProperty("--pps", pps);
      inner.classList.toggle("far", pps < 1.5);
      drawRuler(); drawWaves(); drawWords(); paint(true);
    }
    let SL = 0;                                    // the axis's scroll, kept by its scroll event (reading it forces a layout)
    const setSL = (v) => { SL = Math.max(0, Math.min(v, DUR * pps - width())); lanes.scrollLeft = SL; };
    const view = () => { const w = width(); return { x0: SL, w, t0: SL / pps, t1: (SL + w) / pps }; };
    function prepCanvas(c, h) {
      const v = view(), dpr = window.devicePixelRatio || 1;
      c.style.left = v.x0 + "px"; c.style.width = v.w + "px"; c.style.height = h + "px";
      c.width = Math.max(1, Math.round(v.w * dpr)); c.height = Math.max(1, Math.round(h * dpr));
      const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, v.w, h); return { g, v };
    }
    const font = (px, w) => `${w || 400} ${px}px ${cssv("--font") || "system-ui"}`;
    function drawRuler() {
      if (!ruler || !width()) return;
      const { g, v } = prepCanvas(ruler, 26);
      const steps = [1, 5, 10, 30, 60, 120, 300, 600, 900, 1800, 3600];
      const step = steps.find((s) => s * pps >= 74) || 3600;
      g.fillStyle = cssv("--muted"); g.strokeStyle = cssv("--line"); g.font = font(11); g.textBaseline = "top";
      for (let s = Math.floor(v.t0 / step) * step; s <= v.t1; s += step) {
        const x = s * pps - v.x0; g.beginPath(); g.moveTo(x + 0.5, 15); g.lineTo(x + 0.5, 26); g.stroke(); g.fillText(fmt(s), x + 4, 3);
      }
      if (M.video && VDUR < DUR - 1) {
        const x = VDUR * pps - v.x0;
        if (x > 0 && x < v.w) { g.fillStyle = cssv("--lime-d"); g.fillRect(x, 0, 2, 26); g.textAlign = "right"; g.fillText("סוף הווידאו", x - 4, 14); g.textAlign = "start"; }
      }
    }
    function showFrames() {
      const L = box && box.querySelector('.mf-lane[data-lane="frames"]'); if (!L || L.hidden) return;
      const v = view(), pad = v.t1 - v.t0;
      for (const el of L.children) {
        if (!el.dataset.bg) continue;
        const i = +el.dataset.i, f = M.frames[i];
        const d = ((M.frames[i + 1] ? M.frames[i + 1].t : f.t + 20) - f.t) * pps;
        // a thumbnail too thin to read is not fetched
        if (d >= 14 && f.t > v.t0 - pad && f.t < v.t1 + pad) { el.style.backgroundImage = `url('${el.dataset.bg}')`; delete el.dataset.bg; }
      }
    }
    function drawWaves() {
      showFrames();
      if (!box) return;
      for (const c of box.querySelectorAll("canvas[data-audio]")) {
        if (c.parentElement.hidden) continue;
        const a = audio.find((x) => x.id === c.dataset.audio), h = c.parentElement.clientHeight;
        const { g, v } = prepCanvas(c, h);
        const active = a.id === "meet" ? (!M.video || a.on) : (!a.el || a.on);   // a track this page cannot play keeps a readable shape
        g.fillStyle = active ? (a.id === "meet" ? cssv("--sky") : cssv("--lime")) : cssv("--line");
        const e = a.env, r = a.rate;
        for (let x = 0; x < v.w; x++) {
          const ta = (v.x0 + x) / pps - a.offset, tb = (v.x0 + x + 1) / pps - a.offset;
          if (tb < 0 || ta > a.duration) continue;
          const i0 = Math.max(0, Math.floor(ta * r)), i1 = Math.min(e.length - 1, Math.max(i0, Math.floor(tb * r)));
          let m = 0; for (let i = i0; i <= i1; i++) if (e[i] > m) m = e[i];
          const y = (m / 255) * (h - 6); g.fillRect(x, (h - y) / 2, 1, Math.max(1, y));
        }
        if (a.offset > 0 || a.duration < DUR) {
          g.fillStyle = cssv("--muted");
          for (const edge of [a.offset, a.offset + a.duration]) { const x = edge * pps - v.x0; if (x >= 0 && x <= v.w) g.fillRect(x, 0, 1, h); }
        }
      }
    }
    let nowTurn = -1, curWord = -1;
    function drawWords() {
      if (!wordsC || wordsC.parentElement.hidden || !width()) return;
      const h = wordsC.parentElement.clientHeight;
      const { g, v } = prepCanvas(wordsC, h);
      g.font = font(12); g.textBaseline = "middle";
      if (pps < 8) {                                 // too far out to read a word
        g.fillStyle = cssv("--muted"); g.textAlign = "center";
        g.direction = "rtl"; g.fillText("הגדילו את ציר הזמן כדי לראות כל מילה ברגע שנאמרה", v.w / 2, h / 2);
        g.textAlign = "start"; g.direction = "ltr"; return;
      }
      for (let i = Math.max(0, findAt(allTurns, v.t0 - 60)); i < allTurns.length && allTurns[i].s <= v.t1; i++) {
        const x = allTurns[i], tk = toks(x);
        if (!x.w || x.w.length !== tk.length) continue;
        const col = fill(x.who);
        for (let k = 0; k < tk.length; k++) {
          const ws = x.s + x.w[k] / 10, we = k + 1 < tk.length ? x.s + x.w[k + 1] / 10 : Math.max(x.e, ws + 0.3);
          if (we < v.t0 || ws > v.t1) continue;
          const px = ws * pps - v.x0, pw = Math.max(3, (we - ws) * pps), cur = i === nowTurn && k === curWord;
          g.fillStyle = cur ? col : cssv("--surface-2"); g.fillRect(px, 4, pw - 1, h - 8);
          g.fillStyle = col; g.fillRect(px, 4, 2, h - 8);
          g.save(); g.beginPath(); g.rect(px + 3, 0, Math.max(0, pw - 5), h); g.clip();
          g.direction = "rtl"; g.textAlign = "right";
          g.fillStyle = cur ? cssv("--" + hueOf(x.who) + "-ink") : cssv("--ink"); g.fillText(tk[k], px + pw - 3, h / 2);
          g.restore();
        }
      }
    }
    const findAt = (arr, x, s = "s") => { let lo = 0, hi = arr.length - 1, best = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m][s] <= x) { best = m; lo = m + 1; } else hi = m - 1; } return best; };
    if (tl) {
      on(lanes, "scroll", () => { SL = lanes.scrollLeft; drawRuler(); drawWaves(); drawWords(); heads.scrollTop = lanes.scrollTop; }, { passive: true });
      const ro = new ResizeObserver((es) => { W = Math.round(es[0].contentRect.width) || lanes.clientWidth; if (pps < fitPps()) pps = fitPps(); layout(); });
      ro.observe(lanes); offs.push(() => ro.disconnect());
    }

    /* ---------- zoom: from the whole meeting to 200 px a second (every word readable) ---------- */
    const zmax = 200;
    const toSlider = (p) => Math.round((1000 * Math.log(p / fitPps())) / Math.log(zmax / fitPps()));
    const fromSlider = (s) => fitPps() * Math.pow(zmax / fitPps(), s / 1000);
    function zoomTo(p, anchorX) {
      if (!tl) return;
      const old = pps; p = Math.max(fitPps(), Math.min(zmax, p));
      const ax = anchorX ?? Math.max(0, Math.min(width(), t * old - SL));
      const ta = (SL + ax) / old;
      pps = p; layout(); setSL(ta * pps - ax);
      const z = q(".mf-zoom", mount.transport || mount.root); if (z) z.value = toSlider(pps);
    }
    if (tl) on(lanes, "wheel", (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const r = lanes.getBoundingClientRect();
      zoomTo(pps * Math.pow(1.0018, -e.deltaY), e.clientX - r.left);
    }, { passive: false });

    /* ---------- the moment being played ---------- */
    const cap = mount.player && q(".mf-cap", mount.player), after = mount.player && q(".mf-after", mount.player);
    const nowEl = () => q(".mf-now", mount.transport || mount.root);
    let curFrame = -1, lastSub = "";
    function paint(jump) {
      if (!M.video && still && (M.frames || []).length) {
        const fi = Math.max(0, findAt(M.frames, t, "t"));
        if (fi !== curFrame) { curFrame = fi; still.src = frameSrc(M.frames[fi].f, "f"); }
      }
      if (playhead) playhead.style.left = (t * pps).toFixed(1) + "px";
      const n = nowEl(); if (n) n.textContent = fmt(t, DUR >= 3600);
      if (after) {
        const past = M.video && t >= VDUR - 0.05;
        after.hidden = !past;
        if (past) { const a = covering(t); after.textContent = a ? `הווידאו נגמר כאן — ממשיכים מהקלטה נוספת: ${label(a)}` : "הווידאו נגמר כאן"; }
      }
      const i = findAt(allTurns, t);
      const x = allTurns[i], live = !!x && t - x.e < 4 && t >= x.s - 0.2;
      let k = -1;
      if (x && x.w) for (let j = 0; j < x.w.length && x.s + x.w[j] / 10 <= t; j++) k = j;
      if (i !== nowTurn || k !== curWord) {
        nowTurn = i; curWord = k;
        drawWords();
      }
      if (cap) {
        const html = live ? `<span class="mf-cap-line" dir="${MF.dirOf(textOf(x))}"><b data-hue="${esc(hueOf(x.who))}">${esc(x.who)}</b> ${x.w && toks(x).length === x.w.length ? toks(x).map((w, j) => (j === k ? `<span class="cw">${esc(w)}</span>` : esc(w))).join(" ") : esc(textOf(x))}</span>` : "";
        if (html !== lastSub) { cap.innerHTML = html; lastSub = html; }
      }
      if (tl && follow && (playing || jump)) {
        const px = t * pps - SL;
        if (px < 0 || px > width() * 0.9) setSL(t * pps - width() * 0.25);
      }
      if (mount.scrub) paintScrub();
      for (const f of subs) { try { f({ t, i, word: k, playing, jump: !!jump }); } catch (e) { console.error(e); } }
    }
    const evSubs = {};
    function emit(name) { for (const f of evSubs[name] || []) { try { f(); } catch (e) { console.error(e); } } }

    /* ---------- pointing at the axis ---------- */
    if (tl) {
      on(box, "mousemove", (e) => {
        const el = e.target.closest("[data-tip]");
        if (!el) { tip.hidden = true; return; }
        tip.textContent = el.dataset.tip; tip.dir = MF.dirOf(el.dataset.tip); tip.hidden = false;
        const w = tip.offsetWidth, h = tip.offsetHeight;
        tip.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, e.clientX + 12)) + "px";
        tip.style.top = Math.max(8, e.clientY - h - 12) + "px";
      });
      on(box, "mouseleave", () => { tip.hidden = true; });
      on(inner, "click", (e) => {
        const el = e.target.closest("[data-k]");
        const r = inner.getBoundingClientRect(), at = (e.clientX - r.left) / pps;
        if (!el) { seek(at); return; }
        const k = el.dataset.k, i = +el.dataset.i;
        const arr = { frame: M.frames, screen: M.screens, turn: allTurns, caption: M.captions, topic: M.topics, decision: M.decisions, task: M.tasks, question: M.questions, like: M.likes, insight: M.insights, mark: opt.marks }[k] || [];
        const x = arr[i]; if (!x) return;
        seek(x.t ?? x.s);
        if (opt.onPick) opt.onPick(k, x, i);
      });
      on(ruler, "pointerdown", (e) => {
        const r = inner.getBoundingClientRect();
        const go = (ev) => seek((ev.clientX - r.left) / pps, { hash: false });
        go(e);
        const up = () => { window.removeEventListener("pointermove", go); window.removeEventListener("pointerup", up); MF.setHash("t" + Math.floor(t)); };
        window.addEventListener("pointermove", go); window.addEventListener("pointerup", up);
      });
    }

    /* ---------- the thin bar of a phone: where we are, and where the decisions and tasks were said ---------- */
    function paintScrub() {
      const s = mount.scrub; if (!s.firstChild) {
        const ticks = [].concat((M.decisions || []).map((x) => `<i class="dec" style="--p:${(x.t / DUR) * 100}%"></i>`), (M.tasks || []).map((x) => `<i class="task" style="--p:${(x.t / DUR) * 100}%"></i>`), (opt.marks || []).map((x) => `<i class="mark" style="--p:${(x.t / DUR) * 100}%"></i>`));
        s.innerHTML = `<div class="mf-scrub" dir="ltr" role="slider" tabindex="0" aria-label="מיקום בפגישה" aria-valuemin="0" aria-valuemax="${Math.round(DUR)}"><div class="track"><div class="fill"></div>${ticks.join("")}</div><div class="knob"></div></div>`;
        const bar = s.firstChild;
        const go = (ev) => { const r = bar.getBoundingClientRect(); seek(((ev.clientX - r.left) / r.width) * DUR, { hash: false }); };
        bar.addEventListener("pointerdown", (ev) => { bar.setPointerCapture(ev.pointerId); go(ev); bar.onpointermove = go; });
        bar.addEventListener("pointerup", () => { bar.onpointermove = null; MF.setHash("t" + Math.floor(t)); });
        bar.addEventListener("keydown", (ev) => { if (ev.key === "ArrowRight") { seek(t + 10); ev.preventDefault(); } else if (ev.key === "ArrowLeft") { seek(t - 10); ev.preventDefault(); } });
      }
      const bar = s.firstChild;
      bar.style.setProperty("--p", (t / DUR) * 100 + "%");
      bar.setAttribute("aria-valuenow", Math.round(t)); bar.setAttribute("aria-valuetext", `${fmt(t)} מתוך ${fmt(DUR)}`);
    }

    /* ---------- start ---------- */
    buildLanes();
    if (tl) { pps = fitPps(); layout(); }
    setPlayIcon();
    const api = {
      M, audio, turns: allTurns, get t() { return t; }, get playing() { return playing; }, get follow() { return follow; }, DUR,
      play, pause, toggle: () => (playing ? pause() : play()), seek, setFollow, zoomTo, fit: () => zoomTo(fitPps(), 0),
      zoomIn: () => zoomTo(pps * 1.6), zoomOut: () => zoomTo(pps / 1.6), get pps() { return pps; },
      onTime(f) { subs.add(f); return () => subs.delete(f); },
      on(name, f) { (evSubs[name] = evSubs[name] || []).push(f); },
      rebuild() { buildLanes(); layout(); },            // after an edit, an approval, a new mark
      relayout: () => layout(),
      findTurn: (x) => findAt(allTurns, x),
      destroy() {
        pause(); for (const f of offs) f(); subs.clear();
        try { video.removeAttribute("src"); video.load(); } catch (e) { /* */ }
        for (const a of audio) if (a.el) { a.el.pause(); a.el.removeAttribute("src"); }
      },
    };
    window.__timeline = { audio, now: () => ({ t, playing, pps }) };   // for checks from the browser's console
    return api;
  };
})();
