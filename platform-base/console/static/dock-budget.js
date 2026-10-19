/* dock-budget.js — how many tiles the desktop's dock may draw, as ONE pure function.
 *
 * WHY THIS EXISTS (ai/context/console-dock-capacity-design.md, and
 * `issues/console-desktop-dock-overflows-its-pill-and-hides-17-apps.yaml`): the dock drew one 46px
 * tile per (app × machine) in an uncapped flat row, so its WIDTH was a function of how many apps
 * exist — 2189px of content against a pill capped at `100vw - 40px`, and `.dk{overflow:hidden}`
 * clipped whatever did not fit. At the owner's own width 17 of 40 tiles were unreachable by pointer,
 * and in desktop mode the rail is hidden, so ⌘K was the only way to reach them.
 *
 * The answer is the one `ai/context/platform-navigation-design.md` §3.14 already chose for the
 * rail: the number of visible destinations is a function of the VIEWPORT, never of the estate. This
 * file is that decision and nothing else — no DOM, no globals beyond one namespace — so it can be
 * read, tested (`platform-base/console/test_dock_budget.mjs`) and reasoned about on its own.
 *
 * The arithmetic: a row of `slots` tiles occupies `slots*tile + (slots-1)*gap + pad + sep`; solving
 * for `content <= available` gives the floor below. `slots` is capped at `count + 1` because a dock
 * that fits everything shows everything (plus room for the door it does not need), and floored at
 * `min` so a narrow desktop keeps a usable dock and lets the compact shell take over below
 * `CFG.MIN_WIDTH` — degenerate cases are specified here rather than discovered in a screenshot.
 */
(function (root) {
  "use strict";

  /** The dock's dimensions live HERE and reach CSS as custom properties on `.dk-dock`
   *  (`--dock-tile`, `--dock-gap`, `--dock-pad`): a number that exists in two places is a future
   *  inconsistency, and this is the one place. `sep` is the divider's own width plus its margins. */
  var DOCK = { tile: 46, gap: 8, pad: 20, sep: 5, min: 3 };

  function num(v, dflt) {
    var n = Number(v);
    return isFinite(n) && n >= 0 ? n : dflt;
  }

  /**
   * resolveDock({available, count, tile?, gap?, pad?, sep?, min?}) ->
   *   {slots, showMore}
   *
   * `available` is the width the dock may occupy (the same `100vw - 40px` cap the pill carries),
   * `count` is how many tiles it would draw without a budget (apps + the desk's own tools + the
   * all-windows tile). `slots` is how many of them it may draw: the overflow door, when one is
   * needed, takes the LAST slot.
   */
  function resolveDock(o) {
    o = o || {};
    var tile = num(o.tile, DOCK.tile), gap = num(o.gap, DOCK.gap);
    var pad = num(o.pad, DOCK.pad), sep = num(o.sep, DOCK.sep), min = num(o.min, DOCK.min);
    var count = Math.max(0, Math.floor(num(o.count, 0)));
    var fits = Math.floor((num(o.available, 0) - pad - sep) / (tile + gap));
    var slots = Math.max(min, Math.min(count + 1, fits));
    return { slots: slots, showMore: count > slots };
  }

  /** How many APP tiles are drawn once the desk's own `fixed` tiles and the door are accounted for.
   *  Never fewer than one: with the door present the dock still has to be a launcher. */
  function dockRoom(o, slots, fixed) {
    if (!o || !o.showMore) return null;
    return Math.max(1, slots - fixed - 1);
  }

  root.BinaDockBudget = { DOCK: DOCK, resolveDock: resolveDock, dockRoom: dockRoom };
})(typeof window !== "undefined" ? window : globalThis);
