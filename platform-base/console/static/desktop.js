/* desktop.js — the console's optional desktop mode ("שולחן עבודה").
 *
 * A spatial window manager for the shell, after Scott Jenson's Akademy 2026 prototype (the idea
 * inventory is ai/context/console-desktop-working-memory.md §3.S):
 *   - a centred FOCUS ZONE with a FLANK either side; a window's scale is a function of WHERE it is —
 *     full size in the zone, shrinking along one curve into the flanks (S3, S5, S6);
 *   - the background grid is drawn with that same curve, so the shrink reads as space compressing,
 *     and the rows under a dragged window light up as rails to the screen edge;
 *   - a stashed window stays a live window (S8) and its page reflows narrower so it stays legible;
 *     a window that publishes a widget becomes that widget (S10), any other one an icon far out;
 *   - shaking a dragged window sends every other window to the flanks (S12), stacked in columns;
 *   - Exposé is kept (E) as the contrast the demo drew: modal, and nothing in it can be worked in.
 * Written clean-room — the reference prototypes carry no licence, so no code or asset is taken.
 *
 * Loaded BEFORE app.js. Everything borrowed from the shell (MODULES, mIcon, joinEmbed, route,
 * openPalette, parseModuleHash, themeSaved, applyThemeTo, esc) is read at call time, never at load.
 */
(function () {
  "use strict";

  const BARE = new URLSearchParams(location.search).has("bare");
  if (BARE) document.documentElement.classList.add("bare");

  // A URL may ASK for the desktop — `?desktop` — and the person's own press still wins: the ask is a
  // STARTING state, dropped the first time somebody turns the desktop on or off (enable/disable
  // below). It exists because a surface can draw the office at a fixed desktop size and hand it to
  // somebody who has never been here: the public site's simulator embeds this very shell in a
  // 1440x900 frame, and a first-time visitor has no localStorage for the choice to live in, so the
  // site was showing the classic shell while the product's own face is the window desktop (the
  // owner, 2026-10-09: "הסימולציה באתר תדמית צריכה להציג את המערכת במצב דסקטופ"). Default off, so
  // every other surface — and every URL without the flag — behaves exactly as before.
  let asked = new URLSearchParams(location.search).has("desktop");

  const K = { on: "do-desktop", prefs: "do-desktop-prefs", layout: "do-desktop-layout" };
  const load = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode: layout is simply not kept */ } };

  const CFG = {
    MIN_WIDTH: 1024,        // below this the classic shell is the right tool
    BAR_TOP: 6, BAR_H: 30, DOCK_H: 64, DOCK_GAP: 10,
    S_MIN: 0.16,            // flank scale runs from 1 at the zone edge to this at the screen edge
    WIDGET_S: 0.42,         // a window that publishes a widget becomes it below this scale
    ICON_S: 0.24,           // any other window becomes an icon below this scale
    READ_Z: 0.8,            // a stashed window's page is drawn at no less than this zoom (it reflows narrower)
    GRID: 44,
    SHAKE_REV: 4, SHAKE_TRAVEL: 24, SHAKE_MS: 650, SHAKE_SPREAD: 320, SHAKE_COOL: 900,
    MIN_W: 380, MIN_H: 260, MAX_WINS: 40,
  };
  const DEF_PREFS = { bg: "grid", pill: true, rails: true, morph: false, live: 10, history: true };
  let prefs = Object.assign({}, DEF_PREFS, load(K.prefs, {}));

  let root = null, cvBg = null, cvFx = null, layer = null, dimEl = null, bar = null, dock = null;
  let snapEl = null, helpEl = null, toastEl = null, menuEl = null, menuName = "";
  let wins = [], order = [], seq = 0, focused = null, drag = null, expose = null, flash = null;
  let G = null, booted = false, clockT = 0, saveT = 0, toastT = 0, resizeRaf = 0, measCtx = null, acctFor = undefined;

  // what the rest of the desktop (desktop-memory.js) hangs off: window events, and the native tools
  const listeners = {};
  const emit = (ev, a, b) => (listeners[ev] || []).forEach(fn => { try { fn(a, b); } catch (e) { console.error("[desktop]", ev, e); } });
  const natives = {};

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const h = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const modules = () => (typeof MODULES !== "undefined" && Array.isArray(MODULES) ? MODULES : []);
  const modById = id => modules().find(m => m.id === id);
  // name, icon (and embed/service) of what a window shows: a module, a native tool, or an external
  // app (its own host, framed as is — see openExternal)
  const metaOf = w => modById(w.mid) ||
    (w.native && natives[w.native] ? { id: w.mid, name: natives[w.native].name, icon: natives[w.native].icon }
      : w.ext ? { id: w.mid, name: w.ext.name, icon: w.ext.icon || "external" } : { id: w.mid, name: w.mid, icon: "app" });
  const icon = name => (typeof mIcon === "function" ? mIcon(name) : "");
  // The shell's ONE reading of a remote app (app.js: `remote: {office, label}` on a module entry —
  // an app that runs on a LINKED office, ai/context/dgo-remote-apps.md §4). Borrowed, like
  // `externalUrl` below and for the same reason: one derivation, resolved at call time, empty when
  // the shell has not loaded yet (then a module is simply a module).
  const remoteInfo = m => (typeof window.remoteInfo === "function" ? window.remoteInfo(m) : null);
  const remoteTip = m => (typeof window.remoteTip === "function" ? window.remoteTip(m) : ((m && m.name) || ""));
  const remoteCls = m => (typeof window.remoteCls === "function" ? window.remoteCls(m) : "");
  // …and its MARK (flt-004): the office's colour, as the attribute app.js spells it — borrowed for the
  // same reason and resolved at the same time, so the dock's icons and its «עוד» panel carry the hue
  // the rail, the launcher and the palette carry. Empty when the office publishes no colour.
  const officeHue = m => (typeof window.officeHue === "function" ? window.officeHue(m) : "");
  // The remote facts of a WINDOW: an app on its own host carries them on `w.ext` (openExternal),
  // every other window reads them off the module it shows.
  const remoteOfWin = w => (w && w.ext ? w.ext.remote : remoteInfo(modById(w && w.mid)));
  const escH = s => (typeof esc === "function" ? esc(s) : String(s == null ? "" : s).replace(/[&<>"']/g, ""));
  const colorFor = id => { let x = 7; for (const c of String(id)) x = (x * 31 + c.charCodeAt(0)) >>> 0; return "dk-c" + (x % 7); };
  const SEARCH_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>';
  const GLYPH = {
    play: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5h3.6v14H7zM13.4 5H17v14h-3.6z"/></svg>',
  };

  // ── geometry: the zone, the flanks, and the one curve ─────────────────────────────────────
  function computeGeom() {
    const W = window.innerWidth, H = window.innerHeight;
    // an ultra-wide screen gives each flank a quarter of the width (the zone is the middle half, S5);
    // an ordinary one keeps a narrower flank so the zone still fits a real app
    const f = 0.18 + 0.07 * clamp((W - 1440) / 1120, 0, 1);
    const F = Math.max(200, Math.round(W * f));
    const top = CFG.BAR_TOP + CFG.BAR_H + 12, bottom = H - (CFG.DOCK_H + CFG.DOCK_GAP + 14);
    // The curve's steepness follows the flank: halfway out, a typical window must fit the flank's
    // width. On an ultra-wide screen that lands near the reference prototype's gentle curve; on an
    // ordinary one the flank is a narrow shelf and the curve drops faster to match.
    const zw = W - 2 * F, typ = Math.min(1180, zw * 0.7);
    const sMid = clamp(F / typ, 0.25, 0.7);
    const curve = Math.log((1 - sMid) / (1 - CFG.S_MIN)) / Math.log(0.5);
    G = { W, H, F, zl: F, zr: W - F, top, bottom, cy: (top + bottom) / 2, reach: Math.max(80, F - 12), curve };
  }
  const depth = cx => (cx < G.zl ? clamp((G.zl - cx) / G.reach, 0, 1) : cx > G.zr ? clamp((cx - G.zr) / G.reach, 0, 1) : 0);
  const scaleAt = cx => 1 - (1 - CFG.S_MIN) * Math.pow(depth(cx), G.curve);
  const inZone = w => w.s >= 0.995 || w.max;

  function modeFor(w, s) {
    if (w.max || (expose && expose.active)) return "win";
    if (w.dock === "icon") return w.widget ? "widget" : "icon";   // parked on a flank's icon shelf
    if (w.widget && s <= CFG.WIDGET_S) return "widget";
    if (s <= CFG.ICON_S) return "icon";
    return "win";
  }
  const WG_BOX = { widget: [120, 94], icon: [120, 90] };
  const boxOf = (w, s) => { const m = modeFor(w, s); return m === "win" ? [w.w * s, w.h * s] : WG_BOX[m]; };

  // ── windows ─────────────────────────────────────────────────────────────────────────────
  function urlFor(m, route) {
    if (m.embed && typeof joinEmbed === "function") return joinEmbed(m.embed, route || "");
    return "/?bare=1#/m/" + m.id + (route || "");   // a console-own view: the shell itself, bare
  }

  function createWin(m, o) {
    const w = Object.assign({
      id: "w" + (++seq), mid: m.id, route: "", w: 900, h: 640, cx: G.W / 2, cy: G.cy, s: 1, max: false,
      prev: null, home: null, mode: "", lastFocus: Date.now(), title: "", titleFull: "", widget: null, sleeping: false, rf: 0, native: null,
    }, o);
    const e = h("div", "dk-win" + (w.native ? " native" : ""));
    e.dataset.id = w.id;
    e.setAttribute("role", "region");
    // a native window (a desktop tool such as the memory view) draws DOM into its body; every other
    // window is an app page in an iframe
    const body = w.native ? '<div class="dk-body"><div class="dk-native"></div></div>'
      : '<div class="dk-body"><iframe title="' + escH(m.name) + '"></iframe>' +
        '<div class="dk-sleep">' + icon(m.icon) + '<div>' + escH(m.name) + ' במנוחה · לחצו כדי להעיר</div></div></div>';
    e.innerHTML =
      '<div class="dk-tb"><div class="dk-lights">' +
      '<button class="dk-l close" data-a="close" aria-label="סגירה" title="סגירה"></button>' +
      '<button class="dk-l min" data-a="stash" aria-label="שליחה לצד" title="שליחה לצד"></button>' +
      '<button class="dk-l zoom" data-a="max" aria-label="הגדלה" title="הגדלה"></button></div>' +
      '<div class="dk-title">' + icon(m.icon) + '<span class="dk-t"></span></div><div class="dk-end"></div></div>' + body +
      ["n", "s", "e", "w", "ne", "nw", "se", "sw"].map(d => '<div class="dk-rz ' + d + '" data-rz="' + d + '"></div>').join("") +
      '<div class="dk-wg"><button class="dk-wg-btn" type="button"></button><span class="dk-wg-lbl"></span></div>';
    w.el = e;
    w.frame = e.querySelector("iframe");
    w.body = e.querySelector(".dk-native");
    w.tEl = e.querySelector(".dk-t");
    w.wgBtn = e.querySelector(".dk-wg-btn");
    w.wgLbl = e.querySelector(".dk-wg-lbl");
    if (w.frame) w.frame.addEventListener("load", () => instrument(w));
    else e.querySelector(".dk-body").addEventListener("pointerdown", () => { if (focused !== w) focusWin(w, { keepFocus: true }); });
    const tb = e.querySelector(".dk-tb");
    tb.addEventListener("pointerdown", ev => startMove(ev, w, false));
    tb.addEventListener("dblclick", ev => { if (!ev.target.closest(".dk-l")) toggleMax(w); });
    e.querySelector(".dk-wg").addEventListener("pointerdown", ev => startMove(ev, w, true));
    e.querySelectorAll(".dk-rz").forEach(r => r.addEventListener("pointerdown", ev => startResize(ev, w, r.dataset.rz)));
    e.querySelector(".dk-lights").addEventListener("click", ev => {
      const a = ev.target.closest("[data-a]");
      if (!a) return;
      ev.stopPropagation();
      if (a.dataset.a === "close") closeWin(w);
      else if (a.dataset.a === "stash") stashWins([w], false);
      else toggleMax(w);
    });
    if (!w.native) e.querySelector(".dk-sleep").addEventListener("click", () => focusWin(w));
    // chrome clicks raise at once; clicks INSIDE the page raise on release (instrument), so a drag
    // out of a background window never pulls it forward (P4)
    e.addEventListener("pointerdown", () => { if (!expose && focused !== w) focusWin(w, { keepFocus: true }); }, true);
    layer.appendChild(e);
    wins.push(w);
    order.push(w);
    setTitle(w, "");
    applyPos(w, false);
    return w;
  }

  // The address a window on an app's own host loads: that host, plus the inner route the console
  // link carried (`#/m/<module>/<route>`). One derivation, used by every path that frames one.
  const extSrc = w => BinaExtRoute.framedUrl(w.ext && w.ext.url, w.ext && w.ext.route);

  function loadFrame(w) {
    if (w.ext) {
      // A linked office the platform has already MEASURED as not answering: the card, never the frame.
      // A window on a cross-origin host that fails shows the edge's `Bad Gateway` and cannot be
      // detected from here (a cross-origin frame that never painted throws on read) — so a window that
      // is opened on such an office would show a browser error page over a fact the shell holds.
      // Measured 2026-10-06: vps1's console, `bina.macbook`, the MacBook switched off.
      const m = modById(String(w.mid).replace(/^ext:/, ""));
      const r = remoteOfWin(w) || (m ? remoteInfo(m) : null);
      if (m && r && r.off) { remoteDownCard(w, m); return; }
      if (w.ext.ask) askOwnHost(w, true); else if (w.frame) w.frame.src = extSrc(w); return;
    }
    const m = modById(w.mid);
    if (!m || !w.frame) return;
    w.frame.src = urlFor(m, w.route);
  }

  // The same card the content frame shows (app.js: externalNotice), drawn in a desktop window.
  function remoteDownCard(w, m) {
    if (!w.frame) return;
    const box = w.el.querySelector(".dk-ask") || w.el.querySelector(".dk-body").appendChild(h("div", "dk-ask"));
    box.innerHTML = externalNotice(m, w.ext.url, "");
  }

  // A window on an app's own host is ASKED first where that host cannot show its sign-in inside a
  // frame (app.js: ownHostState) — the shell's own card instead of the browser's error page, and
  // the app once the sign-in is done. Asked again on every return to the tab (askOwnHosts), so a
  // sign-in that ran out becomes the card, and the card becomes the app. A window that is being
  // OPENED takes the browser to that sign-in itself (app.js: enterOwnHost) — nothing is under
  // anybody's hands yet; one that is already open only says so, with the button.
  async function askOwnHost(w, opening) {
    // the tile as the registry has it now: a window restored from a saved layout carries it as it was
    const m = modById(String(w.mid).replace(/^ext:/, "")) || w.ext.ask;
    // …and a window of a LINKED office whose office is measured unreachable (app.js: isOff) is the
    // same card for the same reason — until the person asks for it anyway (the card's «נסה שוב»).
    const need = isOff(m) && !w.ext.anyway ? ""
      : m.signed_in && noNestedHost(location.hostname) ? await ownHostState(m) : "ok";
    if (!wins.includes(w) || w.sleeping) return;
    if (need === "signin" && opening && enterOwnHost(m)) return;
    const card = w.el.querySelector(".dk-ask") || w.el.querySelector(".dk-body").appendChild(h("div", "dk-ask"));
    const was = card.innerHTML;
    // An office that is not answering outranks whatever this host answered: "נדרשת כניסה" about a
    // machine that is switched off is a sentence that sends the owner to the wrong place.
    const off = !!(m && (remoteOfWin(w) || remoteInfo(m) || {}).off);
    card.innerHTML = (need === "ok" && !off) ? "" : externalNotice(m, w.ext.url, off ? "" : need);
    if (need === "ok" && !off && (was || w.frame.getAttribute("src") !== extSrc(w))) w.frame.src = extSrc(w);
  }

  // the page is same-origin (the console proxies every app under /a/<name>/), so the shell can read
  // its title, theme it, and listen for the gestures it needs; a foreign page is simply left alone
  function instrument(w) {
    let d;
    try { d = w.frame.contentDocument; } catch (e) { return; }
    if (!d || w.sleeping || !d.documentElement || String(w.frame.src).endsWith("about:blank")) return;
    try { if (typeof applyThemeTo === "function" && typeof themeSaved === "function") applyThemeTo(d, themeSaved()); } catch (e) { /* not ours */ }
    const upd = () => setTitle(w, d.title || "");
    upd();
    try { new MutationObserver(upd).observe(d.head || d.documentElement, { subtree: true, childList: true, characterData: true }); } catch (e) { /* ignore */ }
    d.addEventListener("pointerdown", () => { w.raise = focused !== w; }, true);
    d.addEventListener("dragstart", () => { w.raise = false; }, true);
    d.addEventListener("pointerup", () => { if (w.raise) { w.raise = false; focusWin(w, { keepFocus: true }); } }, true);
    d.addEventListener("keydown", ev => { if (w !== focused) focusWin(w, { keepFocus: true }); globalKeys(ev); }, true);
    emit("load", w, d);
  }

  function applyPos(w, anim) {
    const s = w.max ? 1 : scaleAt(w.cx);
    w.s = s;
    const mode = modeFor(w, s);
    if (mode !== w.mode) setMode(w, mode);
    const e = w.el;
    e.classList.toggle("anim", !!anim);
    if (mode === "win") {
      e.style.width = w.w + "px";
      e.style.height = w.h + "px";
      e.style.left = (w.cx - w.w / 2) + "px";
      e.style.top = (w.cy - w.h / 2) + "px";
      let tf = "scale(" + s.toFixed(4) + ")";
      // the morph the talk tried and dropped (S7): kept behind a switch, off by default
      if (prefs.morph && s < 0.995) tf = "perspective(1600px) rotateY(" + ((w.cx < G.W / 2 ? 1 : -1) * (1 - s) * 50).toFixed(2) + "deg) " + tf;
      e.style.transform = tf;
    } else {
      const bw = WG_BOX[mode][0], bh = WG_BOX[mode][1];
      e.style.width = bw + "px";
      e.style.height = bh + "px";
      e.style.left = (w.cx - bw / 2) + "px";
      e.style.top = (w.cy - bh / 2) + "px";
      e.style.transform = "none";
    }
    e.classList.toggle("stashed", s < 0.995 && !w.max);
    e.classList.toggle("maxed", !!w.max);
    if (!(drag && drag.w === w)) reflow(w);
    emit("pos", w);
  }

  function setMode(w, mode) {
    w.mode = mode;
    w.el.classList.toggle("m-widget", mode === "widget");
    w.el.classList.toggle("m-icon", mode === "icon");
    renderWidget(w);
  }

  // A stashed window keeps working (S8): below READ_Z its page gets a NARROWER viewport, drawn back up,
  // so the app's own responsive layout takes over — the "responsive web" move the talk borrows (S10).
  function reflow(w) {
    const f = w.frame;
    if (!f) return;
    if (w.mode !== "win" || w.max || w.s >= CFG.READ_Z - 0.01) {
      if (w.rf) { f.style.width = ""; f.style.height = ""; f.style.transform = ""; w.rf = 0; }
      return;
    }
    const k = Math.round((w.s / CFG.READ_Z) * 100) / 100;
    if (w.rf === k) return;
    w.rf = k;
    f.style.width = (100 * k) + "%";
    f.style.height = (100 * k) + "%";
    f.style.transform = "scale(" + (1 / k).toFixed(4) + ")";
  }

  function renderWidget(w) {
    const m = metaOf(w);
    if (w.mode === "widget" && w.widget) {
      const a = w.widget.action;
      w.wgBtn.className = "dk-wg-btn";
      w.wgBtn.innerHTML = (a && GLYPH[a.icon]) || icon(m.icon);
      w.wgBtn.setAttribute("aria-label", a && a.label ? a.label : m.name);
      w.wgLbl.textContent = w.widget.label ? m.name + " · " + w.widget.label : m.name;
    } else {
      w.wgBtn.className = "dk-wg-btn " + colorFor(w.mid);
      w.wgBtn.innerHTML = icon(m.icon);
      w.wgBtn.setAttribute("aria-label", "החזרת " + m.name + " למרכז");
      w.wgLbl.textContent = w.title || m.name;
    }
  }

  // P3: long names keep both ends — the start says what it is, the end says which one
  function midTrunc(text, px, font) {
    measCtx = measCtx || document.createElement("canvas").getContext("2d");
    measCtx.font = font;
    if (measCtx.measureText(text).width <= px) return text;
    const cut = k => text.slice(0, Math.ceil(k / 2)) + "…" + text.slice(text.length - Math.floor(k / 2));
    let lo = 0, hi = text.length;
    while (lo < hi) { const k = Math.ceil((lo + hi) / 2); if (measCtx.measureText(cut(k)).width <= px) lo = k; else hi = k - 1; }
    return cut(lo);
  }
  function setTitle(w, t, force) {
    const m = metaOf(w);
    const name = m.name;
    t = String(t || "").trim();
    // a console view in a window is the shell itself: its page title is the brand line, not a place
    if (!m.embed || t === document.title) t = "";
    const r = remoteOfWin(w);
    // …and the office's own colour ON THE TITLE (flt-004): written before the early return below, so a
    // window REUSED for another module can never keep the previous office's hue.
    if (r && r.hue) w.tEl.setAttribute("data-office-hue", r.hue); else w.tEl.removeAttribute("data-office-hue");
    const full = (t && t !== name && !t.startsWith(name) ? name + " · " + t : (t || name)) +
      // a remote window's title carries the office, for the same reason the bar does: the two
      // entries of one alias are the same name in the same shell
      (r ? " · " + r.label + (r.off ? " (לא זמינה כרגע)" : "") : "");
    if (!force && w.titleFull === full) return;
    w.titleFull = full;
    w.title = t;
    const font = "600 13px " + getComputedStyle(document.body).fontFamily;
    w.tEl.textContent = midTrunc(full, Math.max(60, w.w - 170), font);
    w.tEl.title = full;
    w.el.setAttribute("aria-label", full);
    if (w.mode === "icon") renderWidget(w);
    if (w === focused) updateBar();
  }

  function applyZ() { order.forEach((x, i) => { x.el.style.zIndex = String(10 + i); }); }

  function focusWin(w, opts) {
    opts = opts || {};
    if (!w || wins.indexOf(w) < 0) return;
    if (w.sleeping) wake(w);
    order = order.filter(x => x !== w);
    order.push(w);
    applyZ();
    if (focused !== w) {
      const prev = focused;
      focused = w;
      wins.forEach(x => x.el.classList.toggle("focused", x === w));
      updateBar();
      emit("focus", w, prev);
    }
    w.lastFocus = Date.now();
    if (!opts.noHash && !w.native && !w.ext) writeHash(w);
    if (!opts.keepFocus && w.mode === "win" && w.frame) { try { w.frame.focus({ preventScroll: true }); } catch (e) { /* ignore */ } }
    enforceLive();
    saveSoon();
  }

  // the address bar is always the FOCUSED window's deep link — replaceState, so no hashchange loop
  function writeHash(w) {
    // An app of its own host is still a window of a MODULE, so its address is that module's deep
    // link — `#/m/project-pln/bina/projects/…`, the same address the content frame writes and the
    // same one a person copies. Writing `ext:<id>` (which is this file's window id for it, not a
    // module) named nothing: a reload of that address fell through route() to the FIRST tile, which
    // is a teleport, not a 404 anybody can see.
    const id = String(w.mid).replace(/^ext:/, "");
    const target = BinaExtRoute.deepLink(modById(id) ? id : "",
                                         modById(id) ? "" : w.mid,
                                         (w.ext ? w.ext.route : w.route) || "");
    if (location.hash !== target) history.replaceState(null, "", target);
  }

  function openModule(m, rest, o) {
    o = o || {};
    rest = rest || "";
    // Opening an app is the desktop's "navigation" — it moves no hash, so this is the one moment
    // the shell is asked what a navigation asks (app.js freshen): is there a newer build of this
    // page, and is this page's own sign-in still alive. Without it a desktop left open for days kept
    // running the build it was loaded with, and kept opening windows onto a sign-in that had run out.
    if (typeof freshen === "function") freshen(true);
    // An app of its own host: a window on that host, not a frame of the shell's proxy. `externalUrl`
    // is the shell's one derivation of that origin (app.js, loaded after this file, so it is resolved
    // at call time) — the same URL the content frame uses. The INNER ROUTE travels with it: a console
    // link names a screen inside the app (`#/m/project-pln/bina/projects/<id>/issues/<id>`, which is
    // what the office's own task tool hands the owner), and the content frame has always applied it
    // (app.js openModule); the desktop dropped it, so that link opened Plane at its home screen.
    if (m && m.external && typeof externalUrl === "function") {
      return openExternal({ id: m.id, name: m.name, url: externalUrl(m), route: rest, icon: m.icon,
                            remote: remoteInfo(m), ask: (m.signed_in && noNestedHost(location.hostname)) || m.remote ? m : null }, o);
    }
    const same = wins.filter(x => x.mid === m.id).sort((a, b) => b.lastFocus - a.lastFocus);
    if (same.length && !o.fresh) {
      const w = same[0];
      if (rest && rest !== w.route) { w.route = rest; if (!w.sleeping) loadFrame(w); }
      if (!inZone(w) || w.mode !== "win") bringToZone(w);
      focusWin(w);
      return w;
    }
    return openWin(m, rest, o);
  }

  function openWin(m, rest, o) {
    o = o || {};
    if (!m) return null;
    if (wins.length >= CFG.MAX_WINS) { toast("הגעתם למספר החלונות המרבי"); return null; }
    const n = wins.length % 7, zw = G.zr - G.zl, wh = G.bottom - G.top;
    const ww = o.w || Math.round(clamp(zw * 0.7, 520, 1180));
    const hh = o.h || Math.round(clamp(wh * 0.84, 360, 880));
    const cy = o.cy != null ? o.cy : clamp(G.cy + (n - 3) * 22, G.top + hh / 2, Math.max(G.top + hh / 2, G.bottom - hh / 2));
    const w = createWin(m, { route: rest || "", w: ww, h: hh, cx: o.cx != null ? o.cx : G.W / 2 + (n - 3) * 36, cy });
    if (inZone(w)) w.home = { cx: w.cx, cy: w.cy };
    if (o.sleep) { w.sleeping = true; w.el.classList.add("sleeping"); } else loadFrame(w);
    emit("open", w);
    if (!o.noFocus) focusWin(w); else { applyZ(); enforceLive(); }
    updateDock();
    saveSoon();
    return w;
  }

  // A desktop tool drawn by the shell itself rather than an app page — see api.wm.registerNative.
  function openNative(key, o) {
    o = o || {};
    const spec = natives[key];
    if (!spec || !root) return null;
    const ex = wins.find(x => x.native === key);
    if (ex && !o.fresh) { if (!inZone(ex) || ex.mode !== "win") bringToZone(ex); focusWin(ex); return ex; }
    const zw = G.zr - G.zl, wh = G.bottom - G.top;
    const ww = o.w || Math.round(clamp(spec.w || zw * 0.82, 560, 1400));
    const hh = o.h || Math.round(clamp(spec.h || wh * 0.88, 380, 920));
    const w = createWin({ id: "native:" + key, name: spec.name, icon: spec.icon }, {
      native: key, w: ww, h: hh, cx: o.cx != null ? o.cx : G.W / 2,
      cy: o.cy != null ? o.cy : clamp(G.cy, G.top + hh / 2, Math.max(G.top + hh / 2, G.bottom - hh / 2)),
    });
    if (inZone(w)) w.home = { cx: w.cx, cy: w.cy };
    try { spec.render(w.body, w); } catch (e) { console.error("[desktop] native", key, e); }
    emit("open", w);
    if (!o.noFocus) focusWin(w); else applyZ();
    updateDock();
    saveSoon();
    return w;
  }

  // An app whose UI lives on its OWN host (embed:false — n8n and the like) opens as a window on that
  // host, framed as it is. Whether it shows depends on the app letting the console frame it
  // (X-Frame-Options / CSP frame-ancestors, set where the app is routed); the window always carries a
  // way out to a tab, and says so for a moment, so a refusal is never a mystery.
  function openExternal(spec, o) {
    o = o || {};
    if (!root || !spec || !/^https?:\/\//.test(String(spec.url || ""))) return null;
    const id = "ext:" + (spec.id || spec.url);
    const route = String(spec.route || "");
    const ex = wins.find(x => x.mid === id);
    if (ex && !o.fresh) {
      // A second link to the SAME app is a different SCREEN of it: the window is already open, so
      // what changes is the route it is framing (a work item, a project), not the window.
      if (route && route !== ex.ext.route) { ex.ext.route = route; if (!ex.sleeping) loadFrame(ex); }
      if (!inZone(ex) || ex.mode !== "win") bringToZone(ex);
      focusWin(ex);
      return ex;
    }
    const zw = G.zr - G.zl, wh = G.bottom - G.top;
    const ww = o.w || Math.round(clamp(zw * 0.82, 560, 1400));
    const hh = o.h || Math.round(clamp(wh * 0.88, 380, 920));
    const ext = { url: String(spec.url), route, name: String(spec.name || spec.id || spec.url), icon: spec.icon || "external",
                  remote: spec.remote || null, ask: spec.ask || null };
    const w = createWin({ id, name: ext.name, icon: ext.icon }, {
      ext, w: ww, h: hh, cx: o.cx != null ? o.cx : G.W / 2,
      cy: o.cy != null ? o.cy : clamp(G.cy, G.top + hh / 2, Math.max(G.top + hh / 2, G.bottom - hh / 2)),
    });
    w.el.classList.add("external");
    const out = h("button", "dk-tbtn", icon("external"));
    out.type = "button";
    out.title = "פתיחה בלשונית נפרדת";
    out.setAttribute("aria-label", "פתיחה בלשונית נפרדת");
    out.addEventListener("pointerdown", e => e.stopPropagation());
    out.addEventListener("click", e => { e.stopPropagation(); window.open(ext.url, "_blank", "noopener"); });
    w.el.querySelector(".dk-end").appendChild(out);
    if (!ext.ask) {                     // a host that is asked first never comes up empty unexplained
      const hint = h("div", "dk-exthint");
      hint.textContent = "אם החלון נשאר ריק, האפליקציה אינה מאפשרת הטמעה · אפשר לפתוח אותה בלשונית (הכפתור בכותרת)";
      w.el.querySelector(".dk-body").appendChild(hint);
      setTimeout(() => hint.classList.add("gone"), 7000);
    }
    if (inZone(w)) w.home = { cx: w.cx, cy: w.cy };
    if (o.sleep) { w.sleeping = true; w.el.classList.add("sleeping"); } else loadFrame(w);
    emit("open", w);
    if (!o.noFocus) focusWin(w); else { applyZ(); enforceLive(); }
    updateDock();
    saveSoon();
    return w;
  }

  function closeWin(w) {
    emit("close", w);
    w.el.remove();
    wins = wins.filter(x => x !== w);
    order = order.filter(x => x !== w);
    if (focused === w) {
      focused = null;
      const next = order[order.length - 1];
      if (next) focusWin(next);
      else { updateBar(); history.replaceState(null, "", "#/"); }
    }
    updateDock();
    saveSoon();
  }

  function toggleMax(w) {
    w.dock = null;
    if (!w.max) {
      w.prev = { cx: w.cx, cy: w.cy, w: w.w, h: w.h };
      w.max = true;
      maxGeom(w);
    } else {
      const p = w.prev || {};
      w.max = false;
      w.cx = p.cx != null ? p.cx : G.W / 2;
      w.cy = p.cy != null ? p.cy : G.cy;
      w.w = p.w || Math.round(w.w * 0.8);
      w.h = p.h || Math.round(w.h * 0.8);
    }
    applyPos(w, true);
    setTitle(w, w.title, true);
    focusWin(w);
  }
  // "maximise" fills the focus zone, never the flanks: the periphery stays in view (S3)
  function maxGeom(w) {
    w.cx = G.W / 2;
    w.cy = (G.top + G.bottom) / 2;
    w.w = Math.round(G.zr - G.zl - 16);
    w.h = Math.round(G.bottom - G.top);
  }

  function bringToZone(w) {
    w.dock = null;
    const hm = w.home && w.home.cx >= G.zl && w.home.cx <= G.zr ? w.home : { cx: G.W / 2, cy: G.cy };
    w.cx = hm.cx;
    w.cy = hm.cy;
    applyPos(w, true);
  }

  function sleepWin(w) {
    if (w.sleeping || w.native) return;
    w.sleeping = true;
    w.el.classList.add("sleeping");
    try { w.frame.src = "about:blank"; } catch (e) { /* ignore */ }
  }
  function wake(w) {
    if (!w.sleeping) return;
    w.sleeping = false;
    w.el.classList.remove("sleeping");
    loadFrame(w);
  }
  // Every page a window shows is proxied by the console. Past the live budget the least-recently-used
  // windows sleep — title and route kept, page unloaded — until touched.
  // A window in a flank is there to be WATCHED — an agent's browser working beside the chat that
  // drives it, a widget with a count — so it is never the one put to sleep, however long since it was
  // focused. Sleep takes the zone's back windows and the icon shelf.
  function enforceLive() {
    const pages = () => wins.filter(x => !x.sleeping && !x.native);
    let live = pages();
    if (live.length <= prefs.live) return;
    const watched = x => !inZone(x) && x.mode !== "icon";
    const victims = live.filter(x => x !== focused && !watched(x)).sort((a, b) => a.lastFocus - b.lastFocus);
    while (live.length > prefs.live && victims.length) {
      sleepWin(victims.shift());
      live = pages();
    }
  }

  // An account switch moves the service's pointer; every window showing that service re-reads it —
  // asked first (platform:connection-changed), reloaded if it does not answer. The same contract
  // app.js keeps with the single frame (reloadEmbeddedApp).
  function reloadService(service) {
    wins.filter(x => x.frame && !x.sleeping && (modById(x.mid) || {}).service === service).forEach(w => {
      let acked = false;
      const onAck = e => {
        if (e.origin === location.origin && e.source === w.frame.contentWindow && e.data && e.data.type === "platform:reload-ack") acked = true;
      };
      window.addEventListener("message", onAck);
      try { w.frame.contentWindow.postMessage({ type: "platform:connection-changed", service }, location.origin); } catch (e) { /* reload covers it */ }
      setTimeout(() => { window.removeEventListener("message", onAck); if (!acked) loadFrame(w); }, 400);
    });
  }

  // ── moving, resizing, shaking ────────────────────────────────────────────────────────────
  function startMove(ev, w, fromWidget) {
    if (ev.button !== 0 || expose || compact) return;
    if (!fromWidget && ev.target.closest(".dk-l")) return;
    ev.preventDefault();
    const r = w.el.getBoundingClientRect(), isWin = w.mode === "win";
    drag = {
      kind: "move", w, widget: fromWidget, sx: ev.clientX, sy: ev.clientY, px: ev.clientX, py: ev.clientY,
      u: isWin ? clamp((ev.clientX - r.left) / r.width, 0, 1) : 0.5,
      v: isWin ? clamp((ev.clientY - r.top) / r.height, 0, 1) : 18 / w.h,
      moved: false, shift: ev.shiftKey, snap: null, raf: 0,
      dir: 0, ext: ev.clientX, rev: [], lastShake: 0, pid: ev.pointerId, cap: ev.currentTarget,
    };
    try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
    focusWin(w, { keepFocus: true });
  }

  function startResize(ev, w, dir) {
    if (ev.button !== 0 || expose || compact || !inZone(w)) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (w.max) { w.max = false; w.el.classList.remove("maxed"); }
    drag = {
      kind: "size", w, dir, sx: ev.clientX, sy: ev.clientY, px: ev.clientX, py: ev.clientY, moved: true, raf: 0,
      r0: { l: w.cx - w.w / 2, t: w.cy - w.h / 2, r: w.cx + w.w / 2, b: w.cy + w.h / 2 }, pid: ev.pointerId, cap: ev.currentTarget,
    };
    try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
    root.classList.add("dragging");
    focusWin(w, { keepFocus: true });
  }

  // The window follows the pointer on every move (no frame of lag); only the rails, which are a
  // canvas redraw, are coalesced onto animation frames.
  function onMove(ev) {
    if (!drag) return;
    drag.px = ev.clientX;
    drag.py = ev.clientY;
    drag.shift = ev.shiftKey;
    if (drag.kind === "move") moveStep(); else sizeStep();
  }
  let fxRaf = 0;
  function requestFx() { if (!fxRaf) fxRaf = requestAnimationFrame(() => { fxRaf = 0; drawFx(); }); }

  function moveStep() {
    const d = drag, w = d.w;
    if (!d.moved) {
      if (Math.hypot(d.px - d.sx, d.py - d.sy) < 4) return;
      d.moved = true;
      w.dock = null;   // once grabbed, a parked window follows the curve again
      root.classList.add("dragging");
      if (w.max) { const p = w.prev || {}; w.max = false; w.w = p.w || Math.round(w.w * 0.75); w.h = p.h || Math.round(w.h * 0.8); }
    }
    // keep the grabbed point under the pointer while the scale changes under it: cx and the scale
    // at cx depend on each other, so settle them by fixed-point iteration (converges in a few steps)
    let cx = d.px - (d.u - 0.5) * w.w * scaleAt(d.px);
    for (let i = 0; i < 5; i++) cx = d.px - (d.u - 0.5) * w.w * scaleAt(cx);
    const s = scaleAt(cx);
    let cy = d.py - (d.v - 0.5) * w.h * s;
    if (modeFor(w, s) !== "win") { cx = d.px; cy = d.py; }
    else cy = Math.max(cy, G.top - 16 + (w.h * s) / 2);
    w.cx = clamp(cx, 4, G.W - 4);
    w.cy = clamp(cy, 20, G.H - 24);
    applyPos(w, false);
    shakeCheck(d);
    snapCheck(d);
    requestFx();
  }

  function sizeStep() {
    const d = drag, w = d.w, dx = d.px - d.sx, dy = d.py - d.sy;
    let l = d.r0.l, t = d.r0.t, r = d.r0.r, b = d.r0.b;
    if (d.dir.indexOf("e") >= 0) r += dx;
    if (d.dir.indexOf("w") >= 0) l += dx;
    if (d.dir.indexOf("s") >= 0) b += dy;
    if (d.dir.indexOf("n") >= 0) t += dy;
    if (r - l < CFG.MIN_W) { if (d.dir.indexOf("w") >= 0) l = r - CFG.MIN_W; else r = l + CFG.MIN_W; }
    if (b - t < CFG.MIN_H) { if (d.dir.indexOf("n") >= 0) t = b - CFG.MIN_H; else b = t + CFG.MIN_H; }
    t = Math.max(t, G.top - 16);
    const cx = (l + r) / 2;
    if (cx < G.zl || cx > G.zr) return;   // a resize never carries the centre out of the zone
    w.w = Math.round(r - l);
    w.h = Math.round(b - t);
    w.cx = cx;
    w.cy = (t + b) / 2;
    applyPos(w, false);
  }

  function onUp() {
    if (!drag) return;
    const d = drag, w = d.w;
    drag = null;
    try { if (d.cap) d.cap.releasePointerCapture(d.pid); } catch (e) { /* ignore */ }
    root.classList.remove("dragging");
    snapEl.style.display = "none";
    if (d.kind === "move") {
      if (!d.moved) {
        if (d.widget) widgetClick(w);
        else if (d.shift) stashWins([w], false);
      } else if (d.snap) {
        if (d.snap.max) { w.prev = { cx: w.cx, cy: w.cy, w: w.w, h: w.h }; w.max = true; maxGeom(w); }
        else { w.max = false; w.w = Math.round(d.snap.w); w.h = Math.round(d.snap.h); w.cx = d.snap.l + d.snap.w / 2; w.cy = d.snap.t + d.snap.h / 2; }
      } else if (!inZone(w)) {
        // released in a flank: it docks into that side's column, on the curve and fully on screen
        stashWins([w], false);
        drawFx();
        saveSoon();
        return;
      }
    }
    if (w.s >= 0.995 && !w.max) w.home = { cx: w.cx, cy: w.cy };
    applyPos(w, !!d.snap);
    if (d.kind === "size" || d.snap) setTitle(w, w.title, true);
    drawFx();
    saveSoon();
  }

  // S12: a window shaken while dragged sends every OTHER window to the flanks. Stateless on purpose,
  // as in the reference prototype — nothing is remembered; a window comes back by being dragged back.
  function shakeCheck(d) {
    const x = d.px, now = performance.now();
    if (d.dir === 0) { if (Math.abs(x - d.ext) >= CFG.SHAKE_TRAVEL) { d.dir = Math.sign(x - d.ext); d.ext = x; } return; }
    if ((x - d.ext) * d.dir > 0) { d.ext = x; return; }
    if (Math.abs(x - d.ext) < CFG.SHAKE_TRAVEL) return;
    d.rev.push({ t: now, x: d.ext });
    d.dir = -d.dir;
    d.ext = x;
    d.rev = d.rev.filter(r => now - r.t <= CFG.SHAKE_MS);
    if (d.rev.length < CFG.SHAKE_REV || now - d.lastShake < CFG.SHAKE_COOL) return;
    const xs = d.rev.map(r => r.x);
    if (Math.max.apply(null, xs) - Math.min.apply(null, xs) > CFG.SHAKE_SPREAD) return;
    d.lastShake = now;
    d.rev = [];
    stashWins(wins.filter(x2 => x2 !== d.w), true);
  }

  function snapCheck(d) {
    const w = d.w;
    if (!d.shift || !inZone(w)) { d.snap = null; snapEl.style.display = "none"; return; }
    const zw = G.zr - G.zl, hh = G.bottom - G.top;
    let r = null;
    if (d.py < G.top + 24) r = { l: G.zl + 8, t: G.top, w: zw - 16, h: hh, max: true };
    else if (d.px < G.zl + zw * 0.2) r = { l: G.zl + 8, t: G.top, w: zw / 2 - 12, h: hh };
    else if (d.px > G.zr - zw * 0.2) r = { l: G.zl + zw / 2 + 4, t: G.top, w: zw / 2 - 12, h: hh };
    d.snap = r;
    if (!r) { snapEl.style.display = "none"; return; }
    snapEl.style.display = "block";
    snapEl.style.left = r.l + "px";
    snapEl.style.top = r.t + "px";
    snapEl.style.width = r.w + "px";
    snapEl.style.height = r.h + "px";
  }

  function widgetClick(w) {
    if (w.mode === "widget" && w.widget && w.widget.action) {
      if (w.sleeping) wake(w);
      try { w.frame.contentWindow.postMessage({ type: "bina:widget-action", id: w.widget.action.id }, location.origin); } catch (e) { /* ignore */ }
    } else {
      bringToZone(w);
      focusWin(w);
    }
  }

  // ── the stash: two columns per flank, most recent inside ───────────────────────────────
  function stashWins(list, fromShake) {
    list = list.filter(Boolean);
    if (!list.length) return;
    const all = new Set(list);
    // windows already out in a flank join the re-pack of their side, so the columns stay tidy
    wins.forEach(x => { if (!inZone(x) && !(drag && drag.w === x)) all.add(x); });
    const L = [], R = [];
    let alt = 0;
    all.forEach(x => {
      if (x.max) { const p = x.prev || {}; x.max = false; x.w = p.w || x.w; x.h = p.h || x.h; }
      if (inZone(x)) x.home = { cx: x.cx, cy: x.cy };
      const side = Math.abs(x.cx - G.W / 2) < 2 ? (alt++ % 2 ? 1 : -1) : (x.cx < G.W / 2 ? -1 : 1);
      (side < 0 ? L : R).push(x);
    });
    packSide(L, -1);
    packSide(R, 1);
    if (fromShake) { flash = { t0: performance.now(), dur: 900 }; drawFx(); toast("ניעור · שאר החלונות נשלחו לצדדים"); }
    saveSoon();
  }

  // The centre x, on the curve, for a window docked in a flank: the innermost (largest) position whose
  // box is fully on screen and clears `lim` (the zone edge, or the inner column). Where no position
  // does both — a very wide window on a narrow flank — the on-screen one that overlaps `lim` least.
  // A scan, not a bisection: moving inward grows the box, so neither edge is monotone in general.
  function fitCx(w, side, lim, reserve) {
    const edge = side < 0 ? 8 + (reserve || 0) : G.W - 8 - (reserve || 0);
    let best = null, fallback = null;
    for (let i = 0; i <= 600; i++) {
      const cx = side < 0 ? edge + i * 2 : edge - i * 2;
      if (side < 0 ? cx > lim : cx < lim) break;
      const bw = boxOf(w, scaleAt(cx))[0];
      if (side < 0 ? cx - bw / 2 < edge : cx + bw / 2 > edge) continue;
      const gap = side < 0 ? lim - (cx + bw / 2) : (cx - bw / 2) - lim;
      if (gap >= 0) best = cx;
      else if (!fallback || gap > fallback.gap) fallback = { cx, gap };
    }
    if (best != null) return { cx: best, ok: true };
    return { cx: fallback ? fallback.cx : edge - side * 60, ok: false };
  }

  // One flank's stash. The most recent windows form a column of live windows on the curve (S8).
  // What does not fit goes to a second, outer column when the flank is wide enough to hold one —
  // an ultra-wide screen, as in the demo (S13) — or else to a shelf of icons at the foot of the
  // flank: on an ordinary screen the curve leaves room for one column of live windows, not two.
  function packSide(list, side) {
    if (!list.length) return;
    const GAP = 10, avail = G.bottom - G.top, zoneLim = side < 0 ? G.zl - GAP : G.zr + GAP;
    list.forEach(w => { w.dock = null; });
    list.sort((a, b) => b.lastFocus - a.lastFocus);
    const hOf = (w, lim, rsv) => boxOf(w, scaleAt(fitCx(w, side, lim, rsv).cx))[1];
    const split = rsv => {
      const inner = [], outer = [];
      let used = 0;
      for (const w of list) {
        const bh = hOf(w, zoneLim, rsv);
        if (!inner.length || used + bh <= avail) { inner.push(w); used += bh + GAP; } else outer.push(w);
      }
      return { inner, outer };
    };
    // within a column windows keep their vertical order; the stack starts at the top, as in the demo
    const stack = (col, lim, rsv) => {
      col.sort((a, b) => a.cy - b.cy);
      let y = G.top, wrap = 0, edge = side < 0 ? G.zl : G.zr;
      for (const w of col) {
        const cx = fitCx(w, side, lim, rsv).cx;
        const b = boxOf(w, scaleAt(cx));
        if (y + b[1] > G.bottom && y > G.top) { wrap++; y = G.top + wrap * 26; }
        w.cx = cx;
        w.cy = y + b[1] / 2;
        w.dock = "col";
        y += b[1] + GAP;
        edge = side < 0 ? Math.min(edge, cx - b[0] / 2) : Math.max(edge, cx + b[0] / 2);
        applyPos(w, true);
      }
      return edge;
    };
    const one = split(0);
    if (!one.outer.length) { stack(one.inner, zoneLim, 0); return; }
    // two columns: the inner one gives up a strip at the screen edge for the outer one
    const rsv = Math.max(WG_BOX.icon[0], Math.round(G.F * 0.3)) + GAP;
    const two = split(rsv);
    if (two.inner.every(w => fitCx(w, side, zoneLim, rsv).ok)) {
      // dry run of the inner column's outer edge, to see whether the outer column fits beside it
      let innerEdge = side < 0 ? G.zl : G.zr;
      two.inner.forEach(w => {
        const cx = fitCx(w, side, zoneLim, rsv).cx, bw = boxOf(w, scaleAt(cx))[0];
        innerEdge = side < 0 ? Math.min(innerEdge, cx - bw / 2) : Math.max(innerEdge, cx + bw / 2);
      });
      const outerLim = innerEdge + (side < 0 ? -GAP : GAP);
      if (two.outer.every(w => fitCx(w, side, outerLim, 0).ok)) {
        stack(two.inner, zoneLim, rsv);
        stack(two.outer, outerLim, 0);
        return;
      }
    }
    // a narrow flank: one column of live windows, and a shelf of icons under it for the rest
    const IW = WG_BOX.icon[0] + 8, IH = WG_BOX.icon[1] + 8;
    const perRow = Math.max(1, Math.floor((G.F - 16) / IW));
    const shelfH = n => (n ? Math.ceil(n / perRow) * IH : 0);
    let k = one.inner.length;
    const colH = n => list.slice(0, n).reduce((s, w) => s + hOf(w, zoneLim, 0) + GAP, 0);
    while (k > 1 && colH(k) + shelfH(list.length - k) > avail) k--;
    stack(list.slice(0, k), zoneLim, 0);
    list.slice(k).forEach((w, i) => {
      const row = Math.floor(i / perRow), col = i % perRow;
      w.dock = "icon";
      w.cx = side < 0 ? 8 + IW / 2 + col * IW : G.W - 8 - IW / 2 - col * IW;
      w.cy = G.bottom - IH / 2 - row * IH;
      applyPos(w, true);
    });
  }

  function gatherAll() {
    let i = 0;
    wins.forEach(w => {
      if (inZone(w) && w.mode === "win") return;
      const hm = w.home && w.home.cx >= G.zl && w.home.cx <= G.zr ? w.home : { cx: G.W / 2 + (i % 5 - 2) * 40, cy: G.cy + (i % 5 - 2) * 26 };
      i++;
      w.dock = null;
      w.cx = hm.cx;
      w.cy = hm.cy;
      applyPos(w, true);
    });
    saveSoon();
  }

  // ── Exposé (kept for contrast, S2): modal; pick one to leave ────────────────────────────
  function toggleExpose() { if (expose) exitExpose(null); else enterExpose(); }
  function enterExpose() {
    const list = order.slice();
    if (!list.length) return;
    closeMenu();
    expose = { active: true, labels: [] };
    root.classList.add("expose");
    const ax = 40, ay = G.top + 6, aw = G.W - 80, ah = G.bottom - G.top - 30, n = list.length;
    let best = null;
    for (let c = 1; c <= n; c++) {
      const r = Math.ceil(n / c), cw = aw / c, ch = ah / r;
      const sc = Math.min.apply(null, list.map(w => Math.min((cw - 30) / w.w, (ch - 50) / w.h, 1)));
      if (!best || sc > best.sc) best = { c, cw, ch, sc };
    }
    list.forEach((w, i) => {
      const r = Math.floor(i / best.c), c = i % best.c;
      const s = Math.min((best.cw - 30) / w.w, (best.ch - 50) / w.h, 1);
      const cx = ax + (c + 0.5) * best.cw, cy = ay + (r + 0.5) * best.ch - 12;
      if (w.mode !== "win") setMode(w, "win");
      const e = w.el;
      e.classList.add("anim");
      e.style.width = w.w + "px";
      e.style.height = w.h + "px";
      e.style.left = (cx - w.w / 2) + "px";
      e.style.top = (cy - w.h / 2) + "px";
      e.style.transform = "scale(" + s.toFixed(4) + ")";
      const lb = h("div", "dk-xl");
      lb.textContent = w.titleFull || w.mid;
      lb.style.left = cx + "px";
      lb.style.top = (cy + (w.h * s) / 2 + 8) + "px";
      layer.appendChild(lb);
      expose.labels.push(lb);
    });
  }
  function exitExpose(pick) {
    if (!expose) return;
    expose.labels.forEach(l => l.remove());
    expose = null;
    root.classList.remove("expose");
    wins.forEach(w => { w.mode = ""; applyPos(w, true); });
    if (pick) { if (!inZone(pick) || pick.mode !== "win") bringToZone(pick); focusWin(pick); }
  }

  // ── the demo's other levers ────────────────────────────────────────────────────────────
  function doubleWins() {
    const base = wins.slice();
    base.forEach(w => {
      const m = modById(w.mid);
      if (m) openWin(m, w.route, { w: w.w, h: w.h, cx: clamp(w.cx + 60, G.zl, G.zr), cy: clamp(w.cy + 40, G.top + 120, G.bottom - 120), noFocus: true });
    });
    toast("החלונות הוכפלו · נסו עכשיו ניעור");
  }
  function openAll() {
    const todo = modules().filter(m => !wins.some(w => w.mid === m.id));
    todo.forEach(m => openWin(m, "", { noFocus: true }));
    if (todo.length) toast("נפתחו " + todo.length + " יישומים");
  }
  function closeAll() { wins.slice().forEach(closeWin); }
  function openDefaults() {
    const hm = typeof parseModuleHash === "function" ? parseModuleHash() : null;
    modules().filter(m => m.embed && (!hm || m.id !== hm[1])).slice(0, 3).forEach(m => openWin(m, "", { noFocus: true }));
  }
  function resetDesk() {
    closeAll();
    try { localStorage.removeItem(K.layout); } catch (e) { /* ignore */ }
    openDefaults();
    const hm = typeof parseModuleHash === "function" ? parseModuleHash() : null;
    const m = hm && modById(hm[1]);
    if (m) openModule(m, hm[2] || "");
    else if (order.length) focusWin(order[order.length - 1]);
    toast("שולחן העבודה אופס");
  }
  function cycle(dir) {
    if (order.length < 2) return;
    const next = dir > 0 ? order[0] : order[order.length - 2];
    if (!inZone(next) || next.mode !== "win") bringToZone(next);
    focusWin(next);
  }

  // ── background: the tension grid, and the rails ─────────────────────────────────────────
  function sizeCanvas(c) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = Math.round(G.W * dpr);
    c.height = Math.round(G.H * dpr);
    const x = c.getContext("2d");
    x.setTransform(dpr, 0, 0, dpr, 0, 0);
    return x;
  }
  // rows are pinched toward the middle in the flanks by the SAME curve that scales windows, so a
  // window pulled out shrinks exactly as fast as the space under it narrows
  function rowPath(x, y0, x0, x1) {
    const mid = G.H / 2, st = x1 > x0 ? 5 : -5;
    let first = true;
    for (let px = x0; st > 0 ? px <= x1 : px >= x1; px += st) {
      const y = mid + (y0 - mid) * scaleAt(px);
      if (first) { x.moveTo(px, y); first = false; } else x.lineTo(px, y);
    }
  }
  // The desk is drawn in the palette's colours, read where they are written (the theme block, through
  // the stage's element): the sky where the work is, paling toward the flanks as a sky does toward
  // the horizon, and its lines in the sky's own deep step. No colour is named in this file.
  const tok = n => getComputedStyle(root).getPropertyValue("--" + n).trim();
  const tint = (n, a) => { const v = parseInt(tok(n).slice(1), 16); return "rgba(" + (v >> 16) + "," + (v >> 8 & 255) + "," + (v & 255) + "," + a + ")"; };
  function drawBg() {
    const x = sizeCanvas(cvBg), W = G.W, H = G.H, mid = H / 2, step = CFG.GRID;
    sizeCanvas(cvFx);
    x.clearRect(0, 0, W, H);
    root.classList.toggle("wall", prefs.bg === "wallpaper");
    if (prefs.bg === "wallpaper") return;
    const g = x.createLinearGradient(0, 0, W, 0), desk = tok("desk"), far = tok("sky-line");
    g.addColorStop(0, far);
    g.addColorStop(G.zl / W, desk);
    g.addColorStop(G.zr / W, desk);
    g.addColorStop(1, far);
    x.fillStyle = g;
    x.fillRect(0, 0, W, H);
    [[0, H * 0.55], [H, H * 0.5]].forEach(p => {
      const rg = x.createRadialGradient(W / 2, p[0], 0, W / 2, p[0], p[1]);
      rg.addColorStop(0, tint("sky-line", 0.45));
      rg.addColorStop(1, tint("sky-line", 0));
      x.fillStyle = rg;
      x.fillRect(0, 0, W, H);
    });
    x.lineWidth = 1;
    x.strokeStyle = tint("sky-d", 0.16);
    // enough rows that, pinched at the edge, they still fill the height
    const R = Math.ceil(mid / step / CFG.S_MIN) + 1;
    x.beginPath();
    for (let r = -R; r <= R; r++) {
      const y0 = mid + r * step;
      if (Math.abs(y0 - mid) <= mid + step) { x.moveTo(G.zl, y0); x.lineTo(G.zr, y0); }
      rowPath(x, y0, G.zl, 0);
      rowPath(x, y0, G.zr, W);
    }
    x.stroke();
    const cols = [];
    for (let px = W / 2; px <= G.zr; px += step) cols.push(px);
    for (let px = W / 2 - step; px >= G.zl; px -= step) cols.push(px);
    let px = Math.max.apply(null, cols);
    while (px < W) { px += step * scaleAt(px); cols.push(px); }
    px = Math.min.apply(null, cols);
    while (px > 0) { px -= step * scaleAt(px); cols.push(px); }
    x.beginPath();
    cols.forEach(c => { x.moveTo(c, 0); x.lineTo(c, H); });
    x.stroke();
  }
  function drawFx() {
    if (!cvFx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1), x = cvFx.getContext("2d"), W = G.W, H = G.H;
    x.setTransform(dpr, 0, 0, dpr, 0, 0);
    x.clearRect(0, 0, W, H);
    if (!prefs.rails || prefs.bg === "wallpaper") return;
    let sides = [], band = null, alpha = 1, glow = null, from = null;
    if (drag && drag.kind === "move" && drag.moved) {
      const w = drag.w, b = boxOf(w, w.s);
      band = [w.cy - b[1] / 2, w.cy + b[1] / 2];
      sides = w.cx < G.zl ? [-1] : w.cx > G.zr ? [1] : [-1, 1];
      glow = [w.cx, w.cy];
      from = { "-1": Math.min(G.zl, w.cx - b[0] / 2), "1": Math.max(G.zr, w.cx + b[0] / 2) };
    } else if (flash) {
      const t = (performance.now() - flash.t0) / flash.dur;
      if (t >= 1) { flash = null; return; }
      alpha = 1 - t;
      sides = [-1, 1];
      band = [G.top, G.bottom];
      requestAnimationFrame(drawFx);
    } else return;
    const mid = H / 2, step = CFG.GRID, lo = tint("sky-d", (0.25 * alpha).toFixed(3)), hi = tint("sky-d", (0.95 * alpha).toFixed(3));
    x.lineWidth = 1.6;
    x.shadowBlur = 10;
    x.shadowColor = hi;
    for (let r = -Math.ceil(mid / step); r <= Math.ceil(mid / step); r++) {
      const y0 = mid + r * step;
      if (y0 < band[0] - 2 || y0 > band[1] + 2) continue;
      sides.forEach(sd => {
        const x0 = sd < 0 ? G.zl : G.zr, x1 = sd < 0 ? 0 : W;
        const gr = x.createLinearGradient(x0, 0, x1, 0);
        gr.addColorStop(0, lo);
        gr.addColorStop(1, hi);
        x.strokeStyle = gr;
        x.beginPath();
        if (from && from[String(sd)] !== x0) { x.moveTo(from[String(sd)], y0); x.lineTo(x0, y0); }
        rowPath(x, y0, x0, x1);
        x.stroke();
      });
    }
    if (glow) {
      x.shadowBlur = 0;
      const rg = x.createRadialGradient(glow[0], glow[1], 0, glow[0], glow[1], 280);
      rg.addColorStop(0, tint("sky-line", 0.5));
      rg.addColorStop(1, tint("sky-line", 0));
      x.fillStyle = rg;
      x.fillRect(0, 0, W, H);
    }
  }

  // ── menu bar ────────────────────────────────────────────────────────────────────────────
  function buildBar() {
    bar.innerHTML =
      // the mark has one owner, the sidebar brand in index.html; the bar reuses its SVG
      '<button class="dk-logo" data-menu="sys" aria-label="תפריט הלשכה">' +
        ((document.querySelector('.brand .logo svg') || {}).outerHTML || 'ל') + '</button>' +
      '<button class="dk-appname" data-menu="app"></button>' +
      '<button data-menu="win">חלון</button><button data-menu="view">תצוגה</button><button data-menu="help">עזרה</button>' +
      '<span class="dk-grow"></span>' +
      // the focused window's account (drive, mail, …): the classic top-bar chip, following focus
      '<span class="dk-acct hidden"></span>' +
      '<button class="dk-srch" data-act="palette" title="חיפוש (Ctrl K)">' + SEARCH_SVG + '<span>חיפוש</span></button>' +
      '<span class="dk-clock" aria-live="off"></span>';
    bar.addEventListener("click", ev => {
      const b = ev.target.closest("button");
      if (!b) return;
      if (b.dataset.act === "palette") { closeMenu(); if (typeof openPalette === "function") openPalette(); return; }
      if (b.dataset.menu) { if (menuName === b.dataset.menu) closeMenu(); else openMenu(b.dataset.menu, b); }
    });
    bar.addEventListener("mouseover", ev => {
      const b = ev.target.closest("[data-menu]");
      if (b && menuEl && menuName !== b.dataset.menu) openMenu(b.dataset.menu, b);
    });
    tickClock();
    updateBar();
  }
  function applyBarGeom(full) {
    const pill = prefs.pill && !full;
    bar.classList.toggle("pill", pill);
    bar.style.left = pill ? G.zl + "px" : "0px";
    bar.style.right = pill ? (G.W - G.zr) + "px" : "0px";
  }
  function updateBar() {
    if (!bar) return;
    const n = bar.querySelector(".dk-appname");
    // For a remote app the bar names the OFFICE as well: the bar is the one place that says what the
    // focused window IS, and "בינה ודעת" is two different windows on two different machines. The
    // office's MARK rides on that second half (flt-004) — the animal beside its name, the hue on the
    // name itself — so the answer is in the bar itself and not only in a tooltip.
    const r = focused ? remoteOfWin(focused) : null;
    if (n) n.innerHTML = escH(focused ? metaOf(focused).name : "הלשכה הדיגיטלית") + (!r ? ""
      : ` · <span class="dk-office"${r.hue ? ` data-office-hue="${escH(r.hue)}"` : ""}>` +
        (r.animal ? `<span class="office-animal">${icon(r.animal)}</span>` : "") +
        escH(r.label) + (r.off ? " (לא זמינה כרגע)" : "") + "</span>");
    // the account chip follows focus, like a menu bar follows the front app; re-rendered only when
    // the SERVICE changes, since rendering it probes the service
    const slot = bar.querySelector(".dk-acct");
    const m = focused && !focused.native ? modById(focused.mid) : null;
    const svc = m && m.service ? m.service : null;
    if (!slot || svc === acctFor) return;
    acctFor = svc;
    slot.innerHTML = "";
    slot.classList.toggle("hidden", !svc);
    if (svc && typeof renderAccountBar === "function") renderAccountBar(svc, slot);
  }
  function tickClock() {
    const c = bar && bar.querySelector(".dk-clock");
    if (!c) return;
    try {
      c.textContent = new Intl.DateTimeFormat("he-IL", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date());
    } catch (e) { c.textContent = new Date().toLocaleTimeString(); }
  }
  function winLabel(w) { return w.titleFull || metaOf(w).name; }
  function menuItems(name) {
    const f = focused, fm = f && !f.native ? modById(f.mid) : null;
    if (name === "sys") return [
      { label: "הגדרות מסוף…", act: openSettings },
      { label: "קיצורי מקלדת", kbd: "?", act: () => toggleHelp(true) },
      "-",
      { label: "חזרה לתצוגה הרגילה", act: () => api.disable() },
    ];
    if (name === "app") return [
      { label: fm ? "חלון נוסף של " + fm.name : "חלון נוסף", disabled: !fm, act: () => openWin(fm, f.route) },
      { label: "טעינה מחדש", disabled: !f, act: () => { if (f.sleeping) wake(f); else loadFrame(f); } },
      { label: "שליחה לצד", disabled: !f, act: () => stashWins([f], false) },
      { label: "הגדלה / שחזור", disabled: !f, act: () => toggleMax(f) },
      { label: "סגירת החלון", disabled: !f, act: () => closeWin(f) },
    ];
    if (name === "win") {
      const list = order.slice().reverse().map(w => ({ label: winLabel(w), chk: w === focused, act: () => { if (!inZone(w) || w.mode !== "win") bringToZone(w); focusWin(w); } }));
      return [
        { label: "ניעור: כל השאר לצדדים", kbd: "S", disabled: !f, act: () => stashWins(wins.filter(x => x !== focused), true) },
        { label: "החזרת הכל למרכז", act: gatherAll },
        { label: "כל החלונות", kbd: "E", act: toggleExpose },
        { label: "זיכרון: סיפור, עוגנים וציר זמן", kbd: "M", disabled: !natives.memory, act: () => openNative("memory") },
        "-",
        { label: "פתיחת כל היישומים", act: openAll },
        { label: "הכפלת החלונות (הדגמה)", kbd: "D", act: doubleWins },
        { label: "איפוס שולחן העבודה", kbd: "4", act: resetDesk },
        { label: "סגירת כל החלונות", disabled: !wins.length, act: closeAll },
      ].concat(list.length ? ["-"].concat(list) : []);
    }
    if (name === "view") return [
      { label: "רקע רשת מתיחה", kbd: "G", chk: prefs.bg === "grid", act: () => setPref("bg", prefs.bg === "grid" ? "wallpaper" : "grid") },
      { label: "תפריט עליון ממורכז", kbd: "1", chk: prefs.pill, act: () => setPref("pill", !prefs.pill) },
      { label: "מסילות אור בגרירה", chk: prefs.rails, act: () => setPref("rails", !prefs.rails) },
      { label: "כיפוף בצדדים (ניסוי שנדחה)", kbd: "0", chk: prefs.morph, act: () => setPref("morph", !prefs.morph) },
    ];
    return [
      { label: "קיצורי מקלדת", kbd: "?", act: () => toggleHelp(true) },
      { label: "הגדרות שולחן העבודה", act: openSettings },
    ];
  }
  function openMenu(name, btn) {
    closeMenu();
    const items = menuItems(name);
    menuEl = h("div", "dk-menu");
    menuEl.setAttribute("role", "menu");
    items.forEach(it => {
      if (it === "-") { menuEl.appendChild(h("hr")); return; }
      const b = h("button", "", '<span class="lbl">' + (it.chk != null ? '<span class="chk' + (it.chk ? " on" : "") + '"></span>' : "") +
        "<span></span></span>" + (it.kbd ? "<kbd>" + escH(it.kbd) + "</kbd>" : ""));
      b.querySelector(".lbl span:last-child").textContent = it.label;
      b.setAttribute("role", "menuitem");
      if (it.disabled) b.disabled = true;
      b.addEventListener("click", ev => { ev.stopPropagation(); closeMenu(); it.act(); });
      menuEl.appendChild(b);
    });
    root.appendChild(menuEl);
    const r = btn.getBoundingClientRect();
    const mw = menuEl.offsetWidth;
    menuEl.style.top = (r.bottom + 6) + "px";
    menuEl.style.left = clamp(r.right - mw, 6, G.W - mw - 6) + "px";
    menuName = name;
    btn.classList.add("open");
  }
  function closeMenu() {
    if (menuEl) menuEl.remove();
    menuEl = null;
    menuName = "";
    if (bar) bar.querySelectorAll("button.open").forEach(b => b.classList.remove("open"));
  }
  function openSettings() {
    const m = modById("settings");
    if (m) openModule(m, "");
  }

  // ── dock ────────────────────────────────────────────────────────────────────────────────
  // WHY THE DOCK IS BUDGETED (ai/context/console-dock-capacity-design.md): one 46px tile per
  // (app × machine) in an uncapped row made the dock's WIDTH a function of how many apps exist —
  // 2189px of content against a pill capped at `100vw - 40px`, hard-clipped, which at the owner's
  // own width left 17 of 40 tiles unreachable by pointer while the desktop's rail was hidden.
  //
  // The answer is the one `platform-navigation-design.md` §3.14 already chose for the rail: how many
  // destinations are visible is a function of the VIEWPORT, never of the estate. The arithmetic is
  // `static/dock-budget.js` (pure, unit-tested by `platform-base/console/test_dock_budget.mjs`); this
  // code spends it — the tiles that fit are drawn, and everything else lives behind ONE overflow door
  // in the last slot, which opens the grouped launcher grid with a filter. Geometry stops depending
  // on N, so no install can move or clip a tile, and nothing is ever unreachable.
  function dockBudget() {
    const B = window.BinaDockBudget || {};
    const L = B.DOCK || { tile: 46, gap: 8, pad: 20, sep: 5, min: 3 };
    const keys = Object.keys(natives);
    const apps = modules();
    const fixed = keys.length + 1;            // the desk's own tools + «כל החלונות»
    const budget = (B.resolveDock || (() => ({ slots: apps.length + fixed + 1, showMore: false })))({
      available: Math.max(0, window.innerWidth - 40), count: apps.length + fixed,
      tile: L.tile, gap: L.gap, pad: L.pad, sep: L.sep, min: L.min,
    });
    // The door takes the LAST slot, and the desk's own tools never go behind it: what is left for app
    // tiles is slots − fixed − 1 (`dockRoom` never returns fewer than one, and below CFG.MIN_WIDTH the
    // compact shell takes over, so this cannot degenerate into "a dock with no apps").
    const room = budget.showMore
      ? (B.dockRoom ? B.dockRoom(budget, budget.slots, fixed) : Math.max(1, budget.slots - fixed - 1))
      : apps.length;
    return { L: L, budget: budget, shown: apps.slice(0, room), behind: apps.slice(room), keys: keys };
  }

  function appTile(m) {
    // A remote app (one that runs on a LINKED office — the shell's remoteInfo, resolved at call time
    // like everything else borrowed from app.js) sits in the dock beside the local ones, with the
    // same corner mark the rail gives it and its office's name in the tooltip. Two tiles for one
    // alias is the normal case, so the mark and the tip are what tell a person which of the two opens
    // the other machine.
    const b = h("button", "dk-ic " + colorFor(m.id) + remoteCls(m),
      icon(m.icon) + '<span class="tip"></span>');
    b.querySelector(".tip").textContent = remoteTip(m);
    // …and WHICH other machine, in the office's own colour (flt-004): the dock's bracket above is the
    // "not this machine" mark every surface gives a remote app, and this is the half that names it.
    const r = remoteInfo(m);
    if (r && r.hue) b.dataset.officeHue = r.hue;
    b.dataset.mid = m.id;
    b.setAttribute("aria-label", remoteTip(m));
    b.addEventListener("click", ev => {
      const mm = modById(m.id);
      if (!mm) return;
      if (ev.ctrlKey || ev.metaKey || ev.shiftKey) openWin(mm, ""); else openModule(mm, "");
    });
    return b;
  }

  function moreTile(behind) {
    // One door, always in the same place (last child — leftmost in RTL) and always the same size, and
    // it says how many apps are behind it. Its glyph is its own: it first wore the all-windows one,
    // and the two sat side by side as the same grey tile twice, told apart by a count badge
    // (hp-laptop, 2026-10-06). Three dots is what "there is more behind this" looks like everywhere.
    const b = h("button", "dk-ic dk-c6 dk-more-ic",
      icon("more") + '<span class="tip"></span><span class="dk-more-n num"></span>');
    b.querySelector(".tip").textContent = "עוד " + behind.length + " אפליקציות";
    b.querySelector(".dk-more-n").textContent = String(behind.length);
    b.setAttribute("aria-label", "עוד " + behind.length + " אפליקציות — כל האפליקציות");
    b.addEventListener("click", () => openDockMore());
    return b;
  }

  // The door's panel: the EXISTING grouped launcher (same registry, same `group` order, same .htile
  // grid as renderHome(), same filter-in-place idiom as BinaNav) — nothing about it is invented, which
  // is why it cannot drift from the launcher. Every app is here, not only the ones the dock had to
  // hide: a door that shows a different set than the launcher is a second answer to "what is
  // installed". The `is-remote` mark and the office label ride along (dgo-remote-apps.md §4).
  function openDockMore() {
    closeDockMore();
    if (!root) return;
    const apps = modules();
    const ov = h("div", "dk-more");
    ov.setAttribute("role", "dialog");
    ov.setAttribute("aria-label", "כל האפליקציות");
    const box = h("div", "dk-more-box");
    const head = h("div", "dk-more-head");
    head.innerHTML = `<b>כל האפליקציות</b><small class="num">${apps.length}</small>`;
    const q = h("input", "dk-more-q");
    q.type = "search";
    q.placeholder = "חיפוש אפליקציה…";
    q.setAttribute("aria-label", "חיפוש אפליקציה");
    const list = h("div", "dk-more-list");
    const draw = () => {
      // the shell's one matcher (app.js moduleMatches): name, description, id, office — any case
      const hits = apps.filter(m => moduleMatches(m, q.value));
      const groups = [];
      hits.forEach(m => {
        let g = groups.find(x => x.name === (m.group || ""));
        if (!g) { g = { name: m.group || "", mods: [] }; groups.push(g); }
        g.mods.push(m);
      });
      list.innerHTML = groups.length ? groups.map(g =>
        (g.name ? `<div class="dk-more-grp">${esc(g.name)}</div>` : "") +
        `<div class="home-grid">${g.mods.map(m =>
          `<button class="htile${remoteCls(m)}"${officeHue(m)} data-mid="${esc(m.id)}">` +
            `<span class="htile-ic">${mIcon(m.icon)}</span>` +
            `<span class="htile-nm">${esc(m.name)}</span>` + officeLine(m) +
            `</button>`).join("")}</div>`).join("") : `<div class="dk-more-none">אין תוצאות</div>`;
      list.querySelectorAll("[data-mid]").forEach(el => el.addEventListener("click", ev => {
        const mm = modById(el.dataset.mid);
        closeDockMore();
        if (!mm) return;
        if (ev.ctrlKey || ev.metaKey || ev.shiftKey) openWin(mm, ""); else openModule(mm, "");
      }));
    };
    q.addEventListener("input", draw);
    ov.addEventListener("pointerdown", ev => { if (ev.target === ov) closeDockMore(true); });
    box.append(head, q, list);
    ov.appendChild(box);
    root.appendChild(ov);
    draw();
    q.focus();
  }
  // `back` = the panel was DISMISSED (Escape, a click beside it), not used to open an app: focus
  // goes back to the door it came from. It used to land on <body>, so a keyboard had to walk the
  // whole dock again to reach the place it had just left.
  function closeDockMore(back) {
    if (!root) return;
    const ov = root.querySelector(".dk-more");
    if (!ov) return;
    ov.remove();
    const door = back && dock && dock.querySelector(".dk-more-ic");
    if (door) door.focus();
  }

  function buildDock() {
    if (!dock) return;
    const d = dockBudget();
    // One source for the dock's dimensions: they are set HERE, from dock-budget.js, and consumed by
    // CSS as custom properties (a number that exists in two places is a future inconsistency).
    dock.style.setProperty("--dock-tile", d.L.tile + "px");
    dock.style.setProperty("--dock-gap", d.L.gap + "px");
    dock.style.setProperty("--dock-pad", (d.L.pad / 2) + "px");
    dock.innerHTML = "";
    d.shown.forEach(m => dock.appendChild(appTile(m)));
    dock.appendChild(h("span", "sep"));
    // the desktop's own tools (registered by desktop-memory.js), then the all-windows view
    d.keys.forEach(key => {
      const sp = natives[key];
      const b = h("button", "dk-ic " + (sp.color || "dk-c2"), icon(sp.icon) + '<span class="tip"></span>');
      b.querySelector(".tip").textContent = sp.name;
      b.dataset.mid = "native:" + key;
      b.setAttribute("aria-label", sp.name);
      b.addEventListener("click", () => openNative(key));
      dock.appendChild(b);
    });
    const all = h("button", "dk-ic dk-c6", icon("grid") + '<span class="tip">כל החלונות</span>');
    all.setAttribute("aria-label", "כל החלונות");
    all.addEventListener("click", toggleExpose);
    dock.appendChild(all);
    if (d.behind.length) dock.appendChild(moreTile(d.behind));
    updateDock();
  }
  function updateDock() {
    if (!dock) return;
    const open = new Set(wins.map(w => w.mid));
    dock.querySelectorAll("[data-mid]").forEach(b => b.classList.toggle("run", open.has(b.dataset.mid)));
  }

  // ── help, toast, keys ───────────────────────────────────────────────────────────────────
  function buildHelp() {
    const rows = [
      ["S", "ניעור: כל החלונות האחרים נשלחים לצדדים. אפשר גם לנער חלון בזמן שגוררים אותו"],
      ["E", "כל החלונות: התצוגה הישנה, להשוואה. בוחרים חלון כדי לצאת"],
      ["D", "הכפלת החלונות, כדי לראות איך הסידור עומד בעומס"],
      ["1", "תפריט עליון: ממורכז לאזור המיקוד, או לכל הרוחב"],
      ["G", "רקע: רשת מתיחה או טפט"],
      ["0", "כיפוף החלונות בצדדים (ניסוי שנדחה)"],
      ["4", "איפוס שולחן העבודה"],
      ["M", "זיכרון: מה עשיתם, מה היה חשוב, ומה עשתה המערכת באותו זמן"],
      ["Alt `", "מעבר בין חלונות"],
      ["Ctrl K", "חיפוש ופתיחה של יישום"],
      ["Shift", "בגרירה: הצמדה לחצי המסך או להגדלה. בלחיצה על כותרת: שליחה לצד"],
      ["?", "הצגה או הסתרה של הכרטיס הזה"],
    ];
    helpEl.innerHTML = "<h3>שולחן העבודה</h3><dl>" + rows.map(r => "<dt><kbd>" + r[0] + "</kbd></dt><dd>" + r[1] + "</dd>").join("") + "</dl>" +
      '<p class="dk-note">גררו חלון אל אחד הצדדים: הוא מתכווץ לאורך הרשת ונשאר חי ופעיל. חלון שמפרסם יישומון הופך לכפתור.</p>';
  }
  function toggleHelp(show) {
    const on = show == null ? !helpEl.classList.contains("show") : show;
    helpEl.classList.toggle("show", on);
  }
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastT);
    toastT = setTimeout(() => toastEl.classList.remove("show"), 1900);
  }
  function globalKeys(e) {
    if (e.altKey && e.code === "Backquote") { e.preventDefault(); cycle(e.shiftKey ? -1 : 1); return; }
    // Ctrl-K from INSIDE a window: the page's own document never reaches app.js's listener
    if ((e.ctrlKey || e.metaKey) && e.code === "KeyK" && e.target && e.target.ownerDocument && e.target.ownerDocument !== document) {
      e.preventDefault();
      if (typeof openPalette === "function") openPalette();
    }
  }
  function onKey(e) {
    if (!root) return;
    if (e.key === "Escape") {
      if (root.querySelector(".dk-more")) { closeDockMore(true); return; }
      if (menuEl) { closeMenu(); return; }
      if (helpEl.classList.contains("show")) { toggleHelp(false); return; }
      if (expose) { exitExpose(null); return; }
    }
    globalKeys(e);
    if (e.defaultPrevented) return;
    const t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || ""));
    if (typing || e.ctrlKey || e.metaKey || e.altKey || document.querySelector(".pal-ov")) return;
    const acts = {
      Digit1: () => setPref("pill", !prefs.pill),
      KeyE: toggleExpose,
      KeyD: doubleWins,
      KeyS: () => { if (focused) stashWins(wins.filter(x => x !== focused), true); },
      Digit4: resetDesk,
      KeyG: () => setPref("bg", prefs.bg === "grid" ? "wallpaper" : "grid"),
      Digit0: () => setPref("morph", !prefs.morph),
      KeyM: () => { if (natives.memory) openNative("memory"); },
    };
    const a = !e.shiftKey && acts[e.code];
    if (a) { e.preventDefault(); a(); return; }
    if (e.key === "?" || (e.code === "Slash" && e.shiftKey)) { e.preventDefault(); toggleHelp(); }
  }
  function onRootDown(e) {
    if (menuEl && !e.target.closest(".dk-menu") && !e.target.closest("[data-menu]")) closeMenu();
    if (expose) {
      const we = e.target.closest(".dk-win");
      e.preventDefault();
      e.stopPropagation();
      exitExpose(we ? wins.find(w => w.el === we) : null);
      return;
    }
    if (e.target === root || e.target === layer || e.target === dimEl) root.focus({ preventScroll: true });
  }

  // ── messages from the pages in the windows ──────────────────────────────────────────────
  function sanitizeWidget(d) {
    const a = d.action && typeof d.action === "object" ? d.action : null;
    const action = a && a.id ? { id: String(a.id).slice(0, 40), label: String(a.label || "").slice(0, 40), icon: a.icon === "play" || a.icon === "pause" ? a.icon : "" } : null;
    return { label: String(d.label || "").slice(0, 40), action };
  }
  window.addEventListener("message", e => {
    if (!root || e.origin !== location.origin || !e.data || typeof e.data !== "object") return;
    const w = wins.find(x => x.frame && x.frame.contentWindow === e.source);
    if (!w) return;
    if (e.data.type === "bina:route" && typeof e.data.path === "string" && /^[/?][^#]*$/.test(e.data.path)) {
      const next = e.data.path === "/" ? "" : e.data.path;
      if (next === w.route) return;
      w.route = next;
      if (w === focused) writeHash(w);
      emit("route", w);
      saveSoon();
    } else if (e.data.type === "bina:widget") {
      // an app that can collapse to a control says so; the shell draws it when the window is far out
      w.widget = sanitizeWidget(e.data);
      w.mode = "";
      applyPos(w, false);
    }
  });

  // ── persistence ─────────────────────────────────────────────────────────────────────────
  function saveSoon() { clearTimeout(saveT); saveT = setTimeout(saveLayout, 400); }
  function saveLayout() {
    if (!root) return;
    save(K.layout, {
      v: 1, W: G.W,
      wins: order.map(w => ({ mid: w.mid, native: w.native || null, ext: w.ext || null, route: w.route, cx: Math.round(w.cx), cy: Math.round(w.cy), w: w.w, h: w.h, max: w.max, prev: w.prev, home: w.home, dock: w.dock || null, lf: w.lastFocus })),
    });
  }
  function restoreLayout() {
    const L = load(K.layout, null);
    if (!L || !Array.isArray(L.wins) || !L.wins.length) return false;
    const kx = L.W ? G.W / L.W : 1;
    const items = L.wins.filter(x => x && (x.native ? natives[x.native] : x.ext ? x.ext.url : modById(x.mid)));
    if (!items.length) return false;
    const live = new Set(items.filter(x => !x.native).sort((a, b) => (b.lf || 0) - (a.lf || 0)).slice(0, prefs.live));
    items.forEach(x => {
      const o = { w: x.w, h: x.h, cx: x.cx * kx, cy: x.cy, noFocus: true, sleep: !x.native && !live.has(x) };
      const w = x.native ? openNative(x.native, o) : x.ext ? openExternal(Object.assign({ id: String(x.mid).replace(/^ext:/, "") }, x.ext), o) : openWin(modById(x.mid), x.route || "", o);
      if (!w) return;
      w.prev = x.prev || null;
      w.home = x.home ? { cx: x.home.cx * kx, cy: x.home.cy } : null;
      w.lastFocus = x.lf || 0;
      w.dock = x.dock === "icon" || x.dock === "col" ? x.dock : null;
      if (x.max) { w.max = true; maxGeom(w); }
      applyPos(w, false);
    });
    const top = order[order.length - 1];
    if (top) focusWin(top, { noHash: true, keepFocus: true });
    return true;
  }

  // ── mounting ────────────────────────────────────────────────────────────────────────────
  function mount() {
    if (root) return;
    compact = false;
    computeGeom();
    document.documentElement.classList.add("dk-on");
    root = h("div", "dk");
    root.id = "dk";
    root.tabIndex = -1;
    root.setAttribute("aria-label", "שולחן עבודה");
    cvBg = h("canvas");
    cvFx = h("canvas");
    layer = h("div", "dk-layer");
    dimEl = h("div", "dk-dim");
    layer.appendChild(dimEl);
    bar = h("div", "dk-bar");
    bar.setAttribute("role", "menubar");
    dock = h("nav", "dk-dock");
    dock.setAttribute("aria-label", "יישומים");
    snapEl = h("div", "dk-snap");
    helpEl = h("div", "dk-help");
    toastEl = h("div", "dk-toast");
    toastEl.setAttribute("role", "status");
    root.append(cvBg, cvFx, layer, snapEl, bar, dock, helpEl, toastEl);
    document.body.appendChild(root);
    buildBar();
    buildDock();
    buildHelp();
    drawBg();
    // S4: the menu bar starts full width and pulls in to the focus zone, as the demo's first step
    applyBarGeom(true);
    if (prefs.pill) setTimeout(() => { if (bar) applyBarGeom(); }, 350);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    window.addEventListener("keydown", onKey, true);
    root.addEventListener("pointerdown", onRootDown, true);
    emit("mount");
    if (!restoreLayout()) openDefaults();
    clockT = setInterval(tickClock, 20000);
  }
  function unmount() {
    if (!root) return;
    saveLayout();
    emit("unmount");
    acctFor = undefined;
    compact = false;
    clearInterval(clockT);
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
    window.removeEventListener("keydown", onKey, true);
    closeMenu();
    root.remove();
    root = cvBg = cvFx = layer = dimEl = bar = dock = snapEl = helpEl = toastEl = null;
    wins = [];
    order = [];
    focused = drag = expose = flash = null;
    document.documentElement.classList.remove("dk-on");
  }
  const wanted = () => asked || !!load(K.on, false);
  const wideEnough = () => window.innerWidth >= CFG.MIN_WIDTH;

  // A desktop that is already up and gets NARROWER — a side pane dragged in, a window halved — stays
  // up in a compact form: the focused window fills the screen and every other one waits behind it,
  // still loaded. Handing back to the classic shell here would tear every window down and reload its
  // page, an agent's running chat and the live browser it drives included. A screen that is narrow
  // from the start (a phone) never mounts the desktop at all; that is the classic shell's job.
  let compact = false;
  function setCompact(on) {
    if (!root || compact === on) return;
    compact = on;
    root.classList.toggle("compact", on);
    closeMenu();
    if (!on) return;
    if (expose) exitExpose(null);
    if (focused && focused.mode !== "win") bringToZone(focused);
  }

  // debounced with a timer, not a frame: a backgrounded tab gets no frames, and a resize there must
  // still be handled
  window.addEventListener("resize", () => {
    if (BARE || !booted || resizeRaf) return;
    resizeRaf = setTimeout(() => {
      resizeRaf = 0;
      if (root && !wideEnough()) { setCompact(true); return; }
      if (!root && wanted() && wideEnough()) { mount(); if (typeof route === "function") route(); return; }
      if (!root) return;
      if (compact) setCompact(false);   // back to the full desktop; positions rescale from the width it had
      const oldW = G.W;
      computeGeom();
      const k = G.W / oldW;
      wins.forEach(w => { if (w.max) maxGeom(w); else w.cx *= k; if (w.home) w.home.cx *= k; applyPos(w, false); });
      applyBarGeom();
      // The dock's budget is a function of the viewport (and zoom is a resize), so a new width is a
      // new dock — never a timer, never a frame: this runs inside the same debounced resize.
      buildDock();
      drawBg();
      drawFx();
    }, 80);
  });
  // the desk is drawn from the theme's values, so the machine turning dark or light redraws it
  matchMedia("(prefers-color-scheme:dark)").addEventListener("change", () => { if (root && !compact) drawBg(); });

  function setPref(k, v) {
    prefs[k] = v;
    save(K.prefs, prefs);
    if (!root) return;
    if (k === "bg" || k === "rails") { drawBg(); drawFx(); }
    else if (k === "pill") applyBarGeom();
    else if (k === "morph") wins.forEach(w => applyPos(w, true));
    else if (k === "live") enforceLive();
  }

  // ── the settings view (classic #content, or a bare window inside the desktop) ───────────
  function renderSettings(c) {
    // inside a desktop window the switches steer the desktop around it, not this bare copy
    let host = null;
    try { if (BARE && window.parent !== window && window.parent.BinaDesktop) host = window.parent.BinaDesktop; } catch (e) { /* ignore */ }
    const target = host || api;
    prefs = Object.assign({}, DEF_PREFS, load(K.prefs, {}));
    const row = (k, label, note, on) => '<label class="dk-row"><input type="checkbox" data-k="' + k + '"' + (on ? " checked" : "") + "><b>" + label + "</b>" +
      (note ? '<span class="sub">' + note + "</span>" : "") + "</label>";
    c.innerHTML = '<div class="wcard dk-set"><h3>שולחן עבודה</h3>' +
      '<div class="sub">מצב תצוגה שבו כל יישום נפתח בחלון משלו. במרכז המסך אזור המיקוד; חלון שנגרר אל אחד הצדדים מתכווץ ונשאר חי ופעיל. ' +
      "ניעור של חלון שולח את כל השאר לצדדים, וחלון שמפרסם יישומון הופך לכפתור.</div>" +
      row("on", "מצב שולחן עבודה", "במסכים ברוחב 1024 פיקסלים ומעלה", wanted()) +
      row("grid", "רקע רשת מתיחה", "הרשת נדחסת בצדדים באותה עקומה שמכווצת את החלונות", prefs.bg === "grid") +
      row("pill", "תפריט עליון ממורכז", "התפריט נמשך אל אזור המיקוד", prefs.pill) +
      row("rails", "מסילות אור בזמן גרירה", "", prefs.rails) +
      row("morph", "כיפוף חלונות בצדדים", "ניסוי שנדחה בהרצאה: הטקסט מפסיק להיות קריא", prefs.morph) +
      row("history", "היסטוריית עבודה", "נשמרת בדפדפן הזה בלבד ל-30 יום, בלי תוכן: זמן, גלילה ומספר פעולות", prefs.history !== false) +
      '<label class="dk-row"><b>חלונות פעילים בו-זמנית</b><select data-k="live">' +
      [6, 10, 14, 20].map(n => "<option" + (prefs.live === n ? " selected" : "") + ">" + n + "</option>").join("") +
      '</select><span class="sub">חלונות ותיקים יותר נכנסים למנוחה עד שנוגעים בהם</span></label>' +
      '<div class="dk-row"><button class="btn ghost sm" type="button" data-k="reset">איפוס סידור החלונות</button></div>' +
      '<div class="dk-note" title="המקורות והמיפוי המלא: ai/context/console-desktop-working-memory.md">הרעיונות מבוססים על ההרצאה של סקוט ג׳נסון ב-Akademy 2026.</div></div>';
    c.querySelectorAll("[data-k]").forEach(inp => {
      const k = inp.dataset.k;
      if (k === "reset") { inp.addEventListener("click", () => target.reset()); return; }
      inp.addEventListener("change", () => {
        if (k === "on") { if (inp.checked) target.enable(); else target.disable(); }
        else if (k === "grid") target.setPref("bg", inp.checked ? "grid" : "wallpaper");
        else if (k === "live") target.setPref("live", Number(inp.value) || DEF_PREFS.live);
        else target.setPref(k, inp.checked);
      });
    });
    // What the office does when this machine locks, turns its display off or closes its lid —
    // the machine service owns it; power-settings.js draws the card.
    if (window.BinaPower) window.BinaPower.render(c);
  }

  const api = {
    // called by app.js boot() once MODULES is loaded, right before the first route()
    boot() { booted = true; if (!BARE && wanted() && wideEnough()) mount(); },
    isOn: () => !!root,
    openModule: (m, rest) => openModule(m, rest),
    refresh() { if (root) buildDock(); },
    askOwnHosts() { wins.forEach(w => { if (w.ext && w.ext.ask && !w.sleeping) askOwnHost(w); }); },
    askAnyway(id) { const w = wins.find(x => x.mid === "ext:" + id); if (w) { w.ext.anyway = true; askOwnHost(w); } },
    renderSettings,
    setPref,
    reset() { if (root) resetDesk(); else try { localStorage.removeItem(K.layout); } catch (e) { /* ignore */ } },
    enable() {
      asked = false;                    // a person asked; the URL's ask has served its purpose
      save(K.on, true);
      if (BARE || root) return;
      if (!wideEnough()) return;
      mount();
      if (typeof route === "function") route();
    },
    disable() {
      asked = false;
      save(K.on, false);
      if (!root) return;
      unmount();
      if (typeof route === "function") route();
    },
    // app.js reloadEmbeddedApp() hands an account switch here while the desktop is up
    reloadService,
    // an app on its own host (embed:false), opened as a window — app-management's "open" calls this
    openExternal: spec => openExternal(spec),
    // The window manager as the rest of the desktop sees it (desktop-memory.js): events —
    // mount, unmount, open, close, focus(w, prev), route, load(w, doc), pos — the windows, and the
    // few verbs a tool needs. A window object is shared, not copied: read it, do not rewrite it.
    wm: {
      on(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
      wins: () => wins.slice(),
      focused: () => focused,
      root: () => root,
      geom: () => G,
      meta: metaOf,
      modById,
      openModule: (m, rest) => (root ? openModule(m, rest || "") : null),
      openNative: (key, o) => openNative(key, o),
      focus: w => { if (!inZone(w) || w.mode !== "win") bringToZone(w); focusWin(w); },
      close: closeWin,
      toast,
      icon,
      colorFor,
      prefs: () => prefs,
      setPref,
      // a desktop tool: {key, name, icon, color, w, h, render(bodyEl, win)} — a dock icon and a window
      registerNative(spec) { natives[spec.key] = spec; if (root) buildDock(); },
    },
  };
  window.BinaDesktop = api;
})();
