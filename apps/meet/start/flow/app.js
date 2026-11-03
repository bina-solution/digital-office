/* Meeting timeline: one clock for the call video and the side recordings, and every track of the meeting
   (screens, audio, who held the floor, reviewed transcript, live captions, topics, decisions, tasks) on one
   zoomable time axis. Data: window.MEETING from data.js. No network calls except the media files. */
(() => {
  const M = window.MEETING;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (t) => { t = Math.max(0, Math.floor(t)); return `${Math.floor(t / 3600)}:${String(Math.floor(t % 3600 / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`; };
  const DUR = M.meeting.duration;
  const VDUR = M.video ? M.video.duration : 0;
  // the meeting's own files: next to this page (a published page), or under FLOW_BASE (meet-flow in the office,
  // where the console sets <base href="/a/meet/"> and every path is written from the app's root: flow/<room>/…)
  const FB = window.FLOW_BASE || "";
  const rel = (u) => (!u || /^([a-z][a-z0-9+.-]*:|\/|#)/i.test(u) ? u : FB + u);
  const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim()
    || getComputedStyle(document.documentElement).color;   // a token that is missing draws in the page's ink (G82)
  // a speaker's colour is a hue of the office palette (data: {"William": "sky"}); a hex from an older bundle still works.
  // color() fills a block, colorText() writes a name on the ground (the hue's «-d», 4.5:1 or more)
  const hueOf = (who) => (M.colors || {})[who] || "";
  const color = (who) => { const h = hueOf(who); return h.startsWith("#") ? h : cssv(h ? "--" + h : "--muted"); };
  const colorText = (who) => { const h = hueOf(who); return h.startsWith("#") ? h : cssv(h ? "--" + h + "-d" : "--muted"); };
  // a line of the list into the middle of ITS box only (scrollIntoView moved the whole page on a phone)
  const centerIn = (el, smooth) => { const box = el && el.closest(".pane"); if (!box) return; const r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
    box.scrollTo({ top: box.scrollTop + (r.top - b.top) - (box.clientHeight - r.height) / 2, behavior: smooth ? "smooth" : "auto" }); };

  document.title = M.meeting.title + " · ציר זמן";
  $("title").textContent = M.meeting.title;
  $("subtitle").textContent = M.meeting.subtitle || "";
  if ((M.meeting.docs || []).length) {   // the meeting's documents (status and decisions, the plan, the analysis)
    const d = document.createElement("nav"); d.className = "docs"; d.setAttribute("aria-label", "מסמכים");
    d.innerHTML = M.meeting.docs.map((x) => `<a href="${esc(rel(x.href))}">${esc(x.title)}</a>`).join("");
    $("subtitle").after(d);
  }
  $("tdur").textContent = fmt(DUR);

  /* ---------- media and the one clock ---------- */
  const video = $("video");
  if (M.video) video.src = rel(M.video.src);
  // frames come either as files (office hosting) or embedded in frames.js (a published page)
  const frameSrc = (f, kind) => (window.FRAMES && window.FRAMES[f]) || rel(`frames/${kind}/${f}`);
  const still = document.createElement("img");
  still.className = "still"; still.alt = "";
  if (!M.video) { video.hidden = true; if (M.frames.length) video.parentElement.prepend(still); }
  if (M.note) {
    const n = document.createElement("div"); n.className = "note";
    n.innerHTML = esc(M.note.text) + (M.note.href ? ` <a href="${esc(M.note.href)}" target="_blank" rel="noopener">${esc(M.note.link || "")}</a>` : "");
    document.querySelector(".top").after(n);
  }
  const audio = M.audio.map((a) => {
    const el = a.src ? new Audio() : null;
    if (el) { el.preload = "metadata"; el.src = rel(a.src); }
    let env = null;
    if (a.env) { const b = atob(a.env.b64); env = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) env[i] = b.charCodeAt(i); }
    return { ...a, el, env, rate: a.env ? a.env.rate : 10, on: a.id === "meet" };
  });
  let t = 0, playing = false, rate = 1, follow = true, raf = 0;
  const covering = (x) => audio.find((a) => a.el && a.on && x >= a.offset && x < a.offset + a.duration)
    || audio.find((a) => a.el && x >= a.offset && x < a.offset + a.duration);
  // with no media at this moment (a transcript-only call, or a gap) a wall clock moves the playhead
  let wall = null;
  function masterTime() {
    if (M.video && t < VDUR - 0.05 && !video.ended) { wall = null; return video.currentTime; }
    const a = covering(t);
    if (a && !a.el.paused) { wall = null; return a.offset + a.el.currentTime; }
    if (!playing) return t;
    const now = performance.now();
    if (!wall) wall = { t0: t, at: now };
    return wall.t0 + (now - wall.at) / 1000 * rate;
  }
  // the side recordings only run while the master really moves (not while the video loads a far seek)
  const videoActive = () => M.video && t < VDUR - 0.05;
  const videoRolling = () => !video.paused && !video.seeking && video.readyState >= 3;
  function syncSide(force) {
    const masterOk = videoActive() ? videoRolling() : true;
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
  let timer = 0;
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
    playing = true; $("play").textContent = "❚❚";
    if (M.video && t < VDUR - 0.05) { video.playbackRate = rate; video.play().catch(() => {}); }
    syncSide(true);
    raf = requestAnimationFrame(frameLoop);
    timer = setInterval(tick, 100); // keeps the clock and the side recordings in step when frames are throttled
  }
  for (const ev of ["playing", "waiting", "seeked", "stalled"]) video.addEventListener(ev, () => { if (playing) syncSide(true); });
  function pause() {
    playing = false; wall = null; $("play").textContent = "▶";
    video.pause(); for (const a of audio) if (a.el) a.el.pause();
    cancelAnimationFrame(raf); clearInterval(timer);
    // the page's own path: a <base> (the console's) must not move the address to the app's root
    try { history.replaceState(null, "", location.pathname + location.search + "#t" + Math.floor(t)); } catch (e) { /* a sandboxed page may refuse */ }
    paint();
  }
  function seek(x) {
    t = Math.max(0, Math.min(DUR, x)); wall = null;
    if (M.video) video.currentTime = Math.min(t, VDUR - 0.05);
    if (playing && M.video && t < VDUR - 0.05 && video.paused) video.play().catch(() => {});
    syncSide(true);
    paint(true);
  }
  video.addEventListener("ended", () => { if (playing) { t = VDUR; syncSide(true); } });
  $("play").onclick = () => (playing ? pause() : play());
  $("back5").onclick = () => seek(t - 5);
  $("fwd5").onclick = () => seek(t + 5);
  $("rate").onchange = (e) => { rate = +e.target.value; video.playbackRate = rate; for (const a of audio) if (a.el) a.el.playbackRate = rate; };
  $("follow").onchange = (e) => { follow = e.target.checked; };
  $("audioBtns").innerHTML = audio.map((a, i) => `<button data-a="${i}" class="${a.on ? "on" : ""}" title="${esc(a.label)}">${esc(a.id === "meet" ? "הפגישה" : a.short || a.label.replace(/^.*«(.*)».*$/, "iPad · $1"))}</button>`).join("");
  $("audioBtns").onclick = (e) => {
    const b = e.target.closest("button[data-a]"); if (!b) return;
    const a = audio[+b.dataset.a]; a.on = !a.on; b.classList.toggle("on", a.on); syncSide(true); drawWaves();
  };

  /* ---------- lanes ---------- */
  const lanes = $("lanes"), inner = $("inner"), box = $("laneBox"), heads = $("heads");
  let pps = 0.2;
  const fitPps = () => Math.max(0.01, (lanes.clientWidth - 4) / DUR);
  const LANES = [];
  function lane(id, title, cls = "", extra = "") {
    heads.insertAdjacentHTML("beforeend", `<div class="h ${cls}" data-lane="${id}"><span>${esc(title)}</span>${extra}</div>`);
    const el = document.createElement("div"); el.className = "lane " + cls; el.id = "lane-" + id; box.appendChild(el);
    LANES.push(el); return el;
  }
  heads.insertAdjacentHTML("beforeend", `<div class="h r"><span class="muted">זמן</span></div>`);
  const item = (cls, s, d, html, tip, data) => `<div class="${cls}" style="--s:${s};--d:${d}" data-tip="${esc(tip)}" ${data || ""}>${html}</div>`;

  // video frames
  if (M.frames.length) {
    const L = lane("frames", "וידאו");
    L.innerHTML = M.frames.map((f, i) => {
      const d = (M.frames[i + 1] ? M.frames[i + 1].t : f.t + 20) - f.t;
      return `<div class="fr" style="--s:${f.t};--d:${d};background-image:url('${frameSrc(f.f, "t")}')" data-tip="${fmt(f.t)}" data-k="frame" data-i="${i}"></div>`;
    }).join("");
  }
  // screens
  if (M.screens.length) {
    const L = lane("screens", "מה על המסך");
    L.innerHTML = M.screens.map((s, i) => item("it2 scr " + (s.kind || ""), s.s, s.e - s.s, esc(s.label), `${fmt(s.s)}–${fmt(s.e)}\n${s.label}\n${s.detail || ""}`, `data-k="screen" data-i="${i}"`)).join("");
  }
  // audio waveforms
  for (const a of audio) {
    if (!a.env) continue;
    const L = lane("a-" + a.id, a.id === "meet" ? "קול: הפגישה" : "קול: " + (a.short || a.label.replace(/^.*«(.*)».*$/, "iPad «$1»")));
    const c = document.createElement("canvas"); c.dataset.audio = a.id; L.appendChild(c);
  }
  // who was in the call (bridge joins/leaves), when there is no speaker log
  if ((M.presence || []).length) {
    const who = [...new Set(M.presence.map((p) => p.who))];
    for (const w of who) {
      const L = lane("pr-" + who.indexOf(w), "בשיחה: " + w);
      L.innerHTML = M.presence.filter((p) => p.who === w).map((p) => `<div class="it2 flr" style="--s:${p.s};--d:${p.e - p.s};background:var(--presence)" data-tip="${esc(w)} ${fmt(p.s)}–${fmt(p.e)}"></div>`).join("");
    }
  }
  // floor
  if (M.floor.length) {
    const L = lane("floor", "מי מדבר (גשר)");
    L.innerHTML = M.floor.map((f) => `<div class="it2 flr" style="--s:${f.s};--d:${f.e - f.s};background:${color(f.who)}" data-tip="${esc(f.who)} ${fmt(f.s)}"></div>`).join("");
  }
  // transcript (+ after-call lines)
  const allTurns = M.turns.concat((M.tail || []).map((x) => ({ ...x, tail: true })));
  {
    const L = lane("turns", M.meeting.transcript_label || "תמלול", "tall");
    L.innerHTML = allTurns.map((x, i) => item("it2 turn", x.s, Math.max(0.5, x.e - x.s), esc(x.text || "—"),
      `${fmt(x.s)} ${x.who}${x.tail ? " · אחרי השיחה" : ""}\n${x.text}`, `data-k="turn" data-i="${i}" style="--s:${x.s};--d:${Math.max(0.5, x.e - x.s)};background:${color(x.who)}"`)).join("");
    // item() already wrote a style; the second style attribute is ignored, so fix colours here
    L.querySelectorAll(".turn").forEach((el, i) => { el.style.background = color(allTurns[i].who); });
  }
  // every word at the moment it was said (when the data has word times): a canvas, drawn only for what is in view
  const toksOf = (x) => x._t || (x._t = (x.text || "").split(/\s+/).filter(Boolean));
  const wordsC = allTurns.some((x) => x.w) ? (() => { const c = document.createElement("canvas"); lane("words", "מילים").appendChild(c); return c; })() : null;
  if (M.captions.length) {
    const L = lane("captions", "כתוביות חיות");
    L.innerHTML = M.captions.map((c, i) => item("it2 cap", c.s, Math.max(1, c.e - c.s), esc(c.text), `${fmt(c.s)} (כתובית חיה)\n${c.text}`, `data-k="caption" data-i="${i}"`)).join("");
  }
  if (M.topics.length) {
    const L = lane("topics", "נושאים", "tall");
    L.innerHTML = M.topics.map((x, i) => item("it2 top", x.s, Math.max(5, x.e - x.s), esc(x.title), `${fmt(x.s)}–${fmt(x.e)}\n${x.title}`, `data-k="topic" data-i="${i}"`)).join("");
  }
  const markers = (id, title, arr, cls, k) => {
    if (!arr.length) return;
    const L = lane(id, title);
    L.innerHTML = arr.map((x, i) => `<div class="mk ${typeof cls === "function" ? cls(x) : cls}" style="--s:${x.t}" data-tip="${esc(fmt(x.t) + "\n" + (x.id ? x.id + " · " : "") + x.text)}" data-k="${k}" data-i="${i}"></div>`).join("");
  };
  markers("insights", "תובנות", M.insights || [], "ins", "insight");
  markers("decisions", "החלטות", M.decisions, "dec", "decision");
  markers("tasks", "משימות", M.tasks, "task", "task");
  markers("questions", "שאלות פתוחות", M.questions, "q", "question");
  markers("likes", "אהבו / דחו", M.likes, (x) => (x.kind === "rejected" ? "rej" : "like"), "like");

  /* ---------- ruler, waves, layout ---------- */
  const ruler = $("ruler");
  function layout() {
    inner.style.width = Math.ceil(DUR * pps) + "px";
    inner.style.setProperty("--pps", pps);
    drawRuler(); drawWaves(); drawWords(); paint(true);
  }
  function view() { const w = lanes.clientWidth; return { x0: lanes.scrollLeft, w, t0: lanes.scrollLeft / pps, t1: (lanes.scrollLeft + w) / pps }; }
  function prepCanvas(c, h) {
    const v = view(), dpr = window.devicePixelRatio || 1;
    c.style.left = v.x0 + "px"; c.style.width = v.w + "px"; c.style.height = h + "px";
    c.width = Math.round(v.w * dpr); c.height = Math.round(h * dpr);
    const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, v.w, h); return { g, v };
  }
  function drawRuler() {
    const { g, v } = prepCanvas(ruler, 26);
    ruler.style.position = "relative";
    const steps = [1, 5, 10, 30, 60, 120, 300, 600, 900, 1800, 3600];
    const step = steps.find((s) => s * pps >= 70) || 3600;
    g.fillStyle = cssv("--ink2"); g.strokeStyle = cssv("--tick"); g.font = "11px system-ui"; g.textBaseline = "top";
    for (let s = Math.floor(v.t0 / step) * step; s <= v.t1; s += step) {
      const x = s * pps - v.x0; g.beginPath(); g.moveTo(x + .5, 14); g.lineTo(x + .5, 26); g.stroke(); g.fillText(fmt(s), x + 3, 2);
    }
    const vEnd = M.video ? VDUR : (M.meeting.video_end || 0);
    if (vEnd) { const x = vEnd * pps - v.x0; if (x > 0 && x < v.w) { g.fillStyle = cssv("--after"); g.fillRect(x, 0, 2, 26); g.fillText("סוף הווידאו", x - 64, 13); } }
  }
  function drawWaves() {
    for (const c of box.querySelectorAll("canvas[data-audio]")) {
      const a = audio.find((x) => x.id === c.dataset.audio); const h = c.parentElement.clientHeight;
      const { g, v } = prepCanvas(c, h);
      // a track that cannot play on this page (no media here) is drawn as active, so its shape stays readable
      const active = a.id === "meet" ? (!M.video || a.on) : (!a.el || a.on);
      g.fillStyle = active ? (a.id === "meet" ? cssv("--wave") : cssv("--wave2")) : cssv("--waveoff");
      const e = a.env, r = a.rate;
      for (let x = 0; x < v.w; x++) {
        const ta = (v.x0 + x) / pps - a.offset, tb = (v.x0 + x + 1) / pps - a.offset;
        if (tb < 0 || ta > a.duration) continue;
        let i0 = Math.max(0, Math.floor(ta * r)), i1 = Math.min(e.length - 1, Math.max(i0, Math.floor(tb * r))), m = 0;
        for (let i = i0; i <= i1; i++) if (e[i] > m) m = e[i];
        const y = (m / 255) * (h - 4); g.fillRect(x, (h - y) / 2, 1, Math.max(1, y));
      }
      if (a.offset > 0 || a.duration < DUR) { // clip edges
        g.fillStyle = cssv("--ink2");
        for (const edge of [a.offset, a.offset + a.duration]) { const x = edge * pps - v.x0; if (x >= 0 && x <= v.w) g.fillRect(x, 0, 1, h); }
      }
    }
  }
  let nowTurn = -1, curWord = -1, nowLive = false;
  function drawWords() {
    if (!wordsC) return;
    const h = wordsC.parentElement.clientHeight;
    const { g, v } = prepCanvas(wordsC, h);
    g.font = "12px system-ui"; g.textBaseline = "middle";
    if (pps < 8) { // too far out to read a word
      g.fillStyle = cssv("--ink2"); g.textAlign = "center";
      g.fillText("הגדילו את הזום כדי לראות כל מילה ברגע שנאמרה", v.w / 2, h / 2); g.textAlign = "start"; return;
    }
    for (let i = Math.max(0, findAt(allTurns, v.t0 - 60)); i < allTurns.length && allTurns[i].s <= v.t1; i++) {
      const x = allTurns[i], toks = toksOf(x);
      if (!x.w || x.w.length !== toks.length) continue;
      const col = color(x.who);
      for (let k = 0; k < toks.length; k++) {
        const ws = x.s + x.w[k] / 10, we = k + 1 < toks.length ? x.s + x.w[k + 1] / 10 : Math.max(x.e, ws + 0.3);
        if (we < v.t0 || ws > v.t1) continue;
        const px = ws * pps - v.x0, pw = Math.max(3, (we - ws) * pps), on = i === nowTurn && k === curWord;
        g.fillStyle = on ? col : cssv("--panel2"); g.fillRect(px, 4, pw - 1, h - 8);
        g.fillStyle = col; g.fillRect(px, 4, 2, h - 8); // the speaker's colour where the word starts
        g.save(); g.beginPath(); g.rect(px + 3, 0, Math.max(0, pw - 5), h); g.clip();
        g.fillStyle = on ? cssv("--onblock") : cssv("--ink"); g.fillText(toks[k], px + 5, h / 2);
        g.restore();
      }
    }
  }
  lanes.addEventListener("scroll", () => { drawRuler(); drawWaves(); drawWords(); heads.scrollTop = lanes.scrollTop; });
  window.addEventListener("resize", () => { if (pps < fitPps()) pps = fitPps(); layout(); });

  // zoom: slider is logarithmic between "whole meeting" and 200 px per second (close enough to read every word)
  const zmax = 200;
  const toSlider = (p) => Math.round(1000 * Math.log(p / fitPps()) / Math.log(zmax / fitPps()));
  const fromSlider = (v) => fitPps() * Math.pow(zmax / fitPps(), v / 1000);
  function zoomTo(p, anchorX) {
    const old = pps; p = Math.max(fitPps(), Math.min(zmax, p));
    const ax = anchorX ?? Math.max(0, Math.min(lanes.clientWidth, t * old - lanes.scrollLeft));
    const ta = (lanes.scrollLeft + ax) / old;
    pps = p; layout(); lanes.scrollLeft = ta * pps - ax; $("zoom").value = toSlider(pps);
  }
  $("zoom").oninput = (e) => zoomTo(fromSlider(+e.target.value));
  $("fit").onclick = () => zoomTo(fitPps(), 0);
  lanes.addEventListener("wheel", (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    const r = lanes.getBoundingClientRect();
    zoomTo(pps * Math.pow(1.0015, -e.deltaY), e.clientX - r.left);
  }, { passive: false });

  /* ---------- painting the current moment ---------- */
  const trList = $("trList");
  let curTurn = -1, curScreen = -1;
  const findAt = (arr, x, s = "s", e = "e") => { let lo = 0, hi = arr.length - 1, best = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m][s] <= x) { best = m; lo = m + 1; } else hi = m - 1; } return best >= 0 && x < (arr[best][e] ?? Infinity) + 1.5 ? best : best; };
  let curFrame = -1;
  function paint(jump) {
    if (!M.video && M.frames.length) {
      const fi = Math.max(0, findAt(M.frames, t, "t", "t"));
      if (fi !== curFrame) { curFrame = fi; still.src = frameSrc(M.frames[fi].f, "f"); }
    }
    inner.style.setProperty("--t", t);
    $("playhead").style.setProperty("--t", t);
    $("tnow").textContent = fmt(t);
    $("after").classList.toggle("hidden", !(M.video && t >= VDUR - 0.05));
    const i = findAt(allTurns, t);
    // the subtitle: the line being said, with the word being said marked (and the words lane follows)
    const x = allTurns[i], live = !!x && t - x.e < 4;
    let k = -1;
    if (x && x.w) for (let j = 0; j < x.w.length && x.s + x.w[j] / 10 <= t; j++) k = j;
    if (i !== nowTurn || k !== curWord || live !== nowLive) {
      nowTurn = i; curWord = k; nowLive = live;
      $("now").innerHTML = live ? `<b style="color:${colorText(x.who)}">${esc(x.who)}</b>${x.w ? toksOf(x).map((w, j) => (j === k ? `<span class="cw">${esc(w)}</span>` : esc(w))).join(" ") : esc(x.text)}` : "";
      drawWords();
    }
    if (i !== curTurn) {
      curTurn = i;
      trList.querySelector(".it.cur")?.classList.remove("cur");
      const li = trList.querySelector(`.it[data-i="${i}"]`);
      if (li) { li.classList.add("cur"); if (follow && (playing || jump)) centerIn(li, !jump); }
    }
    if (follow && (playing || jump)) {
      const x = t * pps - lanes.scrollLeft;
      if (x < 0 || x > lanes.clientWidth * 0.9) lanes.scrollLeft = t * pps - lanes.clientWidth * 0.25;
    }
  }

  /* ---------- side lists ---------- */
  const alts = (x) => x.alts ? Object.entries(x.alts).map(([k, v]) => `<div><b>${esc(k)}:</b> ${esc(v)}</div>`).join("") : "";
  const flags = (x) => (x.flags || []).map((f) => `<span class="flag">${esc(f)}</span>`).join("");
  const mark = (s) => esc(s).replace(/\[\?\]/g, '<span class="q">[?]</span>').replace(/\[לא ברור\]/g, '<span class="q">[לא ברור]</span>');
  let tailHead = false;
  trList.innerHTML = allTurns.map((x, i) => {
    let h = "";
    if (x.tail && !tailHead) { tailHead = true; h = `<div id="tailHead" class="sub" style="padding:10px 4px">— אחרי שהשיחה בווידאו נגמרה (רק הקלטת הגיבוי של Shlomo, iPad) —</div>`; }
    // an emptied line either lost its words to the next/previous line (the reviewer moved them) or was invented
    const gone = (x.flags || []).some((f) => /moved/.test(f)) ? "(ריק — המילים שלו עברו לשורה הסמוכה)" : "(נמחק — המזהה המציא מילים שלא נאמרו)";
    return h + `<div class="it" data-i="${i}" data-t="${x.s}"><span class="tm">${fmt(x.s)}</span><span class="who" style="color:${colorText(x.who)}">${esc(x.who)}</span><span class="tx">${x.text ? mark(x.text) : `<span class="muted">${gone}</span>`}</span><div class="alts">${alts(x)}${flags(x)}</div></div>`;
  }).join("");
  $("showOrig").onchange = (e) => document.body.classList.toggle("showorig", e.target.checked);
  const listOf = (el, arr, row) => { $(el).innerHTML = arr.map((x, i) => `<div class="it" data-i="${i}" data-t="${x.t ?? x.s}">${row(x)}</div>`).join("") || '<div class="muted">אין</div>'; };
  listOf("topicList", M.topics, (x) => `<span class="tm">${fmt(x.s)}</span><b>${esc(x.title)}</b><div class="sub">${esc((x.body || "").slice(0, 280))}…</div>`);
  listOf("decList", M.decisions, (x) => `<span class="tm">${fmt(x.t)}</span>${x.id ? `<b>${esc(x.id)}</b> ` : ""}${esc(x.text)}<div class="sub">${esc(x.type || "")}${x.also && x.also.length ? " · גם ב-" + x.also.map(fmt).join(", ") : ""}</div>`);
  listOf("taskList", M.tasks, (x) => `<span class="tm">${fmt(x.t)}</span>${x.who ? `<b>${esc(x.who)}</b> · ` : ""}${esc(x.text)}<div class="sub">${esc([x.area, x.where, x.due].filter(Boolean).join(" · "))}</div>`);
  listOf("qList", M.questions, (x) => `<span class="tm">${fmt(x.t)}</span>${esc(x.text)}`);
  listOf("likeList", M.likes, (x) => `<span class="tm">${fmt(x.t)}</span><b>${x.kind === "rejected" ? "נדחה" : "אהבו"}</b> · ${esc(x.text)}`);
  listOf("insList", M.insights || [], (x) => `<span class="tm">${fmt(x.t)}</span>${esc(x.text)}<div class="sub">${esc(x.kind)}</div>`);
  for (const id of ["trList", "topicList", "decList", "taskList", "qList", "likeList", "insList"]) {
    $(id).addEventListener("click", (e) => { const it = e.target.closest(".it[data-t]"); if (it) seek(+it.dataset.t); });
  }
  $("tabs").onclick = (e) => {
    const b = e.target.closest("button[data-tab]"); if (!b) return;
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p.id === "p-" + b.dataset.tab));
  };
  function showSel(html) {
    $("selBox").innerHTML = html; $("selBox").classList.remove("muted");
    document.querySelector('#tabs button[data-tab="sel"]').click();
  }

  /* ---------- timeline interaction ---------- */
  const tip = $("tip");
  box.addEventListener("mousemove", (e) => {
    const el = e.target.closest("[data-tip]");
    if (!el) { tip.classList.add("hidden"); return; }
    tip.textContent = el.dataset.tip; tip.classList.remove("hidden");
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(window.innerWidth - w - 8, e.clientX + 12) + "px";
    tip.style.top = Math.max(8, e.clientY - h - 12) + "px";
  });
  box.addEventListener("mouseleave", () => tip.classList.add("hidden"));
  inner.addEventListener("click", (e) => {
    const el = e.target.closest("[data-k]");
    const r = inner.getBoundingClientRect();
    const at = (e.clientX - r.left) / pps;
    if (!el) { seek(at); return; }
    const k = el.dataset.k, i = +el.dataset.i;
    if (k === "frame") { const f = M.frames[i]; seek(f.t); showSel(`<h3>המסך ב-${fmt(f.t)}</h3><img src="${frameSrc(f.f, "f")}" alt="">`); }
    else if (k === "screen") { const s = M.screens[i]; seek(s.s); showSel(`<h3>${esc(s.label)}</h3><div class="sub">${fmt(s.s)}–${fmt(s.e)}</div><p class="body">${esc(s.detail || "")}</p>${(s.frames || []).slice(0, 3).map((f) => `<img src="${frameSrc(f, "f")}" alt="">`).join("")}`); }
    else if (k === "turn") { seek(allTurns[i].s); }
    else if (k === "caption") { const c = M.captions[i]; seek(c.s); showSel(`<h3>כתובית חיה ${fmt(c.s)}</h3><p class="body">${esc(c.text)}</p><div class="sub">כך הופיע בזמן השיחה (באיחור, ולפעמים חסר).</div>`); }
    else if (k === "topic") { const x = M.topics[i]; seek(x.s); showSel(`<h3>${esc(x.title)}</h3><div class="sub">${fmt(x.s)}–${fmt(x.e)}</div><p class="body">${esc(x.body)}</p>`); }
    else {
      const arr = { decision: M.decisions, task: M.tasks, question: M.questions, like: M.likes, insight: M.insights }[k]; const x = arr[i]; seek(x.t);
      showSel(`<h3>${esc({ decision: "החלטה", task: "משימה", question: "שאלה פתוחה", like: x.kind === "rejected" ? "נדחה" : "אהבו", insight: "תובנה · " + (x.kind || "") }[k])} ${x.id ? esc(x.id) : ""}</h3><div class="sub">${fmt(x.t)}${x.also && x.also.length ? " · גם ב-" + x.also.map(fmt).join(", ") : ""}</div><p class="body">${esc(x.text)}</p>${x.who ? `<div class="sub">מי: ${esc(x.who)}</div>` : ""}${x.where ? `<div class="sub">איפה: ${esc(x.where)}</div>` : ""}`);
    }
  });
  ruler.addEventListener("mousedown", (e) => {
    const r = inner.getBoundingClientRect();
    const go = (ev) => seek((ev.clientX - r.left) / pps);
    go(e);
    const up = () => { window.removeEventListener("mousemove", go); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", go); window.addEventListener("mouseup", up);
  });

  /* ---------- search ---------- */
  $("q").addEventListener("input", (e) => {
    const q = e.target.value.trim();
    let n = 0;
    box.querySelectorAll("#lane-turns .turn").forEach((el, i) => { const hit = q && (allTurns[i].text || "").includes(q); el.classList.toggle("hit", !!hit); n += hit ? 1 : 0; });
    let tailHit = false;
    trList.querySelectorAll(".it").forEach((el) => {
      const i = +el.dataset.i, tx = el.querySelector(".tx"), x = allTurns[i];
      if (!x.text) { el.style.display = q ? "none" : ""; return; }
      const hit = !q || x.text.includes(q);
      el.style.display = hit ? "" : "none";
      tailHit = tailHit || (hit && !!x.tail);
      tx.innerHTML = q && hit ? mark(x.text).split(esc(q)).join(`<mark>${esc(q)}</mark>`) : mark(x.text);
    });
    if ($("tailHead")) $("tailHead").style.display = tailHit ? "" : "none";
    if (!q) centerIn(trList.querySelector(".it.cur"), false);  // back to where the playhead is
    $("qn").textContent = q ? `${n} שורות` : "";
  });

  /* ---------- keys and start ---------- */
  window.addEventListener("keydown", (e) => {
    if (e.target.matches("input[type=search], input[type=text], select")) return;
    if (e.code === "Space") { e.preventDefault(); playing ? pause() : play(); }
    else if (e.key === "ArrowRight") seek(t + (e.shiftKey ? 30 : 5));
    else if (e.key === "ArrowLeft") seek(t - (e.shiftKey ? 30 : 5));
    else if (e.key === "+" || e.key === "=") zoomTo(pps * 1.5);
    else if (e.key === "-") zoomTo(pps / 1.5);
  });
  window.__timeline = { audio, now: () => ({ t, playing, pps }) }; // for checks from the console
  pps = fitPps(); layout(); $("zoom").value = 0;
  if (!audio.some((a) => a.el)) $("audioBtns").innerHTML = '<span class="muted">בלי ניגון בעמוד הזה</span>';
  const h = location.hash.match(/t=?(\d+)/);
  if (h) { zoomTo(4); seek(+h[1]); } else seek(0);
})();
