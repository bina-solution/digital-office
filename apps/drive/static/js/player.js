/* player.js — one audio player for the whole app (Spotify's bar, SoundCloud's waveform). It keeps
   playing while the person browses; a long recording resumes where it was left; the device's own
   controls (lock screen, keyboard media keys) drive it through MediaSession. The viewer's audio
   page is a big face of this same player, never a second one. */
(function () {
  "use strict";
  const { html, hooks, state, set, L, ic, fmtDur, contentUrl, localGet, localSet } = F;
  const audio = new Audio();
  audio.preload = "metadata";
  let saveTick = 0;

  const cur = () => state.player.queue[state.player.index] || null;
  const pset = (p) => set({ player: { ...state.player, ...p } });
  const titleOf = (it) => { const m = (state.media || {})[it.id] || it.meta || {}; return m.title || F.splitName(it.name)[0]; };
  const artistOf = (it) => { const m = (state.media || {})[it.id] || it.meta || {}; return [m.artist, m.album].filter(Boolean).join(" · ") || F.fmtWhen(it.created); };

  function play(queue, index) {
    pset({ queue, index, expanded: state.player.expanded });
    load(true);
  }
  function load(autoplay) {
    const it = cur();
    if (!it) return;
    audio.src = contentUrl(it.id);
    const pos = (localGet("pos", {}) || {})[it.id];
    audio.addEventListener("loadedmetadata", function once() {
      audio.removeEventListener("loadedmetadata", once);
      if (pos && pos > 10 && pos < audio.duration - 10) audio.currentTime = pos;
    });
    if (autoplay) audio.play().catch(() => pset({ playing: false }));
    pset({ time: 0, duration: 0 });
    session(it);
  }
  const toggle = () => (audio.paused ? audio.play().catch(() => {}) : audio.pause());
  function next(auto) {
    const p = state.player;
    if (!p.queue.length) return;
    if (auto && p.repeat === "one") { audio.currentTime = 0; audio.play(); return; }
    let i = p.shuffle ? Math.floor(Math.random() * p.queue.length) : p.index + 1;
    if (i >= p.queue.length) { if (auto && p.repeat !== "all") { pset({ playing: false }); return; } i = 0; }
    pset({ index: i }); load(true);
  }
  function prev() {
    if (audio.currentTime > 4) { audio.currentTime = 0; return; }
    const p = state.player;
    pset({ index: Math.max(0, p.index - 1) }); load(true);
  }
  const seek = (t) => { if (isFinite(t)) audio.currentTime = Math.max(0, Math.min(t, audio.duration || t)); };
  const skip = (d) => seek(audio.currentTime + d);
  function close() { audio.pause(); audio.removeAttribute("src"); audio.load(); pset({ queue: [], index: -1, playing: false, expanded: false }); }

  audio.addEventListener("play", () => pset({ playing: true }));
  audio.addEventListener("pause", () => pset({ playing: false }));
  audio.addEventListener("ended", () => { remember(0); next(true); });
  audio.addEventListener("durationchange", () => pset({ duration: audio.duration || 0 }));
  audio.addEventListener("timeupdate", () => {
    pset({ time: audio.currentTime });
    if (++saveTick % 20 === 0) remember(audio.currentTime);
  });
  audio.addEventListener("error", () => { if (audio.getAttribute("src")) { pset({ playing: false }); F.tell(L("הדפדפן לא מצליח לנגן את הקובץ הזה", "This browser cannot play this file"), "bad"); } });
  function remember(t) { const it = cur(); if (!it) return; const all = localGet("pos", {}) || {}; if (t > 10) all[it.id] = t; else delete all[it.id]; localSet("pos", all); }

  function session(it) {
    if (!("mediaSession" in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({ title: titleOf(it), artist: artistOf(it), album: L("קבצים", "Files"),
        artwork: [{ src: F.thumbUrl(it, 512), sizes: "512x512", type: "image/webp" }] });
      const a = navigator.mediaSession.setActionHandler.bind(navigator.mediaSession);
      a("play", () => audio.play()); a("pause", () => audio.pause());
      a("previoustrack", prev); a("nexttrack", () => next(false));
      a("seekbackward", () => skip(-15)); a("seekforward", () => skip(15));
      a("seekto", (e) => seek(e.seekTime));
    } catch (e) { /* an older browser */ }
  }

  /* the waveform: the server's peaks, drawn in the palette read at run time */
  function Wave({ it, time, duration, tall }) {
    const ref = hooks.useRef(), [peaks, setPeaks] = hooks.useState(null);
    hooks.useEffect(() => {
      let off = false;
      setPeaks(null);
      F.api("api/file/" + encodeURIComponent(it.id) + "/peaks").then((d) => !off && setPeaks(d.peaks || [])).catch(() => !off && setPeaks([]));
      return () => (off = true);
    }, [it.id]);
    hooks.useEffect(() => {
      const c = ref.current; if (!c) return;
      const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
      c.width = w * dpr; c.height = h * dpr;
      const g = c.getContext("2d"); g.scale(dpr, dpr);
      const css = getComputedStyle(c), on = css.getPropertyValue("--accent").trim(), offc = css.getPropertyValue("--line").trim();
      const bars = Math.max(20, Math.floor(w / 4)), frac = duration ? time / duration : 0;
      const src = peaks && peaks.length ? peaks : null;
      const rtl = getComputedStyle(document.documentElement).direction === "rtl";
      for (let i = 0; i < bars; i++) {
        const v = src ? src[Math.floor((i / bars) * src.length)] || 0 : 0.18;
        const bh = Math.max(2, v * (h - 4)), x = rtl ? w - (i + 1) * 4 : i * 4;
        g.fillStyle = i / bars <= frac ? on : offc;
        g.fillRect(x, (h - bh) / 2, 2.5, bh);
      }
    });
    function at(e) {
      const r = ref.current.getBoundingClientRect(), rtl = getComputedStyle(document.documentElement).direction === "rtl";
      let f = (e.clientX - r.left) / r.width; if (rtl) f = 1 - f;
      seek(Math.max(0, Math.min(1, f)) * (duration || 0));
    }
    return html`<div class=${"wave" + (tall ? " tall" : "")} onPointerDown=${(e) => { e.currentTarget.setPointerCapture(e.pointerId); at(e); }}
      onPointerMove=${(e) => e.buttons && at(e)} role="slider" aria-label=${L("מיקום בהקלטה", "Position")} aria-valuemin="0"
      aria-valuemax=${Math.round(duration || 0)} aria-valuenow=${Math.round(time || 0)} tabindex="0"
      onKeyDown=${(e) => { if (e.key === "ArrowLeft") skip(document.dir === "rtl" ? 5 : -5); if (e.key === "ArrowRight") skip(document.dir === "rtl" ? -5 : 5); }}>
      <canvas ref=${ref}></canvas></div>`;
  }

  /* a track without its own art shows the note — the failure is kept for THAT track (a reset effect lost
     the race to a cached 404 and left a broken picture); a cover that is already broken when it is
     attached counts as failed too */
  function Cover({ it, big }) {
    const [badFor, setBadFor] = hooks.useState(null);
    if (!it || badFor === it.id) return ic("music", big ? "xl" : "");
    const fail = () => setBadFor(it.id);
    return html`<img key=${it.id} src=${F.thumbUrl(it, big ? 512 : 128)} alt="" onError=${fail}
      ref=${(el) => { if (el && el.complete && el.naturalWidth === 0) fail(); }} />`;
  }

  /* the bar under the content (and a floating card above the tabs on a phone) */
  function PlayerBar() {
    const p = F.useStore((s) => s.player);
    const w = F.useStore((s) => s.size.w);
    const it = p.queue[p.index];
    if (!it) return null;
    const frac = p.duration ? (p.time / p.duration) * 100 : 0;
    return html`<div class="fx-player" role="region" aria-label=${L("נגן", "Player")}>
      <div class="pl-now" onClick=${() => w === "n" ? pset({ expanded: true }) : F.viewer.open(p.queue, p.index)} title=${L("פתיחה", "Open")}>
        <div class="cover"><${Cover} it=${it} /></div>
        <div class="t"><b><bdi>${titleOf(it)}</bdi></b><span>${artistOf(it)}</span></div>
      </div>
      <div class="pl-mid">
        <div class="pl-ctl">
          ${w !== "n" && html`<button class=${"icbtn" + (p.shuffle ? " on" : "")} title=${L("ערבוב", "Shuffle")} onClick=${() => pset({ shuffle: !p.shuffle })}>${ic("shuffle", "sm")}</button>`}
          ${w !== "n" && html`<button class="icbtn" title=${L("הקודם", "Previous")} onClick=${prev}>${ic("prev", "sm")}</button>`}
          <button class="big" title=${p.playing ? L("השהיה", "Pause") : L("ניגון", "Play")} onClick=${toggle}>${ic(p.playing ? "pause" : "play", "sm")}</button>
          <button class="icbtn" title=${L("הבא", "Next")} onClick=${() => next(false)}>${ic("next", "sm")}</button>
          ${w !== "n" && html`<button class=${"icbtn" + (p.repeat ? " on" : "")} title=${L("חזרה", "Repeat")}
            onClick=${() => pset({ repeat: p.repeat === "all" ? "one" : p.repeat === "one" ? "" : "all" })}>${ic("repeat", "sm")}</button>`}
        </div>
        <div class="pl-seek">
          <span class="num">${fmtDur(p.time)}</span>
          <input type="range" min="0" max=${p.duration || 0} step="1" value=${p.time} aria-label=${L("מיקום", "Position")}
            onInput=${(e) => seek(Number(e.target.value))} />
          <span class="num">${fmtDur(p.duration)}</span>
        </div>
      </div>
      <div class="pl-end">
        <button class="icbtn" title=${audio.muted ? L("השמעה", "Unmute") : L("השתקה", "Mute")} onClick=${() => { audio.muted = !audio.muted; pset({}); }}>${ic(audio.muted ? "mute" : "volume", "sm")}</button>
        <input type="range" min="0" max="1" step="0.05" value=${audio.volume} aria-label=${L("עוצמה", "Volume")} onInput=${(e) => { audio.volume = Number(e.target.value); pset({}); }} />
        <button class="icbtn" title=${L("סגירת הנגן", "Close player")} onClick=${close}>${ic("x", "sm")}</button>
      </div>
      <div class="pl-bar"><i style=${"width:" + frac + "%"}></i></div>
    </div>
    ${p.expanded && w === "n" && html`<${NowPlaying} />`}`;
  }

  /* the phone's full «now playing» */
  function NowPlaying() {
    const p = F.useStore((s) => s.player);
    const it = p.queue[p.index];
    if (!it) return null;
    return html`<div class="np" role="dialog" aria-label=${L("מתנגן עכשיו", "Now playing")}>
      <div class="np-head">
        <button class="icbtn" title=${L("סגירה", "Close")} onClick=${() => pset({ expanded: false })}>${ic("chevron-down")}</button>
        <span class="muted ell">${L("מתנגן עכשיו", "Now playing")}</span>
        <button class="icbtn" title=${L("פרטים", "Details")} onClick=${() => { pset({ expanded: false }); F.viewer.open(p.queue, p.index); }}>${ic("expand")}</button>
      </div>
      <div class="art"><div><${Cover} it=${it} big /></div></div>
      <div><h2><bdi>${titleOf(it)}</bdi></h2><div class="sub">${artistOf(it)}</div></div>
      <${Wave} it=${it} time=${p.time} duration=${p.duration} />
      <div class="times"><span class="num">${fmtDur(p.time)}</span><span class="num">-${fmtDur(Math.max(0, p.duration - p.time))}</span></div>
      <div class="ctl">
        <button class="icbtn" title=${L("15 שניות אחורה", "Back 15 seconds")} onClick=${() => skip(-15)}>${ic("back15")}</button>
        <button class="icbtn" title=${L("הקודם", "Previous")} onClick=${prev}>${ic("prev")}</button>
        <button class="big" title=${p.playing ? L("השהיה", "Pause") : L("ניגון", "Play")} onClick=${toggle}>${ic(p.playing ? "pause" : "play", "lg")}</button>
        <button class="icbtn" title=${L("הבא", "Next")} onClick=${() => next(false)}>${ic("next")}</button>
        <button class="icbtn" title=${L("15 שניות קדימה", "Forward 15 seconds")} onClick=${() => skip(15)}>${ic("fwd15")}</button>
      </div>
    </div>`;
  }

  F.player = { audio, play, toggle, next, prev, seek, skip, close, cur, titleOf, artistOf, Wave, Cover, PlayerBar };
})();
