/* «פגישות» — sheet.js: the bottom sheet of a phone (DGO-1325). The owner, 2026-11-03: «כל החלק התחתון לא באמת נפתח
   כלפי מעלה וקשה מאוד להתנהל מזה … לאפשר להגדיל את זה». Three snaps — peek (the tab bar alone), half (the default)
   and full (everything but a mini-player) — dragged by its grabber and its tab bar only (the pane under them
   scrolls), tapped on the grabber, moved by the keyboard. Full is a step in the browser's history, so Back (and Esc)
   returns to half; the snap is in the address (?sheet=) and in MF.store, so a reload keeps it. A candidate for
   bina-ui: nothing in it knows meetings. */
(() => {
  "use strict";
  const MF = window.MF;
  const SNAPS = ["peek", "half", "full"];

  // el: the sheet; o.box: what it sits in (its height is the page's); o.handles: what drags it; o.heights(boxH) →
  // {peek, half, full} in px; o.onSnap(snap); o.key: the store's key
  MF.Sheet = function Sheet(el, o) {
    const box = o.box, key = o.key || "sheet";
    const offs = [];
    const on = (n, ev, fn, opt) => { n.addEventListener(ev, fn, opt); offs.push(() => n.removeEventListener(ev, fn, opt)); };
    const fromUrl = () => { const v = new URLSearchParams(location.search).get("sheet"); return SNAPS.includes(v) ? v : null; };
    let snap = fromUrl() || MF.store.get(key, "half");
    if (!SNAPS.includes(snap)) snap = "half";
    let pushed = false, pending = null, active = false;

    const H = () => box.getBoundingClientRect().height || window.innerHeight;
    const hs = () => o.heights(H());
    function apply(px, animate) {
      el.classList.toggle("mf-dragging", !animate);
      box.style.setProperty("--sheet-h", Math.round(px) + "px");
    }
    let shown = false;                                            // the first snap is drawn where it is, not slid to
    function paint() {
      if (!active) return;
      apply(hs()[snap], shown);
      if (!shown) { shown = true; requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("mf-dragging"))); }
      box.dataset.snap = snap;
      const g = el.querySelector(".mf-grab");
      if (g) { g.setAttribute("aria-valuenow", SNAPS.indexOf(snap)); g.setAttribute("aria-valuetext", { peek: "מקופל", half: "חצי מסך", full: "מסך מלא" }[snap]); }
      if (o.onSnap) o.onSnap(snap);
    }
    // true when the address took it (a page with no address of its own — a frame made from text — takes none)
    function writeUrl(push) {
      const q = new URLSearchParams(location.search);
      if (snap === "half") q.delete("sheet"); else q.set("sheet", snap);
      const s = q.toString(), href = location.pathname + (s ? "?" + s : "") + location.hash;
      try { history[push ? "pushState" : "replaceState"](Object.assign({}, history.state, { mfSheet: snap }), "", href); return true; } catch (e) { return false; }
    }
    // the one way a snap changes: full is entered with a step of history (so Back leaves it), and left by taking it back
    function set(next, why) {
      if (!SNAPS.includes(next) || !active) return;
      const was = snap;
      if (next === was) { paint(); return; }
      if (was === "full" && pushed && why !== "pop") { pending = next; pushed = false; history.back(); return; }
      snap = next;
      MF.store.set(key, snap);
      if (why !== "pop") {
        const took = writeUrl(next === "full");
        if (next === "full") pushed = took;               // only a step we really made is taken back
      }
      paint();
    }
    // Back: the address says where the sheet is; a step we took back lands where the gesture asked
    function onPop() {
      if (!active) return false;
      const want = pending || fromUrl() || "half";
      pending = null; pushed = false;
      if (want !== snap) { snap = want; MF.store.set(key, snap); }
      if (want !== (fromUrl() || "half")) writeUrl(false);
      paint();
      return true;
    }

    /* dragging: on the grabber and the tab bar only; a move under 6 px is a tap (a tab stays a button) */
    let drag = null;
    function down(e) {
      if (!active || (e.pointerType === "mouse" && e.button !== 0)) return;
      drag = { id: e.pointerId, y0: e.clientY, h0: hs()[snap], t0: performance.now(), moved: false, el: e.currentTarget, last: e.clientY, lt: performance.now(), v: 0 };
    }
    function move(e) {
      if (!drag || e.pointerId !== drag.id) return;
      const dy = e.clientY - drag.y0;
      if (!drag.moved && Math.abs(dy) < 6) return;
      if (!drag.moved) { drag.moved = true; try { drag.el.setPointerCapture(drag.id); } catch (err) { /* */ } }
      const now = performance.now();
      drag.v = (e.clientY - drag.last) / Math.max(1, now - drag.lt);   // px per ms, + is down
      drag.last = e.clientY; drag.lt = now;
      const h = hs();
      apply(Math.max(h.peek, Math.min(h.full, drag.h0 - dy)), false);
      e.preventDefault();
    }
    function up(e) {
      if (!drag || e.pointerId !== drag.id) return;
      const d = drag; drag = null;
      if (!d.moved) return;                                       // a tap: the tab's own click goes on
      el.classList.remove("mf-dragging");
      const h = hs(), cur = parseFloat(getComputedStyle(box).getPropertyValue("--sheet-h")) || h[snap];
      let next = SNAPS.reduce((a, b) => (Math.abs(h[b] - cur) < Math.abs(h[a] - cur) ? b : a), snap);
      if (Math.abs(d.v) > 0.6) {                                  // a flick: one snap in its direction
        const i = SNAPS.indexOf(snap) + (d.v < 0 ? 1 : -1);
        next = SNAPS[Math.max(0, Math.min(SNAPS.length - 1, i))];
      }
      d.el.dataset.dragged = "1"; setTimeout(() => { delete d.el.dataset.dragged; }, 50);
      set(next, "drag");
    }
    for (const hnd of o.handles || []) {
      on(hnd, "pointerdown", down);
      on(hnd, "pointermove", move, { passive: false });
      on(hnd, "pointerup", up);
      on(hnd, "pointercancel", up);
      // the click that ends a drag is not a tap (on a tab, or on the grabber's own toggle)
      on(hnd, "click", (e) => { if (hnd.dataset.dragged) { e.stopImmediatePropagation(); e.preventDefault(); } }, true);
    }
    const grab = el.querySelector(".mf-grab");
    if (grab) {
      on(grab, "click", () => set(snap === "full" ? "half" : snap === "half" ? "full" : "half", "tap"));
      on(grab, "keydown", (e) => {
        const i = SNAPS.indexOf(snap);
        if (e.key === "ArrowUp") { e.preventDefault(); set(SNAPS[Math.min(2, i + 1)], "key"); }
        else if (e.key === "ArrowDown") { e.preventDefault(); set(SNAPS[Math.max(0, i - 1)], "key"); }
      });
    }
    const ro = new ResizeObserver(() => paint());
    ro.observe(box); offs.push(() => ro.disconnect());

    return {
      get snap() { return snap; },
      set, onPop,
      // the sheet works only while the page is a phone's; on a wide screen it is a pane and the address keeps nothing
      activate(v) {
        if (v === active) return;
        active = v;
        if (!v) { box.style.removeProperty("--sheet-h"); delete box.dataset.snap; shown = false; return; }
        if (snap === "full" && !(history.state && history.state.mfSheet === "full")) {
          // a reload at full: the step to leave it by is made again, so Back still returns to half
          const keep = snap; snap = "half"; const took = writeUrl(false); snap = keep; pushed = took && writeUrl(true);
        }
        paint();
      },
      escape() { if (active && snap === "full") { set("half", "key"); return true; } return false; },
      destroy() { for (const f of offs) f(); },
    };
  };
})();
