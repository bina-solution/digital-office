/* widget.js — «קבצים» in a window too small for the app (a console window dragged down toward its
   smallest, 380×260; a short strip): ONE thing, the one that matters now, filling the box — never
   the whole app squeezed into it. In this order:
     1. something plays     → the player's face: the cover, the wave, the five buttons
     2. a file is open      → the viewer itself, its bar thinned to ×, the name and ⋯ (files.css)
     3. pictures            → a frame that shows them one at a time (Photos, or a folder that is
                              mostly pictures): every 6 s, a swipe or an arrow, a tap opens it
     4. videos              → their posters one at a time; a tap plays it in the viewer
     5. any other place     → its own short list: a tap opens, a long press or a right click is the
                              item's menu
   The place's name is the switch: another place, the parent folder, a list instead of a frame. The
   full app comes back by itself when the window grows (shell.js measures the box). The shapes inside
   answer the widget's own box, not the screen — .wg is a size container (files.css). */
(function () {
  "use strict";
  const { html, hooks, state, set, L, ic, fmtDur, fmtWhen, fmtSize, thumbUrl, contentUrl } = F;
  const T = F.types, U = F.ui;

  const PLACE_ICON = { home: "home", folder: "drive", recent: "clock", starred: "star", photos: "image", music: "music",
    videos: "film", trash: "trash", search: "search" };
  const keyOf = (r) => r.view + ":" + (r.id || "");
  const isPicture = (f) => ["image", "raster"].includes(T.kindOf(f));
  const isSound = (f) => T.isMedia(f) === "audio";
  const newest = (a, b) => String(b.taken || b.created || "").localeCompare(String(a.taken || a.created || ""));
  function placeName(r) {
    if (r.view === "folder") { const f = F.data.folderPath(r.id).slice(-1)[0]; return f ? f.name : L("הקבצים שלי", "My files"); }
    if (r.view === "search") return L("חיפוש", "Search") + (r.q ? " · " + r.q : "");
    const t = F.shell.TITLES[r.view] || F.shell.TITLES.home;
    return L(t[0], t[1]);
  }
  const placeIcon = (r) => (r.view === "folder" && r.id ? "folder" : PLACE_ICON[r.view] || "home");

  /* which face a place gets — a frame for pictures and for videos, a list for the rest — unless the
     person chose the other one for this place */
  function faceOf(r, files) {
    const chosen = (state.wgAs || {})[keyOf(r)];
    if (r.view === "videos") return chosen === "list" || !files.length ? "list" : "videos";
    const pics = files.filter(isPicture).length;
    if (!pics) return "list";
    if (chosen) return chosen;
    return r.view === "photos" || (r.view === "folder" && pics >= 3 && pics >= files.length * 0.6) ? "frame" : "list";
  }
  const choose = (as) => set({ wgAs: { ...(state.wgAs || {}), [keyOf(state.route)]: as } });
  function switchMenu(e, face) {
    const r = state.route, S = F.shell, out = [];
    if (r.view === "folder" && r.id) {
      const up = F.data.folderPath(r.id).slice(-2, -1)[0];
      out.push({ icon: "folder", label: L("לתיקייה ", "Up to ") + (up ? up.name : L("הקבצים שלי", "My files")), run: () => F.go({ view: "folder", id: up ? up.id : "" }) });
    }
    const files = state.list.files;
    if (face !== "list") out.push({ icon: "list", label: L("הצגה כרשימה", "Show as a list"), run: () => choose("list") });
    else if (r.view === "videos" && files.length) out.push({ icon: "film", label: L("הסרטונים שכאן, אחד־אחד", "The videos here, one at a time"), run: () => choose("frame") });
    else if (files.some(isPicture)) out.push({ icon: "image", label: L("התמונות שכאן, אחת־אחת", "The pictures here, one at a time"), run: () => choose("frame") });
    if (out.length) out.push({ sep: true });
    [...S.PLACES, ...S.MEDIA].forEach((p) => out.push({ icon: p.icon, label: L(p.he, p.en), run: () => F.go(p) }));
    U.openMenu(out, e, L("מה להציג כאן", "What to show here"));
  }
  function PlaceSwitch({ face }) {
    const r = F.useStore((s) => s.route);
    F.useStore((s) => s.folders);           // a folder's name arrives with the folders
    return html`<button class="wg-place" title=${L("מה להציג כאן", "What to show here")} aria-haspopup="menu" onClick=${(e) => switchMenu(e, face)}>
      ${ic(placeIcon(r), "sm")}<b><bdi>${placeName(r)}</bdi></b>${ic("chevron-down", "sm")}</button>`;
  }

  /* ── playing: the player's face ─────────────────────────────────────────── */
  function play(files, it) {
    const q = files.filter(isSound);
    if (!q.length) return;
    F.player.play(q, Math.max(0, q.findIndex((x) => x.id === (it && it.id))));
    set({ wgList: false });
  }
  /* onMin: the face folds into a line under the place (shown again from that line) */
  function PlayerFace({ onMin }) {
    const p = F.useStore((s) => s.player);
    const it = p.queue[p.index];
    if (!it) return null;
    const P = F.player, rest = Math.max(0, (p.duration || 0) - (p.time || 0));
    return html`<section class="wgp" role="region" aria-label=${L("נגן", "Player")}>
      <div class="art"><${P.Cover} it=${it} big /></div>
      <div class="info">
        <div class="ttl">
          <span class="t"><b title=${it.name}><bdi>${P.titleOf(it)}</bdi></b><span>${P.artistOf(it)}</span></span>
          <button class="icbtn" title=${L("מזעור הנגן", "Minimize the player")} onClick=${onMin}>${ic("chevron-down")}</button>
          <button class="icbtn" title=${L("סגירת הנגן", "Close the player")} onClick=${P.close}>${ic("x")}</button>
        </div>
        <${P.Wave} it=${it} time=${p.time} duration=${p.duration} />
        <div class="times"><span class="num">${fmtDur(p.time)}</span><span class="num">-${fmtDur(rest)}</span></div>
      </div>
      <div class="ctl">
        <button class="icbtn skip" title=${L("15 שניות אחורה", "Back 15 seconds")} onClick=${() => P.skip(-15)}>${ic("back15")}</button>
        <button class="icbtn" title=${L("הקודם", "Previous")} onClick=${P.prev}>${ic("prev")}</button>
        <button class="big" title=${p.playing ? L("השהיה", "Pause") : L("ניגון", "Play")} onClick=${P.toggle}>${ic(p.playing ? "pause" : "play", "lg")}</button>
        <button class="icbtn" title=${L("הבא", "Next")} disabled=${p.queue.length < 2} onClick=${() => P.next(false)}>${ic("next")}</button>
        <button class="icbtn skip" title=${L("15 שניות קדימה", "Forward 15 seconds")} onClick=${() => P.skip(15)}>${ic("fwd15")}</button>
      </div>
    </section>`;
  }
  /* the folded player: one line at the bottom of the list */
  function NowBar() {
    const p = F.useStore((s) => s.player);
    const it = p.queue[p.index];
    if (!it) return null;
    const pct = p.duration ? Math.min(100, (p.time / p.duration) * 100) : 0;
    return html`<div class="wg-now" role="region" aria-label=${L("נגן", "Player")}>
      <button class="wg-now-open" title=${L("פתיחת הנגן", "Open the player")} onClick=${() => set({ wgList: false })}>
        <span class="th"><${F.player.Cover} it=${it} /></span>
        <span class="t"><b><bdi>${F.player.titleOf(it)}</bdi></b><span><span class="num">${fmtDur(p.time)} / ${fmtDur(p.duration)}</span></span></span>
      </button>
      <button class="wg-go" title=${p.playing ? L("השהיה", "Pause") : L("ניגון", "Play")} onClick=${F.player.toggle}>${ic(p.playing ? "pause" : "play", "sm")}</button>
      <button class="icbtn" title=${L("סגירת הנגן", "Close the player")} onClick=${F.player.close}>${ic("x", "sm")}</button>
      <i class="wg-now-bar" style=${"width:" + pct + "%"}></i>
    </div>`;
  }

  /* ── pictures and videos: one at a time ─────────────────────────────────── */
  /* the picture, then the file itself (a small image), then the type's glyph — never a broken one */
  function Pic({ it, onDead }) {
    const [n, setN] = hooks.useState(0);
    const srcs = T.hasThumb(it) ? [thumbUrl(it, 1024)] : [];
    if (T.kindOf(it) === "image" && Number(it.size) < 12e6) srcs.push(contentUrl(it.id));
    if (n >= srcs.length) return html`<span class="wgf-glyph">${ic(T.icon(it), "xl")}</span>`;
    return html`<img class="fg" key=${srcs[n]} src=${srcs[n]} alt=${it.name} draggable="false"
      onError=${() => { if (n + 1 >= srcs.length && onDead) onDead(it.id); setN(n + 1); }} />`;
  }
  function Frame({ items: all, video, face }) {
    // a picture nothing can draw is stepped over (a video keeps its glyph: it still plays)
    const [dead, setDead] = hooks.useState(null);
    const kill = video ? null : (id) => setDead((d) => ({ ...(d || {}), [id]: 1 }));
    const items = dead ? all.filter((x) => !dead[x.id]) : all;
    const n = items.length;
    const [at, setAt] = hooks.useState(0);
    const [gone, setGone] = hooks.useState(null);         // the slide fading out under the new one
    // a person who asked for less motion steps the pictures by hand; the slideshow is one press away
    const [paused, setPaused] = hooks.useState(() => matchMedia("(prefers-reduced-motion: reduce)").matches);
    const hold = F.useStore((s) => !!(s.viewer || s.menu || s.dialog));
    const sw = hooks.useRef(null), swiped = hooks.useRef(false);
    const i = n ? Math.min(at, n - 1) : 0, it = items[i];
    const step = (d) => { if (n < 2) return; setGone(it); setAt((i + d + n) % n); };
    const open = () => F.viewer.open(items, i);
    /* the next picture is decoded before it is shown — a slide never flashes empty */
    hooks.useEffect(() => {
      if (video || paused || hold || n < 2) return;
      let off = false;
      const t = setTimeout(() => {
        const im = new Image(), go = () => { if (!off) step(1); };
        im.src = thumbUrl(items[(i + 1) % n], 1024);
        (im.decode ? im.decode() : Promise.resolve()).then(go, go);
      }, 6000);
      return () => { off = true; clearTimeout(t); };
    }, [i, n, paused, hold, video]);
    hooks.useEffect(() => { if (!gone) return; const t = setTimeout(() => setGone(null), 700); return () => clearTimeout(t); }, [gone]);
    /* the keyboard, while nothing else is open: the arrows step, Space pauses, Enter opens */
    hooks.useEffect(() => {
      const key = (e) => {
        if (state.viewer || state.menu || state.dialog || (e.target.closest && e.target.closest("input,textarea,[contenteditable]"))) return;
        const rtl = document.dir === "rtl";
        if (e.key === "ArrowLeft") step(rtl ? 1 : -1);
        else if (e.key === "ArrowRight") step(rtl ? -1 : 1);
        else if (e.key === " " && !video && n > 1) { e.preventDefault(); setPaused((x) => !x); }
        else if (e.key === "Enter" && e.target === document.body) open();
      };
      addEventListener("keydown", key);
      return () => removeEventListener("keydown", key);
    });
    if (!it) return html`<${Rows} face="list" />`;
    const rtl = document.dir === "rtl";
    const down = (e) => { if (!e.target.closest("button")) sw.current = { x: e.clientX, y: e.clientY }; };
    const up = (e) => {
      const s = sw.current; sw.current = null;
      if (!s) return;
      const dx = e.clientX - s.x, dy = e.clientY - s.y;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.5) { swiped.current = true; step((dx > 0) === rtl ? 1 : -1); }
    };
    const click = (e) => { if (e.target.closest("button")) return; if (swiped.current) { swiped.current = false; return; } open(); };
    const stop = (e) => e.stopPropagation();
    const m = it.meta || {};
    const where = (F.data.folderPath(it.folder || "").slice(-1)[0] || {}).name;
    const caption = video ? F.splitName(it.name)[0]
      : [fmtWhen(it.taken || it.created), state.route.view !== "folder" ? where : ""].filter(Boolean).join(" · ");
    const sub = [n > 1 ? L(`${i + 1} מתוך ${n}`, `${i + 1} of ${n}`) : "", video && m.duration ? fmtDur(m.duration) : ""].filter(Boolean).join(" · ");
    const slide = (x, cls) => html`<div class=${"wgf-s" + cls} key=${x.id} style=${"--pic:url(" + JSON.stringify(thumbUrl(x, 1024)) + ")"}><${Pic} it=${x} onDead=${kill} /></div>`;
    return html`<div class=${"wgf" + (video ? " video" : "")} role="group" aria-roledescription=${L("מצגת", "carousel")}
      aria-label=${placeName(state.route)} onPointerDown=${down} onPointerUp=${up} onClick=${click}>
      ${gone && gone.id !== it.id && slide(gone, " gone")}
      ${slide(it, gone ? " in" : "")}
      ${video && html`<span class="wgf-play" aria-hidden="true">${ic("play", "lg")}</span>`}
      <div class="wgf-top" onClick=${stop}><${PlaceSwitch} face=${face} /></div>
      ${n > 1 && html`<button class="wgf-nav prev" title=${L("הקודם", "Previous")} onClick=${(e) => { stop(e); step(-1); }}>${ic("chevron", rtl ? "" : "flip")}</button>
        <button class="wgf-nav next" title=${L("הבא", "Next")} onClick=${(e) => { stop(e); step(1); }}>${ic("chevron", rtl ? "flip" : "")}</button>`}
      <div class="wgf-cap">
        <span class="t"><b><bdi>${caption}</bdi></b>${sub && html`<span>${sub}</span>`}</span>
        ${!video && n > 1 && html`<button class="wgf-btn" title=${paused ? L("המשך המצגת", "Resume the slideshow") : L("השהיית המצגת", "Pause the slideshow")}
          onClick=${(e) => { stop(e); setPaused(!paused); }}>${ic(paused ? "play" : "pause", "sm")}</button>`}
      </div>
    </div>`;
  }

  /* ── any other place: its own short list ───────────────────────────────── */
  const Note = ({ icon, text, bad, children }) => html`<div class=${"wg-note" + (bad ? " bad" : "")}>${ic(icon, "lg")}<span>${text}</span>${children}</div>`;
  function emptyText(r) {
    return ({ trash: L("האשפה ריקה", "Trash is empty"), starred: L("עוד אין כאן כוכבים", "No starred items yet"),
      recent: L("עוד לא נפתח כלום", "Nothing opened yet"), photos: L("עוד אין כאן תמונות", "No photos yet"),
      music: L("עוד אין כאן אודיו", "No audio yet"), videos: L("עוד אין כאן סרטונים", "No videos yet"),
      search: L("לא נמצא כלום", "Nothing found"), home: L("עוד אין כאן קבצים — אפשר לגרור לכאן", "No files yet — drag them here") })[r.view]
      || L("התיקייה ריקה — אפשר לגרור לכאן קבצים", "This folder is empty — drag files here");
  }
  function Row({ it, files, music }) {
    const on = F.useStore((s) => { const c = s.player.queue[s.player.index]; return c && c.id === it.id ? (s.player.playing ? 2 : 1) : 0; });
    const ctx = F.useStore((s) => !!(s.menu && s.menu.for === it.id));
    const press = hooks.useRef({ at: 0, long: false, timer: 0 });
    const folder = it.kind === "folder", sound = isSound(it);
    const menu = (e) => U.openMenu(U.actionsFor([it], "widget"), e, it.name, it.id);
    const open = () => {
      if (folder) return F.go({ view: "folder", id: it.id });
      if (sound) return on ? F.player.toggle() : play(files, it);
      const rest = files.filter((x) => x.kind !== "folder");
      F.viewer.open(rest, Math.max(0, rest.findIndex((x) => x.id === it.id)));
    };
    const quit = () => clearTimeout(press.current.timer);
    const dur = (it.meta || {}).duration;
    const meta = folder ? (it.count ? F.count(it.count, ["קובץ אחד", "1 file"], ["קבצים", "files"]) : L("תיקייה", "Folder"))
      : music ? (it.meta || {}).artist || fmtWhen(it.created) : [fmtWhen(it.created), fmtSize(it.size)].filter(Boolean).join(" · ");
    return html`<div class=${"wg-r" + (on ? " on" : "") + (ctx ? " ctx" : "")} role="listitem" tabIndex="0" data-id=${it.id}
      onClick=${() => { if (press.current.long) { press.current.long = false; return; } open(); }}
      onKeyDown=${(e) => { if (e.key === "Enter") open(); else if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) { e.preventDefault(); menu(e); } }}
      onContextMenu=${(e) => { e.preventDefault(); if (Date.now() - press.current.at > 1500) menu(e); }}
      onPointerDown=${(e) => {
        if (e.pointerType !== "touch") return;
        press.current.at = Date.now(); quit();
        press.current.timer = setTimeout(() => { press.current.long = true; navigator.vibrate && navigator.vibrate(12); menu(e); }, 480);
      }}
      onPointerUp=${quit} onPointerCancel=${quit}
      onPointerMove=${(e) => { if (e.pointerType === "touch" && Math.abs(e.movementX) + Math.abs(e.movementY) > 6) quit(); }}>
      <span class=${"th" + (folder ? " folder" : "")}>${music ? html`<${F.player.Cover} it=${it} />` : html`<${U.Thumb} it=${it} size=${96} />`}</span>
      <span class="t"><span class="fname"><${U.Name} name=${it.name} /></span><span class="meta">${meta}</span></span>
      ${sound && html`${dur ? html`<span class="wg-dur num">${fmtDur(dur)}</span>` : ""}
        <span class="wg-pl" aria-hidden="true">${on === 2 ? html`<span class="eq"><i></i><i></i><i></i></span>` : ic("play", "sm")}</span>`}
    </div>`;
  }
  function Rows({ face }) {
    const r = F.useStore((s) => s.route);
    const list = F.useStore((s) => s.list);
    F.useStore((s) => s.sort);
    const music = r.view === "music";
    const files = music ? [...list.files].sort(newest) : r.view === "home" ? list.files : F.views.sorted(list.files);
    const items = r.view === "home" ? [...files, ...list.folders] : [...list.folders, ...files];
    const n = list.files.length + list.folders.length;
    const canAdd = r.view === "folder" || r.view === "home";
    return html`<div class="wg-list">
      <header class="wg-h">
        <${PlaceSwitch} face=${face} />
        ${!list.loading && n > 0 && html`<span class="wg-n num" title=${F.count(n, ["פריט אחד", "1 item"], ["פריטים", "items"])}>${n}</span>`}
        <span class="spacer"></span>
        ${music && files.some(isSound) && html`<button class="wg-go" title=${L("ניגון הכל", "Play all")} onClick=${() => play(files, null)}>${ic("play", "sm")}</button>`}
        ${canAdd && html`<button class="icbtn" title=${L("הוספה: העלאה, תיקייה חדשה", "Add: upload, new folder")} aria-label=${L("הוספה", "Add")}
          onClick=${(e) => F.shell.addMenu(e, r.view === "folder" ? r.id || "" : undefined)}>${ic("plus")}</button>`}
      </header>
      <div class="wg-rows" role="list" aria-busy=${list.loading ? "true" : "false"}>
        ${list.loading && !items.length ? html`<${U.Skeleton} rows=${4} />`
          : list.error && !items.length ? html`<${Note} icon="alert" bad text=${list.error}>
              <button class="btn sm" onClick=${() => F.data.loadList(true)}>${ic("refresh", "sm")}${L("נסו שוב", "Try again")}</button></${Note}>`
          : !items.length ? html`<${Note} icon=${placeIcon(r)} text=${emptyText(r)} />`
          : items.slice(0, 300).map((it) => html`<${Row} key=${it.id} it=${it} files=${files} music=${music} />`)}
      </div>
    </div>`;
  }

  /* ── the widget ────────────────────────────────────────────────────────── */
  function Widget() {
    const r = F.useStore((s) => s.route);
    const files = F.useStore((s) => s.list.files);
    const loading = F.useStore((s) => s.list.loading);
    F.useStore((s) => s.wgAs);
    const playing = F.useStore((s) => s.player.index >= 0 && s.player.queue.length > 0);
    const asList = F.useStore((s) => !!s.wgList);
    if (r.view === "open") return html`<div class="wg"><${F.views.Content} /></div>`;
    if (playing && !asList) return html`<div class="wg"><${PlayerFace} onMin=${() => set({ wgList: true })} /></div>`;
    const face = loading && !files.length ? "list" : faceOf(r, files);
    const body = face === "frame" ? html`<${Frame} key=${keyOf(r)} items=${files.filter(isPicture).sort(newest)} face=${face} />`
      : face === "videos" ? html`<${Frame} key=${keyOf(r)} items=${[...files].sort(newest)} video face=${face} />`
      : html`<${Rows} face=${face} />`;
    return html`<div class="wg">${body}${playing && html`<${NowBar} />`}</div>`;
  }

  /* ── the console's own smallest form ───────────────────────────────────────
     A console window pushed far to a side is drawn by the console as one round button and a line,
     once its app has said what they are (console desktop.js, `bina:widget`). While something plays
     they are play/pause and the track; while a take is recorded, pause/resume; while files go up,
     the percent. Said only once there is something to say, and again only when it changes. */
  let said = "";
  function say(msg) {
    if (window.parent === window) return;
    const k = JSON.stringify(msg);
    if (k === said) return;
    said = k;
    try { window.parent.postMessage(Object.assign({ type: "bina:widget" }, msg), location.origin); } catch (e) { /* not in the console */ }
  }
  const LIVE = ["queued", "sending", "finishing"];
  function Publish() {
    const track = F.useStore((s) => { const it = s.player.queue[s.player.index]; return it ? it.id + (s.player.playing ? "+" : "") : ""; });
    const up = F.useStore((s) => {
      const live = s.uploads.filter((u) => LIVE.includes(u.state));
      if (!live.length) return -1;
      const t = live.reduce((a, u) => a + u.size, 0), d = live.reduce((a, u) => a + Math.min(u.sent, u.size), 0);
      return t ? Math.floor((d / t) * 10) * 10 : 0;
    });
    const rec = F.useStore((s) => (s.rec && s.rec.phase) || "");
    hooks.useEffect(() => {
      const it = F.player.cur(), playing = track.endsWith("+");
      if (rec === "recording" || rec === "paused") {
        const on = rec === "recording";
        say({ label: on ? L("מקליט", "Recording") : L("ההקלטה מושהית", "Recording paused"),
          action: { id: on ? "rec-pause" : "rec-resume", icon: on ? "pause" : "play", label: on ? L("השהיית ההקלטה", "Pause the recording") : L("המשך ההקלטה", "Resume the recording") } });
      } else if (it) say({ label: F.player.titleOf(it), action: { id: "play", icon: playing ? "pause" : "play", label: playing ? L("השהיה", "Pause") : L("ניגון", "Play") } });
      else if (up >= 0) say({ label: L(`מעלה · ${up}%`, `Uploading · ${up}%`) });
      else if (said) say({ label: "" });
    }, [track, up, rec]);
    return null;
  }
  // the console's button, pressed: only the console itself (this window's parent, this origin) is heard
  addEventListener("message", (e) => {
    if (e.source !== window.parent || e.origin !== location.origin || !e.data || e.data.type !== "bina:widget-action") return;
    if (e.data.id === "play") F.player.toggle();
    else if (e.data.id === "rec-pause" && F.recorder) F.recorder.pause();
    else if (e.data.id === "rec-resume" && F.recorder) F.recorder.resume();
  });

  F.widget = { Widget, PlayerFace, Publish };
})();
